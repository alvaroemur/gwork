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

Necesitas un OAuth client de tipo "desktop" en Google Cloud Console con las APIs Drive, Sheets y Docs habilitadas. Descarga el JSON y guárdalo en:

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

## Diagramas

Ver `docs/arquitectura.html` (servir con `python3 -m http.server 8765 --directory docs/`).
