"""Sync module for eredmine-agent-gateway. Orchestrates fetching from API and caching to DB."""

from __future__ import annotations

from typing import Any, Optional

from .db import Easy8DB
from .manager import Easy8Manager


def _extract_id(obj: Any, default: Any = None) -> Any:
    """Safely extract 'id' from a dict-like object or return default."""
    if isinstance(obj, dict):
        return obj.get("id", default)
    return default


def sync_project(
    project_id: int,
    db: Optional[Easy8DB] = None,
    manager: Optional[Easy8Manager] = None,
) -> None:
    """Fetch issues/journals for a project and upsert them to the database."""
    if manager is None:
        manager = Easy8Manager()
    if db is None:
        db = Easy8DB()

    # Ensure sync_state table exists to track incremental updates
    with db.conn:
        db.conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_state ("
            "project_id INTEGER PRIMARY KEY, "
            "last_sync TEXT)"
        )

    last_sync_row = db.conn.execute(
        "SELECT last_sync FROM sync_state WHERE project_id = ?", (project_id,)
    ).fetchone()
    last_sync = last_sync_row[0] if last_sync_row else None
    max_updated_on = last_sync

    offset = 0
    limit = 100

    while True:
        params = {
            "project_id": project_id,
            "status_id": "*",
            "include": "journals",
            "limit": limit,
            "offset": offset,
        }
        if last_sync:
            params["updated_on"] = f">={last_sync}"

        issues = manager.get_issues(params=params)

        if not issues:
            break

        for issue_data in issues:
            # Track the latest updated_on
            updated_on = issue_data.get("updated_on")
            if updated_on:
                if not max_updated_on or updated_on > max_updated_on:
                    max_updated_on = updated_on

            # Upsert the issue
            issue_record = {
                "id": issue_data.get("id"),
                "project_id": _extract_id(
                    issue_data.get("project"), default=project_id
                ),
                "subject": issue_data.get("subject", ""),
                "description": issue_data.get("description", ""),
                "status_id": _extract_id(issue_data.get("status")),
                "author_id": _extract_id(issue_data.get("author")),
                "due_date": issue_data.get("due_date"),
                "start_date": issue_data.get("start_date"),
                "priority_id": _extract_id(issue_data.get("priority")),
            }
            db.upsert_issue(issue_record)

            # Upsert journals as comments
            journals = issue_data.get("journals", [])
            for journal in journals:
                notes = journal.get("notes", "")
                if not notes:
                    continue  # Only store journals with actual notes

                comment_record = {
                    "id": journal.get("id"),
                    "issue_id": issue_data.get("id"),
                    "notes": notes,
                    "author_id": _extract_id(journal.get("user")),
                    "created_on": journal.get("created_on"),
                }
                db.upsert_comment(comment_record)

        if len(issues) < limit:
            break
        offset += limit

    # Update sync_state if we found newer issues
    if max_updated_on and max_updated_on != last_sync:
        with db.conn:
            db.conn.execute(
                "INSERT INTO sync_state (project_id, last_sync) VALUES (?, ?) "
                "ON CONFLICT(project_id) DO UPDATE "
                "SET last_sync=excluded.last_sync",
                (project_id, max_updated_on),
            )
