import sqlite3
from eredmine_agent_gateway.db import Easy8DB


def test_migration_from_old_schema(tmp_path):
    db_file = tmp_path / "old_schema.db"

    # Create a database with the old schema (6 columns in issues)
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            name TEXT,
            description TEXT,
            identifier TEXT
        );

        CREATE TABLE issues (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            subject TEXT,
            description TEXT,
            status_id INTEGER,
            author_id INTEGER,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );

        CREATE TABLE comments (
            id INTEGER PRIMARY KEY,
            issue_id INTEGER,
            notes TEXT,
            author_id INTEGER,
            created_on TEXT,
            FOREIGN KEY(issue_id) REFERENCES issues(id)
        );
        """
    )
    # Insert a sample row in old issues table
    conn.execute(
        "INSERT INTO issues "
        "(id, project_id, subject, description, status_id, author_id) "
        "VALUES (1, 10, 'Old Issue', 'Old Desc', 1, 5);"
    )
    conn.commit()
    conn.close()

    # Now open with Easy8DB which should migrate the schema
    db = Easy8DB(db_path=str(db_file))

    cursor = db.conn.cursor()
    cursor.execute("PRAGMA table_info(issues);")
    columns = {row["name"]: row["type"] for row in cursor.fetchall()}

    expected_columns = {
        "id": "INTEGER",
        "project_id": "INTEGER",
        "subject": "TEXT",
        "description": "TEXT",
        "status_id": "INTEGER",
        "author_id": "INTEGER",
        "due_date": "TEXT",
        "start_date": "TEXT",
        "priority_id": "INTEGER",
    }

    for col_name, col_type in expected_columns.items():
        assert col_name in columns
        assert columns[col_name] == col_type

    # Verify existing row retained its data
    cursor.execute("SELECT * FROM issues WHERE id=1")
    row = dict(cursor.fetchone())
    assert row["subject"] == "Old Issue"
    assert row["due_date"] is None
    assert row["start_date"] is None
    assert row["priority_id"] is None

    db.conn.close()


def test_migration_idempotence(tmp_path):
    db_file = tmp_path / "idempotence.db"

    # Initializing multiple times should not raise errors
    db1 = Easy8DB(db_path=str(db_file))
    db1.conn.close()

    db2 = Easy8DB(db_path=str(db_file))
    cursor = db2.conn.cursor()
    cursor.execute("PRAGMA table_info(issues);")
    columns = [row["name"] for row in cursor.fetchall()]
    assert "due_date" in columns
    assert "start_date" in columns
    assert "priority_id" in columns
    db2.conn.close()


def test_upsert_issue_with_new_fields(tmp_path):
    db_file = tmp_path / "upsert_test.db"
    db = Easy8DB(db_path=str(db_file))
    db.upsert_project({"id": 1, "name": "Project 1"})

    issue_data = {
        "id": 10,
        "project_id": 1,
        "subject": "Due & Priority Issue",
        "description": "Details",
        "status_id": 2,
        "author_id": 5,
        "due_date": "2026-08-30",
        "start_date": "2026-08-01",
        "priority_id": 3,
    }

    db.upsert_issue(issue_data)

    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM issues WHERE id=10")
    row = dict(cursor.fetchone())
    assert row["id"] == 10
    assert row["due_date"] == "2026-08-30"
    assert row["start_date"] == "2026-08-01"
    assert row["priority_id"] == 3

    # Update with None
    issue_data["due_date"] = None
    issue_data["priority_id"] = None
    db.upsert_issue(issue_data)

    cursor.execute("SELECT * FROM issues WHERE id=10")
    row = dict(cursor.fetchone())
    assert row["due_date"] is None
    assert row["priority_id"] is None
    db.conn.close()


def test_db_context_manager(tmp_path):
    db_file = tmp_path / "context_mgr.db"
    with Easy8DB(db_path=str(db_file)) as db:
        db.upsert_project({"id": 1, "name": "Context Mgr Project"})
        cursor = db.conn.cursor()
        cursor.execute("SELECT name FROM projects WHERE id=1")
        assert cursor.fetchone()["name"] == "Context Mgr Project"
