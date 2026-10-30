import pytest

from eredmine_agent_gateway.db import Easy8DB
from eredmine_agent_gateway.reporting import generate_base_report


@pytest.fixture
def mock_db(tmp_path):
    db_path = tmp_path / "test_cache.db"
    db = Easy8DB(db_path=str(db_path))

    # Insert mock data
    db.upsert_project(
        {
            "id": 1,
            "name": "Test Project",
            "description": "A project for testing",
            "identifier": "test-proj",
        }
    )

    db.upsert_issue(
        {
            "id": 101,
            "project_id": 1,
            "subject": "Test Issue 1",
            "description": "Issue description",
            "status_id": 1,
            "author_id": 42,
        }
    )

    db.upsert_comment(
        {
            "id": 1001,
            "issue_id": 101,
            "notes": "This is a comment",
            "author_id": 42,
            "created_on": "2023-01-01T12:00:00Z",
        }
    )

    return db


def test_generate_base_report(mock_db):
    report = generate_base_report(project_id=1, db=mock_db)

    assert "# Project Overview: Test Project" in report
    assert "A project for testing" in report
    assert "## Open Issues" in report
    assert "Test Issue 1" in report
    assert "## Recent Activity" in report
    assert "This is a comment" in report


def test_generate_base_report_no_data(mock_db):
    report = generate_base_report(project_id=999, db=mock_db)

    assert "No data found for project 999" in report
