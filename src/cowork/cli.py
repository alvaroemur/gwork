from __future__ import annotations

import sys
import warnings
from pathlib import Path
import click

warnings.filterwarnings("ignore", category=FutureWarning, module="google")
warnings.filterwarnings("ignore", category=Warning, module="urllib3")

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


@sync.command("apply")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Directorio del cliente.")
@click.option("--account", default=None, help="Cuenta de Google (email) para gog-cli.")
@click.option("--only", multiple=True, help="Solo aplicar estos paths locales.")
@click.option(
    "--force-content-push",
    is_flag=True,
    default=False,
    help="Permite apply en Docs con protect_styling (destruye estilo nativo vía Pandoc).",
)
def apply(root: Path, account: str, only: tuple, force_content_push: bool):
    """Ejecuta el plan: batchUpdate de Sheets, upload de Docs, write-back local."""
    sys.exit(cmd_apply(
        root, only=list(only), account=account,
        force_content_push=force_content_push,
    ))


@sync.command("fetch")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Directorio del cliente (contiene .drivesync.yaml).")
@click.option("--account", default=None, help="Cuenta de Google (email) para gog-cli.")
@click.option("--only", multiple=True, help="Solo inspeccionar estos paths locales.")
@click.option("--comments", "-c", is_flag=True, help="Incluir comentarios abiertos de Drive.")
@click.option("--diff", "-d", is_flag=True, help="Diff aproximado local vs texto plano del Doc.")
@click.option("--json", "as_json", is_flag=True, help="Salida JSON (para agentes).")
def fetch(root: Path, account: str, only: tuple, comments: bool, diff: bool, as_json: bool):
    """Lee Drive vs local: drift, comentarios, diff. Solo lectura — no escribe."""
    sys.exit(cmd_fetch(
        root,
        account=account,
        only=list(only),
        comments=comments,
        diff=diff,
        as_json=as_json,
    ))


@sync.command("sync")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Directorio del cliente (contiene .drivesync.yaml).")
@click.option("--account", default=None, help="Cuenta de Google (email) para gog-cli.")
@click.option("--only", multiple=True, help="Solo sincronizar estos paths locales.")
@click.option("--apply", is_flag=True, help="Tras preflight + plan, ejecutar apply.")
@click.option(
    "--force-content-push",
    is_flag=True,
    default=False,
    help="Permite apply en Docs con protect_styling (destruye estilo nativo vía Pandoc).",
)
@click.option("--comments", "-c", is_flag=True, help="Durante preflight, mostrar comentarios.")
@click.option("--diff", "-d", is_flag=True, help="Durante preflight, mostrar diff aproximado.")
def sync_cmd(root: Path, account: str, only: tuple, apply: bool,
             force_content_push: bool, comments: bool, diff: bool):
    """Preflight fetch → plan → (opcional) apply. Aborta si Drive diverge del snapshot."""
    sys.exit(cmd_sync(
        root,
        account=account,
        only=list(only),
        apply=apply,
        force_content_push=force_content_push,
        comments=comments,
        diff=diff,
    ))
