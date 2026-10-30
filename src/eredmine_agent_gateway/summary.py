"""Summary module for eredmine-agent-gateway — live Easy8 project markdown generation."""

from __future__ import annotations

import warnings
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .config import resolve_priority_map
from .exceptions import Easy8Error, Easy8RequestError
from .history import status_since
from .manager import Easy8Manager

TIME_DATA_UNAVAILABLE = "nicht verfügbar"


def _parse_date(date_val: Any) -> date | None:
    """Safely parse a date, datetime, or ISO string into a date object."""
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


def _get_status_id(issue: dict[str, Any]) -> int | None:
    """Extract numeric status ID from issue dict."""
    status_id = issue.get("status_id")
    if status_id is not None:
        try:
            return int(status_id)
        except (ValueError, TypeError):
            pass
    status_obj = issue.get("status")
    if isinstance(status_obj, dict):
        val = status_obj.get("id")
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    elif isinstance(status_obj, (int, str)):
        try:
            return int(status_obj)
        except (ValueError, TypeError):
            pass
    return None


def _extract_priority_id(issue: dict[str, Any]) -> int | None:
    """Extract numeric priority ID from issue dict if available."""
    prio_id = issue.get("priority_id")
    if prio_id is not None:
        try:
            return int(prio_id)
        except (ValueError, TypeError):
            pass
    prio_obj = issue.get("priority")
    if isinstance(prio_obj, dict):
        val = prio_obj.get("id")
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    elif isinstance(prio_obj, (int, str)):
        try:
            return int(prio_obj)
        except (ValueError, TypeError):
            pass
    return None


def _get_priority_display(
    issue: dict[str, Any],
    priority_map: dict[int, str] | None = None,
) -> str:
    """Extract priority display name using priority_map or fallback."""
    if priority_map is None:
        priority_map = resolve_priority_map()

    prio_id = _extract_priority_id(issue)
    if prio_id is not None and prio_id in priority_map:
        return priority_map[prio_id]

    prio_obj = issue.get("priority")
    if isinstance(prio_obj, dict) and prio_obj.get("name"):
        return str(prio_obj["name"])
    if isinstance(prio_obj, str) and prio_obj and not prio_obj.isdigit():
        return prio_obj

    prio_name = issue.get("priority_name")
    if prio_name:
        return str(prio_name)

    if prio_id is not None:
        return str(prio_id)

    return "-"


def _format_hours(hours: float) -> str:
    """Format floating point hours with German decimal comma."""
    return f"{hours:.1f}".replace(".", ",") + " h"


def _sanitize_table_cell(text: str) -> str:
    """Sanitize string for inclusion in a Markdown table cell."""
    return text.replace("\r", " ").replace("\n", " ").replace("|", " ").strip()


def _fetch_all_issues(
    manager: Easy8Manager, project_id: int, limit: int = 100
) -> list[dict[str, Any]]:
    """Fetch all open issues of a project, including journals.

    "Open" follows the status definitions of the Easy8 installation.
    """
    issues: list[dict[str, Any]] = []
    offset = 0
    while True:
        params: dict[str, Any] = {
            "project_id": project_id,
            "status_id": "open",
            "include": "journals",
            "limit": limit,
        }
        if offset > 0:
            params["offset"] = offset

        batch = manager.get_issues(params=params)
        if not batch:
            break
        issues.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return issues


def _count_closed_issues(manager: Easy8Manager, project_id: int) -> int:
    """Return the number of closed issues of a project.

    "Closed" follows the status definitions of the Easy8 installation.
    """
    _, total = manager.get_issues_page(
        params={"project_id": project_id, "status_id": "closed", "limit": 1}
    )
    return total


def _fetch_all_time_entries(
    manager: Easy8Manager, project_id: int, limit: int = 100
) -> list[dict[str, Any]] | None:
    """Fetch all time entries for a project with pagination.

    Returns ``None`` when the user lacks permission to view time entries
    (HTTP 403), so that the summary can still be produced without them.
    """
    entries: list[dict[str, Any]] = []
    offset = 0
    while True:
        params: dict[str, Any] = {"project_id": project_id, "limit": limit}
        if offset > 0:
            params["offset"] = offset
        try:
            batch = manager.get_time_entries(request_params=params)
        except Easy8RequestError as exc:
            if exc.status_code == 403:
                return None
            raise
        if not batch:
            break
        entries.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return entries


def _resolve_project_name(
    manager: Easy8Manager, project_id: int, issues: list[dict[str, Any]]
) -> str:
    """Determine project name from issues or by calling project endpoint."""
    for issue in issues:
        proj = issue.get("project")
        if isinstance(proj, dict) and proj.get("name"):
            return str(proj["name"])

    try:
        project_data = manager.get_project(project_id)
        if isinstance(project_data, dict) and project_data.get("name"):
            return str(project_data["name"])
    except (Easy8Error, OSError, ValueError, KeyError):
        pass

    return f"Projekt {project_id}"


def _extract_comments_and_activities(
    issues: list[dict[str, Any]], time_entries: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[date], int]:
    """Extract comments, all activity dates, and issue comment counts."""
    all_comments: list[dict[str, Any]] = []
    all_activity_dates: list[date] = []
    issues_with_comments_count = 0

    for issue in issues:
        issue_id = issue.get("id")
        subject = issue.get("subject", "")

        for key in ("updated_on", "created_on", "start_date"):
            d = _parse_date(issue.get(key))
            if d:
                all_activity_dates.append(d)

        journals = issue.get("journals") or []
        issue_has_comment = False
        for journal in journals:
            notes = (journal.get("notes") or "").strip()
            if not notes:
                continue
            issue_has_comment = True
            c_created = journal.get("created_on")
            c_date = _parse_date(c_created)
            if c_date:
                all_activity_dates.append(c_date)
            if journal.get("private_notes"):
                # Private notes are internal and never customer communication.
                continue
            all_comments.append({
                "issue_id": issue_id,
                "subject": subject,
                "notes": notes,
                "created_on": c_created or "",
                "date": c_date,
            })

        if issue_has_comment:
            issues_with_comments_count += 1

    for te in time_entries:
        for key in ("spent_on", "created_on", "updated_on"):
            d = _parse_date(te.get(key))
            if d:
                all_activity_dates.append(d)

    return all_comments, all_activity_dates, issues_with_comments_count


def _calculate_open_issue_warnings(
    open_issues: list[dict[str, Any]],
    today: date,
    stale_days: int,
    priority_map: dict[int, str] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[int],
]:
    """Compute overdue, stale, and due-soon warnings, plus open issue ages."""
    seven_days_later = today + timedelta(days=7)
    overdue_warnings: list[dict[str, Any]] = []
    stale_warnings: list[dict[str, Any]] = []
    due_soon_warnings: list[dict[str, Any]] = []
    open_issue_ages: list[int] = []

    for issue in open_issues:
        issue_id = issue.get("id")
        subject = issue.get("subject", "")
        priority_display = _get_priority_display(
            issue, priority_map=priority_map
        )

        due_d = _parse_date(issue.get("due_date"))
        if due_d:
            if due_d < today:
                overdue_warnings.append({
                    "id": issue_id,
                    "subject": subject,
                    "due_date": due_d.isoformat(),
                    "priority": priority_display,
                })
            elif today <= due_d <= seven_days_later:
                due_soon_warnings.append({
                    "id": issue_id,
                    "subject": subject,
                    "due_date": due_d.isoformat(),
                    "priority": priority_display,
                })

        start_d = _parse_date(issue.get("start_date"))
        created_d = _parse_date(issue.get("created_on"))
        age_candidates = [d for d in (start_d, created_d) if d is not None]
        if age_candidates:
            age_days = (today - min(age_candidates)).days
            if age_days >= 0:
                open_issue_ages.append(age_days)

        activity_candidates = [
            _parse_date(issue.get("updated_on")),
            start_d,
            created_d,
        ]
        for j in issue.get("journals") or []:
            if (j.get("notes") or "").strip():
                jd = _parse_date(j.get("created_on"))
                if jd:
                    activity_candidates.append(jd)

        valid_activities = [d for d in activity_candidates if d is not None]
        if valid_activities:
            latest_issue_activity = max(valid_activities)
            inactivity_days = (today - latest_issue_activity).days
            if inactivity_days > stale_days:
                stale_warnings.append({
                    "id": issue_id,
                    "subject": subject,
                    "last_activity": latest_issue_activity.isoformat(),
                    "priority": priority_display,
                })
        else:
            stale_warnings.append({
                "id": issue_id,
                "subject": subject,
                "last_activity": "unbekannt",
                "priority": priority_display,
            })

    return overdue_warnings, stale_warnings, due_soon_warnings, open_issue_ages


def _calculate_time_metrics(
    issues: list[dict[str, Any]], time_entries: list[dict[str, Any]]
) -> tuple[float, int, int]:
    """Calculate total hours, TE count, and issues without time entries."""
    issue_ids_with_te: set[int] = set()
    total_hours = 0.0

    for te in time_entries:
        try:
            total_hours += float(te.get("hours") or 0.0)
        except (ValueError, TypeError):
            pass
        issue_obj = te.get("issue")
        te_issue_id = None
        if isinstance(issue_obj, dict):
            te_issue_id = issue_obj.get("id")
        elif "issue_id" in te:
            te_issue_id = te.get("issue_id")
        if te_issue_id is not None:
            try:
                issue_ids_with_te.add(int(te_issue_id))
            except (ValueError, TypeError):
                pass

    all_issue_ids = {
        issue.get("id") for issue in issues if issue.get("id") is not None
    }
    without_time_entries_count = len(all_issue_ids - issue_ids_with_te)
    return total_hours, len(time_entries), without_time_entries_count


def _render_header_section(project_name: str, project_id: int) -> list[str]:
    """Render markdown title and metadata header."""
    now = datetime.now(tz=timezone.utc).astimezone()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    return [
        f"# Projektzusammenfassung: {project_name} (ID: {project_id})",
        "",
        f"**Erstellt:** {now_str}  ",
        "**Datenstand:** Live (Easy8-API)",
    ]


def _render_project_status_section(
    total_issues: int,
    open_issues_count: int,
    closed_issues_count: int,
    avg_age_days: int,
    without_time_entries_count: int,
    stale_count: int,
    stale_days: int,
    issues_with_comments_count: int,
    total_hours: float,
    latest_activity_str: str,
    time_data_available: bool = True,
) -> list[str]:
    """Render project status KPI table."""
    without_te_display = (
        str(without_time_entries_count)
        if time_data_available
        else TIME_DATA_UNAVAILABLE
    )
    hours_display = (
        _format_hours(total_hours) if time_data_available else TIME_DATA_UNAVAILABLE
    )
    return [
        "---",
        "",
        "## Projektstatus",
        "",
        "| Kennzahl | Wert |",
        "|---|---|",
        f"| Issues gesamt | {total_issues} |",
        f"| Offen | {open_issues_count} |",
        f"| Geschlossen | {closed_issues_count} |",
        f"| Ø Alter offener Issues | {avg_age_days} Tage |",
        f"| Offene Issues ohne Zeitbuchung | {without_te_display} |",
        f"| Issues ohne Aktivität (>{stale_days} Tage) | {stale_count} |",
        f"| Offene Issues mit Kommentaren | {issues_with_comments_count} |",
        f"| Gesamtstunden | {hours_display} |",
        f"| Letzte Aktivität | {latest_activity_str} |",
    ]


def _render_warnings_section(
    overdue_warnings: list[dict[str, Any]],
    stale_warnings: list[dict[str, Any]],
    due_soon_warnings: list[dict[str, Any]],
    stale_days: int,
) -> list[str]:
    """Render warnings section callout block if any warnings exist."""
    if not (overdue_warnings or stale_warnings or due_soon_warnings):
        return []

    lines: list[str] = [
        "---",
        "",
        "## ⚠️ Warnungen",
    ]

    if overdue_warnings:
        count = len(overdue_warnings)
        label = (
            "1 Issue überfällig"
            if count == 1
            else f"{count} Issues überfällig"
        )
        lines.append("")
        lines.append(
            f"> ⚠️ **{label}** "
            "(Fälligkeitsdatum überschritten, noch offen):"
        )
        for w in overdue_warnings:
            lines.append(
                f"> - #{w['id']} „{_sanitize_table_cell(w['subject'])}\""
                f" – fällig seit {w['due_date']} "
                f"(Priorität: {w['priority']})"
            )

    if stale_warnings:
        count = len(stale_warnings)
        label = "1 Issue stale" if count == 1 else f"{count} Issues stale"
        lines.append("")
        lines.append(
            f"> ⚠️ **{label}** "
            f"(>{stale_days} Tage ohne Aktivität, noch offen):"
        )
        for w in stale_warnings:
            lines.append(
                f"> - #{w['id']} „{_sanitize_table_cell(w['subject'])}\""
                f" – letzte Aktivität: {w['last_activity']} "
                f"(Priorität: {w['priority']})"
            )

    if due_soon_warnings:
        count = len(due_soon_warnings)
        label = (
            "1 Issue fällig in ≤7 Tagen:"
            if count == 1
            else f"{count} Issues fällig in ≤7 Tagen:"
        )
        lines.append("")
        lines.append(f"> ⚠️ **{label}**")
        for w in due_soon_warnings:
            lines.append(
                f"> - #{w['id']} „{_sanitize_table_cell(w['subject'])}\""
                f" – fällig: {w['due_date']} "
                f"(Priorität: {w['priority']})"
            )

    return lines


def _render_open_issues_section(
    open_issues: list[dict[str, Any]],
    today: date,
    priority_map: dict[int, str] | None = None,
) -> list[str]:
    """Render open issues table."""
    lines: list[str] = [
        "---",
        "",
        "## Offene Issues",
        "",
        (
            "| ID | Betreff | Status | Im Status (Tage) | Priorität | Fällig am "
            "| Alter (Tage) | Kommentare |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for issue in open_issues:
        iid = issue.get("id", "")
        subj = _sanitize_table_cell(issue.get("subject", ""))
        status_obj = issue.get("status")
        status_name = _sanitize_table_cell(
            str(status_obj.get("name") or "-") if isinstance(status_obj, dict) else "-"
        )
        since = status_since(issue)
        in_status_str = str(max((today - since).days, 0)) if since else "-"
        prio = _get_priority_display(issue, priority_map=priority_map)
        due_val = issue.get("due_date") or "-"
        start_d = _parse_date(issue.get("start_date"))
        created_d = _parse_date(issue.get("created_on"))
        cands = [d for d in (start_d, created_d) if d is not None]
        age_str = str((today - min(cands)).days) if cands else "-"

        c_count = sum(
            1
            for j in (issue.get("journals") or [])
            if (j.get("notes") or "").strip()
        )
        lines.append(
            f"| {iid} | {subj} | {status_name} | {in_status_str} | {prio} "
            f"| {due_val} | {age_str} | {c_count} |"
        )
    return lines


def _render_time_entries_section(
    total_hours: float, total_te_count: int, time_data_available: bool = True
) -> list[str]:
    """Render time entries summary table."""
    if not time_data_available:
        return [
            "---",
            "",
            "## Zeitbuchungen (Zusammenfassung)",
            "",
            (
                "_Keine Berechtigung zum Lesen von Zeitbuchungen in Easy8 – "
                "Zeitdaten sind nicht verfügbar._"
            ),
        ]
    avg_hours = (total_hours / total_te_count) if total_te_count > 0 else 0.0
    return [
        "---",
        "",
        "## Zeitbuchungen (Zusammenfassung)",
        "",
        "| Kennzahl | Wert |",
        "|---|---|",
        f"| Gesamtstunden | {_format_hours(total_hours)} |",
        f"| Buchungen gesamt | {total_te_count} |",
        f"| Ø Stunden pro Buchung | {_format_hours(avg_hours)} |",
    ]


def _render_customer_communication_section(
    all_comments: list[dict[str, Any]],
) -> list[str]:
    """Render customer communication table with up to 10 latest comments."""
    sorted_comments = sorted(
        all_comments,
        key=lambda c: c.get("created_on") or "",
        reverse=True,
    )[:10]

    lines: list[str] = [
        "---",
        "",
        "## Kundenkommunikation in offenen Issues (letzte 10 Kommentare)",
        "",
        "| Issue | Betreff | Kommentar (Auszug) | Datum |",
        "|---|---|---|---|",
    ]
    for c in sorted_comments:
        raw_notes = _sanitize_table_cell(c.get("notes", ""))
        excerpt = raw_notes[:37] + "..." if len(raw_notes) > 40 else raw_notes
        comment_display = f"„{excerpt}\""
        c_date_val = c.get("date")
        date_str = c_date_val.isoformat() if c_date_val else "-"
        lines.append(
            f"| #{c['issue_id']} | {_sanitize_table_cell(c['subject'])} "
            f"| {comment_display} | {date_str} |"
        )
    return lines


def generate_summary(
    project_id: int,
    stale_days: int = 14,
    manager: Easy8Manager | None = None,
    today: date | None = None,
    closed_status_ids: frozenset[int] | None = None,
    priority_map: dict[int, str] | None = None,
) -> str:
    """Generate structured Markdown summary using live Easy8 API data.

    Args:
        project_id: Numeric Easy8 project ID.
        stale_days: Inactivity threshold in days for stale open issues.
        manager: Optional Easy8Manager instance (dependency injection).
        today: Optional reference date for deterministic testing.
        closed_status_ids: Deprecated and ignored. Open and closed issues
            follow the status definitions of the Easy8 installation.
        priority_map: Optional mapping from priority IDs to labels.

    Returns:
        Structured Markdown string.
    """
    if stale_days < 0:
        raise ValueError("stale_days must be non-negative")

    if manager is None:
        manager = Easy8Manager()

    if today is None:
        today = datetime.now(tz=timezone.utc).date()

    if closed_status_ids is not None:
        warnings.warn(
            "closed_status_ids is ignored: open and closed issues follow the "
            "status definitions of the Easy8 installation.",
            DeprecationWarning,
            stacklevel=2,
        )

    if priority_map is None:
        priority_map = resolve_priority_map()

    # 1. Fetch live open issues, the closed count and time entries
    open_issues = _fetch_all_issues(manager, project_id)
    closed_issues_count = _count_closed_issues(manager, project_id)
    fetched_time_entries = _fetch_all_time_entries(manager, project_id)
    time_data_available = fetched_time_entries is not None
    time_entries = fetched_time_entries or []

    # 2. Determine project name
    project_name = _resolve_project_name(manager, project_id, open_issues)

    # 3. Extract comments and activity dates
    all_comments, all_activity_dates, issues_with_comments_count = (
        _extract_comments_and_activities(open_issues, time_entries)
    )

    # 4. Calculate issue metrics & warnings
    overdue_warnings, stale_warnings, due_soon_warnings, open_issue_ages = (
        _calculate_open_issue_warnings(
            open_issues,
            today,
            stale_days,
            priority_map=priority_map,
        )
    )

    # 5. Calculate time entry metrics
    total_hours, total_te_count, without_time_entries_count = (
        _calculate_time_metrics(open_issues, time_entries)
    )

    # 6. Aggregate general KPIs
    avg_age_days = (
        round(sum(open_issue_ages) / len(open_issue_ages))
        if open_issue_ages
        else 0
    )
    latest_activity_str = (
        max(all_activity_dates).isoformat() if all_activity_dates else "Keine"
    )

    # 7. Build markdown document
    sections: list[list[str]] = [
        _render_header_section(project_name, project_id),
        _render_project_status_section(
            total_issues=len(open_issues) + closed_issues_count,
            open_issues_count=len(open_issues),
            closed_issues_count=closed_issues_count,
            avg_age_days=avg_age_days,
            without_time_entries_count=without_time_entries_count,
            stale_count=len(stale_warnings),
            stale_days=stale_days,
            issues_with_comments_count=issues_with_comments_count,
            total_hours=total_hours,
            latest_activity_str=latest_activity_str,
            time_data_available=time_data_available,
        ),
    ]

    warnings_lines = _render_warnings_section(
        overdue_warnings=overdue_warnings,
        stale_warnings=stale_warnings,
        due_soon_warnings=due_soon_warnings,
        stale_days=stale_days,
    )
    if warnings_lines:
        sections.append(warnings_lines)

    sections.extend([
        _render_open_issues_section(
            open_issues, today, priority_map=priority_map
        ),
        _render_time_entries_section(
            total_hours, total_te_count, time_data_available
        ),
        _render_customer_communication_section(all_comments),
    ])

    full_lines: list[str] = []
    for section in sections:
        if full_lines:
            full_lines.append("")
        full_lines.extend(section)

    return "\n".join(full_lines)
