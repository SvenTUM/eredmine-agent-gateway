"""CLI entrypoint for eredmine-agent-gateway — generic Easy8/Redmine access only.

No reminder or job-orchestration commands are defined here.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .config import resolve_api_key
from .exceptions import Easy8ConfigurationError, Easy8Error
from .manager import Easy8Manager
from .sync import sync_project
from .tools import GROUP_BY_VALUES, Easy8Tools, describe_error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="erag",
        description=(
            "Generic Redmine/Easy8 access tool. Use --help on subcommands for"
            " details."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- auth-check ---
    auth_parser = subparsers.add_parser(
        "auth-check",
        help=(
            "Verify that REDMINE_API_KEY is configured and reaches the"
            " Easy8 server"
        ),
        description=(
            "Verify that REDMINE_API_KEY is configured and the Easy8 server"
            " is reachable."
        ),
    )
    auth_parser.set_defaults(handler=_handle_auth_check)

    # --- whoami ---
    whoami_parser = subparsers.add_parser(
        "whoami",
        help="Show the Easy8 user who owns the configured API key",
        description="Show the Easy8 user who owns the configured API key.",
    )
    whoami_parser.set_defaults(handler=_handle_whoami)

    # --- projects ---
    projects_parser = subparsers.add_parser(
        "projects",
        help="List projects visible to the user (JSON)",
        description="List Easy8 projects visible to the user as compact JSON.",
    )
    projects_parser.add_argument(
        "--name",
        dest="name_contains",
        default=None,
        help="Case-insensitive text to match in project name or identifier",
    )
    projects_parser.add_argument(
        "--include-closed",
        action="store_true",
        default=False,
        help="Also list closed and archived projects",
    )
    _add_page_arguments(projects_parser, default_limit=50)
    projects_parser.set_defaults(handler=_handle_projects)

    # --- issue get ---
    issue_get_parser = subparsers.add_parser(
        "issue",
        help="Retrieve a single issue by ID (JSON)",
        description=(
            "Retrieve a single issue with description, custom fields, relations,"
            " child issues, attachment metadata and comments as compact JSON."
        ),
    )
    issue_get_parser.add_argument(
        "issue_id", type=int, help="Numeric issue ID"
    )
    issue_get_parser.add_argument(
        "--max-journals",
        type=int,
        default=20,
        help="Most recent comments to include, 0 = none (default: 20)",
    )
    issue_get_parser.set_defaults(handler=_handle_issue_get)

    # --- issue history ---
    history_parser = subparsers.add_parser(
        "history",
        help="Show the change history of an issue (JSON)",
        description=(
            "Show the periods an issue spent in each status and the changes of"
            " status, assignee, priority, dates and done ratio as compact JSON."
        ),
    )
    history_parser.add_argument("issue_id", type=int, help="Numeric issue ID")
    history_parser.add_argument(
        "--max-changes",
        type=int,
        default=50,
        help="Most recent field changes to include, 0 = none (default: 50)",
    )
    history_parser.set_defaults(handler=_handle_issue_history)

    # --- issues list ---
    issues_parser = subparsers.add_parser(
        "issues",
        help="Search issues matching optional filters (JSON)",
        description=(
            "Search issues, most recently updated first, as compact JSON."
        ),
    )
    issues_parser.add_argument(
        "--project-id", type=int, default=None, help="Filter by project ID"
    )
    issues_parser.add_argument(
        "--status",
        default="open",
        help="open (default), closed, all or a numeric status ID",
    )
    issues_parser.add_argument(
        "--assigned-to",
        default=None,
        help="Filter by assignee: 'me' or a numeric user ID",
    )
    issues_parser.add_argument(
        "--updated-since",
        default=None,
        help="Only issues updated on or after this date (YYYY-MM-DD)",
    )
    _add_page_arguments(issues_parser, default_limit=25)
    issues_parser.set_defaults(handler=_handle_issues_list)

    # --- time-entries list ---
    te_parser = subparsers.add_parser(
        "time-entries",
        help="List or aggregate time entries (JSON)",
        description=(
            "List time entries as compact JSON, or aggregate hours with"
            " --group-by."
        ),
    )
    te_parser.add_argument(
        "--user",
        default=None,
        help="Filter by user: 'me' or a numeric user ID",
    )
    te_parser.add_argument(
        "--project-id", type=int, default=None, help="Filter by project ID"
    )
    te_parser.add_argument(
        "--issue-id", type=int, default=None, help="Filter by issue ID"
    )
    te_parser.add_argument(
        "--from",
        dest="from_date",
        default=None,
        help="First day to include (YYYY-MM-DD)",
    )
    te_parser.add_argument(
        "--to",
        dest="to_date",
        default=None,
        help="Last day to include (YYYY-MM-DD)",
    )
    te_parser.add_argument(
        "--group-by",
        choices=GROUP_BY_VALUES,
        default=None,
        help="Aggregate hours per group instead of listing entries",
    )
    _add_page_arguments(te_parser, default_limit=50)
    te_parser.set_defaults(handler=_handle_time_entries_list)

    # --- sync project ---
    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync issues and comments for a specific project",
        description=(
            "Fetch issues and comments for a project "
            "and write them to the local database."
        ),
    )
    sync_parser.add_argument(
        "--project-id",
        required=True,
        type=int,
        help="Numeric project ID to sync",
    )
    sync_parser.set_defaults(handler=_handle_sync)

    # --- report-base ---
    report_base_parser = subparsers.add_parser(
        "report-base",
        help="Generate a base Markdown report from local DB",
        description=(
            "Generate a base Markdown report from local DB without "
            "hitting Redmine API."
        ),
    )
    report_base_parser.add_argument(
        "--project-id", type=int, required=True, help="Numeric project ID"
    )
    report_base_parser.set_defaults(handler=_handle_report_base)

    # --- stats ---
    stats_parser = subparsers.add_parser(
        "stats",
        help="Display aggregated project statistics from local DB",
        description=(
            "Display aggregated project statistics from local DB without "
            "hitting Redmine API."
        ),
    )
    stats_parser.add_argument(
        "--project-id",
        type=int,
        required=True,
        help="Numeric project ID",
    )
    stats_parser.add_argument(
        "--stale-days",
        type=int,
        default=14,
        help="Inactivity threshold in days for stale issues (default: 14)",
    )
    stats_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output in JSON format",
    )
    stats_parser.set_defaults(handler=_handle_stats)

    # --- summary ---
    summary_parser = subparsers.add_parser(
        "summary",
        help="Generate a structured Markdown summary using live Easy8 API",
        description=(
            "Generate a structured Markdown summary of a project using live "
            "data from the Easy8 API."
        ),
    )
    summary_parser.add_argument(
        "--project-id",
        type=int,
        required=True,
        help="Numeric project ID",
    )
    summary_parser.add_argument(
        "--stale-days",
        type=int,
        default=14,
        help="Inactivity threshold in days for stale issues (default: 14)",
    )
    summary_parser.set_defaults(handler=_handle_summary)

    # --- mcp ---
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Start the read-only MCP server (stdio) for AI agents",
        description=(
            "Start the read-only MCP server over stdio. Requires the optional"
            " 'mcp' extra (pip install 'eredmine-agent-gateway[mcp]')."
        ),
    )
    mcp_parser.set_defaults(handler=_handle_mcp)

    return parser


def _add_page_arguments(
    parser: argparse.ArgumentParser, default_limit: int
) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=default_limit,
        help=f"Page size, 1-100 (default: {default_limit})",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Number of results to skip (use next_offset from the output)",
    )


def _handle_auth_check(_args: argparse.Namespace) -> int:
    """Verify credentials by performing a generic reachability check.

    Uses a minimal ``issues.json?limit=1`` call — no domain-specific
    assumption about a particular issue ID existing.
    """
    try:
        resolve_api_key()
    except Easy8ConfigurationError:
        print("AUTH FAIL: REDMINE_API_KEY is not set.", file=sys.stderr)
        return 1

    manager = Easy8Manager()
    try:
        # Generic reachability check: list issues with limit=1.
        # This validates API key, server reachability, and basic read
        # permission without depending on any specific issue ID.
        issues = manager.get_issues(params={"limit": 1})
        print(
            f"AUTH OK: Connected to {manager._client._base_url} successfully "
            f"(retrieved {len(issues)} issue(s) as reachability probe)."
        )
        return 0
    except Easy8Error as exc:
        print(f"AUTH FAIL: {exc}", file=sys.stderr)
        return 1


def _run_tool(tool_name: str, **arguments: Any) -> int:
    """Run one agent tool and print its output unchanged (same as MCP)."""
    try:
        resolve_api_key()
        tools = Easy8Tools(Easy8Manager())
        output = getattr(tools, tool_name)(**arguments)
    except (Easy8Error, ValueError) as exc:
        print(f"ERROR: {describe_error(exc)}", file=sys.stderr)
        return 1
    print(output)
    return 0


def _handle_whoami(_args: argparse.Namespace) -> int:
    return _run_tool("whoami")


def _handle_projects(args: argparse.Namespace) -> int:
    return _run_tool(
        "list_projects",
        name_contains=args.name_contains,
        include_closed=args.include_closed,
        limit=args.limit,
        offset=args.offset,
    )


def _handle_issue_get(args: argparse.Namespace) -> int:
    return _run_tool(
        "get_issue", issue_id=args.issue_id, max_journals=args.max_journals
    )


def _handle_issue_history(args: argparse.Namespace) -> int:
    return _run_tool(
        "get_issue_history", issue_id=args.issue_id, max_changes=args.max_changes
    )


def _handle_issues_list(args: argparse.Namespace) -> int:
    return _run_tool(
        "search_issues",
        project_id=args.project_id,
        status=args.status,
        assigned_to=args.assigned_to,
        updated_since=args.updated_since,
        limit=args.limit,
        offset=args.offset,
    )


def _handle_time_entries_list(args: argparse.Namespace) -> int:
    return _run_tool(
        "list_time_entries",
        user=args.user,
        project_id=args.project_id,
        issue_id=args.issue_id,
        from_date=args.from_date,
        to_date=args.to_date,
        group_by=args.group_by,
        limit=args.limit,
        offset=args.offset,
    )


def _handle_sync(args: argparse.Namespace) -> int:
    """Sync project issues and comments."""
    try:
        resolve_api_key()
    except Easy8ConfigurationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        sync_project(args.project_id)
        print(f"Sync completed successfully for project {args.project_id}.")
        return 0
    except Easy8Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _handle_report_base(args: argparse.Namespace) -> int:
    """Generate and print base markdown report."""
    from .reporting import generate_base_report

    try:
        report = generate_base_report(args.project_id)
        print(report)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _handle_stats(args: argparse.Namespace) -> int:
    """Compute and display project statistics from local DB."""
    from .stats import (
        compute_project_stats,
        format_stats_json,
        format_stats_text,
    )

    try:
        stats = compute_project_stats(
            project_id=args.project_id,
            stale_days=args.stale_days,
        )
        if args.json:
            print(format_stats_json(stats))
        else:
            print(format_stats_text(stats, project_id=args.project_id))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _handle_summary(args: argparse.Namespace) -> int:
    """Print the Markdown project summary using live Easy8 API data."""
    return _run_tool(
        "project_summary",
        project_id=args.project_id,
        stale_days=args.stale_days,
    )


def _handle_mcp(_args: argparse.Namespace) -> int:
    """Serve the read-only agent tools over stdio (MCP)."""
    try:
        from .mcp_server import run_stdio_server
    except ImportError as exc:
        print(
            "ERROR: The MCP server requires the optional 'mcp' extra: "
            f"pip install 'eredmine-agent-gateway[mcp]' ({exc})",
            file=sys.stderr,
        )
        return 1
    run_stdio_server()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns exit code.

    Catches SystemExit from argparse (--help, parse errors) and returns
    the code instead of propagating the exception, so callers (or tests)
    receive a clean return value.
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if exc.code is not None else 0

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
