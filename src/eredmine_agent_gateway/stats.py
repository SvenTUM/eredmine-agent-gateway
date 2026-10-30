"""Project statistics computation and formatting from local SQLite DB."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import sqlite3
from typing import Any, Sequence

from .config import resolve_closed_status_ids
from .db import Easy8DB


def _parse_date(date_val: Any) -> date | None:
    """Safely parse a date, datetime, or ISO timestamp to a date object."""
    if date_val is None:
        return None
    if isinstance(date_val, date) and not isinstance(date_val, datetime):
        return date_val
    if isinstance(date_val, datetime):
        return date_val.date()
    if not isinstance(date_val, str):
        return None
    cleaned = date_val.strip()
    if len(cleaned) < 10:
        return None
    try:
        return date.fromisoformat(cleaned[:10])
    except ValueError:
        return None


def _get_field(row: Any, key: str) -> Any:
    """Safely retrieve a field value from a dict or sqlite3.Row."""
    if hasattr(row, "keys") and key in row.keys():
        return row[key]
    if isinstance(row, dict):
        return row.get(key)
    return None


def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    """Check whether a table exists in the SQLite database."""
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _get_last_sync(cursor: sqlite3.Cursor, project_id: int) -> str | None:
    """Retrieve the last sync ISO timestamp for a project if available."""
    if not _table_exists(cursor, "sync_state"):
        return None
    cursor.execute(
        "SELECT last_sync FROM sync_state WHERE project_id = ?",
        (project_id,),
    )
    row = cursor.fetchone()
    return str(row[0]) if row and row[0] else None


def _get_project_issues(
    cursor: sqlite3.Cursor,
    project_id: int,
    closed_status_ids: frozenset[int] | None = None,
) -> tuple[list[Any], list[Any]]:
    """Retrieve and partition project issues into open and closed lists."""
    if closed_status_ids is None:
        closed_status_ids = resolve_closed_status_ids()
    cursor.execute("SELECT * FROM issues WHERE project_id = ?", (project_id,))
    all_issues = cursor.fetchall()
    open_issues: list[Any] = []
    closed_issues: list[Any] = []
    for issue in all_issues:
        raw_status = _get_field(issue, "status_id")
        try:
            status_id = int(raw_status) if raw_status is not None else None
        except (ValueError, TypeError):
            status_id = None

        if status_id is not None and status_id in closed_status_ids:
            closed_issues.append(issue)
        else:
            open_issues.append(issue)
    return open_issues, closed_issues


def _get_comment_metrics(
    cursor: sqlite3.Cursor, issue_ids: Sequence[int]
) -> tuple[int, dict[int, str]]:
    """Retrieve comment counts and latest timestamps for given issues."""
    if not issue_ids or not _table_exists(cursor, "comments"):
        return 0, {}

    placeholders = ",".join("?" * len(issue_ids))
    cursor.execute(
        f"""
        SELECT issue_id, MAX(created_on)
        FROM comments
        WHERE issue_id IN ({placeholders})
        GROUP BY issue_id
        """,
        tuple(issue_ids),
    )
    rows = cursor.fetchall()
    latest_comments = {
        row[0]: row[1] for row in rows if row[0] is not None and row[1]
    }
    with_comments_count = len(latest_comments)
    return with_comments_count, latest_comments


def _get_time_entry_metrics(
    cursor: sqlite3.Cursor,
    project_id: int,
    issue_ids: Sequence[int],
    total_issues: int,
) -> tuple[int, float]:
    """Calculate issues without time entries and total tracked hours."""
    if not _table_exists(cursor, "time_entries"):
        return total_issues, 0.0

    issues_with_te: set[int] = set()
    if issue_ids:
        placeholders = ",".join("?" * len(issue_ids))
        cursor.execute(
            f"SELECT DISTINCT issue_id FROM time_entries "
            f"WHERE issue_id IN ({placeholders})",
            tuple(issue_ids),
        )
        issues_with_te = {
            row[0] for row in cursor.fetchall() if row[0] is not None
        }

    without_time_entries = total_issues - len(
        issues_with_te.intersection(set(issue_ids))
    )

    cursor.execute("PRAGMA table_info(time_entries)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "hours" not in columns:
        return without_time_entries, 0.0

    if "project_id" in columns and issue_ids:
        placeholders = ",".join("?" * len(issue_ids))
        cursor.execute(
            f"""
            SELECT COALESCE(SUM(hours), 0.0) FROM time_entries
            WHERE project_id = ? OR issue_id IN ({placeholders})
            """,
            (project_id, *issue_ids),
        )
    elif "project_id" in columns:
        cursor.execute(
            """
            SELECT COALESCE(SUM(hours), 0.0) FROM time_entries
            WHERE project_id = ?
            """,
            (project_id,),
        )
    elif issue_ids:
        placeholders = ",".join("?" * len(issue_ids))
        cursor.execute(
            f"""
            SELECT COALESCE(SUM(hours), 0.0) FROM time_entries
            WHERE issue_id IN ({placeholders})
            """,
            tuple(issue_ids),
        )
    else:
        return without_time_entries, 0.0

    sum_row = cursor.fetchone()
    total_hours = float(sum_row[0] or 0.0) if sum_row else 0.0
    return without_time_entries, total_hours


def _calculate_open_issue_metrics(
    open_issues: list[Any],
    latest_comments: dict[int, str],
    last_sync: str | None,
    stale_days: int,
    today: date | None = None,
) -> tuple[int, int, int, float]:
    """Compute overdue, due within 7 days, stale count, and avg issue age."""
    if today is None:
        today = date.today()
    seven_days_later = today + timedelta(days=7)

    overdue = 0
    due_within_7_days = 0
    stale = 0
    open_issue_ages: list[int] = []

    for issue in open_issues:
        issue_id = _get_field(issue, "id")

        # 1. Due date checks
        due_d = _parse_date(_get_field(issue, "due_date"))
        if due_d:
            if due_d < today:
                overdue += 1
            elif today <= due_d <= seven_days_later:
                due_within_7_days += 1

        # 2. Age calculation: earliest of start_date, created_on, last_sync
        start_date_val = _get_field(issue, "start_date")
        created_on_val = _get_field(issue, "created_on")
        age_candidates = [
            _parse_date(start_date_val),
            _parse_date(created_on_val),
            _parse_date(last_sync),
        ]
        valid_age_dates = [d for d in age_candidates if d is not None]
        if valid_age_dates:
            earliest_d = min(valid_age_dates)
            age_days = (today - earliest_d).days
            if age_days >= 0:
                open_issue_ages.append(age_days)

        # 3. Stale calculation: latest activity compared to threshold
        if stale_days == 0:
            stale += 1
        else:
            updated_on_val = _get_field(issue, "updated_on")
            comment_date_val = latest_comments.get(issue_id)
            activity_candidates = [
                _parse_date(updated_on_val),
                _parse_date(comment_date_val),
                _parse_date(start_date_val),
                _parse_date(last_sync),
            ]
            valid_activity_dates = [
                d for d in activity_candidates if d is not None
            ]
            if valid_activity_dates:
                latest_activity = max(valid_activity_dates)
                inactivity_days = (today - latest_activity).days
                if inactivity_days > stale_days:
                    stale += 1
            else:
                stale += 1

    avg_age = (
        round(sum(open_issue_ages) / len(open_issue_ages), 1)
        if open_issue_ages
        else 0.0
    )
    return overdue, due_within_7_days, stale, avg_age


def compute_project_stats(
    project_id: int,
    stale_days: int = 14,
    db: Easy8DB | None = None,
    closed_status_ids: frozenset[int] | None = None,
) -> dict[str, Any]:
    """Compute aggregated project statistics offline from local SQLite DB."""
    if stale_days < 0:
        raise ValueError("stale_days must be non-negative")

    if closed_status_ids is None:
        closed_status_ids = resolve_closed_status_ids()

    should_close_db = False
    if db is None:
        db = Easy8DB()
        should_close_db = True

    try:
        cursor = db.conn.cursor()
        last_sync = _get_last_sync(cursor, project_id)
        open_issues, closed_issues = _get_project_issues(
            cursor, project_id, closed_status_ids=closed_status_ids
        )

        all_issues = open_issues + closed_issues
        all_issue_ids = [
            _get_field(issue, "id")
            for issue in all_issues
            if _get_field(issue, "id") is not None
        ]
        total_count = len(all_issues)
        open_count = len(open_issues)
        closed_count = len(closed_issues)

        with_comments_count, latest_comments = _get_comment_metrics(
            cursor, all_issue_ids
        )
        without_te_count, total_hours = _get_time_entry_metrics(
            cursor, project_id, all_issue_ids, total_count
        )
        overdue, due_7, stale, avg_age = _calculate_open_issue_metrics(
            open_issues, latest_comments, last_sync, stale_days
        )

        return {
            "project_id": project_id,
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "data_source": "local_db",
            "last_sync": last_sync,
            "stale_days_threshold": stale_days,
            "issues": {
                "total": total_count,
                "open": open_count,
                "closed": closed_count,
                "without_time_entries": without_te_count,
                "stale": stale,
                "with_comments": with_comments_count,
                "overdue": overdue,
                "due_within_7_days": due_7,
                "avg_age_open_days": avg_age,
            },
            "time_entries": {
                "total_hours": total_hours,
            },
        }
    finally:
        if should_close_db:
            db.close()


def format_stats_text(
    stats: dict[str, Any], project_id: int | None = None
) -> str:
    """Format project statistics as a human-readable text table."""
    if project_id is None:
        project_id = stats.get("project_id", 0)

    issues = stats.get("issues", {})
    time_entries = stats.get("time_entries", {})
    stale_days = stats.get("stale_days_threshold", 14)
    last_sync = stats.get("last_sync")
    last_sync_str = str(last_sync) if last_sync else "Keine"

    total = issues.get("total", 0)
    open_count = issues.get("open", 0)
    closed_count = issues.get("closed", 0)
    without_te = issues.get("without_time_entries", 0)
    stale = issues.get("stale", 0)
    with_comments = issues.get("with_comments", 0)
    avg_age = issues.get("avg_age_open_days", 0.0)
    overdue = issues.get("overdue", 0)
    due_7 = issues.get("due_within_7_days", 0)
    total_hours = time_entries.get("total_hours", 0.0)

    avg_age_int = int(round(avg_age))
    avg_age_str = f"{avg_age_int} Tage"
    hours_str = f"{total_hours:.1f}".replace(".", ",") + " h"

    lines = [
        f"Projektstatus – Projekt {project_id}",
        "═" * 38,
        f"Issues gesamt:                     {total:>2}",
        f"  Offen:                           {open_count:>2}",
        f"  Geschlossen:                     {closed_count:>2}",
        "",
        f"Issues ohne Zeitbuchung:            {without_te:>2}",
        f"Issues ohne Aktivität (>{stale_days} Tage):   {stale:>2}",
        f"Issues mit Kommentaren:             {with_comments:>2}",
        "",
        f"Durchschn. Alter offener Issues:   {avg_age_str}",
        f"Gesamtstunden (alle Zeiteinträge): {hours_str}",
        "",
        "Fälligkeitsübersicht:",
        f"  Überfällig:                       {overdue:>2}",
        f"  Fällig in ≤7 Tagen:               {due_7:>2}",
        "",
        f"Letzte Synchronisation:    {last_sync_str}",
        "═" * 38,
    ]
    return "\n".join(lines)


def format_stats_json(stats: dict[str, Any]) -> str:
    """Format project statistics as JSON string."""
    return json.dumps(stats, indent=2, ensure_ascii=False)
