"""
title: Easy8
author: Sven van Crombrugge
author_url: https://github.com/SvenTUM/eredmine-agent-gateway
version: 4.0.0
license: GPL-3.0-or-later
description: Read-only access to Easy8 (Easy Redmine) with each user's personal API key.
required_open_webui_version: 0.11.0
requirements: eredmine-agent-gateway @ https://github.com/SvenTUM/eredmine-agent-gateway/archive/refs/tags/v4.0.0.tar.gz
"""

# Open WebUI workspace tool for eredmine-agent-gateway.
#
# Every public method of `Tools` becomes a tool for the model. Each call runs
# with the calling user's personal Easy8 API key (user settings), so Easy8's
# access rights always apply. The tool offers no write functions.
#
# The tool logic lives in the `eredmine_agent_gateway` package (installed through the
# `requirements` line above or pre-installed in the Open WebUI image); this
# file only adapts it to Open WebUI. Tool names, parameters and descriptions
# are identical to the eredmine-agent-gateway MCP server and CLI.

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from pydantic import BaseModel, Field

from eredmine_agent_gateway.constants import DEFAULT_TIMEOUT_SECONDS
from eredmine_agent_gateway.exceptions import Easy8Error
from eredmine_agent_gateway.manager import Easy8Manager
from eredmine_agent_gateway.tools import TOOL_NAMES, Easy8Tools, describe_error

MISSING_KEY_MESSAGE = (
    "No personal Easy8 API key is configured for this user. Ask the user to "
    "open the user settings (valves) of the 'Easy8' tool in the chat "
    "and enter their API key from Easy8: My account -> API access key."
)


class Tools:
    class Valves(BaseModel):
        easy8_base_url: str = Field(
            default="",
            description=(
                "Base URL of the Easy8 server as reachable from Open WebUI. "
                "Empty: use ERAG_BASE_URL or the eredmine-agent-gateway configuration file."
            ),
        )
        request_timeout_seconds: int = Field(
            default=DEFAULT_TIMEOUT_SECONDS,
            ge=1,
            le=300,
            description="Timeout per Easy8 request in seconds.",
        )

    class UserValves(BaseModel):
        easy8_api_key: str = Field(
            default="",
            description=(
                "Your personal Easy8 API key (Easy8: My account -> API access "
                "key). It is only used for your own requests."
            ),
            json_schema_extra={"input": {"type": "password"}},
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def whoami(
        self,
        __user__: dict | None = None,
        __event_emitter__: Any = None,
    ) -> str:
        return await self._run("whoami", __user__, __event_emitter__)

    async def list_projects(
        self,
        name_contains: str | None = None,
        include_closed: bool = False,
        limit: int = 50,
        offset: int = 0,
        __user__: dict | None = None,
        __event_emitter__: Any = None,
    ) -> str:
        return await self._run(
            "list_projects",
            __user__,
            __event_emitter__,
            name_contains=name_contains,
            include_closed=include_closed,
            limit=limit,
            offset=offset,
        )

    async def search_issues(
        self,
        project_id: int | None = None,
        status: str = "open",
        assigned_to: str | None = None,
        updated_since: str | None = None,
        limit: int = 25,
        offset: int = 0,
        __user__: dict | None = None,
        __event_emitter__: Any = None,
    ) -> str:
        return await self._run(
            "search_issues",
            __user__,
            __event_emitter__,
            project_id=project_id,
            status=status,
            assigned_to=assigned_to,
            updated_since=updated_since,
            limit=limit,
            offset=offset,
        )

    async def get_issue(
        self,
        issue_id: int,
        max_journals: int = 20,
        __user__: dict | None = None,
        __event_emitter__: Any = None,
    ) -> str:
        return await self._run(
            "get_issue",
            __user__,
            __event_emitter__,
            issue_id=issue_id,
            max_journals=max_journals,
        )

    async def get_issue_history(
        self,
        issue_id: int,
        max_changes: int = 50,
        __user__: dict | None = None,
        __event_emitter__: Any = None,
    ) -> str:
        return await self._run(
            "get_issue_history",
            __user__,
            __event_emitter__,
            issue_id=issue_id,
            max_changes=max_changes,
        )

    async def list_time_entries(
        self,
        user: str | None = None,
        project_id: int | None = None,
        issue_id: int | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        group_by: str | None = None,
        limit: int = 50,
        offset: int = 0,
        __user__: dict | None = None,
        __event_emitter__: Any = None,
    ) -> str:
        return await self._run(
            "list_time_entries",
            __user__,
            __event_emitter__,
            user=user,
            project_id=project_id,
            issue_id=issue_id,
            from_date=from_date,
            to_date=to_date,
            group_by=group_by,
            limit=limit,
            offset=offset,
        )

    async def project_summary(
        self,
        project_id: int,
        stale_days: int = 14,
        __user__: dict | None = None,
        __event_emitter__: Any = None,
    ) -> str:
        return await self._run(
            "project_summary",
            __user__,
            __event_emitter__,
            project_id=project_id,
            stale_days=stale_days,
        )

    async def _run(
        self,
        tool_name: str,
        user: dict | None,
        event_emitter: Any,
        **arguments: Any,
    ) -> str:
        api_key = _user_api_key(user)
        if not api_key:
            return MISSING_KEY_MESSAGE

        await _emit_status(event_emitter, "Querying Easy8 ...", done=False)
        try:
            # eredmine-agent-gateway performs blocking HTTP requests; keep the event loop free.
            output = await asyncio.to_thread(
                self._call_tool, tool_name, api_key, arguments
            )
        except (Easy8Error, ValueError) as exc:
            output = f"Error: {describe_error(exc)}"
        await _emit_status(event_emitter, "Easy8 query finished", done=True)
        return output

    def _call_tool(
        self, tool_name: str, api_key: str, arguments: dict[str, Any]
    ) -> str:
        manager = Easy8Manager(
            api_key=api_key,
            base_url=self.valves.easy8_base_url.strip() or None,
            request_timeout=self.valves.request_timeout_seconds,
        )
        return getattr(Easy8Tools(manager), tool_name)(**arguments)


# The model-facing descriptions come from the eredmine-agent-gateway tool layer, so Open WebUI,
# the MCP server and the CLI always describe the tools identically.
# Indentation is stripped because Open WebUI passes the raw text to the model.
for _tool_name in TOOL_NAMES:
    getattr(Tools, _tool_name).__doc__ = inspect.cleandoc(
        getattr(Easy8Tools, _tool_name).__doc__ or ""
    )


def _user_api_key(user: dict | None) -> str:
    valves = (user or {}).get("valves")
    if isinstance(valves, dict):
        key = valves.get("easy8_api_key", "")
    else:
        key = getattr(valves, "easy8_api_key", "")
    return (key or "").strip()


async def _emit_status(event_emitter: Any, description: str, done: bool) -> None:
    if event_emitter is None:
        return
    await event_emitter(
        {"type": "status", "data": {"description": description, "done": done}}
    )
