"""Tests for the read-only agent tool layer (eredmine_agent_gateway.tools)."""

from __future__ import annotations

import inspect
import json
from datetime import date
from typing import Any

import pytest

from eredmine_agent_gateway.exceptions import Easy8ConfigurationError, Easy8RequestError
from eredmine_agent_gateway.tools import (
    AGGREGATION_CAP,
    TOOL_NAMES,
    Easy8Tools,
    describe_error,
    parse_tool_docstring,
)


class FakeManager:
    """In-memory stand-in for Easy8Manager that records request params."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.user: dict[str, Any] = {}
        self.projects: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.issues_total: int | None = None
        self.issue: dict[str, Any] = {}
        self.time_entries: list[dict[str, Any]] = []
        self.statuses: list[dict[str, Any]] = []
        self.priorities: list[dict[str, Any]] = []
        self.users: dict[int, dict[str, Any]] = {}

    def get_current_user(self) -> dict[str, Any]:
        self.calls.append(("user", None))
        return self.user

    def get_projects_page(self, params):
        self.calls.append(("projects", params))
        start, limit = params["offset"], params["limit"]
        return self.projects[start : start + limit], len(self.projects)

    def get_issues_page(self, params):
        self.calls.append(("issues", params))
        total = self.issues_total if self.issues_total is not None else len(self.issues)
        return self.issues, total

    def get_issue(self, issue_id, params=None):
        self.calls.append(("issue", (issue_id, params)))
        return self.issue

    def get_time_entries_page(self, params):
        self.calls.append(("time_entries", params))
        start, limit = params["offset"], params["limit"]
        return self.time_entries[start : start + limit], len(self.time_entries)

    def get_issue_statuses(self):
        self.calls.append(("statuses", None))
        return self.statuses

    def get_issue_priorities(self):
        self.calls.append(("priorities", None))
        return self.priorities

    def get_user(self, user_id):
        self.calls.append(("user_lookup", user_id))
        if user_id not in self.users:
            raise Easy8RequestError("Not found", status_code=404)
        return self.users[user_id]


@pytest.fixture
def manager() -> FakeManager:
    return FakeManager()


@pytest.fixture
def tools(manager: FakeManager) -> Easy8Tools:
    return Easy8Tools(manager)


def _ref(ref_id: int, name: str) -> dict[str, Any]:
    return {"id": ref_id, "name": name}


def _raw_issue(issue_id: int) -> dict[str, Any]:
    """A realistic Redmine issue payload as returned by issues.json."""
    return {
        "id": issue_id,
        "project": _ref(42, "Kundenportal Müller"),
        "tracker": _ref(1, "Fehler"),
        "status": _ref(2, "In Bearbeitung"),
        "priority": _ref(3, "Hoch"),
        "author": _ref(5, "Anna Autorin"),
        "assigned_to": _ref(7, "Ben Bearbeiter"),
        "subject": f"Login schlägt fehl #{issue_id}",
        "description": "Beim Login erscheint ein Timeout. " * 12,
        "start_date": "2026-08-01",
        "due_date": None,
        "done_ratio": 0,
        "is_private": False,
        "estimated_hours": None,
        "custom_fields": [
            {"id": 1, "name": "Kunde", "value": "Müller GmbH"},
            {"id": 2, "name": "Ticketnummer extern", "value": ""},
            {"id": 3, "name": "Abrechenbar", "value": "1"},
        ],
        "created_on": "2026-08-01T08:15:00Z",
        "updated_on": "2026-08-18T16:40:12Z",
        "closed_on": None,
    }


def _raw_time_entry(entry_id: int, hours: float, user: str, day: str) -> dict:
    return {
        "id": entry_id,
        "project": _ref(42, "Kundenportal"),
        "issue": {"id": 100 + entry_id % 3},
        "user": _ref(len(user), user),
        "activity": _ref(9, "Entwicklung"),
        "hours": hours,
        "comments": "Analyse",
        "spent_on": day,
        "created_on": f"{day}T17:00:00Z",
        "updated_on": f"{day}T17:00:00Z",
        "custom_fields": [{"id": 4, "name": "Ort", "value": "Remote"}],
    }


# --- output contract --------------------------------------------------------


def test_json_output_is_compact_and_unescaped(tools, manager):
    manager.issues = [_raw_issue(1)]
    output = tools.search_issues()

    assert "\n" not in output
    assert ", " not in output and '": ' not in output
    assert "schlägt" in output and "\\u" not in output
    assert "null" not in output


def test_search_items_are_flattened_and_without_empty_fields(tools, manager):
    manager.issues = [_raw_issue(1)]
    item = json.loads(tools.search_issues())["items"][0]

    assert item == {
        "id": 1,
        "subject": "Login schlägt fehl #1",
        "project": "Kundenportal Müller",
        "tracker": "Fehler",
        "status": "In Bearbeitung",
        "priority": "Hoch",
        "assigned_to": "Ben Bearbeiter",
        "updated": "2026-08-18",
    }


@pytest.mark.parametrize(
    ("tool_name", "attribute", "raw"),
    [
        ("search_issues", "issues", [_raw_issue(i) for i in range(25)]),
        (
            "list_time_entries",
            "time_entries",
            [_raw_time_entry(i, 1.5, "Ben", "2026-08-18") for i in range(50)],
        ),
        (
            "list_projects",
            "projects",
            [
                {
                    "id": i,
                    "name": f"Projekt {i}",
                    "identifier": f"projekt-{i}",
                    "description": "Beschreibung des Kundenprojekts. " * 4,
                    "homepage": "",
                    "status": 1,
                    "is_public": False,
                    "inherit_members": False,
                    "created_on": "2025-01-01T10:00:00Z",
                    "updated_on": "2026-01-01T10:00:00Z",
                }
                for i in range(50)
            ],
        ),
    ],
)
def test_list_outputs_are_at_least_half_the_raw_size(
    tools, manager, tool_name, attribute, raw
):
    setattr(manager, attribute, raw)
    output = getattr(tools, tool_name)()
    raw_size = len(json.dumps({attribute: raw, "total_count": len(raw)}))

    assert len(output) <= raw_size * 0.5


# --- whoami -----------------------------------------------------------------


def test_whoami(tools, manager):
    manager.user = {
        "id": 12,
        "login": "bbearbeiter",
        "firstname": "Ben",
        "lastname": "Bearbeiter",
        "mail": "x@example.com",
        "api_key": "should-never-leak",
    }
    assert json.loads(tools.whoami()) == {
        "id": 12,
        "login": "bbearbeiter",
        "name": "Ben Bearbeiter",
    }


# --- list_projects ----------------------------------------------------------


def test_list_projects_filters_and_pages_through_api(tools, manager):
    manager.projects = [
        {"id": i, "name": f"Alpha {i}", "identifier": f"a{i}", "status": 1}
        for i in range(150)
    ] + [
        {"id": 900, "name": "Beta", "identifier": "beta", "status": 1,
         "parent": _ref(1, "Alpha 1")},
        {"id": 901, "name": "Old Beta", "identifier": "old", "status": 5},
    ]

    result = json.loads(tools.list_projects(name_contains="BETA"))

    assert result == {
        "items": [{"id": 900, "identifier": "beta", "name": "Beta", "parent": "Alpha 1"}],
        "total": 1,
    }
    api_offsets = [params["offset"] for kind, params in manager.calls]
    assert api_offsets == [0, 100]


def test_list_projects_include_closed_and_pagination(tools, manager):
    manager.projects = [
        {"id": 1, "name": "A", "identifier": "a", "status": 1},
        {"id": 2, "name": "B", "identifier": "b", "status": 5},
        {"id": 3, "name": "C", "identifier": "c", "status": 9},
    ]

    first = json.loads(tools.list_projects(include_closed=True, limit=2))
    second = json.loads(tools.list_projects(include_closed=True, limit=2, offset=2))

    assert [p["id"] for p in first["items"]] == [1, 2]
    assert first["items"][1]["status"] == "closed"
    assert first["next_offset"] == 2
    assert second == {
        "items": [{"id": 3, "identifier": "c", "name": "C", "status": "archived"}],
        "total": 3,
    }


# --- search_issues ----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [("open", "open"), ("CLOSED", "closed"), ("all", "*"), ("5", "5")],
)
def test_search_issues_status_mapping(tools, manager, status, expected):
    tools.search_issues(status=status)
    assert manager.calls[-1][1]["status_id"] == expected


def test_search_issues_filter_mapping(tools, manager):
    tools.search_issues(
        project_id=42,
        assigned_to="me",
        updated_since="2026-08-01",
        limit=10,
        offset=20,
    )
    assert manager.calls[-1][1] == {
        "status_id": "open",
        "sort": "updated_on:desc",
        "limit": 10,
        "offset": 20,
        "project_id": 42,
        "assigned_to_id": "me",
        "updated_on": ">=2026-08-01",
    }


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"status": "pending"}, "status must be"),
        ({"assigned_to": "ben"}, "assigned_to must be"),
        ({"updated_since": "01.08.2026"}, "YYYY-MM-DD"),
        ({"limit": 0}, "limit must be between 1 and 100"),
        ({"limit": 101}, "limit must be between 1 and 100"),
        ({"offset": -1}, "offset must not be negative"),
    ],
)
def test_search_issues_rejects_invalid_arguments(tools, manager, kwargs, message):
    with pytest.raises(ValueError, match=message):
        tools.search_issues(**kwargs)
    assert manager.calls == []


def test_search_issues_envelope_next_offset(tools, manager):
    manager.issues = [_raw_issue(i) for i in range(25)]
    manager.issues_total = 60

    first = json.loads(tools.search_issues())

    assert first["total"] == 60 and first["next_offset"] == 25
    manager.issues = manager.issues[:10]
    last = json.loads(tools.search_issues(offset=50, limit=25))
    assert "next_offset" not in last


def test_search_issues_empty_result_keeps_envelope(tools, manager):
    assert json.loads(tools.search_issues()) == {"items": [], "total": 0}


# --- get_issue --------------------------------------------------------------


def _journal(journal_id: int, notes: str, private: bool = False) -> dict:
    return {
        "id": journal_id,
        "user": _ref(7, "Ben Bearbeiter"),
        "notes": notes,
        "private_notes": private,
        "created_on": f"2026-08-{journal_id:02d}T10:00:00Z",
        "details": [],
    }


def test_get_issue_detail(tools, manager):
    issue = _raw_issue(10)
    issue.update(
        {
            "parent": {"id": 5},
            "spent_hours": 3.5,
            "relations": [
                {"id": 1, "issue_id": 10, "issue_to_id": 11,
                 "relation_type": "blocks", "delay": None},
                {"id": 2, "issue_id": 12, "issue_to_id": 10,
                 "relation_type": "precedes", "delay": 2},
            ],
            "children": [{"id": 13, "tracker": _ref(2, "Aufgabe"), "subject": "Teil"}],
            "attachments": [
                {"id": 1, "filename": "log.txt", "filesize": 1024,
                 "content_url": "https://x/attachments/1", "author": _ref(5, "A"),
                 "created_on": "2026-08-02T09:00:00Z"}
            ],
            "journals": [
                _journal(1, "Erste Rückmeldung"),
                {**_journal(2, ""), "details": [{"name": "status_id"}]},
                _journal(3, "Interne Einschätzung", private=True),
            ],
        }
    )
    manager.issue = issue

    detail = json.loads(tools.get_issue(10))

    assert manager.calls == [
        ("issue", (10, {"include": "journals,relations,children,attachments"}))
    ]
    assert detail["project_id"] == 42
    assert detail["assigned_to_id"] == 7
    assert detail["parent_id"] == 5
    assert detail["done_ratio"] == 0
    assert detail["custom_fields"] == {"Kunde": "Müller GmbH", "Abrechenbar": "1"}
    assert detail["relations"] == [
        {"type": "blocks", "issue_id": 11},
        {"type": "follows", "issue_id": 12, "delay": 2},
    ]
    assert detail["children"] == [{"id": 13, "subject": "Teil", "tracker": "Aufgabe"}]
    assert detail["attachments"] == [
        {"filename": "log.txt", "size": 1024, "created": "2026-08-02"}
    ]
    assert detail["journals"] == [
        {"date": "2026-08-01", "author": "Ben Bearbeiter", "notes": "Erste Rückmeldung"},
        {
            "date": "2026-08-03",
            "author": "Ben Bearbeiter",
            "notes": "Interne Einschätzung",
            "private": True,
        },
    ]
    assert "journals_omitted" not in detail
    assert "due_date" not in detail and "private" not in detail


def test_get_issue_caps_journals(tools, manager):
    manager.issue = {"id": 1, "journals": [_journal(i, f"n{i}") for i in range(1, 8)]}

    capped = json.loads(tools.get_issue(1, max_journals=2))
    none = json.loads(tools.get_issue(1, max_journals=0))

    assert [j["notes"] for j in capped["journals"]] == ["n6", "n7"]
    assert capped["journals_omitted"] == 5
    assert "journals" not in none and none["journals_omitted"] == 7


def test_get_issue_rejects_negative_max_journals(tools):
    with pytest.raises(ValueError, match="max_journals"):
        tools.get_issue(1, max_journals=-1)


def test_get_issue_empty_payload_is_not_found(tools):
    with pytest.raises(Easy8RequestError) as exc_info:
        tools.get_issue(99)
    assert exc_info.value.status_code == 404


# --- list_time_entries ------------------------------------------------------


def test_list_time_entries_filter_mapping_and_items(tools, manager):
    manager.time_entries = [_raw_time_entry(1, 2.0, "Ben", "2026-08-18")]

    result = json.loads(
        tools.list_time_entries(
            user="me",
            project_id=42,
            issue_id=101,
            from_date="2026-08-01",
            to_date="2026-08-31",
        )
    )

    assert manager.calls[-1][1] == {
        "user_id": "me",
        "project_id": 42,
        "issue_id": 101,
        "from": "2026-08-01",
        "to": "2026-08-31",
        "limit": 50,
        "offset": 0,
    }
    assert result == {
        "items": [
            {
                "id": 1,
                "date": "2026-08-18",
                "hours": 2.0,
                "user": "Ben",
                "project": "Kundenportal",
                "issue_id": 101,
                "activity": "Entwicklung",
                "comments": "Analyse",
            }
        ],
        "total": 1,
    }


def test_list_time_entries_group_by_user(tools, manager):
    manager.time_entries = [
        _raw_time_entry(i, 1.25, "Ben" if i % 2 else "Anna", "2026-08-18")
        for i in range(150)
    ]

    result = json.loads(tools.list_time_entries(project_id=42, group_by="user"))

    assert result == {
        "total_hours": 187.5,
        "entry_count": 150,
        "groups": [
            {"key": "Anna", "hours": 93.75, "entries": 75},
            {"key": "Ben", "hours": 93.75, "entries": 75},
        ],
    }
    offsets = [params["offset"] for _, params in manager.calls]
    assert offsets == [0, 100]


def test_list_time_entries_group_by_date_and_issue(tools, manager):
    manager.time_entries = [
        _raw_time_entry(1, 1.0, "Ben", "2026-08-19"),
        _raw_time_entry(2, 2.0, "Ben", "2026-08-18"),
        {**_raw_time_entry(3, 4.0, "Ben", "2026-08-18"), "issue": None},
    ]

    by_date = json.loads(tools.list_time_entries(group_by="date"))
    by_issue = json.loads(tools.list_time_entries(group_by="issue"))

    assert [g["key"] for g in by_date["groups"]] == ["2026-08-18", "2026-08-19"]
    assert by_issue["groups"][0] == {"key": "(none)", "hours": 4.0, "entries": 1}


def test_list_time_entries_group_by_flags_incomplete_above_cap(tools, manager):
    manager.time_entries = [
        _raw_time_entry(i, 1.0, "Ben", "2026-08-18")
        for i in range(AGGREGATION_CAP + 5)
    ]

    result = json.loads(tools.list_time_entries(group_by="project"))

    assert result["entry_count"] == AGGREGATION_CAP
    assert result["incomplete"] is True


def test_list_time_entries_rejects_unknown_group_by(tools, manager):
    with pytest.raises(ValueError, match="group_by must be one of"):
        tools.list_time_entries(group_by="customer")
    assert manager.calls == []


# --- project_summary --------------------------------------------------------


def test_project_summary_delegates_to_generate_summary(tools, manager, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_summary(**kwargs):
        captured.update(kwargs)
        return "# Projektzusammenfassung"

    monkeypatch.setattr("eredmine_agent_gateway.tools.generate_summary", fake_summary)

    assert tools.project_summary(42, stale_days=7) == "# Projektzusammenfassung"
    assert captured == {"project_id": 42, "stale_days": 7, "manager": manager}


# --- error messages and documentation ---------------------------------------


@pytest.mark.parametrize(
    ("status", "fragment"),
    [(401, "API key is invalid"), (403, "permissions"), (404, "not visible")],
)
def test_describe_error_status_messages(status, fragment):
    message = describe_error(Easy8RequestError("GET failed", status_code=status))
    assert fragment in message


def test_describe_error_passes_other_errors_through():
    assert describe_error(Easy8RequestError("Network error 500")) == (
        "Network error 500"
    )
    assert describe_error(Easy8ConfigurationError("Missing key")) == "Missing key"
    assert describe_error(ValueError("bad limit")) == "bad limit"


def test_every_tool_documents_all_parameters():
    for name in TOOL_NAMES:
        method = getattr(Easy8Tools, name)
        description, params = parse_tool_docstring(method.__doc__)
        signature_params = [
            p for p in inspect.signature(method).parameters if p != "self"
        ]
        assert description, name
        assert list(params) == signature_params, name


# --- get_issue_history --------------------------------------------------------


def _change(timestamp, author, *details):
    return {
        "id": hash(timestamp) % 1000,
        "created_on": timestamp,
        "user": author,
        "notes": "",
        "details": [
            {"property": "attr", "name": name, "old_value": old, "new_value": new}
            for name, old, new in details
        ],
    }


def _history_issue() -> dict[str, Any]:
    return {
        "id": 77,
        "subject": "Schnittstelle",
        "status": _ref(10, "Kunde prüft"),
        "priority": _ref(3, "Hoch"),
        "author": _ref(1, "Anna Autorin"),
        "assigned_to": _ref(2, "Ben Bearbeiter"),
        "created_on": "2026-09-01T08:00:00Z",
        "journals": [
            _change(
                "2026-09-03T09:00:00Z",
                _ref(1, "Anna Autorin"),
                ("status_id", "1", "19"),
                ("assigned_to_id", None, "5"),
            ),
            _change(
                "2026-09-10T09:00:00Z",
                _ref(2, "Ben Bearbeiter"),
                ("status_id", "19", "10"),
                ("assigned_to_id", "5", "2"),
                ("done_ratio", "0", "80"),
                ("due_date", "2026-09-15", "2026-09-30"),
                ("subject", "Alt", "Neu"),
            ),
        ],
    }


@pytest.fixture
def history_manager(manager: FakeManager, monkeypatch) -> FakeManager:
    monkeypatch.setattr("eredmine_agent_gateway.tools._today", lambda: date(2026, 9, 20))
    manager.issue = _history_issue()
    manager.statuses = [
        {"id": 1, "name": "Offen", "is_closed": False},
        {"id": 19, "name": "In Umsetzung", "is_closed": False},
        {"id": 10, "name": "Kunde prüft", "is_closed": False},
    ]
    manager.users = {5: {"id": 5, "firstname": "Clara", "lastname": "Consult"}}
    return manager


def test_get_issue_history_periods_and_changes(tools, history_manager):
    result = json.loads(tools.get_issue_history(77))

    assert result["status"] == "Kunde prüft"
    assert result["status_since"] == "2026-09-10"
    assert result["days_in_status"] == 10
    assert result["status_periods"] == [
        {"status": "Offen", "from": "2026-09-01", "to": "2026-09-03", "days": 2},
        {"status": "In Umsetzung", "from": "2026-09-03", "to": "2026-09-10", "days": 7},
        {"status": "Kunde prüft", "from": "2026-09-10", "days": 10},
    ]
    assert result["changes"] == [
        {"date": "2026-09-03", "by": "Anna Autorin", "field": "status",
         "from": "Offen", "to": "In Umsetzung"},
        {"date": "2026-09-03", "by": "Anna Autorin", "field": "assignee",
         "to": "Clara Consult"},
        {"date": "2026-09-10", "by": "Ben Bearbeiter", "field": "status",
         "from": "In Umsetzung", "to": "Kunde prüft"},
        {"date": "2026-09-10", "by": "Ben Bearbeiter", "field": "assignee",
         "from": "Clara Consult", "to": "Ben Bearbeiter"},
        {"date": "2026-09-10", "by": "Ben Bearbeiter", "field": "done_ratio",
         "from": 0, "to": 80},
        {"date": "2026-09-10", "by": "Ben Bearbeiter", "field": "due_date",
         "from": "2026-09-15", "to": "2026-09-30"},
    ]
    assert "changes_omitted" not in result
    assert history_manager.calls[0] == ("issue", (77, {"include": "journals"}))


def test_get_issue_history_loads_lookups_once_and_lazily(tools, history_manager):
    tools.get_issue_history(77)

    kinds = [kind for kind, _ in history_manager.calls]
    assert kinds.count("statuses") == 1
    assert "priorities" not in kinds  # no priority change in this history
    assert [call for call in history_manager.calls if call[0] == "user_lookup"] == [
        ("user_lookup", 5)
    ]


def test_get_issue_history_limits_changes(tools, history_manager):
    result = json.loads(tools.get_issue_history(77, max_changes=2))

    assert [change["field"] for change in result["changes"]] == [
        "done_ratio",
        "due_date",
    ]
    assert result["changes_omitted"] == 4
    assert len(result["status_periods"]) == 3


def test_get_issue_history_without_changes(tools, history_manager):
    result = json.loads(tools.get_issue_history(77, max_changes=0))

    assert "changes" not in result
    assert result["changes_omitted"] == 6


def test_get_issue_history_falls_back_to_ids(tools, history_manager):
    history_manager.statuses = []
    history_manager.users = {}
    result = json.loads(tools.get_issue_history(77))

    assert result["status_periods"][0]["status"] == "status 1"
    assert result["status_periods"][-1]["status"] == "Kunde prüft"
    assert result["changes"][1]["to"] == "user 5"


def test_get_issue_history_resolves_priorities(tools, history_manager):
    history_manager.issue["journals"].append(
        _change("2026-09-12T09:00:00Z", _ref(2, "Ben Bearbeiter"),
                ("priority_id", "2", "3"))
    )
    history_manager.priorities = [{"id": 2, "name": "Normal"}]
    result = json.loads(tools.get_issue_history(77))

    assert result["changes"][-1] == {
        "date": "2026-09-12", "by": "Ben Bearbeiter", "field": "priority",
        "from": "Normal", "to": "Hoch",
    }


def test_get_issue_history_without_status_changes(tools, manager, monkeypatch):
    monkeypatch.setattr("eredmine_agent_gateway.tools._today", lambda: date(2026, 9, 20))
    manager.issue = {
        "id": 8,
        "status": _ref(1, "Offen"),
        "created_on": "2026-09-15T08:00:00Z",
        "journals": [{"id": 1, "notes": "Nur ein Kommentar", "details": []}],
    }
    result = json.loads(tools.get_issue_history(8))

    assert result["status_since"] == "2026-09-15"
    assert result["days_in_status"] == 5
    assert result["status_periods"] == [
        {"status": "Offen", "from": "2026-09-15", "days": 5}
    ]
    assert ("statuses", None) not in manager.calls


def test_get_issue_history_rejects_negative_limit(tools):
    with pytest.raises(ValueError, match="max_changes"):
        tools.get_issue_history(1, max_changes=-1)


def test_get_issue_history_missing_issue(tools, manager):
    manager.issue = {}
    with pytest.raises(Easy8RequestError) as exc_info:
        tools.get_issue_history(404)
    assert exc_info.value.status_code == 404
