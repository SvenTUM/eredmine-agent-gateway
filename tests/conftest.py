"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

SETTING_ENV_VARS = (
    "ERAG_CONFIG",
    "ERAG_BASE_URL",
    "ERAG_CLOSED_STATUS_IDS",
    "ERAG_PRIORITY_MAP",
    "ERAG_ALLOW_WRITE",
)


def _user_config_path(tmp_path: Path) -> Path:
    return tmp_path / "home" / ".erag" / "config.ini"


@pytest.fixture(autouse=True)
def _isolate_user_settings(monkeypatch, tmp_path) -> None:
    """Keep the developer's own eredmine-agent-gateway settings out of every test.

    The default configuration file points into the test's temporary
    directory, and its environment variables are removed, so tests see
    the built-in defaults unless they configure something themselves.
    """
    for name in SETTING_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "eredmine_agent_gateway.config.default_config_path", lambda: _user_config_path(tmp_path)
    )


@pytest.fixture
def user_config_file(tmp_path) -> Callable[..., Path]:
    """Return a function that writes the per-user configuration file."""

    def write(content: str, encoding: str = "utf-8") -> Path:
        path = _user_config_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return path

    return write
