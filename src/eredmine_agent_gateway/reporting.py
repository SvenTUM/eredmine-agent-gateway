"""Reporting module for eredmine-agent-gateway."""

from __future__ import annotations

from .db import Easy8DB


def generate_base_report(project_id: int, db: Easy8DB | None = None) -> str:
    """Generate a Markdown report of a project's status from local DB."""
    if db is None:
        db = Easy8DB()

    cursor = db.conn.cursor()

    # 1. Project Overview
    cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    project = cursor.fetchone()

    if not project:
        return (
            f"# Project {project_id}\n\n"
            f"No data found for project {project_id}."
        )

    project_name = project["name"] or "Unknown"
    project_desc = project["description"] or "No description."

    # 2. Open Issues
    cursor.execute(
        "SELECT * FROM issues WHERE project_id = ? ORDER BY id DESC",
        (project_id,),
    )
    issues = cursor.fetchall()

    # 3. Recent Activity (Comments)
    cursor.execute(
        """
        SELECT c.*, i.subject
        FROM comments c
        JOIN issues i ON c.issue_id = i.id
        WHERE i.project_id = ?
        ORDER BY c.created_on DESC
        LIMIT 10
        """,
        (project_id,),
    )
    comments = cursor.fetchall()

    # Formatting Markdown
    lines = []
    lines.append(f"# Project Overview: {project_name}")
    lines.append("")
    lines.append(
        f"**ID:** {project['id']} | **Identifier:** {project['identifier']}"
    )
    lines.append("")
    lines.append(f"{project_desc}")
    lines.append("")

    lines.append("## Open Issues")
    lines.append("")
    if issues:
        lines.append("| ID | Subject | Status ID | Author ID |")
        lines.append("|---|---|---|---|")
        for issue in issues:
            lines.append(
                f"| {issue['id']} | {issue['subject']} "
                f"| {issue['status_id']} | {issue['author_id']} |"
            )
    else:
        lines.append("No open issues found.")
    lines.append("")

    lines.append("## Recent Activity")
    lines.append("")
    if comments:
        lines.append("| Issue | Comment | Author ID | Date |")
        lines.append("|---|---|---|---|")
        for comment in comments:
            notes = (comment["notes"] or "").replace("\n", " ")
            if len(notes) > 50:
                notes = notes[:47] + "..."
            lines.append(
                f"| #{comment['issue_id']} {comment['subject']} "
                f"| {notes} "
                f"| {comment['author_id']} "
                f"| {comment['created_on']} |"
            )
    else:
        lines.append("No recent activity.")

    return "\n".join(lines)
