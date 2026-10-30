from __future__ import annotations

from typing import Any

from .client import RedmineClient
from .config import resolve_api_key, resolve_base_url
from .constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
)
from .issues import IssueService
from .time_entries import TimeEntryParams


class Easy8Manager:
    """Stable public API for generic Easy8/Redmine access.

    Write methods (`create_time_entry`, `update_issue`) are blocked unless
    the system configuration enables writes via `ERAG_ALLOW_WRITE`.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        request_timeout: int = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ):
        resolved_api_key = resolve_api_key(api_key)
        self._client = RedmineClient(
            base_url=resolve_base_url(base_url),
            api_key=resolved_api_key,
            timeout_seconds=request_timeout,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff,
        )
        self._issues = IssueService(self._client)

    @property
    def base_url(self) -> str:
        return self._client.base_url

    def get_current_user(self) -> dict[str, Any]:
        """Return the user who owns the API key."""
        payload = self._client.get("users/current.json")
        return payload.get("user", {})

    def get_user(self, user_id: int) -> dict[str, Any]:
        """Return one user, as far as the API key may see them."""
        payload = self._client.get(f"users/{user_id}.json")
        return payload.get("user", {})

    def get_issue_statuses(self) -> list[dict[str, Any]]:
        """Return the issue statuses of the installation (id, name, is_closed)."""
        payload = self._client.get("issue_statuses.json")
        return payload.get("issue_statuses", [])

    def get_issue_priorities(self) -> list[dict[str, Any]]:
        """Return the issue priorities of the installation (id, name)."""
        payload = self._client.get("enumerations/issue_priorities.json")
        return payload.get("issue_priorities", [])

    def get_project(
        self, project_id: int | str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = self._client.get(f"projects/{project_id}.json", params=params)
        return payload.get("project", {})

    def get_projects_page(
        self, params: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of visible projects and the total count."""
        return self._get_page("projects.json", "projects", params)

    def get_issue(
        self, issue_id: int, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return self._issues.get_issue(issue_id, params=params)

    def get_issues(
        self, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return self._issues.get_issues(params=params)

    def get_issues_page(
        self, params: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of issues and the total count of matches."""
        return self._get_page("issues.json", "issues", params)

    def get_issue_relations(self, issue_id: int) -> list[dict[str, Any]]:
        return self._issues.get_issue_relations(issue_id)

    def get_time_entries(
        self, request_params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        payload = self._client.get("time_entries.json", params=request_params)
        return payload.get("time_entries", [])

    def get_time_entries_page(
        self, params: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        """Return one page of time entries and the total count of matches."""
        return self._get_page("time_entries.json", "time_entries", params)

    def create_time_entry(
        self, time_entry_parameters: TimeEntryParams
    ) -> dict[str, Any]:
        payload = {
            "time_entry": {
                "issue_id": time_entry_parameters.issue_id,
                "hours": time_entry_parameters.hours,
                "activity_id": time_entry_parameters.activity_id,
                "comments": time_entry_parameters.comments,
                "spent_on": time_entry_parameters.spent_on,
            }
        }
        if time_entry_parameters.custom_field_values:
            cf_vals = time_entry_parameters.custom_field_values
            payload["time_entry"]["custom_field_values"] = cf_vals

        return self._client.post("time_entries.json", payload)

    def update_issue(
        self, issue_id: int, update_parameters: dict[str, Any]
    ) -> dict[str, Any]:
        return self._client.put(f"issues/{issue_id}.json", update_parameters)

    def _get_page(
        self, endpoint: str, key: str, params: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], int]:
        payload = self._client.get(endpoint, params=params)
        items = payload.get(key) or []
        total = payload.get("total_count")
        if not isinstance(total, int):
            total = len(items)
        return items, total
