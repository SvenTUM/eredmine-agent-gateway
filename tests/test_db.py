import sqlite3
import pytest
from eredmine_agent_gateway.db import Easy8DB


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_cache.db"
    db = Easy8DB(db_path=str(db_file))
    yield db
    db.conn.close()


def test_db_initialization(temp_db):
    # Verify tables are created
    cursor = temp_db.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert "projects" in tables
    assert "issues" in tables
    assert "comments" in tables


def test_upsert_project(temp_db):
    project_data = {
        "id": 1,
        "name": "Test Project",
        "description": "A project for testing",
        "identifier": "test-proj",
    }

    # Insert
    temp_db.upsert_project(project_data)
    cursor = temp_db.conn.cursor()
    cursor.execute("SELECT * FROM projects WHERE id=1")
    row = dict(cursor.fetchone())
    assert row["name"] == "Test Project"

    # Update
    project_data["name"] = "Updated Project"
    temp_db.upsert_project(project_data)
    cursor.execute("SELECT * FROM projects WHERE id=1")
    row = dict(cursor.fetchone())
    assert row["name"] == "Updated Project"


def test_upsert_issue(temp_db):
    temp_db.upsert_project({"id": 1, "name": "Parent Project"})

    issue_data = {
        "id": 100,
        "project_id": 1,
        "subject": "Test Issue",
        "description": "Issue description",
        "status_id": 2,
        "author_id": 5,
    }

    # Insert
    temp_db.upsert_issue(issue_data)
    cursor = temp_db.conn.cursor()
    cursor.execute("SELECT * FROM issues WHERE id=100")
    row = dict(cursor.fetchone())
    assert row["subject"] == "Test Issue"

    # Update
    issue_data["subject"] = "Updated Issue Subject"
    temp_db.upsert_issue(issue_data)
    cursor.execute("SELECT * FROM issues WHERE id=100")
    row = dict(cursor.fetchone())
    assert row["subject"] == "Updated Issue Subject"


def test_upsert_comment(temp_db):
    temp_db.upsert_project({"id": 1, "name": "Parent Project"})
    temp_db.upsert_issue(
        {"id": 100, "project_id": 1, "subject": "Parent Issue"}
    )

    comment_data = {
        "id": 500,
        "issue_id": 100,
        "notes": "This is a test comment",
        "author_id": 5,
        "created_on": "2023-01-01T12:00:00Z",
    }

    # Insert
    temp_db.upsert_comment(comment_data)
    cursor = temp_db.conn.cursor()
    cursor.execute("SELECT * FROM comments WHERE id=500")
    row = dict(cursor.fetchone())
    assert row["notes"] == "This is a test comment"

    # Update
    comment_data["notes"] = "Updated comment notes"
    temp_db.upsert_comment(comment_data)
    cursor.execute("SELECT * FROM comments WHERE id=500")
    row = dict(cursor.fetchone())
    assert row["notes"] == "Updated comment notes"


def test_invalid_data_type(temp_db):
    temp_db.upsert_project({"id": 1, "name": "Parent Project"})

    issue_data = {
        "id": "not-an-int",
        "project_id": 1,
        "subject": "Test",
    }
    with pytest.raises(sqlite3.IntegrityError):
        temp_db.upsert_issue(issue_data)
