from click.testing import CliRunner

from gwork.cli import main


runner = CliRunner()


def test_root_help_lists_public_commands():
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "sync" in result.output
    assert "style" in result.output
    assert "init" in result.output
    assert "organize" in result.output
    assert "item" in result.output
    assert "Sync and style Google Docs and Sheets" in result.output


def test_init_delegates_to_manifest_initializer(monkeypatch):
    calls = []

    def fake_init(path, doc_id, account):
        calls.append((path.name, doc_id, account))
        return 0

    monkeypatch.setattr("gwork.cli.cmd_manifest_init", fake_init)
    result = runner.invoke(
        main,
        [
            "init",
            "--manifest",
            ".gwork.yaml",
            "--doc-id",
            "DOC",
            "--account",
            "user@example.com",
        ],
    )

    assert result.exit_code == 0
    assert calls == [(".gwork.yaml", "DOC", "user@example.com")]


def test_style_audit_can_skip_template_refresh(monkeypatch):
    calls = []

    def fake_audit(path, account, tab, refresh):
        calls.append((path.name, account, tab, refresh))
        return 0

    monkeypatch.setattr("gwork.cli.cmd_style_audit", fake_audit)
    result = runner.invoke(
        main,
        [
            "style",
            "audit",
            "--manifest",
            "pyproject.toml",
            "--no-refresh-template",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("pyproject.toml", None, None, False)]


def test_item_add_is_plan_only_by_default(monkeypatch, tmp_path):
    manifest = tmp_path / ".gwork.yaml"
    manifest.write_text("version: 1\nitems: []\n", encoding="utf-8")
    plan = {
        "manifest_path": manifest,
        "manifest": {},
        "actions": [{"action": "create_local", "local": "docs/brief/main.md"}],
    }
    calls = []
    monkeypatch.setattr("gwork.cli.plan_organization", lambda *args, **kwargs: plan)
    monkeypatch.setattr("gwork.cli.apply_organization", lambda value: calls.append(value))

    result = runner.invoke(main, [
        "item", "add", "--root", str(tmp_path),
        "--drive-id", "DOC", "--type", "doc",
    ])

    assert result.exit_code == 0
    assert "Plan only" in result.output
    assert calls == []


def test_organize_apply_writes_plan(monkeypatch, tmp_path):
    manifest = tmp_path / ".gwork.yaml"
    manifest.write_text("version: 1\nitems: []\n", encoding="utf-8")
    plan = {"manifest_path": manifest, "manifest": {}, "actions": []}
    calls = []
    monkeypatch.setattr("gwork.cli.plan_organization", lambda *args, **kwargs: plan)
    monkeypatch.setattr("gwork.cli.apply_organization", lambda value: calls.append(value))

    result = runner.invoke(main, ["organize", "--root", str(tmp_path), "--apply"])

    assert result.exit_code == 0
    assert "Applied organization" in result.output
    assert calls == [plan]


def test_item_add_apply_discovers_and_writes_nested_mirror(monkeypatch, tmp_path):
    (tmp_path / ".gwork.yaml").write_text(
        "version: 1\n"
        "transport:\n"
        "  provider: gog\n"
        "  account: user@example.com\n"
        "items: []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "gwork.sync.organization.drive_get",
        lambda *_: {"file": {"name": "Team plan"}},
    )
    monkeypatch.setattr(
        "gwork.sync.organization.docs_list_tabs",
        lambda *_: [
            {
                "tabProperties": {"tabId": "root", "title": "Summary"},
                "childTabs": [
                    {"tabProperties": {"tabId": "child", "title": "Appendix"}}
                ],
            }
        ],
    )

    result = runner.invoke(main, [
        "item", "add", "--root", str(tmp_path),
        "--drive-id", "DOC", "--type", "doc", "--apply",
    ])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "docs/team-plan/summary.md").exists()
    assert (tmp_path / "docs/team-plan/summary/appendix.md").exists()
    written = (tmp_path / ".gwork.yaml").read_text(encoding="utf-8")
    assert "version: 2" in written
    assert "id: child" in written
