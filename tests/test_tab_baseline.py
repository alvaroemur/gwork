"""Per-tab baseline, plan summary, scoped apply, and pull. No network: gog is faked."""

from pathlib import Path

import pytest
import yaml

from gwork.sync import baseline as bl
from gwork.sync import commands
from gwork.sync.manifest import load_manifest
from gwork.sync.pull import raw_to_markdown
from gwork.sync.state import State

DOC = "DOC1"
TAB_A, TAB_B = "t.a", "t.b"


# --- fake Drive ----------------------------------------------------------

def raw_from_lines(lines, images=False):
    """Build a `docs raw`-like dict from normalized lines."""
    content = [{"sectionBreak": {}, "endIndex": 1}]
    index = 1
    styles = {"TITLE": "TITLE", "H1": "HEADING_1", "H2": "HEADING_2", "H3": "HEADING_3"}
    for line in lines:
        kind, _, text = line.partition("|")
        if kind == "T":
            cells = [{"content": [{"paragraph": {"elements": [{"textRun": {"content": c + "\n"}}]}}]}
                     for c in text.split("|")]
            content.append({"table": {"tableRows": [{"tableCells": cells}]}})
            continue
        paragraph = {"elements": [{"textRun": {"content": text + "\n"}}],
                     "paragraphStyle": {"namedStyleType": styles.get(kind, "NORMAL_TEXT")}}
        if kind == "LIST":
            paragraph["bullet"] = {"listId": "l1"}
        end = index + len(text) + 1
        content.append({"startIndex": index, "endIndex": end, "paragraph": paragraph})
        index = end
    if images:
        content.append({"paragraph": {"elements": [{"inlineObjectElement": {"inlineObjectId": "x"}}]}})
    return {"body": {"content": content}}


class FakeDrive:
    def __init__(self, tabs):
        self.tabs = {k: list(v) for k, v in tabs.items()}
        self.images = set()
        self.writes = []
        self.reads = 0

    def docs_raw(self, doc_id, tab_id=None, all_tabs=False, account=None):
        self.reads += 1
        return raw_from_lines(self.tabs[tab_id], images=tab_id in self.images)

    def replace(self, drive_id, md_text, tab_id=None, account=None, **_):
        self.writes.append(tab_id)
        self.tabs[tab_id] = bl.blocks_from_markdown(md_text)
        return "2026-10-02T10:00:00Z"


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/a.md").write_text("# Title A\n\nParagraph one.\n\nParagraph two.\n")
    (tmp_path / "docs/b.md").write_text("# Title B\n\nOther tab.\n")
    (tmp_path / ".gwork.yaml").write_text(yaml.safe_dump({
        "version": 2,
        "transport": {"provider": "gog", "account": "x@example.com"},
        "files": [{"drive_id": DOC, "type": "doc", "title": "T", "directory": "docs",
                   "resources": [
                       {"id": TAB_A, "title": "A", "local": "docs/a.md"},
                       {"id": TAB_B, "title": "B", "local": "docs/b.md"}]}],
    }))
    drive = FakeDrive({
        TAB_A: ["H1|Title A", "P|Paragraph one.", "P|Old paragraph."],
        TAB_B: ["H1|Title B", "P|Other tab."],
    })
    monkeypatch.setattr(commands, "docs_raw", drive.docs_raw)
    monkeypatch.setattr(bl, "docs_raw", drive.docs_raw)
    monkeypatch.setattr(commands, "fetch_doc_modified_time", lambda *a, **k: "2026-10-02T09:00:00Z")
    monkeypatch.setattr(commands, "replace_doc_content_ast", drive.replace)
    return tmp_path, drive


def plan_entries(root, only=None):
    from gwork.sync.decisions import read_decisions
    commands.cmd_plan(root, only=only)
    manifest = load_manifest(root)
    return {e["local"]: e for e in read_decisions(manifest.decisions_path)["items"]}


# --- normalization and diff ----------------------------------------------

def test_markdown_and_remote_normalize_to_same_lines():
    md = "# Title\n\nIt’s “quoted”  text.\n\n- item\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    remote = raw_from_lines(["H1|Title", 'P|It\'s "quoted" text.', "LIST|item", "T|a|b", "T|1|2"])
    assert bl.blocks_from_markdown(md) == bl.blocks_from_raw(remote)


def test_diff_summary_counts_paragraph_changes():
    summary = bl.diff_blocks(["P|a", "P|b", "P|c"], ["P|a", "P|B", "P|c", "P|d"])
    assert (summary.added, summary.removed, summary.changed) == (1, 0, 1)
    assert bl.diff_blocks(["P|a"], ["P|a"]).label() == "sin cambios"


def test_inline_objects_are_detected_and_ignored_in_text():
    raw = raw_from_lines(["P|text"], images=True)
    assert bl.has_inline_objects(raw)
    assert bl.blocks_from_raw(raw) == ["P|text"]


# --- bootstrap -----------------------------------------------------------

def test_bootstrap_baselines_remote_and_reports_divergence(project, capsys):
    root, drive = project
    assert commands.cmd_bootstrap(root) == 0
    base = bl.load_baseline(root, "docs/a.md")
    assert base.blocks == ["H1|Title A", "P|Paragraph one.", "P|Old paragraph."]
    out = capsys.readouterr().out
    assert "diverges" in out          # a.md differs from Drive
    assert "docs/b.md in sync" in out
    assert State(root / ".gwork.state.json").get_doc("docs/a.md").baseline_hash == base.hash


def test_bootstrap_skips_existing_baseline_unless_forced(project):
    root, drive = project
    commands.cmd_bootstrap(root)
    drive.tabs[TAB_A] = ["P|changed on drive"]
    commands.cmd_bootstrap(root)
    assert bl.load_baseline(root, "docs/a.md").blocks[0] == "H1|Title A"
    commands.cmd_bootstrap(root, force=True)
    assert bl.load_baseline(root, "docs/a.md").blocks == ["P|changed on drive"]


# --- plan ----------------------------------------------------------------

def test_plan_without_baseline_is_not_drift(project):
    root, _ = project
    entry = plan_entries(root)["docs/a.md"]
    assert entry["status"] == "no_baseline"
    assert entry["diff"] == {"added": 0, "removed": 0, "changed": 1, "tables": 0}


def test_plan_ready_when_remote_matches_baseline(project):
    root, _ = project
    commands.cmd_bootstrap(root)
    entries = plan_entries(root)
    assert entries["docs/a.md"]["status"] == "ok"
    assert entries["docs/b.md"]["status"] == "noop"


def test_plan_flags_remote_edit_per_tab_only(project):
    root, drive = project
    commands.cmd_bootstrap(root)
    drive.tabs[TAB_A].append("P|Edited by a human on Drive.")
    entries = plan_entries(root)
    assert entries["docs/a.md"]["status"] == "doc_drift"
    assert entries["docs/b.md"]["status"] == "noop"   # untouched tab is not drift


# --- apply ---------------------------------------------------------------

def test_apply_requires_explicit_target_for_docs(project):
    root, drive = project
    commands.cmd_bootstrap(root)
    commands.cmd_plan(root)
    assert commands.cmd_apply(root) == 2
    assert drive.writes == []


def test_dry_run_sends_nothing_and_keeps_state(project):
    root, drive = project
    commands.cmd_bootstrap(root)
    commands.cmd_plan(root, only=["docs/a.md"])
    before = (root / ".gwork.state.json").read_text()
    assert commands.cmd_apply(root, only=["docs/a.md"], dry_run=True) == 0
    assert drive.writes == []
    assert (root / ".gwork.state.json").read_text() == before


def test_apply_writes_only_the_selected_tab_and_rebaselines(project):
    root, drive = project
    commands.cmd_bootstrap(root)
    commands.cmd_plan(root, only=["docs/a.md"])
    b_before = list(drive.tabs[TAB_B])
    assert commands.cmd_apply(root, only=["docs/a.md"]) == 0
    assert drive.writes == [TAB_A]
    assert drive.tabs[TAB_B] == b_before
    assert drive.tabs[TAB_A][-1] == "P|Paragraph two."
    assert bl.load_baseline(root, "docs/a.md").blocks == drive.tabs[TAB_A]
    # A second plan finds nothing to do.
    assert plan_entries(root, only=["docs/a.md"])["docs/a.md"]["status"] == "noop"


def test_apply_skips_tab_without_baseline(project):
    root, drive = project
    commands.cmd_plan(root, only=["docs/a.md"])
    commands.cmd_apply(root, only=["docs/a.md"])
    assert drive.writes == []


def test_apply_blocks_remote_edit_until_overwrite_flag(project):
    root, drive = project
    commands.cmd_bootstrap(root)
    drive.tabs[TAB_A].append("P|Human edit.")
    commands.cmd_plan(root, only=["docs/a.md"])
    assert commands.cmd_apply(root, only=["docs/a.md"]) == 1     # pending decision
    assert drive.writes == []
    assert commands.cmd_apply(root, only=["docs/a.md"], overwrite_remote=True) == 0
    assert drive.writes == [TAB_A]


def test_apply_detects_race_after_plan(project):
    root, drive = project
    commands.cmd_bootstrap(root)
    commands.cmd_plan(root, only=["docs/a.md"])
    drive.tabs[TAB_A].append("P|Edit after the plan.")
    commands.cmd_apply(root, only=["docs/a.md"], overwrite_remote=True)
    assert drive.writes == []


def test_apply_refuses_tab_with_images_unless_allowed(project):
    root, drive = project
    commands.cmd_bootstrap(root)
    drive.images.add(TAB_A)
    commands.cmd_plan(root, only=["docs/a.md"])
    commands.cmd_apply(root, only=["docs/a.md"])
    assert drive.writes == []
    commands.cmd_apply(root, only=["docs/a.md"], allow_image_loss=True)
    assert drive.writes == [TAB_A]


# --- pull ----------------------------------------------------------------

def test_raw_to_markdown_renders_headings_lists_and_tables():
    raw = raw_from_lines(["H1|Title", "P|Body", "LIST|one", "LIST|two", "T|a|b", "T|1|2"])
    md = raw_to_markdown(raw)
    assert md.startswith("# Title\n\nBody\n\n- one\n- two\n\n| a | b |")
    assert bl.blocks_from_markdown(md) == bl.blocks_from_raw(raw)


def test_pull_is_read_only_without_apply_and_backs_up_with_it(project, monkeypatch):
    from gwork.sync import pull
    root, drive = project
    monkeypatch.setattr(pull, "docs_raw", drive.docs_raw)
    local = root / "docs/a.md"
    original = local.read_text()
    assert pull.cmd_pull(root, only=["docs/a.md"]) == 0
    assert local.read_text() == original
    assert pull.cmd_pull(root, only=["docs/a.md"], do_apply=True) == 0
    assert "Old paragraph." in local.read_text()
    backups = list((root / ".gwork" / "backups").iterdir())
    assert backups and backups[0].read_text() == original
    assert bl.load_baseline(root, "docs/a.md") is not None
