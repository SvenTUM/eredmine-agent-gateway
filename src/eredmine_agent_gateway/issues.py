from typing import Any


class IssueService:
    def __init__(self, client):
        self._client = client

    def get_issue(
        self, issue_id: int, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = self._client.get(f"issues/{issue_id}.json", params=params)
        return payload.get("issue", {})

    def get_issues(
        self, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        payload = self._client.get("issues.json", params=params)
        return payload.get("issues", [])

    def get_issue_relations(self, issue_id: int) -> list[dict[str, Any]]:
        payload = self._client.get(f"issues/{issue_id}/relations.json")
        return payload.get("relations", [])
