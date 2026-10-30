"""Unit tests for erag summary command and summary generation module."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from eredmine_agent_gateway.cli import main
from eredmine_agent_gateway.exceptions import Easy8RequestError
from eredmine_agent_gateway.summary import generate_summary


@pytest.fixture
def mock_manager() -> MagicMock:
    manager = MagicMock()
    manager.get_issues.return_value = []
    manager.get_issues_page.return_value = ([], 0)
    manager.get_time_entries.return_value = []
    manager.get_project.return_value = {"name": "Test Project"}
    return manager


def test_summary_sections_present(mock_manager: MagicMock) -> None:
    """Verify all mandatory sections are present in generated markdown."""
    mock_manager.get_issues.return_value = [
        {
            "id": 101,
            "subject": "Implement feature X",
            "status_id": 1,
            "priority": {"id": 2, "name": "Normal"},
            "created_on": "2026-08-01T10:00:00Z",
            "updated_on": "2026-08-18T10:00:00Z",
            "due_date": "2026-08-30",
            "journals": [
                {
                    "id": 1,
                    "notes": "Feature X in progress",
                    "created_on": "2026-08-18T12:00:00Z",
                }
            ],
            "project": {"id": 42, "name": "Alpha Project"},
        }
    ]
    mock_manager.get_time_entries.return_value = [
        {
            "id": 1,
            "hours": 3.5,
            "issue": {"id": 101},
            "spent_on": "2026-08-18",
        }
    ]

    output = generate_summary(
        project_id=42,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert "# Projektzusammenfassung: Alpha Project (ID: 42)" in output
    assert "**Datenstand:** Live (Easy8-API)" in output
    assert "## Projektstatus" in output
    assert "## Offene Issues" in output
    assert "## Zeitbuchungen (Zusammenfassung)" in output
    assert "## Kundenkommunikation in offenen Issues (letzte 10 Kommentare)" in output
    assert "| Issues gesamt | 1 |" in output
    assert "| Offen | 1 |" in output
    assert "| Geschlossen | 0 |" in output
    assert "| Gesamtstunden | 3,5 h |" in output
    assert "| Buchungen gesamt | 1 |" in output
    assert "| Ø Stunden pro Buchung | 3,5 h |" in output
    assert "#101" in output
    assert "Feature X in progress" in output


def test_no_warnings_section_when_none(mock_manager: MagicMock) -> None:
    """Verify ## ⚠️ Warnungen is omitted when no warnings exist."""
    mock_manager.get_issues.return_value = [
        {
            "id": 200,
            "subject": "On track task",
            "status_id": 1,
            "priority_id": 2,
            "created_on": "2026-08-15T10:00:00Z",
            "updated_on": "2026-08-18T10:00:00Z",
            "due_date": "2026-09-10",
            "journals": [],
        }
    ]

    output = generate_summary(
        project_id=1,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert "## ⚠️ Warnungen" not in output


def test_overdue_warning(mock_manager: MagicMock) -> None:
    """Verify overdue warning is triggered when due_date < today."""
    mock_manager.get_issues.return_value = [
        {
            "id": 1042,
            "subject": "Fehler in Lagerverwaltung",
            "status_id": 1,
            "priority": {"name": "Hoch"},
            "created_on": "2026-07-01T10:00:00Z",
            "updated_on": "2026-08-18T10:00:00Z",
            "due_date": "2026-08-10",
            "journals": [],
        }
    ]

    output = generate_summary(
        project_id=1,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert "## ⚠️ Warnungen" in output
    assert (
        "> ⚠️ **1 Issue überfällig** "
        "(Fälligkeitsdatum überschritten, noch offen):"
    ) in output
    assert (
        "#1042 „Fehler in Lagerverwaltung\" – fällig seit 2026-08-10 "
        "(Priorität: Hoch)"
    ) in output


def test_stale_warning(mock_manager: MagicMock) -> None:
    """Verify stale warning is triggered when issue activity > stale_days."""
    mock_manager.get_issues.return_value = [
        {
            "id": 1038,
            "subject": "Datenbankoptimierung",
            "status_id": 1,
            "priority": {"id": 1, "name": "Low"},
            "created_on": "2026-07-01T10:00:00Z",
            "updated_on": "2026-07-30T10:00:00Z",
            "due_date": "2026-09-30",
            "journals": [],
        }
    ]

    output = generate_summary(
        project_id=1,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert "## ⚠️ Warnungen" in output
    assert (
        "> ⚠️ **1 Issue stale** "
        "(>14 Tage ohne Aktivität, noch offen):"
    ) in output
    assert (
        "#1038 „Datenbankoptimierung\" – letzte Aktivität: 2026-07-30 "
        "(Priorität: Low)"
    ) in output


def test_due_soon_warning(mock_manager: MagicMock) -> None:
    """Verify due soon warning when today <= due_date <= today + 7 days."""
    mock_manager.get_issues.return_value = [
        {
            "id": 1050,
            "subject": "Release-Vorbereitung v2.1",
            "status_id": 1,
            "priority": {"name": "Hoch"},
            "created_on": "2026-08-01T10:00:00Z",
            "updated_on": "2026-08-18T10:00:00Z",
            "due_date": "2026-08-22",
            "journals": [],
        }
    ]

    output = generate_summary(
        project_id=1,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert "## ⚠️ Warnungen" in output
    assert "> ⚠️ **1 Issue fällig in ≤7 Tagen:**" in output
    assert (
        "#1050 „Release-Vorbereitung v2.1\" – fällig: 2026-08-22 "
        "(Priorität: Hoch)"
    ) in output


def test_multiple_warnings_plural_heading(mock_manager: MagicMock) -> None:
    """Verify plural headings when multiple warnings occur in a category."""
    mock_manager.get_issues.return_value = [
        {
            "id": 101,
            "subject": "Bug 1",
            "status_id": 1,
            "priority_id": 3,
            "created_on": "2026-08-01T10:00:00Z",
            "updated_on": "2026-08-18T10:00:00Z",
            "due_date": "2026-08-10",
        },
        {
            "id": 102,
            "subject": "Bug 2",
            "status_id": 2,
            "priority_id": 2,
            "created_on": "2026-08-01T10:00:00Z",
            "updated_on": "2026-08-18T10:00:00Z",
            "due_date": "2026-08-12",
        },
    ]

    output = generate_summary(
        project_id=1,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert (
        "> ⚠️ **2 Issues überfällig** "
        "(Fälligkeitsdatum überschritten, noch offen):"
    ) in output
    assert "#101" in output
    assert "#102" in output


def test_stale_days_custom_threshold(mock_manager: MagicMock) -> None:
    """Verify custom --stale-days changes stale classification threshold."""
    mock_manager.get_issues.return_value = [
        {
            "id": 300,
            "subject": "Medium inactivity task",
            "status_id": 1,
            "created_on": "2026-08-01T10:00:00Z",
            "updated_on": "2026-08-09T10:00:00Z",
            "due_date": "2026-09-30",
        }
    ]

    output_14 = generate_summary(
        project_id=1,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )
    assert "## ⚠️ Warnungen" not in output_14
    assert "| Issues ohne Aktivität (>14 Tage) | 0 |" in output_14

    output_7 = generate_summary(
        project_id=1,
        stale_days=7,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )
    assert "## ⚠️ Warnungen" in output_7
    assert (
        "> ⚠️ **1 Issue stale** (>7 Tage ohne Aktivität, noch offen):"
    ) in output_7
    assert "| Issues ohne Aktivität (>7 Tage) | 1 |" in output_7


def test_empty_project(mock_manager: MagicMock) -> None:
    """Verify empty project yields all sections with zero/empty tables."""
    output = generate_summary(
        project_id=999,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert "# Projektzusammenfassung: Test Project (ID: 999)" in output
    assert "## Projektstatus" in output
    assert "| Issues gesamt | 0 |" in output
    assert "| Offen | 0 |" in output
    assert "| Geschlossen | 0 |" in output
    assert "| Gesamtstunden | 0,0 h |" in output
    assert "## ⚠️ Warnungen" not in output
    assert "## Offene Issues" in output
    assert "## Zeitbuchungen (Zusammenfassung)" in output
    assert "| Buchungen gesamt | 0 |" in output
    assert "## Kundenkommunikation in offenen Issues (letzte 10 Kommentare)" in output


def test_customer_communication_limit_and_order(
    mock_manager: MagicMock,
) -> None:
    """Verify last 10 comments are sorted newest first and truncated."""
    journals: list[dict[str, Any]] = [
        {
            "id": i,
            "notes": f"Comment note number {i} " + ("long text " * 10),
            "created_on": f"2026-08-{i:02d}T10:00:00Z",
        }
        for i in range(1, 16)
    ]
    mock_manager.get_issues.return_value = [
        {
            "id": 1,
            "subject": "Main Issue",
            "status_id": 1,
            "created_on": "2026-08-01T10:00:00Z",
            "updated_on": "2026-08-15T10:00:00Z",
            "journals": journals,
        }
    ]

    output = generate_summary(
        project_id=1,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert "2026-08-15" in output
    assert "2026-08-06" in output
    comm_section = output.split(
        "## Kundenkommunikation in offenen Issues (letzte 10 Kommentare)"
    )[1]
    assert "2026-08-01" not in comm_section
    assert "..." in comm_section


def test_closed_issues_counted_by_server_and_not_listed(
    mock_manager: MagicMock,
) -> None:
    """Open issues and the closed count follow the server's definitions."""
    mock_manager.get_issues.return_value = [
        {
            "id": 12,
            "subject": "Still open",
            "status": {"id": 1, "name": "Offen"},
            "created_on": "2026-08-10T10:00:00Z",
            "updated_on": "2026-08-18T10:00:00Z",
        }
    ]
    mock_manager.get_issues_page.return_value = ([], 2)

    output = generate_summary(
        project_id=1,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert "| Issues gesamt | 3 |" in output
    assert "| Offen | 1 |" in output
    assert "| Geschlossen | 2 |" in output
    issue_params = mock_manager.get_issues.call_args.kwargs["params"]
    assert issue_params["status_id"] == "open"
    count_params = mock_manager.get_issues_page.call_args.kwargs["params"]
    assert count_params["status_id"] == "closed"
    assert count_params["project_id"] == 1


def test_open_issues_table_shows_status_and_days_in_status(
    mock_manager: MagicMock,
) -> None:
    """The open issues table shows the status and since when it applies."""
    mock_manager.get_issues.return_value = [
        {
            "id": 21,
            "subject": "Waiting for customer",
            "status": {"id": 10, "name": "Kunde prüft"},
            "priority": {"id": 2, "name": "Normal"},
            "created_on": "2026-08-01T10:00:00Z",
            "updated_on": "2026-08-12T10:00:00Z",
            "journals": [
                {
                    "id": 1,
                    "created_on": "2026-08-12T09:00:00Z",
                    "details": [
                        {
                            "property": "attr",
                            "name": "status_id",
                            "old_value": "1",
                            "new_value": "10",
                        }
                    ],
                }
            ],
        },
        {
            "id": 22,
            "subject": "Never moved",
            "status": {"id": 1, "name": "Offen"},
            "created_on": "2026-08-15T10:00:00Z",
            "updated_on": "2026-08-15T10:00:00Z",
        },
    ]

    output = generate_summary(
        project_id=1,
        stale_days=14,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert (
        "| ID | Betreff | Status | Im Status (Tage) | Priorität | Fällig am "
        "| Alter (Tage) | Kommentare |"
    ) in output
    assert "| 21 | Waiting for customer | Kunde prüft | 7 | Normal |" in output
    assert "| 22 | Never moved | Offen | 4 |" in output


def test_closed_status_ids_argument_is_deprecated(
    mock_manager: MagicMock,
) -> None:
    with pytest.warns(DeprecationWarning, match="closed_status_ids is ignored"):
        generate_summary(
            project_id=1,
            manager=mock_manager,
            today=date(2026, 8, 19),
            closed_status_ids=frozenset({5}),
        )


def test_cli_summary_missing_project_id() -> None:
    """Verify CLI exits with code != 0 when --project-id is omitted."""
    exit_code = main(["summary"])
    assert exit_code != 0


@patch("eredmine_agent_gateway.cli.resolve_api_key")
@patch("eredmine_agent_gateway.cli.Easy8Manager")
def test_cli_summary_success(
    mock_manager_cls: MagicMock,
    mock_resolve_key: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify CLI summary command runs successfully and prints to stdout."""
    mock_resolve_key.return_value = "dummy-key"
    mock_inst = MagicMock()
    mock_manager_cls.return_value = mock_inst
    mock_inst.get_issues.return_value = [
        {
            "id": 1,
            "subject": "CLI Task",
            "status_id": 1,
            "created_on": "2026-08-10T10:00:00Z",
            "updated_on": "2026-08-18T10:00:00Z",
            "due_date": "2026-09-01",
            "project": {"name": "CLI Project"},
        }
    ]
    mock_inst.get_issues_page.return_value = ([], 0)
    mock_inst.get_time_entries.return_value = []

    exit_code = main(["summary", "--project-id", "1", "--stale-days", "10"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "# Projektzusammenfassung: CLI Project (ID: 1)" in captured.out
    assert captured.err == ""


@patch("eredmine_agent_gateway.cli.resolve_api_key")
def test_cli_summary_missing_api_key(
    mock_resolve_key: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify CLI exits 1 and writes to stderr when API key is missing."""
    from eredmine_agent_gateway.exceptions import Easy8ConfigurationError

    mock_resolve_key.side_effect = Easy8ConfigurationError("No API key")

    exit_code = main(["summary", "--project-id", "1"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "ERROR: No API key" in captured.err


@patch("eredmine_agent_gateway.cli.resolve_api_key")
@patch("eredmine_agent_gateway.cli.Easy8Manager")
def test_cli_summary_api_error_handling(
    mock_manager_cls: MagicMock,
    mock_resolve_key: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify Easy8Error yields clean stderr message and exit code 1."""
    mock_resolve_key.return_value = "dummy-key"
    mock_inst = MagicMock()
    mock_manager_cls.return_value = mock_inst
    mock_inst.get_issues.side_effect = Easy8RequestError("Network error 500")

    exit_code = main(["summary", "--project-id", "1"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "ERROR: Network error 500" in captured.err


def test_negative_stale_days_raises_value_error(
    mock_manager: MagicMock,
) -> None:
    """Verify negative stale_days raises ValueError."""
    with pytest.raises(ValueError, match="stale_days must be non-negative"):
        generate_summary(project_id=1, stale_days=-1, manager=mock_manager)


def test_helper_parse_date_and_formatting() -> None:
    """Verify _parse_date, _format_hours, and _sanitize_table_cell helpers."""
    from datetime import datetime, timezone
    from eredmine_agent_gateway.summary import _format_hours, _parse_date, _sanitize_table_cell

    assert _parse_date(None) is None
    assert _parse_date(123) is None
    assert _parse_date("short") is None
    assert _parse_date("invalid-date-string") is None
    assert _parse_date("2026-08-19T10:00:00Z") == date(2026, 8, 19)
    assert _parse_date(date(2026, 8, 19)) == date(2026, 8, 19)
    assert _parse_date(
        datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
    ) == date(2026, 8, 19)

    assert _format_hours(0.0) == "0,0 h"
    assert _format_hours(3.5) == "3,5 h"
    assert _format_hours(12.34) == "12,3 h"

    assert _sanitize_table_cell("hello\r\nworld|test") == "hello  world test"


def test_priority_and_status_display_fallbacks(
    mock_manager: MagicMock,
) -> None:
    """Verify priority display handles diverse object structures."""
    from eredmine_agent_gateway.summary import _get_priority_display, _get_status_id

    # Default map: {1: "Low", 2: "Normal", 3: "High", 4: "Urgent",
    # 5: "Immediate"}
    assert _get_priority_display({"priority": {"name": "Hoch"}}) == "Hoch"
    assert _get_priority_display({"priority": {"id": 3}}) == "High"
    assert _get_priority_display({"priority": "Dringend"}) == "Dringend"
    assert _get_priority_display({"priority": 4}) == "Urgent"
    assert _get_priority_display({"priority_name": "Kritisch"}) == "Kritisch"
    # Not in default map -> fallback to str(id)
    assert _get_priority_display({"priority_id": 9}) == "9"
    assert _get_priority_display({}) == "-"

    # With custom priority map
    custom_map = {1: "Low", 2: "Normal", 3: "High"}
    assert (
        _get_priority_display(
            {"priority": {"id": 1}}, priority_map=custom_map
        )
        == "Low"
    )
    assert (
        _get_priority_display(
            {"priority_id": 3}, priority_map=custom_map
        )
        == "High"
    )

    assert _get_status_id({"status_id": "1"}) == 1
    assert _get_status_id({"status": {"id": 2}}) == 2
    assert _get_status_id({"status": "3"}) == 3
    assert _get_status_id({}) is None


def test_project_name_fallback(mock_manager: MagicMock) -> None:
    """Verify fallback to 'Projekt N' when name cannot be determined."""
    mock_manager.get_issues.return_value = []
    mock_manager.get_time_entries.return_value = []
    mock_manager.get_project.side_effect = Easy8RequestError("Not found")

    output = generate_summary(
        project_id=404,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )
    assert "# Projektzusammenfassung: Projekt 404 (ID: 404)" in output


def test_summary_uses_priority_map_and_ignores_closed_status_setting(
    mock_manager: MagicMock, monkeypatch
) -> None:
    """ERAG_PRIORITY_MAP applies; ERAG_CLOSED_STATUS_IDS does not matter."""
    monkeypatch.setenv("ERAG_CLOSED_STATUS_IDS", "2,4")
    monkeypatch.setenv("ERAG_PRIORITY_MAP", "1=Low,2=Medium,3=High")

    mock_manager.get_issues.return_value = [
        {
            "id": 101,
            "project_id": 1,
            "subject": "Open per server, status 2",
            "status": {"id": 2, "name": "Angenommen"},
            "priority_id": 1,
        },
        {
            "id": 102,
            "project_id": 1,
            "subject": "Open issue with custom prio",
            "status": {"id": 3, "name": "In Arbeit"},
            "priority_id": 3,
            "start_date": "2026-08-10",
        },
    ]
    mock_manager.get_time_entries.return_value = []

    output = generate_summary(
        project_id=1,
        manager=mock_manager,
        today=date(2026, 8, 19),
    )

    assert "| Offen | 2 |" in output
    assert "| Geschlossen | 0 |" in output
    assert "| 102 | Open issue with custom prio | In Arbeit |" in output
    assert "| High | - |" in output


def test_time_entries_fetched_across_pages(mock_manager: MagicMock) -> None:
    """Hours from all pages of time entries are summed (not only page 1)."""
    page_one = [{"id": i, "hours": 1.0, "spent_on": "2026-08-18"} for i in range(100)]
    page_two = [{"id": 100 + i, "hours": 0.5, "spent_on": "2026-08-18"} for i in range(3)]
    mock_manager.get_time_entries.side_effect = [page_one, page_two]

    output = generate_summary(
        project_id=42, manager=mock_manager, today=date(2026, 8, 19)
    )

    assert "| Gesamtstunden | 101,5 h |" in output
    assert "| Buchungen gesamt | 103 |" in output
    offsets = [
        c.kwargs["request_params"].get("offset")
        for c in mock_manager.get_time_entries.call_args_list
    ]
    assert offsets == [None, 100]


def test_time_entries_forbidden_still_produces_summary(
    mock_manager: MagicMock,
) -> None:
    """A 403 on time entries yields a summary with a 'not available' note."""
    mock_manager.get_issues.return_value = [
        {"id": 7, "subject": "Task", "status_id": 1,
         "created_on": "2026-08-10T10:00:00Z"}
    ]
    mock_manager.get_time_entries.side_effect = Easy8RequestError(
        "403 Forbidden", status_code=403
    )

    output = generate_summary(
        project_id=42, manager=mock_manager, today=date(2026, 8, 19)
    )

    assert "| Gesamtstunden | nicht verfügbar |" in output
    assert "| Offene Issues ohne Zeitbuchung | nicht verfügbar |" in output
    assert "Zeitdaten sind nicht verfügbar" in output
    assert "| Buchungen gesamt |" not in output


def test_time_entries_other_errors_still_raise(mock_manager: MagicMock) -> None:
    """Errors other than 403 on time entries are not swallowed."""
    mock_manager.get_time_entries.side_effect = Easy8RequestError(
        "500 Server Error", status_code=500
    )
    with pytest.raises(Easy8RequestError):
        generate_summary(project_id=42, manager=mock_manager)


def test_private_notes_excluded_from_customer_communication(
    mock_manager: MagicMock,
) -> None:
    """Private (internal) notes never appear in customer communication."""
    mock_manager.get_issues.return_value = [
        {
            "id": 101,
            "subject": "Task",
            "status_id": 1,
            "created_on": "2026-08-01T10:00:00Z",
            "journals": [
                {"id": 1, "notes": "Public reply", "private_notes": False,
                 "created_on": "2026-08-10T10:00:00Z"},
                {"id": 2, "notes": "Internal margin info", "private_notes": True,
                 "created_on": "2026-08-12T10:00:00Z"},
            ],
        }
    ]

    output = generate_summary(
        project_id=42, manager=mock_manager, today=date(2026, 8, 19)
    )

    assert "Public reply" in output
    assert "Internal margin info" not in output
