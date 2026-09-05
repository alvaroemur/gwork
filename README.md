# cowork-drivesync

Sincroniza archivos locales CSV/MD a Google Drive (Sheets/Docs) con flujo tipo PR:
`plan` produce un diff revisable, `apply` ejecuta tras aprobación.

## Instalación

```
cd ~/Dev/cowork-drivesync
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Pandoc debe estar instalado en el sistema (`brew install pandoc`).

## Autenticación

Necesitás un OAuth client de tipo "desktop" en Google Cloud Console con las APIs Drive, Sheets y Docs habilitadas. Descargá el JSON y guardalo en:

```
~/.config/cowork/drivesync/client_secret.json
```

La primera corrida abre el navegador para autorizar; el token se cachea en
`~/.config/cowork/drivesync/token.json`.

## Uso

```
cd ~/Cowork/inspiro/clientes/mifondo
cowork sync plan        # lee manifiesto, compara local vs Drive, genera preview/
                        # y decisions.yaml con las celdas ambiguas
# revisar .drivesync/preview/decisions.yaml, resolver pendientes
cowork sync apply       # ejecuta el plan: batchUpdate de Sheets, upload de Docs
```

## Sistema de diseño de Google Docs (`cowork style`)

Aplica un design system declarado en `.gdoc-sync.yaml` a un Doc gobernado:

```
cowork style audit    # audita el doc contra el manifiesto, sin escribir
cowork style plan     # dry-run: qué requests de batchUpdate saldrían
cowork style apply    # purga separadores, calibra página y envía el lote atómico
cowork style init     # crea un Doc nuevo con los namedStyles ya sembrados
```

`init` es el único camino para que HEADING_1 y compañía lleven los tokens de
marca: la Docs API no expone `updateNamedStyles`, así que un documento que ya
existe solo admite el overlay de `apply`. Detalle en la skill `gdoc-style-sync`.

## Diagramas

Ver `docs/arquitectura.html` (servir con `python3 -m http.server 8765 --directory docs/`).
