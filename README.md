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

### fetch / sync (agente o humano)

```
cd ~/Cowork/inspiro/comercial/mifondo_oportunidades-ia
cowork sync fetch --comments --diff --only docs/entregables/requisitos_v2/00_principal.md
# Solo lectura: drift local/remoto, comentarios, diff aproximado

cowork sync sync --only docs/entregables/requisitos_v2/00_principal.md
# Preflight fetch → plan. Aborta si Drive cambió sin reflejo en local.

cowork sync sync --apply --only docs/entregables/requisitos_v2/00_principal.md
# Preflight OK → plan → apply (respeta protect_styling salvo --force-content-push)
```

Estados de preflight (`sync_status`):

| Estado | Significado |
|--------|-------------|
| `noop` | Local y remoto alineados al snapshot |
| `local_only` | Cambió el markdown local — candidato a push |
| `remote_only` | Cambió Drive después del último apply — **no escribir** |
| `conflict` | Cambiaron ambos — **no escribir** |

### plan / apply (flujo clásico)

```
cd ~/Cowork/inspiro/clientes/mifondo
cowork sync plan        # lee manifiesto, compara local vs Drive, genera preview/
                        # y decisions.yaml con las celdas ambiguas
# revisar .drivesync/preview/decisions.yaml, resolver pendientes
cowork sync apply       # ejecuta el plan: batchUpdate de Sheets, upload de Docs
```

## Diagramas

Ver `docs/arquitectura.html` (servir con `python3 -m http.server 8765 --directory docs/`).
