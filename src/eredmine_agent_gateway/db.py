"""Database access layer for eredmine-agent-gateway SQLite caching."""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, Sequence


class Easy8DB:
    """Local SQLite persistence layer for eredmine-agent-gateway projects, issues,
    and comments.
    """

    PROJECT_FIELDS: Sequence[str] = (
        "id",
        "name",
        "description",
        "identifier",
    )
    ISSUE_FIELDS: Sequence[str] = (
        "id",
        "project_id",
        "subject",
        "description",
        "status_id",
        "author_id",
        "due_date",
        "start_date",
        "priority_id",
    )
    COMMENT_FIELDS: Sequence[str] = (
        "id",
        "issue_id",
        "notes",
        "author_id",
        "created_on",
    )

    SCHEMA_MIGRATIONS_ISSUES: Sequence[tuple[str, str]] = (
        ("due_date", "TEXT"),
        ("start_date", "TEXT"),
        ("priority_id", "INTEGER"),
    )

    def __init__(self, db_path: str = "~/.erag/cache.db") -> None:
        self.db_path = os.path.expanduser(db_path)
        self._ensure_dir()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

        # Optimize performance and data integrity
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")

        self._create_tables()
        self._migrate_issues_table()

    def _ensure_dir(self) -> None:
        dir_name = os.path.dirname(self.db_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    def _create_tables(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    description TEXT,
                    identifier TEXT
                );

                CREATE TABLE IF NOT EXISTS issues (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER,
                    subject TEXT,
                    description TEXT,
                    status_id INTEGER,
                    author_id INTEGER,
                    due_date TEXT,
                    start_date TEXT,
                    priority_id INTEGER,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY,
                    issue_id INTEGER,
                    notes TEXT,
                    author_id INTEGER,
                    created_on TEXT,
                    FOREIGN KEY(issue_id) REFERENCES issues(id)
                );
                """
            )

    def _migrate_issues_table(self) -> None:
        cursor = self.conn.execute("PRAGMA table_info(issues);")
        existing_columns = {row["name"] for row in cursor.fetchall()}
        with self.conn:
            for col_name, col_type in self.SCHEMA_MIGRATIONS_ISSUES:
                if col_name not in existing_columns:
                    self.conn.execute(
                        f"ALTER TABLE issues ADD COLUMN {col_name} {col_type};"
                    )

    def _upsert(
        self, table: str, data: Dict[str, Any], fields: Sequence[str]
    ) -> None:
        columns = ", ".join(fields)
        placeholders = ", ".join(f":{f}" for f in fields)
        updates = ", ".join(f"{f}=excluded.{f}" for f in fields if f != "id")

        query = f"""
            INSERT INTO {table} ({columns})
            VALUES ({placeholders})
            ON CONFLICT(id) DO UPDATE SET {updates}
        """
        payload = {f: data.get(f) for f in fields}
        with self.conn:
            self.conn.execute(query, payload)

    def upsert_project(self, project: Dict[str, Any]) -> None:
        self._upsert("projects", project, self.PROJECT_FIELDS)

    def upsert_issue(self, issue: Dict[str, Any]) -> None:
        self._upsert("issues", issue, self.ISSUE_FIELDS)

    def upsert_comment(self, comment: Dict[str, Any]) -> None:
        self._upsert("comments", comment, self.COMMENT_FIELDS)

    def close(self) -> None:
        """Close the underlying SQLite database connection."""
        self.conn.close()

    def __enter__(self) -> Easy8DB:
        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        self.close()
