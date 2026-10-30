"""Tests for the eredmine-agent-gateway CLI surface — generic commands only."""

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _src_on_path():
    src_path = Path("easy8/src").resolve()
    sys.path.insert(0, str(src_path))
    yield
    sys.path.remove(str(src_path))


def _import_cli():
    return importlib.import_module("eredmine_agent_gateway.cli")


def test_cli_module_importable():
    """The cli module can be imported."""
    cli = _import_cli()
    assert hasattr(cli, "main")


def test_cli_help_shows_generic_commands(capsys):
    """erag --help shows expected generic command structure."""
    cli = _import_cli()
    exit_code = cli.main(["--help"])
    captured = capsys.readouterr()
    help_text = captured.out

    assert exit_code == 0
    assert "usage: erag" in help_text
    # Generic commands should be listed
    assert "auth-check" in help_text
    assert "issue" in help_text
    assert "issues" in help_text
    assert "time-entries" in help_text


def test_cli_no_args_shows_help(capsys):
    """Running erag with no arguments shows help and exits 0."""
    cli = _import_cli()
    exit_code = cli.main([])
    captured = capsys.readouterr()
    help_text = captured.out

    assert exit_code == 0
    assert "usage: erag" in help_text


def test_cli_auth_check_missing_key_exits_nonzero(capsys, monkeypatch):
    """auth-check without REDMINE_API_KEY prints error and exits 1."""
    monkeypatch.delenv("REDMINE_API_KEY", raising=False)
    cli = _import_cli()
    exit_code = cli.main(["auth-check"])
    captured = capsys.readouterr()
    err_text = captured.err

    assert exit_code == 1
    assert "AUTH FAIL" in err_text
    assert "REDMINE_API_KEY" in err_text


def test_cli_auth_check_success(capsys, monkeypatch):
    """auth-check with valid key and mocked API returns 0."""
    monkeypatch.setenv("REDMINE_API_KEY", "test-key-123")
    cli = _import_cli()

    # Mock Easy8Manager.get_issues to return a minimal result
    # (simulates a successful reachability probe)
    import eredmine_agent_gateway.manager as mgr_mod

    def mock_init(
        self,
        api_key=None,
        base_url="",
        request_timeout=10,
        max_retries=3,
        retry_backoff=1.0,
    ):
        # Skip real client init; just set _client with a dummy base_url
        self._client = type(
            "FakeClient", (), {"_base_url": "https://easy8.example.com"}
        )()
        self._issues = None  # not needed for the mocked path

    monkeypatch.setattr(mgr_mod.Easy8Manager, "__init__", mock_init)

    monkeypatch.setattr(
        mgr_mod.Easy8Manager,
        "get_issues",
        lambda self, params=None: [{"id": 42, "subject": "dummy"}],
    )

    exit_code = cli.main(["auth-check"])
    captured = capsys.readouterr()
    out_text = captured.out

    assert exit_code == 0
    assert "AUTH OK" in out_text
    assert "easy8.example.com" in out_text
    assert "1 issue(s)" in out_text


def test_cli_no_reminder_or_job_commands_in_help(capsys):
    """CLI help must not contain reminder/job orchestration commands."""
    cli = _import_cli()
    exit_code = cli.main(["--help"])
    captured = capsys.readouterr()
    help_text = captured.out

    assert exit_code == 0
    forbidden = ["reminder", "remind", "job", "runner", "orchestrat"]
    for term in forbidden:
        msg = f"Forbidden term '{term}' found in CLI help"
        assert term not in help_text, msg


def test_cli_subcommand_registry_no_reminder_commands():
    """Verify the subcommand registry contains only generic commands."""
    cli = _import_cli()
    parser = cli._build_parser()

    # Collect registered subcommands
    subcommands = list(parser._subparsers._group_actions[0].choices.keys())
    expected = {
        "auth-check",
        "issue",
        "history",
        "issues",
        "time-entries",
        "sync",
        "report-base",
        "stats",
        "summary",
        "whoami",
        "projects",
        "mcp",
    }
    diff = set(subcommands) ^ expected
    assert set(subcommands) == expected, f"Unexpected commands: {diff}"


def test_cli_unknown_command_exits_nonzero(capsys):
    """An unknown command yields error and non-zero exit code."""
    cli = _import_cli()
    exit_code = cli.main(["nonexistent-command"])
    captured = capsys.readouterr()
    err_text = captured.err

    assert exit_code == 2  # argparse error
    assert "invalid choice" in err_text


def test_cli_issue_get_missing_id_shows_error(capsys):
    """issue without an ID shows argparse error."""
    cli = _import_cli()
    exit_code = cli.main(["issue"])
    captured = capsys.readouterr()
    err_text = captured.err

    assert exit_code == 2
    assert "required" in err_text
    assert "issue_id" in err_text
