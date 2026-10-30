"""Tests for the Open WebUI workspace tool (integrations/open_webui).

The tool file is loaded outside Open WebUI; the helpers below mirror how
Open WebUI discovers tool functions and parses the frontmatter.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import re
from importlib import metadata
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

import pytest

from eredmine_agent_gateway.exceptions import Easy8RequestError
from eredmine_agent_gateway.tools import TOOL_NAMES, Easy8Tools

TOOL_FILE = (
    Path(__file__).resolve().parents[1] / "integrations" / "open_webui" / "erag_tool.py"
)


def _load_tool_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("easy8_owui_tool", TOOL_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter(content: str) -> dict[str, str]:
    """Same rules as Open WebUI: first line is triple quotes, `key: value`."""
    lines = content.splitlines()
    assert lines[0].strip() == '"""'
    result: dict[str, str] = {}
    for line in lines[1:]:
        if '"""' in line:
            break
        match = re.match(r"^\s*([a-z_]+):\s*(.*)\s*$", line, re.IGNORECASE)
        if match:
            result[match.group(1)] = match.group(2).strip()
    return result


def _public_functions(tools: object) -> list[str]:
    """Same selection as Open WebUI's get_functions_from_tool."""
    return sorted(
        name
        for name in dir(tools)
        if callable(getattr(tools, name))
        and not name.startswith("_")
        and not inspect.isclass(getattr(tools, name))
    )


@pytest.fixture(scope="module")
def module() -> ModuleType:
    return _load_tool_module()


class RecordingManager:
    """Stands in for Easy8Manager and records the key used per call."""

    instances: ClassVar[list[RecordingManager]] = []

    def __init__(self, api_key=None, base_url=None, request_timeout=10, **_):
        self.api_key = api_key
        self.base_url = base_url
        self.request_timeout = request_timeout
        self.fail_with: Exception | None = None
        RecordingManager.instances.append(self)

    def get_current_user(self):
        return {"id": 1, "login": self.api_key, "firstname": "Jörg"}

    def get_issues_page(self, params):
        return [{"id": 5, "subject": "Prüfung", "status": {"id": 1, "name": "Neu"}}], 1

    def get_issue(self, issue_id, params=None):
        raise Easy8RequestError(f"GET failed for issue {issue_id}", status_code=403)


@pytest.fixture
def recording(module, monkeypatch) -> type[RecordingManager]:
    RecordingManager.instances = []
    monkeypatch.setattr(module, "Easy8Manager", RecordingManager)
    return RecordingManager


def _user(module: ModuleType, key: str) -> dict[str, Any]:
    return {"id": "u1", "valves": module.Tools.UserValves(easy8_api_key=key)}


def _run(coroutine):
    return asyncio.run(coroutine)


# --- file structure -----------------------------------------------------------


def test_frontmatter_declares_metadata_and_matching_release():
    frontmatter = _frontmatter(TOOL_FILE.read_text(encoding="utf-8"))
    version = metadata.version("eredmine-agent-gateway")

    assert frontmatter["title"] == "Easy8"
    assert frontmatter["version"] == version
    assert frontmatter["description"]
    assert frontmatter["required_open_webui_version"]
    assert frontmatter["requirements"] == (
        "eredmine-agent-gateway @ https://github.com/SvenTUM/eredmine-agent-gateway/archive/refs/tags/"
        f"v{version}.tar.gz"
    )


def test_file_is_independent_of_open_webui_internals():
    content = TOOL_FILE.read_text(encoding="utf-8")

    assert not re.search(r"^\s*(from|import)\s+open_webui", content, re.MULTILINE)
    # Open WebUI rewrites these import prefixes in tool sources.
    for fragment in ("from utils", "from apps", "from main", "from config"):
        assert fragment not in content


# --- tool surface -------------------------------------------------------------


def test_exposes_exactly_the_tool_layer_functions(module):
    assert _public_functions(module.Tools()) == sorted(TOOL_NAMES)


@pytest.mark.parametrize("tool_name", TOOL_NAMES)
def test_parameters_and_descriptions_match_tool_layer(module, tool_name):
    method = getattr(module.Tools, tool_name)
    reference = getattr(Easy8Tools, tool_name)

    params = {
        name: p.default
        for name, p in inspect.signature(method).parameters.items()
        if name != "self" and not name.startswith("__")
    }
    reference_params = {
        name: p.default
        for name, p in inspect.signature(reference).parameters.items()
        if name != "self"
    }

    assert params == reference_params
    assert method.__doc__ == inspect.cleandoc(reference.__doc__)
    assert inspect.iscoroutinefunction(method)


def test_user_key_field_is_masked_and_admin_valves_exist(module):
    key_field = module.Tools.UserValves.model_fields["easy8_api_key"]
    admin_fields = module.Tools.Valves.model_fields

    assert key_field.json_schema_extra == {"input": {"type": "password"}}
    assert set(admin_fields) == {"easy8_base_url", "request_timeout_seconds"}


# --- behaviour ----------------------------------------------------------------


@pytest.mark.parametrize("user", [None, {}, {"valves": None}])
def test_missing_key_returns_instruction_without_request(module, recording, user):
    result = _run(module.Tools().whoami(__user__=user))

    assert result == module.MISSING_KEY_MESSAGE
    assert recording.instances == []


def test_blank_key_counts_as_missing(module, recording):
    result = _run(module.Tools().whoami(__user__=_user(module, "   ")))
    assert result == module.MISSING_KEY_MESSAGE


def test_each_call_uses_the_calling_users_key(module, recording):
    tools = module.Tools()

    first = _run(tools.whoami(__user__=_user(module, "key-anna")))
    second = _run(tools.whoami(__user__=_user(module, "key-ben")))

    assert [m.api_key for m in recording.instances] == ["key-anna", "key-ben"]
    assert '"login":"key-anna"' in first and '"login":"key-ben"' in second


def test_output_is_identical_to_tool_layer(module, recording):
    result = _run(
        module.Tools().search_issues(
            project_id=3, __user__=_user(module, "k"), __event_emitter__=None
        )
    )
    expected = Easy8Tools(RecordingManager(api_key="k")).search_issues(project_id=3)

    assert result == expected


def test_admin_valves_are_passed_to_the_manager(module, recording):
    tools = module.Tools()
    tools.valves = module.Tools.Valves(
        easy8_base_url=" https://easy8.internal ", request_timeout_seconds=30
    )
    _run(tools.whoami(__user__=_user(module, "k")))

    manager = recording.instances[0]
    assert (manager.base_url, manager.request_timeout) == ("https://easy8.internal", 30)


def test_empty_base_url_valve_defers_to_package_resolution(module, recording):
    _run(module.Tools().whoami(__user__=_user(module, "k")))
    assert recording.instances[0].base_url is None


def test_errors_are_returned_as_text_without_key(module, recording):
    result = _run(
        module.Tools().get_issue(issue_id=9, __user__=_user(module, "secret-key-9"))
    )

    assert result.startswith("Error: Access denied (HTTP 403)")
    assert "secret-key-9" not in result


def test_invalid_arguments_are_returned_as_text(module, recording):
    result = _run(
        module.Tools().search_issues(status="pending", __user__=_user(module, "k"))
    )
    assert result.startswith("Error: status must be")


def test_status_events_are_emitted(module, recording):
    events: list[dict[str, Any]] = []

    async def emitter(event):
        events.append(event)

    _run(module.Tools().whoami(__user__=_user(module, "k"), __event_emitter__=emitter))

    assert [e["type"] for e in events] == ["status", "status"]
    assert [e["data"]["done"] for e in events] == [False, True]
