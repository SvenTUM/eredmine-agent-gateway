"""Change history of issues, derived from their journals.

Easy8 records every change of an issue attribute as a journal detail with
the old and the new value. These helpers turn the details of the tracked
attributes into a chronological list of changes and into the periods an
issue spent in each status. Values stay raw (IDs as strings); resolving them
to names is up to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

# Journal attribute name -> field name used in results.
TRACKED_ATTRIBUTES: dict[str, str] = {
    "status_id": "status",
    "assigned_to_id": "assignee",
    "priority_id": "priority",
    "due_date": "due_date",
    "start_date": "start_date",
    "done_ratio": "done_ratio",
}


@dataclass(frozen=True)
class FieldChange:
    """One change of a tracked attribute, as recorded in a journal."""

    timestamp: str
    author_id: int | None
    author: str | None
    field: str
    old_value: str | None
    new_value: str | None


@dataclass(frozen=True)
class StatusPeriod:
    """A period an issue spent in one status; `end` is None while current."""

    status_id: str | None
    start: date | None
    end: date | None


def to_date(value: Any) -> date | None:
    """Parse the date part of an ISO date or timestamp string."""
    if not isinstance(value, str) or len(value.strip()) < 10:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def field_changes(issue: dict[str, Any]) -> list[FieldChange]:
    """Return the changes of the tracked attributes, oldest first."""
    journals = sorted(
        issue.get("journals") or [], key=lambda journal: journal.get("created_on") or ""
    )
    changes: list[FieldChange] = []
    for journal in journals:
        user = journal.get("user") if isinstance(journal.get("user"), dict) else {}
        for detail in journal.get("details") or []:
            if detail.get("property") != "attr":
                continue
            field = TRACKED_ATTRIBUTES.get(detail.get("name"))
            if field is None:
                continue
            changes.append(
                FieldChange(
                    timestamp=journal.get("created_on") or "",
                    author_id=user.get("id"),
                    author=user.get("name"),
                    field=field,
                    old_value=_text(detail.get("old_value")),
                    new_value=_text(detail.get("new_value")),
                )
            )
    return changes


def status_periods(
    issue: dict[str, Any], changes: list[FieldChange] | None = None
) -> list[StatusPeriod]:
    """Return the periods the issue spent in each status, oldest first.

    The first period starts at the creation of the issue; the last one is the
    current status and has no end.
    """
    if changes is None:
        changes = field_changes(issue)
    status_changes = [change for change in changes if change.field == "status"]

    current = issue.get("status")
    current_id = _text(current.get("id") if isinstance(current, dict) else current)
    status_id = status_changes[0].old_value if status_changes else current_id
    start = to_date(issue.get("created_on"))

    periods: list[StatusPeriod] = []
    for change in status_changes:
        end = to_date(change.timestamp)
        periods.append(StatusPeriod(status_id, start, end))
        status_id, start = change.new_value, end
    periods.append(StatusPeriod(status_id, start, None))
    return periods


def status_since(issue: dict[str, Any]) -> date | None:
    """Return the day the issue entered its current status."""
    return status_periods(issue)[-1].start


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
