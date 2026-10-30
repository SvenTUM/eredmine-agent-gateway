"""Unit tests for eredmine_agent_gateway.stats module and erag stats CLI command."""

from datetime import date, timedelta
import json
import pytest

from eredmine_agent_gateway.cli import main
from eredmine_agent_gateway.db import Easy8DB
from eredmine_agent_gateway.stats import (
    compute_project_stats,
    format_stats_json,
    format_stats_text,
)


@pytest.fixture
def temp_db(tmp_path):
    """Fixture providing a temporary SQLite database."""
    db_file = tmp_path / "test_stats.db"
    db = Easy8DB(db_path=str(db_file))
    yield db
    db.conn.close()


def test_compute_stats_empty_project(temp_db):
    """Empty DB yields all 0 counts and null last_sync."""
    stats = compute_project_stats(project_id=999, db=temp_db)

    assert stats["project_id"] == 999
    assert stats["data_source"] == "local_db"
    assert stats["last_sync"] is None
    assert stats["stale_days_threshold"] == 14
    assert isinstance(stats["generated_at"], str)

    issues = stats["issues"]
    assert issues["total"] == 0
    assert issues["open"] == 0
    assert issues["closed"] == 0
    assert issues["without_time_entries"] == 0
    assert issues["stale"] == 0
    assert issues["with_comments"] == 0
    assert issues["overdue"] == 0
    assert issues["due_within_7_days"] == 0
    assert issues["avg_age_open_days"] == 0.0

    assert stats["time_entries"]["total_hours"] == 0.0


def test_open_closed_counts(temp_db):
    """Verify issues are properly partitioned into open and closed."""
    temp_db.upsert_project({"id": 1, "name": "Test Project"})

    # Open issues (status_id not in CLOSED_STATUS_IDS, e.g. 1, 2)
    temp_db.upsert_issue(
        {"id": 101, "project_id": 1, "status_id": 1, "subject": "Open 1"}
    )
    temp_db.upsert_issue(
        {"id": 102, "project_id": 1, "status_id": 2, "subject": "Open 2"}
    )

    # Closed issues (status_id 5, 6)
    temp_db.upsert_issue(
        {"id": 103, "project_id": 1, "status_id": 6, "subject": "Closed 1"}
    )
    temp_db.upsert_issue(
        {"id": 104, "project_id": 1, "status_id": 5, "subject": "Closed 2"}
    )

    stats = compute_project_stats(project_id=1, db=temp_db)
    assert stats["issues"]["total"] == 4
    assert stats["issues"]["open"] == 2
    assert stats["issues"]["closed"] == 2


def test_stale_detection(temp_db):
    """Verify stale detection based on start_date and activity."""
    temp_db.upsert_project({"id": 1, "name": "Test Project"})
    today = date.today()

    # Issue 1: Open, updated 20 days ago (stale when threshold=14)
    start_20d_ago = (today - timedelta(days=20)).isoformat()
    temp_db.upsert_issue({
        "id": 101,
        "project_id": 1,
        "status_id": 1,
        "start_date": start_20d_ago,
        "subject": "Stale Issue",
    })

    # Issue 2: Open, updated 5 days ago (fresh when threshold=14)
    start_5d_ago = (today - timedelta(days=5)).isoformat()
    temp_db.upsert_issue({
        "id": 102,
        "project_id": 1,
        "status_id": 1,
        "start_date": start_5d_ago,
        "subject": "Active Issue",
    })

    stats_14 = compute_project_stats(project_id=1, stale_days=14, db=temp_db)
    assert stats_14["issues"]["stale"] == 1

    # With stale_days=4, both issues are stale
    stats_4 = compute_project_stats(project_id=1, stale_days=4, db=temp_db)
    assert stats_4["issues"]["stale"] == 2

    # With stale_days=0, all open issues are stale
    stats_0 = compute_project_stats(project_id=1, stale_days=0, db=temp_db)
    assert stats_0["issues"]["stale"] == 2


def test_stale_detection_with_comments(temp_db):
    """An old issue with a recent comment should not be considered stale."""
    temp_db.upsert_project({"id": 1, "name": "Test Project"})
    today = date.today()

    old_date = (today - timedelta(days=30)).isoformat()
    recent_comment_date = (today - timedelta(days=2)).isoformat()

    temp_db.upsert_issue({
        "id": 101,
        "project_id": 1,
        "status_id": 1,
        "start_date": old_date,
        "subject": "Commented Issue",
    })
    temp_db.upsert_comment({
        "id": 501,
        "issue_id": 101,
        "notes": "Recent update",
        "author_id": 1,
        "created_on": recent_comment_date,
    })

    stats = compute_project_stats(project_id=1, stale_days=14, db=temp_db)
    assert stats["issues"]["stale"] == 0
    assert stats["issues"]["with_comments"] == 1


def test_overdue_and_due_within_7_days(temp_db):
    """Verify overdue and due_within_7_days counts."""
    temp_db.upsert_project({"id": 1, "name": "Test Project"})
    today = date.today()

    # Overdue: due_date < today
    temp_db.upsert_issue({
        "id": 101,
        "project_id": 1,
        "status_id": 1,
        "due_date": (today - timedelta(days=3)).isoformat(),
        "subject": "Overdue",
    })

    # Due within 7 days: today <= due_date <= today + 7
    temp_db.upsert_issue({
        "id": 102,
        "project_id": 1,
        "status_id": 1,
        "due_date": (today + timedelta(days=3)).isoformat(),
        "subject": "Due soon",
    })

    # Due far in future: due_date > today + 7
    temp_db.upsert_issue({
        "id": 103,
        "project_id": 1,
        "status_id": 1,
        "due_date": (today + timedelta(days=20)).isoformat(),
        "subject": "Future",
    })

    # Closed issue with overdue date (should NOT count as overdue)
    temp_db.upsert_issue({
        "id": 104,
        "project_id": 1,
        "status_id": 6,
        "due_date": (today - timedelta(days=5)).isoformat(),
        "subject": "Closed overdue",
    })

    stats = compute_project_stats(project_id=1, db=temp_db)
    assert stats["issues"]["overdue"] == 1
    assert stats["issues"]["due_within_7_days"] == 1


def test_avg_age_open_days(temp_db):
    """Verify average age calculation for open issues."""
    temp_db.upsert_project({"id": 1, "name": "Test Project"})
    today = date.today()

    temp_db.upsert_issue({
        "id": 101,
        "project_id": 1,
        "status_id": 1,
        "start_date": (today - timedelta(days=10)).isoformat(),
    })
    temp_db.upsert_issue({
        "id": 102,
        "project_id": 1,
        "status_id": 1,
        "start_date": (today - timedelta(days=20)).isoformat(),
    })

    stats = compute_project_stats(project_id=1, db=temp_db)
    assert stats["issues"]["avg_age_open_days"] == 15.0


def test_time_entries_and_hours(temp_db):
    """Verify time_entries and total_hours calculation."""
    temp_db.upsert_project({"id": 1, "name": "Test Project"})
    temp_db.upsert_issue({"id": 101, "project_id": 1, "status_id": 1})
    temp_db.upsert_issue({"id": 102, "project_id": 1, "status_id": 1})
    temp_db.upsert_issue({"id": 103, "project_id": 1, "status_id": 1})

    # Create time_entries table and insert records
    with temp_db.conn:
        temp_db.conn.execute(
            """
            CREATE TABLE time_entries (
                id INTEGER PRIMARY KEY,
                issue_id INTEGER,
                project_id INTEGER,
                hours REAL
            )
            """
        )
        temp_db.conn.execute(
            "INSERT INTO time_entries (id, issue_id, project_id, hours) "
            "VALUES (1, 101, 1, 3.5)"
        )
        temp_db.conn.execute(
            "INSERT INTO time_entries (id, issue_id, project_id, hours) "
            "VALUES (2, 101, 1, 2.0)"
        )

    stats = compute_project_stats(project_id=1, db=temp_db)
    assert stats["issues"]["total"] == 3
    assert stats["issues"]["without_time_entries"] == 2
    assert stats["time_entries"]["total_hours"] == 5.5


def test_json_output_keys(temp_db):
    """Verify all expected keys are present in JSON formatted output."""
    temp_db.upsert_project({"id": 42, "name": "PRD Project"})
    temp_db.upsert_issue(
        {"id": 1, "project_id": 42, "status_id": 1, "subject": "Test"}
    )

    # Set last_sync in sync_state
    with temp_db.conn:
        temp_db.conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_state ("
            "project_id INTEGER PRIMARY KEY, last_sync TEXT)"
        )
        temp_db.conn.execute(
            "INSERT INTO sync_state (project_id, last_sync) "
            "VALUES (42, '2026-08-18T20:30:00')"
        )

    stats = compute_project_stats(project_id=42, db=temp_db)
    json_str = format_stats_json(stats)
    parsed = json.loads(json_str)

    assert parsed["project_id"] == 42
    assert parsed["data_source"] == "local_db"
    assert parsed["last_sync"] == "2026-08-18T20:30:00"
    assert parsed["stale_days_threshold"] == 14
    assert "generated_at" in parsed

    assert "issues" in parsed
    expected_issue_keys = {
        "total",
        "open",
        "closed",
        "without_time_entries",
        "stale",
        "with_comments",
        "overdue",
        "due_within_7_days",
        "avg_age_open_days",
    }
    assert set(parsed["issues"].keys()) == expected_issue_keys
    assert "time_entries" in parsed
    assert "total_hours" in parsed["time_entries"]


def test_text_output_format(temp_db):
    """Verify text output contains ═ dividers and expected labels."""
    stats = compute_project_stats(project_id=42, db=temp_db)
    text = format_stats_text(stats, project_id=42)

    assert "═" in text
    assert "Projektstatus – Projekt 42" in text
    assert "Issues gesamt:" in text
    assert "Offen:" in text
    assert "Geschlossen:" in text
    assert "Issues ohne Zeitbuchung:" in text
    assert "Issues ohne Aktivität (>14 Tage):" in text
    assert "Issues mit Kommentaren:" in text
    assert "Durchschn. Alter offener Issues:" in text
    assert "Gesamtstunden (alle Zeiteinträge):" in text
    assert "Fälligkeitsübersicht:"
    assert "Überfällig:" in text
    assert "Fällig in ≤7 Tagen:" in text
    assert "Letzte Synchronisation:" in text


def test_cli_stats_text(monkeypatch, temp_db, capsys):
    """Test CLI erag stats --project-id N text output."""
    temp_db.upsert_project({"id": 1, "name": "CLI Proj"})
    temp_db.upsert_issue(
        {"id": 10, "project_id": 1, "status_id": 1, "subject": "CLI Issue"}
    )

    monkeypatch.setattr("eredmine_agent_gateway.stats.Easy8DB", lambda: temp_db)

    exit_code = main(["stats", "--project-id", "1"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Projektstatus – Projekt 1" in captured.out
    assert "Issues gesamt:" in captured.out


def test_cli_stats_json(monkeypatch, temp_db, capsys):
    """Test CLI erag stats --project-id N --json output."""
    temp_db.upsert_project({"id": 1, "name": "CLI Proj"})
    temp_db.upsert_issue(
        {"id": 10, "project_id": 1, "status_id": 1, "subject": "CLI Issue"}
    )

    monkeypatch.setattr("eredmine_agent_gateway.stats.Easy8DB", lambda: temp_db)

    exit_code = main(["stats", "--project-id", "1", "--json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    parsed = json.loads(captured.out)
    assert parsed["project_id"] == 1
    assert parsed["issues"]["total"] == 1
    assert parsed["issues"]["open"] == 1


def test_cli_stats_missing_project_id(capsys):
    """erag stats without --project-id returns error code 2."""
    exit_code = main(["stats"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "required" in captured.err
    assert "--project-id" in captured.err


def test_no_api_calls_in_stats_module():
    """Verify stats module does not import or use Easy8 API."""
    import eredmine_agent_gateway.stats as stats_mod

    assert not hasattr(stats_mod, "Easy8Manager")
    assert not hasattr(stats_mod, "Easy8Client")


def test_compute_stats_negative_stale_days_raises(temp_db):
    """Negative stale_days raises ValueError."""
    with pytest.raises(ValueError, match="non-negative"):
        compute_project_stats(project_id=1, stale_days=-1, db=temp_db)


def test_stats_multi_project_isolation(temp_db):
    """Verify comments and time entries from project 2 don't leak into 1."""
    temp_db.upsert_project({"id": 1, "name": "Project 1"})
    temp_db.upsert_project({"id": 2, "name": "Project 2"})

    temp_db.upsert_issue({
        "id": 101,
        "project_id": 1,
        "status_id": 1,
        "subject": "Proj 1 Issue",
    })
    temp_db.upsert_issue({
        "id": 201,
        "project_id": 2,
        "status_id": 1,
        "subject": "Proj 2 Issue",
    })

    # Add comment to project 2 issue only
    temp_db.upsert_comment({
        "id": 1,
        "issue_id": 201,
        "notes": "Comment on proj 2",
        "created_on": "2026-08-18T10:00:00",
    })

    # Add time entry to project 2 issue only
    with temp_db.conn:
        temp_db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS time_entries (
                id INTEGER PRIMARY KEY,
                issue_id INTEGER,
                project_id INTEGER,
                hours REAL
            )
            """
        )
        temp_db.conn.execute(
            "INSERT INTO time_entries (id, issue_id, project_id, hours) "
            "VALUES (1, 201, 2, 8.0)"
        )

    stats1 = compute_project_stats(project_id=1, db=temp_db)
    assert stats1["issues"]["total"] == 1
    assert stats1["issues"]["with_comments"] == 0
    assert stats1["issues"]["without_time_entries"] == 1
    assert stats1["time_entries"]["total_hours"] == 0.0

    stats2 = compute_project_stats(project_id=2, db=temp_db)
    assert stats2["issues"]["total"] == 1
    assert stats2["issues"]["with_comments"] == 1
    assert stats2["issues"]["without_time_entries"] == 0
    assert stats2["time_entries"]["total_hours"] == 8.0


def test_due_date_boundary_today(temp_db):
    """Issue due today counts as due_within_7_days, not overdue."""
    temp_db.upsert_project({"id": 1, "name": "Test Project"})
    today = date.today()

    temp_db.upsert_issue({
        "id": 101,
        "project_id": 1,
        "status_id": 1,
        "due_date": today.isoformat(),
        "subject": "Due today",
    })

    stats = compute_project_stats(project_id=1, db=temp_db)
    assert stats["issues"]["overdue"] == 0
    assert stats["issues"]["due_within_7_days"] == 1


def test_parse_date_edge_cases():
    """Verify _parse_date handles various input formats and edge cases."""
    from datetime import datetime
    from eredmine_agent_gateway.stats import _parse_date

    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("short") is None
    assert _parse_date("invalid-date-string") is None
    assert _parse_date(12345) is None
    assert _parse_date("2026-08-19") == date(2026, 8, 19)
    assert _parse_date("2026-08-19T14:30:00") == date(2026, 8, 19)
    assert _parse_date(date(2026, 8, 19)) == date(2026, 8, 19)
    assert _parse_date(datetime(2026, 8, 19, 10, 0, 0)) == date(2026, 8, 19)


def test_cli_stats_negative_stale_days(capsys):
    """erag stats --stale-days -5 prints error message."""
    exit_code = main(["stats", "--project-id", "1", "--stale-days", "-5"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "ERROR" in captured.err


def test_stats_custom_closed_status_ids_env(temp_db, monkeypatch):
    """ERAG_CLOSED_STATUS_IDS overrides default closed statuses."""
    temp_db.upsert_project({"id": 1, "name": "Test Project"})
    temp_db.upsert_issue(
        {"id": 101, "project_id": 1, "status_id": 2, "subject": "S2"}
    )
    temp_db.upsert_issue(
        {"id": 102, "project_id": 1, "status_id": 4, "subject": "S4"}
    )
    temp_db.upsert_issue(
        {"id": 103, "project_id": 1, "status_id": 3, "subject": "S3"}
    )

    monkeypatch.setenv("ERAG_CLOSED_STATUS_IDS", "2,4")
    stats = compute_project_stats(project_id=1, db=temp_db)
    assert stats["issues"]["open"] == 1
    assert stats["issues"]["closed"] == 2


def test_cli_stats_invalid_closed_status_ids_env(
    temp_db, monkeypatch, capsys
):
    """Invalid ERAG_CLOSED_STATUS_IDS produces ERROR and exit code 1."""
    monkeypatch.setenv("ERAG_CLOSED_STATUS_IDS", "abc")
    exit_code = main(["stats", "--project-id", "1"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "ERROR" in captured.err
