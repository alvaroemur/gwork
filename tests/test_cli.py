from click.testing import CliRunner

from gwork.cli import main


runner = CliRunner()


def test_root_help_lists_public_commands():
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "sync" in result.output
    assert "style" in result.output
    assert "init" in result.output
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
