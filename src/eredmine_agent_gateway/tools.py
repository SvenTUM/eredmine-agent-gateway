"""Read-only, transport-agnostic tools for AI agents.

Adapters (CLI, MCP server, Open WebUI tool) call these tools and pass their
output through unchanged, so every entry point returns the same payload.

Output contract for JSON results (token efficiency):
- compact serialization without whitespace, non-ASCII characters unescaped
- null and empty values omitted, reference objects flattened to their name
- timestamps shortened to dates (YYYY-MM-DD)
- list results use the envelope ``items`` / ``total`` / ``next_offset``
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import date, datetime, timezone
from typing import Any

from .exceptions import Easy8RequestError
from .history import FieldChange, field_changes, status_periods
from .manager import Easy8Manager
from .summary import generate_summary

TOOL_NAMES: tuple[str, ...] = (
    "whoami",
    "list_projects",
    "search_issues",
    "get_issue",
    "get_issue_history",
    "list_time_entries",
    "project_summary",
)

MAX_PAGE_SIZE = 100
AGGREGATION_CAP = 2000
GROUP_BY_VALUES: tuple[str, ...] = ("user", "project", "issue", "activity", "date")

_MAX_PROJECT_PAGES = 50
_PROJECT_STATUS_ACTIVE = 1
_PROJECT_STATUS_NAMES = {5: "closed", 9: "archived"}
_STATUS_KEYWORDS = {"open": "open", "closed": "closed", "all": "*"}
_RELATION_INVERSE = {
    "relates": "relates",
    "duplicates": "duplicated",
    "duplicated": "duplicates",
    "blocks": "blocked",
    "blocked": "blocks",
    "precedes": "follows",
    "follows": "precedes",
    "copied_to": "copied_from",
    "copied_from": "copied_to",
}
_ISSUE_DETAIL_INCLUDES = "journals,relations,children,attachments"
_MAX_USER_LOOKUPS = 10
_PARAM_PATTERN = re.compile(r"^:param (\w+):\s*(.*)$")


class Easy8Tools:
    """The read-only agent tools, bound to one `Easy8Manager`.

    Every tool returns a string: compact JSON, or Markdown for
    `project_summary`. Invalid arguments raise `ValueError`; Easy8 failures
    raise `Easy8Error` subclasses (see `describe_error`).
    """

    def __init__(self, manager: Easy8Manager):
        self._manager = manager

    def whoami(self) -> str:
        """Return the Easy8 user who owns the configured API key (id, login, name).

        Use it to resolve "me" or to confirm whose permissions apply.
        """
        user = self._manager.get_current_user()
        name = " ".join(
            part for part in (user.get("firstname"), user.get("lastname")) if part
        )
        return _dumps(
            _compact({"id": user.get("id"), "login": user.get("login"), "name": name})
        )

    def list_projects(
        self,
        name_contains: str | None = None,
        include_closed: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """List Easy8 projects visible to the user (id, identifier, name, parent).

        Use it to map project names to the numeric project IDs other tools need.
        Returns {"items", "total", "next_offset"}; pass next_offset as offset.

        :param name_contains: Case-insensitive text to match in name or identifier.
        :param include_closed: Also list closed and archived projects.
        :param limit: Page size, 1-100.
        :param offset: Number of matches to skip (for pagination).
        """
        _check_page(limit, offset)
        name_filter = (name_contains or "").strip().casefold()

        projects: list[dict[str, Any]] = []
        api_offset = 0
        for _ in range(_MAX_PROJECT_PAGES):
            batch, total = self._manager.get_projects_page(
                {"limit": MAX_PAGE_SIZE, "offset": api_offset}
            )
            projects.extend(batch)
            api_offset += len(batch)
            if not batch or api_offset >= total:
                break

        matches = [
            project
            for project in projects
            if (include_closed or _project_is_active(project))
            and _matches_name(project, name_filter)
        ]
        page = matches[offset : offset + limit]
        items = [
            _compact(
                {
                    "id": project.get("id"),
                    "identifier": project.get("identifier"),
                    "name": project.get("name"),
                    "parent": _name(project.get("parent")),
                    "status": _PROJECT_STATUS_NAMES.get(project.get("status")),
                }
            )
            for project in page
        ]
        return _dumps(_envelope(items, len(matches), offset))

    def search_issues(
        self,
        project_id: int | None = None,
        status: str = "open",
        assigned_to: str | None = None,
        updated_since: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> str:
        """Search Easy8 issues, most recently updated first (no descriptions).

        Items: id, subject, project, tracker, status, priority, assignee, due
        date, last update, parent_id. Use get_issue for full details.
        Returns {"items", "total", "next_offset"}; pass next_offset as offset.

        :param project_id: Numeric project ID (see list_projects).
        :param status: "open" (default), "closed", "all" or a numeric status ID.
        :param assigned_to: "me" or a numeric user ID.
        :param updated_since: Only issues updated on or after this date (YYYY-MM-DD).
        :param limit: Page size, 1-100.
        :param offset: Number of matches to skip (for pagination).
        """
        _check_page(limit, offset)
        params: dict[str, Any] = {
            "status_id": _status_filter(status),
            "sort": "updated_on:desc",
            "limit": limit,
            "offset": offset,
        }
        if project_id is not None:
            params["project_id"] = project_id
        assignee = _user_filter(assigned_to, "assigned_to")
        if assignee is not None:
            params["assigned_to_id"] = assignee
        since = _iso_date(updated_since, "updated_since")
        if since is not None:
            params["updated_on"] = f">={since}"

        issues, total = self._manager.get_issues_page(params)
        items = [_compact(_issue_summary(issue)) for issue in issues]
        return _dumps(_envelope(items, total, offset))

    def get_issue(self, issue_id: int, max_journals: int = 20) -> str:
        """Get one Easy8 issue in full detail.

        Includes description, custom fields, relations, child issues,
        attachment metadata and the comment history (journals with notes only,
        oldest first; private notes are flagged with "private": true).

        :param issue_id: Numeric issue ID.
        :param max_journals: Most recent comments to include (0 = none).
        """
        if max_journals < 0:
            raise ValueError("max_journals must not be negative")
        issue = self._manager.get_issue(
            issue_id, params={"include": _ISSUE_DETAIL_INCLUDES}
        )
        if not issue:
            raise Easy8RequestError(f"Issue {issue_id} not found.", status_code=404)
        return _dumps(_compact(_issue_detail(issue, max_journals)))

    def get_issue_history(self, issue_id: int, max_changes: int = 50) -> str:
        """Get the change history of one Easy8 issue.

        Returns the periods the issue spent in each status (with days) and the
        changes of status, assignee, priority, due date, start date and done
        ratio with date and author, oldest first. Use it to find out since
        when an issue is in its status or how often it was reassigned or
        rescheduled.

        :param issue_id: Numeric issue ID.
        :param max_changes: Most recent field changes to include (0 = none).
        """
        if max_changes < 0:
            raise ValueError("max_changes must not be negative")
        issue = self._manager.get_issue(issue_id, params={"include": "journals"})
        if not issue:
            raise Easy8RequestError(f"Issue {issue_id} not found.", status_code=404)
        changes = field_changes(issue)
        names = _HistoryNames(self._manager, issue)
        history = _issue_history(issue, changes, max_changes, names, _today())
        return _dumps(_compact(history))

    def list_time_entries(
        self,
        user: str | None = None,
        project_id: int | None = None,
        issue_id: int | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        group_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """List Easy8 time entries, or aggregate hours with group_by.

        Without group_by: {"items", "total", "next_offset"} with id, date,
        hours, user, project, issue_id, activity, comments.
        With group_by: {"total_hours", "entry_count", "groups"} over all
        matching entries (limit/offset ignored; "incomplete": true if more than
        2000 entries match - narrow the filters then).

        :param user: "me" or a numeric user ID.
        :param project_id: Numeric project ID (see list_projects).
        :param issue_id: Numeric issue ID.
        :param from_date: First day to include (YYYY-MM-DD).
        :param to_date: Last day to include (YYYY-MM-DD).
        :param group_by: One of "user", "project", "issue", "activity", "date".
        :param limit: Page size, 1-100 (ignored with group_by).
        :param offset: Number of entries to skip (ignored with group_by).
        """
        params: dict[str, Any] = {}
        user_filter = _user_filter(user, "user")
        if user_filter is not None:
            params["user_id"] = user_filter
        if project_id is not None:
            params["project_id"] = project_id
        if issue_id is not None:
            params["issue_id"] = issue_id
        start = _iso_date(from_date, "from_date")
        if start is not None:
            params["from"] = start
        end = _iso_date(to_date, "to_date")
        if end is not None:
            params["to"] = end

        if group_by is not None:
            return _dumps(self._aggregate_time_entries(params, group_by))

        _check_page(limit, offset)
        entries, total = self._manager.get_time_entries_page(
            {**params, "limit": limit, "offset": offset}
        )
        items = [_compact(_time_entry(entry)) for entry in entries]
        return _dumps(_envelope(items, total, offset))

    def project_summary(self, project_id: int, stale_days: int = 14) -> str:
        """Get a Markdown status summary of one Easy8 project (German).

        Contains KPIs, warnings (overdue, stale, due soon), open issues, booked
        hours and recent customer communication. Best first call for project
        overviews and status reports.

        :param project_id: Numeric project ID (see list_projects).
        :param stale_days: Days without activity after which an open issue is stale.
        """
        return generate_summary(
            project_id=project_id, stale_days=stale_days, manager=self._manager
        )

    def _aggregate_time_entries(
        self, params: dict[str, Any], group_by: str
    ) -> dict[str, Any]:
        if group_by not in GROUP_BY_VALUES:
            raise ValueError(
                f"group_by must be one of {', '.join(GROUP_BY_VALUES)}, "
                f"got {group_by!r}"
            )
        entries: list[dict[str, Any]] = []
        total = 0
        while len(entries) < AGGREGATION_CAP:
            batch, total = self._manager.get_time_entries_page(
                {**params, "limit": MAX_PAGE_SIZE, "offset": len(entries)}
            )
            entries.extend(batch)
            if not batch or len(entries) >= total:
                break
        entries = entries[:AGGREGATION_CAP]

        groups: dict[str, list[float]] = {}
        for entry in entries:
            key = _group_key(entry, group_by)
            hours = _hours(entry)
            bucket = groups.setdefault(key, [0.0, 0])
            bucket[0] += hours
            bucket[1] += 1

        if group_by == "date":
            ordered = sorted(groups.items())
        else:
            ordered = sorted(groups.items(), key=lambda kv: (-kv[1][0], kv[0]))

        result: dict[str, Any] = {
            "total_hours": round(sum(_hours(e) for e in entries), 2),
            "entry_count": len(entries),
            "groups": [
                {"key": key, "hours": round(hours, 2), "entries": int(count)}
                for key, (hours, count) in ordered
            ],
        }
        if total > len(entries):
            result["incomplete"] = True
        return result


def describe_error(exc: Exception) -> str:
    """Return a concise, credential-free message for a tool failure."""
    if isinstance(exc, Easy8RequestError):
        if exc.status_code == 401:
            return (
                "Authentication failed (HTTP 401): the Easy8 API key is invalid "
                "or the REST API is not enabled for this user."
            )
        if exc.status_code == 403:
            return (
                "Access denied (HTTP 403): your Easy8 permissions do not allow "
                "this request."
            )
        if exc.status_code == 404:
            return (
                "Not found (HTTP 404): the requested object does not exist or is "
                "not visible with your Easy8 permissions."
            )
    return str(exc)


def parse_tool_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Split a tool docstring into its description and parameter descriptions.

    Parameters are documented with one ``:param name: text`` line each, the
    format Open WebUI parses as well.
    """
    description_lines: list[str] = []
    params: dict[str, str] = {}
    for line in inspect.cleandoc(doc or "").splitlines():
        match = _PARAM_PATTERN.match(line.strip())
        if match:
            params[match.group(1)] = match.group(2).strip()
        elif not params:
            description_lines.append(line)
    return "\n".join(description_lines).strip(), params


# --- output helpers ---------------------------------------------------------


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, (str, list, dict)) and not value)


def _compact(value: Any) -> Any:
    """Recursively drop null and empty values from dicts and lists."""
    if isinstance(value, dict):
        compacted = {key: _compact(item) for key, item in value.items()}
        return {key: item for key, item in compacted.items() if not _is_empty(item)}
    if isinstance(value, list):
        return [item for item in map(_compact, value) if not _is_empty(item)]
    return value


def _envelope(items: list[Any], total: int, offset: int) -> dict[str, Any]:
    envelope: dict[str, Any] = {"items": items, "total": total}
    if items and offset + len(items) < total:
        envelope["next_offset"] = offset + len(items)
    return envelope


def _name(ref: Any) -> Any:
    return ref.get("name") if isinstance(ref, dict) else None


def _ref_id(ref: Any) -> Any:
    return ref.get("id") if isinstance(ref, dict) else None


def _day(value: Any) -> Any:
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return value


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _days(start: date | None, end: date | None) -> int | None:
    if start is None or end is None:
        return None
    return max((end - start).days, 0)


def _today() -> date:
    return datetime.now(tz=timezone.utc).date()


def _hours(entry: dict[str, Any]) -> float:
    try:
        return float(entry.get("hours") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# --- validation helpers -----------------------------------------------------


def _check_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if offset < 0:
        raise ValueError("offset must not be negative")


def _status_filter(value: Any) -> str:
    text = str(value).strip().lower()
    if text in _STATUS_KEYWORDS:
        return _STATUS_KEYWORDS[text]
    if text.isdigit():
        return text
    raise ValueError(
        "status must be 'open', 'closed', 'all' or a numeric status ID, "
        f"got {value!r}"
    )


def _user_filter(value: Any, param: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text == "me" or text.isdigit():
        return text
    raise ValueError(f"{param} must be 'me' or a numeric user ID, got {value!r}")


def _iso_date(value: Any, param: str) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise ValueError(
            f"{param} must be a date in YYYY-MM-DD format, got {value!r}"
        ) from None


# --- mapping helpers --------------------------------------------------------


def _project_is_active(project: dict[str, Any]) -> bool:
    return project.get("status", _PROJECT_STATUS_ACTIVE) == _PROJECT_STATUS_ACTIVE


def _matches_name(project: dict[str, Any], name_filter: str) -> bool:
    if not name_filter:
        return True
    haystacks = (project.get("name") or "", project.get("identifier") or "")
    return any(name_filter in text.casefold() for text in haystacks)


def _issue_summary(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": issue.get("id"),
        "subject": issue.get("subject"),
        "project": _name(issue.get("project")),
        "tracker": _name(issue.get("tracker")),
        "status": _name(issue.get("status")),
        "priority": _name(issue.get("priority")),
        "assigned_to": _name(issue.get("assigned_to")),
        "due_date": issue.get("due_date"),
        "updated": _day(issue.get("updated_on")),
        "parent_id": _ref_id(issue.get("parent")),
    }


def _issue_detail(issue: dict[str, Any], max_journals: int) -> dict[str, Any]:
    issue_id = issue.get("id")
    journals_with_notes = [
        journal
        for journal in issue.get("journals") or []
        if (journal.get("notes") or "").strip()
    ]
    kept = journals_with_notes[-max_journals:] if max_journals > 0 else []

    detail: dict[str, Any] = {
        "id": issue_id,
        "subject": issue.get("subject"),
        "project": _name(issue.get("project")),
        "project_id": _ref_id(issue.get("project")),
        "tracker": _name(issue.get("tracker")),
        "status": _name(issue.get("status")),
        "priority": _name(issue.get("priority")),
        "author": _name(issue.get("author")),
        "assigned_to": _name(issue.get("assigned_to")),
        "assigned_to_id": _ref_id(issue.get("assigned_to")),
        "start_date": issue.get("start_date"),
        "due_date": issue.get("due_date"),
        "done_ratio": issue.get("done_ratio"),
        "estimated_hours": issue.get("estimated_hours"),
        "spent_hours": issue.get("spent_hours"),
        "created": _day(issue.get("created_on")),
        "updated": _day(issue.get("updated_on")),
        "closed": _day(issue.get("closed_on")),
        "parent_id": _ref_id(issue.get("parent")),
        "private": True if issue.get("is_private") else None,
        "description": (issue.get("description") or "").strip(),
        "custom_fields": _custom_fields(issue.get("custom_fields")),
        "relations": [
            _relation(relation, issue_id) for relation in issue.get("relations") or []
        ],
        "children": [
            {
                "id": child.get("id"),
                "subject": child.get("subject"),
                "tracker": _name(child.get("tracker")),
            }
            for child in issue.get("children") or []
        ],
        "attachments": [
            {
                "filename": attachment.get("filename"),
                "size": attachment.get("filesize"),
                "created": _day(attachment.get("created_on")),
            }
            for attachment in issue.get("attachments") or []
        ],
        "journals": [
            {
                "date": _day(journal.get("created_on")),
                "author": _name(journal.get("user")),
                "notes": journal.get("notes", "").strip(),
                "private": True if journal.get("private_notes") else None,
            }
            for journal in kept
        ],
    }
    omitted = len(journals_with_notes) - len(kept)
    if omitted:
        detail["journals_omitted"] = omitted
    return detail


def _issue_history(
    issue: dict[str, Any],
    changes: list[FieldChange],
    max_changes: int,
    names: _HistoryNames,
    today: date,
) -> dict[str, Any]:
    periods = status_periods(issue, changes)
    kept = changes[-max_changes:] if max_changes > 0 else []
    history: dict[str, Any] = {
        "id": issue.get("id"),
        "subject": issue.get("subject"),
        "status": _name(issue.get("status")),
        "status_since": _iso(periods[-1].start),
        "days_in_status": _days(periods[-1].start, today),
        "status_periods": [
            {
                "status": names.value("status", period.status_id),
                "from": _iso(period.start),
                "to": _iso(period.end),
                "days": _days(period.start, period.end or today),
            }
            for period in periods
        ],
        "changes": [
            {
                "date": _day(change.timestamp),
                "by": change.author,
                "field": change.field,
                "from": names.value(change.field, change.old_value),
                "to": names.value(change.field, change.new_value),
            }
            for change in kept
        ],
    }
    omitted = len(changes) - len(kept)
    if omitted:
        history["changes_omitted"] = omitted
    return history


class _HistoryNames:
    """Resolve the raw values of a history to names, loading lookups lazily.

    Names already contained in the issue (current status, priority and
    assignee, journal authors) need no request. Statuses and priorities are
    loaded once per history; users one by one, at most `_MAX_USER_LOOKUPS`.
    Values that cannot be resolved are shown as "<kind> <id>".
    """

    def __init__(self, manager: Easy8Manager, issue: dict[str, Any]):
        self._manager = manager
        self._statuses: dict[str, str] = _seed(issue.get("status"))
        self._priorities: dict[str, str] = _seed(issue.get("priority"))
        self._users: dict[str, str] = {
            **_seed(issue.get("author")),
            **_seed(issue.get("assigned_to")),
        }
        for journal in issue.get("journals") or []:
            self._users.update(_seed(journal.get("user")))
        self._statuses_loaded = False
        self._priorities_loaded = False
        self._user_lookups = 0

    def value(self, field: str, raw: str | None) -> Any:
        if raw is None:
            return None
        if field == "status":
            return self._status(raw)
        if field == "priority":
            return self._priority(raw)
        if field == "assignee":
            return self._user(raw)
        if field == "done_ratio" and raw.isdigit():
            return int(raw)
        return raw

    def _status(self, status_id: str) -> str:
        if status_id not in self._statuses and not self._statuses_loaded:
            self._statuses_loaded = True
            self._statuses.update(_names(self._manager.get_issue_statuses))
        return self._statuses.get(status_id, f"status {status_id}")

    def _priority(self, priority_id: str) -> str:
        if priority_id not in self._priorities and not self._priorities_loaded:
            self._priorities_loaded = True
            self._priorities.update(_names(self._manager.get_issue_priorities))
        return self._priorities.get(priority_id, f"priority {priority_id}")

    def _user(self, user_id: str) -> str:
        if user_id not in self._users and self._user_lookups < _MAX_USER_LOOKUPS:
            self._user_lookups += 1
            try:
                user = self._manager.get_user(int(user_id))
            except (Easy8RequestError, ValueError):
                user = {}
            name = " ".join(
                part for part in (user.get("firstname"), user.get("lastname")) if part
            )
            if name:
                self._users[user_id] = name
        return self._users.get(user_id, f"user {user_id}")


def _seed(ref: Any) -> dict[str, str]:
    if isinstance(ref, dict) and ref.get("id") is not None and ref.get("name"):
        return {str(ref["id"]): str(ref["name"])}
    return {}


def _names(load: Any) -> dict[str, str]:
    """Map IDs to names from a lookup; an unavailable lookup yields nothing."""
    try:
        records = load()
    except Easy8RequestError:
        return {}
    return {
        str(record["id"]): str(record["name"])
        for record in records
        if record.get("id") is not None and record.get("name")
    }


def _custom_fields(fields: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields or []:
        name = field.get("name")
        value = field.get("value")
        if isinstance(value, list):
            value = [item for item in value if not _is_empty(item)]
        if name and not _is_empty(value):
            result[name] = value
    return result


def _relation(relation: dict[str, Any], issue_id: Any) -> dict[str, Any]:
    relation_type = relation.get("relation_type")
    if relation.get("issue_id") == issue_id:
        other = relation.get("issue_to_id")
    else:
        other = relation.get("issue_id")
        relation_type = _RELATION_INVERSE.get(relation_type, relation_type)
    return {"type": relation_type, "issue_id": other, "delay": relation.get("delay")}


def _time_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "date": entry.get("spent_on"),
        "hours": entry.get("hours"),
        "user": _name(entry.get("user")),
        "project": _name(entry.get("project")),
        "issue_id": _ref_id(entry.get("issue")),
        "activity": _name(entry.get("activity")),
        "comments": entry.get("comments"),
    }


def _group_key(entry: dict[str, Any], group_by: str) -> str:
    if group_by == "issue":
        issue_id = _ref_id(entry.get("issue"))
        return f"#{issue_id}" if issue_id is not None else "(none)"
    if group_by == "date":
        return str(entry.get("spent_on") or "(none)")
    return str(_name(entry.get(group_by)) or "(none)")
