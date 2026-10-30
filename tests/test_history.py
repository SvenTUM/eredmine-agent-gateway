"""Tests for the journal-based change history (eredmine_agent_gateway.history)."""

from __future__ import annotations

from datetime import date

from eredmine_agent_gateway.history import (
    FieldChange,
    field_changes,
    status_periods,
    status_since,
    to_date,
)


def _journal(timestamp, *details, user=None, notes=""):
    return {
        "created_on": timestamp,
        "user": user,
        "notes": notes,
        "details": list(details),
    }


def _attr(name, old, new):
    return {"property": "attr", "name": name, "old_value": old, "new_value": new}


def test_field_changes_keeps_tracked_attributes_oldest_first():
    issue = {
        "journals": [
            _journal(
                "2026-09-10T09:00:00Z",
                _attr("status_id", "2", "3"),
                {"property": "attachment", "name": "17", "new_value": "a.pdf"},
                _attr("description", "x", "y"),
                user={"id": 4, "name": "Ben"},
            ),
            _journal("2026-09-01T09:00:00Z", _attr("due_date", "", "2026-09-30")),
            _journal("2026-09-05T09:00:00Z", notes="Nur Text"),
        ]
    }

    assert field_changes(issue) == [
        FieldChange("2026-09-01T09:00:00Z", None, None, "due_date", None, "2026-09-30"),
        FieldChange("2026-09-10T09:00:00Z", 4, "Ben", "status", "2", "3"),
    ]


def test_status_periods_follow_status_changes():
    issue = {
        "status": {"id": 3, "name": "Erledigt"},
        "created_on": "2026-09-01T08:00:00Z",
        "journals": [
            _journal("2026-09-04T09:00:00Z", _attr("status_id", "1", "2")),
            _journal("2026-09-09T09:00:00Z", _attr("status_id", "2", "3")),
        ],
    }

    periods = status_periods(issue)

    assert [(p.status_id, p.start, p.end) for p in periods] == [
        ("1", date(2026, 9, 1), date(2026, 9, 4)),
        ("2", date(2026, 9, 4), date(2026, 9, 9)),
        ("3", date(2026, 9, 9), None),
    ]
    assert status_since(issue) == date(2026, 9, 9)


def test_status_since_without_status_change_is_creation_day():
    issue = {
        "status": {"id": 1},
        "created_on": "2026-09-01T08:00:00Z",
        "journals": [_journal("2026-09-02T09:00:00Z", notes="Kommentar")],
    }

    assert [(p.status_id, p.end) for p in status_periods(issue)] == [("1", None)]
    assert status_since(issue) == date(2026, 9, 1)


def test_to_date_handles_invalid_values():
    assert to_date("2026-09-01T08:00:00Z") == date(2026, 9, 1)
    assert to_date("2026-09-01") == date(2026, 9, 1)
    assert to_date("bad") is None
    assert to_date("2026-13-01") is None
    assert to_date(None) is None
