# Inserción por AST: Markdown → árbol nativo de Google Docs

Estado: implementado (`src/cowork/sync/docs_ast.py`, `replace_doc_content_ast`).

## Problema

`update_doc_content` ([docs.py](../src/cowork/sync/docs.py)) hace

```
PATCH https://www.googleapis.com/upload/drive/v3/files/{id}?uploadType=media
```

con el `.docx` completo que produce Pandoc. Eso no "pierde estilos": **reemplaza
el archivo entero**. En cada push se destruyen las pestañas, los márgenes, el
diseño de página y los `namedStyles` del documento, y el Doc queda con lo que
Pandoc haya decidido.

De ahí salió `protect_styling` y su compuerta `--force-content-push`: una
bandera para admitir que la operación es destructiva y pedir confirmación
humana. La bandera es un parche sobre el mecanismo equivocado.

## Solución

Construir el árbol nativo del documento en vez de subir un archivo:
`deleteContentRange` + `insertText` / `insertTable` + `updateParagraphStyle` con
`namedStyleType` asignado directamente. El documento nunca se reemplaza, así que
márgenes, pestañas y `namedStyles` sobreviven y **lo insertado los hereda**.

Compone con `cowork style`: si el Doc destino ya tiene los `namedStyles` de marca
sembrados con `cowork style init`, insertar un párrafo con
`namedStyleType: HEADING_1` lo deja en Nunito 18pt rosa sin parchar carácter por
carácter.

## Pipeline

```
Markdown → (pandoc -t json) → AST de Pandoc → modelo intermedio → requests
```

El AST de Pandoc se usa como front-end en vez de un parser propio: ya está en el
árbol de dependencias (`pypandoc`), y su gramática cubre CommonMark más tablas.

El **modelo intermedio** (`Paragraph`, `Run`, `Table`) existe para desacoplar la
gramática de Markdown de la Docs API. Es plano: una lista de párrafos y tablas,
sin anidamiento, porque el cuerpo de un Doc también lo es.

### Mapeo de nodos

| Nodo Pandoc | Request de la Docs API |
| :--- | :--- |
| `Header n` | `insertText` + `namedStyleType: HEADING_n` |
| `Para` / `Plain` | `insertText` + `namedStyleType: NORMAL_TEXT` |
| `Strong` / `Emph` / `Strikeout` | `updateTextStyle` con `bold` / `italic` / `strikethrough` |
| `Code` / `CodeBlock` | `updateTextStyle` con `weightedFontFamily: Courier New` |
| `Link` | `updateTextStyle` con `link: {url}` |
| `BulletList` / `OrderedList` | `createParagraphBullets` con preset `BULLET_…` / `NUMBERED_…` |
| `BlockQuote` | `indentStart: 36pt` (el resto del callout lo pone `cowork style`) |
| `Table` | `insertTable` + `insertText` por celda |
| `HorizontalRule` | se descarta (el guard `remove_dash_dividers` los purga igual) |
| `Image`, `Note`, `DefinitionList`, `RawBlock` | `UnsupportedNode` |

`UnsupportedNode` es deliberado: se prefiere fallar ruidosamente antes que
degradar el documento en silencio. El error se levanta en `plan`, no en `apply`,
y el item queda con `status: unsupported_ast`; la salida es declarar
`content_mode: docx_upload` para ese item.

## Desplazamiento de índices UTF-16

La Docs API cuenta posiciones en **unidades UTF-16**, no en caracteres. Un emoji
fuera del BMP ocupa dos. Python cuenta code points, así que toda aritmética de
rangos pasa por `u16len()`; usar `len()` desalinearía cada rango posterior al
primer carácter suplente.

El desplazamiento por inserciones se resuelve con tres reglas, una por fase:

**Fase 1 — inserciones.** Todo se inserta en el **mismo índice** (1) y en **orden
inverso** al del documento. Cada inserción empuja a la derecha lo ya insertado,
de modo que el orden final es el correcto y ningún índice calculado se invalida
a mitad del lote. Un solo `batchUpdate`, sin releer.

**Fase 2 — texto de celdas.** `insertTable` crea las celdas vacías; llenarlas sí
desplaza. Se lee el documento una vez y se insertan las celdas **de la última a
la primera**, así los índices leídos siguen siendo válidos para todas.

**Fase 3 — estilos.** Ninguna request de estilo cambia la longitud del texto
(`updateParagraphStyle`, `updateTextStyle`, `updateTableCellStyle`), así que los
índices de una sola relectura valen para todo el lote. `createParagraphBullets`
va al final: es la única que puede tocar el texto, porque recorta marcadores de
lista preexistentes.

Total: **tres lotes, dos relecturas.**

### Emparejar el modelo con el documento

Las fases 2 y 3 necesitan saber qué elemento del documento corresponde a qué
bloque del modelo. Docs agrega párrafos vacíos por su cuenta (por ejemplo
después de una tabla), así que `match_blocks` no asume posiciones: avanza por el
contenido saltando lo que no corresponde, y empareja los párrafos comparando su
texto. Si no encuentra un bloque, levanta `RuntimeError` en vez de escribir a
ciegas sobre índices equivocados.

## Tablas

Pandoc entrega `TableHead` / `TableBody` / `TableFoot` por separado; el modelo
los aplana a una lista de filas, con la cabecera primera. `insertTable` solo
acepta una grilla rectangular: las celdas combinadas (`rowspan`/`colspan` ≠ 1)
levantan `UnsupportedNode`.

Los anchos de columna y el cebreado **no** son responsabilidad de este módulo.
Docs crea las tablas en `EVENLY_DISTRIBUTED`; fijarlas al ancho útil es trabajo
de `cowork style apply` (guard `auto_restore_table_widths`).

## Enlaces

`link_mode` opera en la capa de transforms, sobre el Markdown, antes de tocar el
AST:

- `preserve` — los enlaces del Markdown pasan tal cual y se vuelven enlaces
  nativos del Doc (`textStyle.link`), no texto azul falso.
- `rewrite_to_drive` — `rewrite_links` reescribe los targets relativos a URLs de
  Drive según el manifiesto; el AST solo ve el resultado.

Los enlaces que un humano puso **en el Doc** se pierden igual: `sync_mode:
replace` reemplaza el cuerpo, y eso no cambia con el AST. Lo que protege ese caso
es el guard de drift (`_doc_remote_drift`), no el mecanismo de escritura.

## Reemplazo por pestaña

`Item.doc_tab` fija la pestaña destino. Cuando está presente:

- `gog docs raw --tab=<id>` devuelve índices **locales a esa pestaña**;
- toda request lleva `tabId` en su `range` o `location`.

Sin `doc_tab` se opera sobre la pestaña por defecto. El borrado previo
(`clear_body_requests`) respeta el párrafo final obligatorio del cuerpo: el rango
va de 1 a `endIndex - 1`, porque Docs rechaza borrar el salto de línea final.

## Retiro de `--force-content-push`

La bandera existía porque el único camino de escritura era destructivo. Con el
AST deja de tener sentido, y se retira en tres pasos:

1. **Ahora.** `content_mode` entra al manifiesto con defecto `ast`. La ruta
   destructiva pasa a ser opt-in (`content_mode: docx_upload`), que es como debía
   haber sido: lo peligroso se pide, no se hereda. `protect_styling` solo
   bloquea el apply en la ruta `docx_upload`; con `ast` el item pasa a `ok`.
   La bandera sigue aceptada y avisa que está en retirada.
2. **Cuando los manifiestos vivos hayan migrado.** `--force-content-push` pasa a
   error si se usa con `content_mode: ast`, en vez de solo avisar.
3. **Después.** Se eliminan la bandera y `update_doc_content`. `protect_styling`
   queda como declaración de intención sin compuerta: con el AST, ningún apply
   destruye el estilo nativo.

Mientras `docx_upload` siga existiendo, `--force-content-push` sigue siendo la
única puerta a una operación que reemplaza el archivo entero.

## Límites conocidos

- **Saltos duros dentro de un párrafo** (`LineBreak`) se aplanan a espacio:
  insertar `\n` abriría un párrafo nuevo y desalinearía el modelo.
- **Listas anidadas** se representan con `indentStart` proporcional al nivel, no
  con los niveles nativos de `createParagraphBullets`.
- **Imágenes, notas al pie y listas de definición** no se traducen.
- Docs deja un **párrafo vacío antes de cada tabla** insertada; es cosmético y
  `cowork style` no lo trata como separador.
