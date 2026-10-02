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
    cmd_manifest_init,
    cmd_plan as cmd_style_plan,
)
from .sync.commands import cmd_bootstrap, cmd_plan, cmd_apply
from .sync.fetch import cmd_fetch, cmd_sync
from .sync.pull import cmd_pull
from .sync.organization import apply_organization, plan_organization


@click.group()
def main():
    """Sync and style Google Docs and Sheets from local files."""


@main.group()
def sync():
    """Sync local Markdown and CSV files with Google Drive."""


_OVERWRITE_OPT = click.option(
    "--overwrite-remote", is_flag=True, default=False,
    help="Accept overwriting Drive edits made after the baseline (review the plan first).")
_IMAGE_OPT = click.option(
    "--allow-image-loss", is_flag=True, default=False,
    help="Allow replacing a tab body that holds inline images (they are deleted).")
_ALL_OPT = click.option(
    "--all", "all_items", is_flag=True, default=False,
    help="Apply every registered item; Docs otherwise require --only.")


@sync.command("bootstrap")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Project directory.")
@click.option("--account", default=None, help="Google account override for gog.")
@click.option("--source", type=click.Choice(["remote", "local"]), default="remote",
              show_default=True, help="Initial source of truth.")
@click.option("--only", multiple=True,
              help="Exact local path, Drive ID, resource ID, or Drive/resource pair.")
@click.option("--force", is_flag=True, default=False,
              help="Rebuild snapshots and baselines that already exist.")
def bootstrap(root: Path, account: str, source: str, only: tuple, force: bool):
    """Baseline Drive per tab/sheet and report local divergence.

    Docs always baseline the real remote content of each tab; a local file that
    differs is reported as diverged instead of being marked in sync.
    """
    sys.exit(cmd_bootstrap(root, source=source, account=account, only=list(only),
                           force=force))


@sync.command("plan")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Project directory containing .gwork.yaml.")
@click.option("--account", default=None, help="Google account override for gog.")
@click.option("--only", multiple=True,
              help="Exact local path, Drive ID, resource ID, or Drive/resource pair.")
def plan(root: Path, account: str, only: tuple):
    """Compare local files with Drive and write review artifacts."""
    sys.exit(cmd_plan(root, account=account, only=list(only)))


@sync.command("fetch")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Project directory containing .gwork.yaml.")
@click.option("--account", default=None, help="Google account override for gog.")
@click.option("--only", multiple=True,
              help="Exact local path, Drive ID, resource ID, or Drive/resource pair.")
@click.option("--comments", is_flag=True, default=False,
              help="Include open Docs and Sheets comments.")
@click.option("--diff", is_flag=True, default=False,
              help="Show an approximate local/remote diff for Docs.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Write JSON output.")
def fetch(root: Path, account: str, only: tuple, comments: bool, diff: bool, as_json: bool):
    """Inspect drift and comments without writing to Drive."""
    sys.exit(cmd_fetch(
        root, account=account, only=list(only), comments=comments, diff=diff, as_json=as_json,
    ))


@sync.command("sync")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Project directory containing .gwork.yaml.")
@click.option("--account", default=None, help="Google account override for gog.")
@click.option("--only", multiple=True,
              help="Exact local path, Drive ID, resource ID, or Drive/resource pair.")
@click.option("--apply", "do_apply", is_flag=True, default=False,
              help="Run plan and apply after a clean preflight.")
@click.option(
    "--force-content-push",
    is_flag=True,
    default=False,
    help="Legacy safeguard for items that use content_mode: docx_upload.",
)
@click.option("--comments", is_flag=True, default=False,
              help="Show open comments during preflight.")
@click.option("--diff", is_flag=True, default=False,
              help="Show an approximate Docs diff during preflight.")
@_OVERWRITE_OPT
@_IMAGE_OPT
@_ALL_OPT
def sync_sync(root: Path, account: str, only: tuple, do_apply: bool,
              force_content_push: bool, comments: bool, diff: bool,
              overwrite_remote: bool, allow_image_loss: bool, all_items: bool):
    """Run fetch and plan, then optionally apply if Drive has not drifted."""
    sys.exit(cmd_sync(
        root, account=account, only=list(only), apply=do_apply,
        force_content_push=force_content_push, comments=comments, diff=diff,
        overwrite_remote=overwrite_remote, allow_image_loss=allow_image_loss,
        all_items=all_items,
    ))


@sync.command("apply")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Project directory.")
@click.option("--account", default=None, help="Google account override for gog.")
@click.option("--only", multiple=True,
              help="Exact local path, Drive ID, resource ID, or Drive/resource pair.")
@click.option(
    "--force-content-push",
    is_flag=True,
    default=False,
    help="Legacy safeguard for docx_upload items that replace the complete file.",
)
@_OVERWRITE_OPT
@_IMAGE_OPT
@_ALL_OPT
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what each Doc tab would receive; send nothing.")
def apply(root: Path, account: str, only: tuple, force_content_push: bool,
          overwrite_remote: bool, allow_image_loss: bool, all_items: bool, dry_run: bool):
    """Apply the reviewed plan to Drive and local files.

    Docs require --only (one tab) or --all. Only the selected tab body is
    replaced; other tabs are hashed before and after to prove they stayed intact.
    """
    sys.exit(cmd_apply(
        root, only=list(only), account=account,
        force_content_push=force_content_push, overwrite_remote=overwrite_remote,
        allow_image_loss=allow_image_loss, dry_run=dry_run, all_items=all_items,
    ))


@sync.command("pull")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Project directory.")
@click.option("--account", default=None, help="Google account override for gog.")
@click.option("--only", multiple=True, required=True,
              help="Exact local path, resource ID, or Drive/resource pair (one Doc tab).")
@click.option("--apply", "do_apply", is_flag=True, default=False,
              help="Overwrite the local Markdown (a backup is kept) and re-baseline.")
def pull(root: Path, account: str, only: tuple, do_apply: bool):
    """Show (or write) one Doc tab as Markdown, to catch manual Drive edits."""
    sys.exit(cmd_pull(root, only=list(only), account=account, do_apply=do_apply))


def _run_organization(plan_data: dict, do_apply: bool) -> None:
    actions = plan_data["actions"]
    if actions:
        for action in actions:
            detail = action.get("local") or action.get("to") or action.get("drive_id")
            click.echo(f"{action['action']}: {detail}")
    else:
        click.echo("Organization is current.")
    if do_apply:
        apply_organization(plan_data)
        click.echo(f"Applied organization to {plan_data['manifest_path']}")
    else:
        click.echo("Plan only. Re-run with --apply to write files and the manifest.")


@main.command("organize")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Project directory containing .gwork.yaml.")
@click.option("--drive-id", "drive_ids", multiple=True,
              help="Reconcile one registered Drive file; repeat as needed.")
@click.option("--account", default=None, help="Google account override for gog.")
@click.option("--apply", "do_apply", is_flag=True, default=False,
              help="Create missing local files and update .gwork.yaml.")
def organize(root: Path, drive_ids: tuple, account: str, do_apply: bool):
    """Discover tabs and worksheets, then reconcile the local organization."""
    try:
        plan_data = plan_organization(
            root / ".gwork.yaml",
            drive_ids=list(drive_ids) or None,
            account=account,
        )
        _run_organization(plan_data, do_apply)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.group("item")
def item():
    """Register Drive files explicitly."""


@item.command("add")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path.cwd, help="Project directory.")
@click.option("--drive-id", required=True, help="Google Doc or Spreadsheet ID.")
@click.option("--type", "item_type", required=True,
              type=click.Choice(["doc", "sheet"]), help="Drive file type.")
@click.option("--directory", default=None,
              help="Stable local directory; defaults from the Drive title.")
@click.option("--account", default=None, help="Google account override for gog.")
@click.option("--apply", "do_apply", is_flag=True, default=False,
              help="Create local files and register the Drive file.")
def item_add(root: Path, drive_id: str, item_type: str, directory: str,
             account: str, do_apply: bool):
    """Preview or apply explicit registration of one Drive file."""
    try:
        plan_data = plan_organization(
            root / ".gwork.yaml",
            registrations=[(drive_id, item_type, directory)],
            drive_ids=[drive_id],
            account=account,
        )
        _run_organization(plan_data, do_apply)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.group()
def style():
    """Audit and apply design tokens declared in .gwork.yaml."""


_MANIFEST_OPT = click.option(
    "--manifest", "manifest_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path(".gwork.yaml"), show_default=True,
    help="Manifest path or its containing directory.",
)
_ACCOUNT_OPT = click.option("--account", default=None,
                            help="Google account override; defaults to transport.account.")
_TAB_OPT = click.option("--tab", default=None, help="Limit the command to one tab ID or title.")


@style.command("audit")
@_MANIFEST_OPT
@_ACCOUNT_OPT
@_TAB_OPT
@click.option(
    "--refresh-template/--no-refresh-template",
    default=True,
    show_default=True,
    help="Extract live tokens and rebuild the template tab before auditing.",
)
def style_audit(manifest_path: Path, account: str, tab: str, refresh_template: bool):
    """Extract tokens, refresh the template tab, and report style drift."""
    sys.exit(cmd_style_audit(
        manifest_path,
        account=account,
        tab=tab,
        refresh=refresh_template,
    ))


@style.command("plan")
@_MANIFEST_OPT
@_ACCOUNT_OPT
@_TAB_OPT
def style_plan(manifest_path: Path, account: str, tab: str):
    """Preview style operations without writing."""
    sys.exit(cmd_style_plan(manifest_path, account=account, tab=tab))


@style.command("apply")
@_MANIFEST_OPT
@_ACCOUNT_OPT
@_TAB_OPT
@click.option("--dry-run", is_flag=True, default=False,
              help="Show the plan without writing.")
def style_apply(manifest_path: Path, account: str, tab: str, dry_run: bool):
    """Apply design tokens to the live document."""
    sys.exit(cmd_style_apply(manifest_path, account=account, tab=tab, dry_run=dry_run))


@style.command("init")
@_MANIFEST_OPT
@_ACCOUNT_OPT
@click.option("--title", required=True, help="Title for the new Google Doc.")
@click.option("--parent", default=None, help="Destination Drive folder.")
@click.option("--source", type=click.Path(exists=True, path_type=Path), default=None,
              help="Markdown source; defaults to a style specimen.")
@click.option("--write-back", is_flag=True, default=False,
              help="Write the new document ID to the manifest.")
def style_init(manifest_path: Path, account: str, title: str, parent: str,
               source: Path, write_back: bool):
    """Create a Google Doc with named styles seeded from the manifest."""
    sys.exit(cmd_style_init(manifest_path, title=title, account=account,
                            parent=parent, source=source, write_back=write_back))


@main.command("init")
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path),
    default=Path(".gwork.yaml"),
    show_default=True,
    help="Manifest to create or update.",
)
@click.option("--doc-id", required=True, help="Existing Google Doc ID or URL.")
@click.option("--account", default=None, help="Google account for gog.")
def init(manifest_path: Path, doc_id: str, account: str):
    """Initialize .gwork.yaml from an existing document."""
    sys.exit(cmd_manifest_init(manifest_path, doc_id=doc_id, account=account))
