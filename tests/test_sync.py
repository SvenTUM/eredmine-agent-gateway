from unittest.mock import patch

from eredmine_agent_gateway.sync import sync_project


@patch("eredmine_agent_gateway.sync.Easy8DB")
@patch("eredmine_agent_gateway.sync.Easy8Manager")
def test_sync_project(mock_manager_class, mock_db_class):
    mock_manager = mock_manager_class.return_value
    mock_db = mock_db_class.return_value

    # Mock db.conn.execute().fetchone() to return None simulating no prior sync
    mock_db.conn.execute.return_value.fetchone.return_value = None

    # Simulate pagination: first call returns 1 issue, second returns empty
    mock_manager.get_issues.side_effect = [
        [
            {
                "id": 101,
                "project": {"id": 1, "name": "Test Project"},
                "subject": "Test Issue",
                "description": "Issue description",
                "status": {"id": 2},
                "author": {"id": 5},
                "journals": [
                    {
                        "id": 1001,
                        "user": {"id": 6},
                        "notes": "First comment",
                        "created_on": "2023-01-01T10:00:00Z",
                    },
                    {
                        "id": 1002,
                        "user": {"id": 7},
                        "notes": "",  # Should be ignored
                        "created_on": "2023-01-01T11:00:00Z",
                    },
                ],
            }
        ]
    ]

    sync_project(1)

    # Verify get_issues was called
    assert mock_manager.get_issues.call_count == 1
    mock_manager.get_issues.assert_any_call(
        params={
            "project_id": 1,
            "status_id": "*",
            "include": "journals",
            "limit": 100,
            "offset": 0,
        }
    )

    # Verify DB upsert calls
    mock_db.upsert_issue.assert_called_once_with(
        {
            "id": 101,
            "project_id": 1,
            "subject": "Test Issue",
            "description": "Issue description",
            "status_id": 2,
            "author_id": 5,
            "due_date": None,
            "start_date": None,
            "priority_id": None,
        }
    )

    # Only the journal with notes should be upserted
    mock_db.upsert_comment.assert_called_once_with(
        {
            "id": 1001,
            "issue_id": 101,
            "notes": "First comment",
            "author_id": 6,
            "created_on": "2023-01-01T10:00:00Z",
        }
    )


@patch("eredmine_agent_gateway.sync.Easy8DB")
@patch("eredmine_agent_gateway.sync.Easy8Manager")
def test_sync_project_with_due_start_priority(
    mock_manager_class, mock_db_class
):
    mock_manager = mock_manager_class.return_value
    mock_db = mock_db_class.return_value

    mock_db.conn.execute.return_value.fetchone.return_value = None

    mock_manager.get_issues.side_effect = [
        [
            {
                "id": 202,
                "project": {"id": 1, "name": "Test Project"},
                "subject": "Detailed Issue",
                "description": "With dates and priority",
                "status": {"id": 1},
                "author": {"id": 10},
                "due_date": "2026-08-30",
                "start_date": "2026-08-01",
                "priority": {"id": 3, "name": "High"},
                "journals": [],
            }
        ],
        [],
    ]

    sync_project(1)

    mock_db.upsert_issue.assert_called_once_with(
        {
            "id": 202,
            "project_id": 1,
            "subject": "Detailed Issue",
            "description": "With dates and priority",
            "status_id": 1,
            "author_id": 10,
            "due_date": "2026-08-30",
            "start_date": "2026-08-01",
            "priority_id": 3,
        }
    )


def test_sync_project_edge_cases_and_dependency_injection():
    from unittest.mock import MagicMock

    mock_manager = MagicMock()
    mock_db = MagicMock()
    mock_db.conn.execute.return_value.fetchone.return_value = None

    mock_manager.get_issues.side_effect = [
        [
            {
                "id": 303,
                "project": None,
                "subject": "Sparse Issue",
                "status": None,
                "author": None,
                "priority": None,
                "due_date": None,
                "start_date": None,
                "journals": [
                    {
                        "id": 2001,
                        "user": None,
                        "notes": "Anonymous comment",
                        "created_on": "2023-01-02T10:00:00Z",
                    }
                ],
            }
        ],
        [],
    ]

    sync_project(project_id=42, db=mock_db, manager=mock_manager)

    mock_db.upsert_issue.assert_called_once_with(
        {
            "id": 303,
            "project_id": 42,
            "subject": "Sparse Issue",
            "description": "",
            "status_id": None,
            "author_id": None,
            "due_date": None,
            "start_date": None,
            "priority_id": None,
        }
    )

    mock_db.upsert_comment.assert_called_once_with(
        {
            "id": 2001,
            "issue_id": 303,
            "notes": "Anonymous comment",
            "author_id": None,
            "created_on": "2023-01-02T10:00:00Z",
        }
    )
