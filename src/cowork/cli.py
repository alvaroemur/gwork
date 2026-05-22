from __future__ import annotations

import sys
import warnings
from pathlib import Path
import click

warnings.filterwarnings("ignore", category=FutureWarning, module="google")
warnings.filterwarnings("ignore", category=Warning, module="urllib3")

from .sync.commands import cmd_bootstrap, cmd_plan, cmd_apply


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
def apply(root: Path, account: str, only: tuple):
    """Ejecuta el plan: batchUpdate de Sheets, upload de Docs, write-back local."""
    sys.exit(cmd_apply(root, only=list(only), account=account))
