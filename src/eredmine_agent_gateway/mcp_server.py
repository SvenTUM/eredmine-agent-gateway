"""Local MCP server (stdio) exposing the read-only eredmine-agent-gateway agent tools.

Requires the optional ``mcp`` extra. The server reads ``REDMINE_API_KEY`` and
further configuration from its environment, which the harness (Claude Code,
opencode, agy) sets in its MCP server configuration.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from importlib import metadata
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .exceptions import Easy8Error
from .manager import Easy8Manager
from .tools import TOOL_NAMES, Easy8Tools, describe_error, parse_tool_docstring

SERVER_NAME = "erag"
SERVER_INSTRUCTIONS = (
    "Read-only access to Easy8 (Easy Redmine) with the user's own permissions. "
    "Use whoami to resolve 'me', list_projects to map project names to IDs and "
    "project_summary for project overviews and get_issue_history to see since "
    "when an issue is in its status and how it changed. List results are "
    "paginated: pass next_offset as offset to continue. Use list_time_entries "
    "with group_by for hour totals instead of listing all entries."
)

ManagerFactory = Callable[[], Easy8Manager]


def build_server(manager_factory: ManagerFactory = Easy8Manager) -> MCPServer:
    """Create the MCP server with exactly the read-only agent tools.

    A new manager is created per tool call, so configuration errors (e.g. a
    missing API key) are reported as tool errors instead of startup failures.
    """
    server = MCPServer(
        name=SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        version=_package_version(),
    )
    for name in TOOL_NAMES:
        description, function = _tool_function(name, manager_factory)
        server.add_tool(
            function,
            name=name,
            description=description,
            annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
            structured_output=False,
        )
    return server


def run_stdio_server() -> None:
    """Serve the tools over stdio until the client disconnects."""
    build_server().run("stdio")


def _tool_function(
    name: str, manager_factory: ManagerFactory
) -> tuple[str, Callable[..., str]]:
    """Wrap a tool-layer method as a plain function for the MCP SDK.

    The wrapper carries the method's signature (without ``self``) with the
    parameter descriptions from the docstring attached as schema metadata.
    """
    method = getattr(Easy8Tools, name)
    description, param_docs = parse_tool_docstring(method.__doc__)
    hints = typing.get_type_hints(method)
    signature = inspect.signature(method)
    parameters = [
        parameter.replace(
            annotation=Annotated[
                hints[parameter.name],
                Field(description=param_docs.get(parameter.name)),
            ]
        )
        for parameter in list(signature.parameters.values())[1:]
    ]

    def call(**kwargs: Any) -> str:
        try:
            return getattr(Easy8Tools(manager_factory()), name)(**kwargs)
        except (Easy8Error, ValueError) as exc:
            raise ToolError(describe_error(exc)) from exc

    call.__name__ = name
    call.__doc__ = description
    call.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=parameters, return_annotation=str
    )
    return description, call


def _package_version() -> str:
    try:
        return metadata.version("eredmine-agent-gateway")
    except metadata.PackageNotFoundError:
        return ""
