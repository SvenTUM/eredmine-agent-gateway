"""Tests for the CLI and MCP adapters of the agent tool layer.

Both adapters must return exactly the tool-layer output (parity) and turn
failures into concise, credential-free messages.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import pytest
from mcp import Client

from eredmine_agent_gateway import cli
from eredmine_agent_gateway.exceptions import Easy8RequestError
from eredmine_agent_gateway.mcp_server import build_server
from eredmine_agent_gateway.tools import TOOL_NAMES, Easy8Tools

SECRET_KEY = "secret-api-key-123"


class FakeManager:
    """Minimal Easy8Manager stand-in returning fixed Redmine payloads."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.calls: list[tuple[str, Any]] = []

    def _record(self, name: str, params: Any) -> None:
        self.calls.append((name, params))
        if self.fail_with is not None:
            raise self.fail_with

    def get_current_user(self):
        self._record("user", None)
        return {"id": 3, "login": "ben", "firstname": "Ben", "lastname": "Müller"}

    def get_projects_page(self, params):
        self._record("projects", params)
        return [{"id": 1, "name": "Portal", "identifier": "portal", "status": 1}], 1

    def get_issues_page(self, params):
        self._record("issues", params)
        issue = {"id": 7, "subject": "Fehler", "status": {"id": 1, "name": "Neu"}}
        return [issue], 1

    def get_issue(self, issue_id, params=None):
        self._record("issue", (issue_id, params))
        return {"id": issue_id, "subject": "Fehler", "description": "Text"}

    def get_time_entries_page(self, params):
        self._record("time_entries", params)
        entry = {"id": 1, "hours": 2.5, "spent_on": "2026-08-18",
                 "user": {"id": 3, "name": "Ben"}}
        return [entry], 1


TOOL_ARGUMENTS: dict[str, dict[str, Any]] = {
    "whoami": {},
    "list_projects": {"name_contains": "port"},
    "search_issues": {"project_id": 1, "assigned_to": "me"},
    "get_issue": {"issue_id": 7},
    "get_issue_history": {"issue_id": 7},
    "list_time_entries": {"user": "me", "group_by": "user"},
}

CLI_ARGUMENTS: dict[str, list[str]] = {
    "whoami": ["whoami"],
    "list_projects": ["projects", "--name", "port"],
    "search_issues": ["issues", "--project-id", "1", "--assigned-to", "me"],
    "get_issue": ["issue", "7"],
    "get_issue_history": ["history", "7"],
    "list_time_entries": ["time-entries", "--user", "me", "--group-by", "user"],
}


def _expected(tool_name: str) -> str:
    return getattr(Easy8Tools(FakeManager()), tool_name)(
        **TOOL_ARGUMENTS[tool_name]
    )


@pytest.fixture
def cli_manager(monkeypatch) -> FakeManager:
    manager = FakeManager()
    monkeypatch.setenv("REDMINE_API_KEY", SECRET_KEY)
    monkeypatch.setattr(cli, "Easy8Manager", lambda: manager)
    return manager


# --- CLI ----------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", list(CLI_ARGUMENTS))
def test_cli_prints_tool_output_unchanged(tool_name, cli_manager, capsys):
    exit_code = cli.main(CLI_ARGUMENTS[tool_name])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == _expected(tool_name) + "\n"
    json.loads(captured.out)
    assert captured.err == ""


def test_cli_maps_all_filter_arguments(cli_manager, capsys):
    cli.main(
        ["issues", "--status", "all", "--updated-since", "2026-08-01",
         "--limit", "10", "--offset", "20"]
    )
    cli.main(
        ["time-entries", "--project-id", "4", "--issue-id", "9",
         "--from", "2026-08-01", "--to", "2026-08-31"]
    )
    cli.main(["issue", "7", "--max-journals", "0"])
    cli.main(["projects", "--include-closed", "--limit", "5", "--offset", "5"])

    issues_params = cli_manager.calls[0][1]
    assert issues_params["status_id"] == "*"
    assert issues_params["updated_on"] == ">=2026-08-01"
    assert (issues_params["limit"], issues_params["offset"]) == (10, 20)
    assert cli_manager.calls[1][1] == {
        "project_id": 4, "issue_id": 9, "from": "2026-08-01",
        "to": "2026-08-31", "limit": 50, "offset": 0,
    }
    assert cli_manager.calls[2][0] == "issue"


def test_cli_invalid_argument_value_reports_error(cli_manager, capsys):
    exit_code = cli.main(["issues", "--assigned-to", "somebody"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert "ERROR: assigned_to must be 'me'" in captured.err


def test_cli_invalid_group_by_is_rejected_by_parser(cli_manager, capsys):
    assert cli.main(["time-entries", "--group-by", "customer"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_cli_http_error_is_described_without_key(monkeypatch, capsys):
    manager = FakeManager(fail_with=Easy8RequestError("GET failed", 404))
    monkeypatch.setenv("REDMINE_API_KEY", SECRET_KEY)
    monkeypatch.setattr(cli, "Easy8Manager", lambda: manager)

    exit_code = cli.main(["issue", "99"])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "Not found (HTTP 404)" in err
    assert SECRET_KEY not in err


def test_cli_missing_api_key(monkeypatch, capsys):
    monkeypatch.delenv("REDMINE_API_KEY", raising=False)
    assert cli.main(["whoami"]) == 1
    assert "REDMINE_API_KEY" in capsys.readouterr().err


def test_cli_mcp_without_extra_names_the_extra(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "eredmine_agent_gateway.mcp_server", None)

    exit_code = cli.main(["mcp"])

    assert exit_code == 1
    assert "eredmine-agent-gateway[mcp]" in capsys.readouterr().err


# --- MCP ----------------------------------------------------------------------


def _run(coroutine):
    return asyncio.run(coroutine)


async def _list_tools(server):
    async with Client(server) as client:
        return (await client.list_tools()).tools


async def _call(server, name: str, arguments: dict[str, Any]):
    async with Client(server) as client:
        return await client.call_tool(name, arguments)


def test_mcp_lists_exactly_the_read_only_tools():
    tools = _run(_list_tools(build_server(FakeManager)))

    assert [tool.name for tool in tools] == list(TOOL_NAMES)
    for tool in tools:
        assert tool.description
        assert tool.input_schema["type"] == "object"
        assert tool.annotations.read_only_hint is True
        for prop in tool.input_schema.get("properties", {}).values():
            assert prop.get("description"), tool.name


def test_mcp_schema_marks_required_parameters():
    tools = {t.name: t for t in _run(_list_tools(build_server(FakeManager)))}

    assert tools["get_issue"].input_schema["required"] == ["issue_id"]
    assert tools["project_summary"].input_schema["required"] == ["project_id"]
    assert "required" not in tools["search_issues"].input_schema


@pytest.mark.parametrize("tool_name", list(TOOL_ARGUMENTS))
def test_mcp_call_returns_tool_output_unchanged(tool_name):
    result = _run(
        _call(build_server(FakeManager), tool_name, TOOL_ARGUMENTS[tool_name])
    )

    assert result.is_error is False
    assert [block.text for block in result.content] == [_expected(tool_name)]
    assert result.structured_content is None


def test_mcp_invalid_argument_is_tool_error():
    result = _run(
        _call(build_server(FakeManager), "search_issues", {"status": "pending"})
    )

    assert result.is_error is True
    assert "status must be" in result.content[0].text


def test_mcp_http_error_is_described_without_key():
    def factory():
        return FakeManager(fail_with=Easy8RequestError("GET failed", 403))

    result = _run(_call(build_server(factory), "get_issue", {"issue_id": 1}))

    assert result.is_error is True
    assert "Access denied (HTTP 403)" in result.content[0].text
    assert SECRET_KEY not in result.content[0].text


def test_mcp_missing_api_key_is_reported_per_call(monkeypatch):
    monkeypatch.delenv("REDMINE_API_KEY", raising=False)

    result = _run(_call(build_server(), "whoami", {}))

    assert result.is_error is True
    assert "REDMINE_API_KEY" in result.content[0].text
