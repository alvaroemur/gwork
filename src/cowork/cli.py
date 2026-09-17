from __future__ import annotations

import sys
import warnings
from pathlib import Path
import click

warnings.filterwarnings("ignore", category=FutureWarning, module="google")
warnings.filterwarnings("ignore", category=Warning, module="urllib3")

from .style.commands import (
    cmd_apply as cmd_style_apply,
    cmd_audit as cmd_style_audit,
    cmd_init as cmd_style_init,
    cmd_plan as cmd_style_plan,
)
from .sync.commands import cmd_bootstrap, cmd_plan, cmd_apply
from .sync.fetch import cmd_fetch, cmd_sync


@click.group()
def main():
    """cowork — herramientas para el flujo de trabajo de Cowork."""


@main.group()
def sync():
    """Sincroniza entregables locales (CSV/MD) con Google Drive."""


@sync.command("bootstrap")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Directorio del cliente.")
@click.option("--account", default=None, help="Cuenta de Google (email) para gog-cli.")
@click.option("--source", type=click.Choice(["remote", "local"]), default="remote",
              show_default=True, help="Fuente de verdad inicial: remote (Drive) o local (CSV).")
def bootstrap(root: Path, account: str, source: str):
    """Establece el snapshot inicial para items sin historial previo. Corre antes del primer plan."""
    sys.exit(cmd_bootstrap(root, source=source, account=account))


@sync.command("plan")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Directorio del cliente (contiene .drivesync.yaml).")
@click.option("--account", default=None, help="Cuenta de Google (email) para gog-cli.")
def plan(root: Path, account: str):
    """Calcula el plan: diff local vs Drive, escribe preview/ y decisions.yaml."""
    sys.exit(cmd_plan(root, account=account))


@sync.command("fetch")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Directorio del cliente (contiene .drivesync.yaml).")
@click.option("--account", default=None, help="Cuenta de Google (email) para gog-cli.")
@click.option("--only", multiple=True, help="Solo estos paths locales.")
@click.option("--comments", is_flag=True, default=False,
              help="Incluye comentarios abiertos de Docs/Sheets.")
@click.option("--diff", is_flag=True, default=False,
              help="Muestra un diff aproximado local vs remoto (solo Docs).")
@click.option("--json", "as_json", is_flag=True, default=False, help="Salida en JSON.")
def fetch(root: Path, account: str, only: tuple, comments: bool, diff: bool, as_json: bool):
    """Solo lectura: drift local/remoto, comentarios abiertos, diff aproximado."""
    sys.exit(cmd_fetch(
        root, account=account, only=list(only), comments=comments, diff=diff, as_json=as_json,
    ))


@sync.command("sync")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Directorio del cliente (contiene .drivesync.yaml).")
@click.option("--account", default=None, help="Cuenta de Google (email) para gog-cli.")
@click.option("--only", multiple=True, help="Solo estos paths locales.")
@click.option("--apply", "do_apply", is_flag=True, default=False,
              help="Tras el preflight OK, ejecuta plan + apply.")
@click.option(
    "--force-content-push",
    is_flag=True,
    default=False,
    help="En retirada: solo aplica a items con content_mode: docx_upload.",
)
@click.option("--comments", is_flag=True, default=False,
              help="Muestra comentarios abiertos durante el preflight.")
@click.option("--diff", is_flag=True, default=False,
              help="Muestra diff aproximado durante el preflight (solo Docs).")
def sync_sync(root: Path, account: str, only: tuple, do_apply: bool,
              force_content_push: bool, comments: bool, diff: bool):
    """Preflight fetch → plan → (--apply) apply. Aborta si Drive divergió del snapshot."""
    sys.exit(cmd_sync(
        root, account=account, only=list(only), apply=do_apply,
        force_content_push=force_content_push, comments=comments, diff=diff,
    ))


@sync.command("apply")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Directorio del cliente.")
@click.option("--account", default=None, help="Cuenta de Google (email) para gog-cli.")
@click.option("--only", multiple=True, help="Solo aplicar estos paths locales.")
@click.option(
    "--force-content-push",
    is_flag=True,
    default=False,
    help="En retirada: solo aplica a items con content_mode: docx_upload, "
         "donde el apply reemplaza el archivo entero.",
)
def apply(root: Path, account: str, only: tuple, force_content_push: bool):
    """Ejecuta el plan: batchUpdate de Sheets, upload de Docs, write-back local."""
    sys.exit(cmd_apply(
        root, only=list(only), account=account,
        force_content_push=force_content_push,
    ))


@main.group()
def style():
    """Aplica un sistema de diseño (.gdoc-sync.yaml) a un Google Doc gobernado."""


_MANIFEST_OPT = click.option(
    "--manifest", "manifest_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path(".gdoc-sync.yaml"), show_default=True,
    help="Ruta al manifiesto de diseño (o al directorio que lo contiene).",
)
_ACCOUNT_OPT = click.option("--account", default=None,
                            help="Cuenta de Google (email); por defecto la del manifiesto.")
_TAB_OPT = click.option("--tab", default=None, help="Restringe a una pestaña (id o título).")


@style.command("audit")
@_MANIFEST_OPT
@_ACCOUNT_OPT
@_TAB_OPT
def style_audit(manifest_path: Path, account: str, tab: str):
    """Audita el documento contra el manifiesto sin escribir nada."""
    sys.exit(cmd_style_audit(manifest_path, account=account, tab=tab))


@style.command("plan")
@_MANIFEST_OPT
@_ACCOUNT_OPT
@_TAB_OPT
def style_plan(manifest_path: Path, account: str, tab: str):
    """Calcula las operaciones de estilo (dry-run)."""
    sys.exit(cmd_style_plan(manifest_path, account=account, tab=tab))


@style.command("apply")
@_MANIFEST_OPT
@_ACCOUNT_OPT
@_TAB_OPT
@click.option("--dry-run", is_flag=True, default=False,
              help="Muestra el plan y termina sin escribir.")
def style_apply(manifest_path: Path, account: str, tab: str, dry_run: bool):
    """Aplica el sistema de diseño al documento vivo."""
    sys.exit(cmd_style_apply(manifest_path, account=account, tab=tab, dry_run=dry_run))


@style.command("init")
@_MANIFEST_OPT
@_ACCOUNT_OPT
@click.option("--title", required=True, help="Título del Doc a crear.")
@click.option("--parent", default=None, help="Carpeta de Drive destino.")
@click.option("--source", type=click.Path(exists=True, path_type=Path), default=None,
              help="Markdown a importar; si se omite, se usa un esqueleto de estilos.")
@click.option("--write-back", is_flag=True, default=False,
              help="Escribe el doc_id resultante en el manifiesto.")
def style_init(manifest_path: Path, account: str, title: str, parent: str,
               source: Path, write_back: bool):
    """Crea un Doc nuevo con los namedStyles del manifiesto ya sembrados."""
    sys.exit(cmd_style_init(manifest_path, title=title, account=account,
                            parent=parent, source=source, write_back=write_back))
