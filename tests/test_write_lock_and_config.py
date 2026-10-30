"""Tests for the write lock, base URL resolution and new manager reads."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from eredmine_agent_gateway.client import RedmineClient
from eredmine_agent_gateway.config import resolve_allow_write, resolve_base_url
from eredmine_agent_gateway.constants import DEFAULT_BASE_URL
from eredmine_agent_gateway.exceptions import (
    Easy8ConfigurationError,
    Easy8RequestError,
    Easy8WriteDisabledError,
)
from eredmine_agent_gateway.manager import Easy8Manager
from eredmine_agent_gateway.time_entries import TimeEntryParams


class _Response:
    def __init__(self, status_code: int = 200, payload: Any = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = "{}"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Client Error for url: https://x.test"
            )

    def json(self) -> Any:
        return self._payload


@pytest.fixture
def sent_requests(monkeypatch) -> list[tuple[str, str]]:
    """Record every outgoing HTTP request instead of sending it."""
    sent: list[tuple[str, str]] = []

    def fake(method: str):
        def _call(url, **kwargs):
            sent.append((method, url))
            return _Response()

        return _call

    for method in ("get", "post", "put"):
        monkeypatch.setattr(f"eredmine_agent_gateway.client.requests.{method}", fake(method))
    return sent


def _manager() -> Easy8Manager:
    return Easy8Manager(api_key="secret-key", base_url="https://x.test")


# --- write lock -----------------------------------------------------------


def test_writes_blocked_by_default_without_network(monkeypatch, sent_requests):
    monkeypatch.delenv("ERAG_ALLOW_WRITE", raising=False)
    manager = _manager()

    with pytest.raises(Easy8WriteDisabledError, match="ERAG_ALLOW_WRITE"):
        manager.create_time_entry(
            TimeEntryParams(issue_id=1, hours=1.0, activity_id=9)
        )
    with pytest.raises(Easy8WriteDisabledError):
        manager.update_issue(1, {"issue": {"notes": "x"}})

    assert sent_requests == []


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", " Yes "])
def test_writes_allowed_with_truthy_values(monkeypatch, sent_requests, value):
    monkeypatch.setenv("ERAG_ALLOW_WRITE", value)
    manager = _manager()

    manager.create_time_entry(TimeEntryParams(issue_id=1, hours=1, activity_id=9))
    manager.update_issue(1, {"issue": {"notes": "x"}})

    assert [m for m, _ in sent_requests] == ["post", "put"]


@pytest.mark.parametrize("value", ["", "false", "0", "no", "ture", "on"])
def test_other_values_keep_writes_blocked(monkeypatch, sent_requests, value):
    monkeypatch.setenv("ERAG_ALLOW_WRITE", value)
    assert resolve_allow_write() is False
    with pytest.raises(Easy8WriteDisabledError):
        _manager().update_issue(1, {"issue": {}})
    assert sent_requests == []


def test_reads_are_not_affected_by_write_lock(monkeypatch, sent_requests):
    monkeypatch.delenv("ERAG_ALLOW_WRITE", raising=False)
    _manager().get_issues()
    assert sent_requests == [("get", "https://x.test/issues.json")]


def test_write_lock_error_does_not_contain_api_key(monkeypatch, sent_requests):
    monkeypatch.delenv("ERAG_ALLOW_WRITE", raising=False)
    with pytest.raises(Easy8WriteDisabledError) as exc_info:
        _manager().update_issue(1, {})
    assert "secret-key" not in str(exc_info.value)


# --- base URL -------------------------------------------------------------


def test_base_url_default(monkeypatch):
    monkeypatch.delenv("ERAG_BASE_URL", raising=False)
    assert resolve_base_url() == DEFAULT_BASE_URL


def test_base_url_from_env_and_explicit_precedence(monkeypatch):
    monkeypatch.setenv("ERAG_BASE_URL", "http://easy8.internal/")
    assert resolve_base_url() == "http://easy8.internal"
    assert resolve_base_url("https://explicit.test") == "https://explicit.test"


def test_base_url_empty_env_counts_as_unset(monkeypatch):
    monkeypatch.setenv("ERAG_BASE_URL", "  ")
    assert resolve_base_url() == DEFAULT_BASE_URL


@pytest.mark.parametrize(
    "value", ["easy8.example.com", "ftp://easy8.test", "https://", "http:///"]
)
def test_base_url_invalid_raises(monkeypatch, value):
    monkeypatch.setenv("ERAG_BASE_URL", value)
    with pytest.raises(Easy8ConfigurationError, match="Invalid Easy8 base URL"):
        resolve_base_url()


def test_manager_uses_env_base_url(monkeypatch, sent_requests):
    monkeypatch.setenv("ERAG_BASE_URL", "https://env.test")
    manager = Easy8Manager(api_key="k")
    manager.get_current_user()
    assert manager.base_url == "https://env.test"
    assert sent_requests == [("get", "https://env.test/users/current.json")]


# --- status codes and new read methods ------------------------------------


@pytest.mark.parametrize("status", [401, 403, 404])
def test_get_error_carries_status_code(monkeypatch, status):
    monkeypatch.setattr(
        "eredmine_agent_gateway.client.requests.get", lambda url, **kw: _Response(status)
    )
    client = RedmineClient("https://x.test", "k", 5, 0, 0)
    with pytest.raises(Easy8RequestError) as exc_info:
        client.get("issues.json")
    assert exc_info.value.status_code == status


def test_get_retry_exhaustion_carries_last_status(monkeypatch):
    monkeypatch.setattr(
        "eredmine_agent_gateway.client.requests.get", lambda url, **kw: _Response(503)
    )
    monkeypatch.setattr("eredmine_agent_gateway.client.time.sleep", lambda s: None)
    client = RedmineClient("https://x.test", "k", 5, 1, 0)
    with pytest.raises(Easy8RequestError) as exc_info:
        client.get("issues.json")
    assert exc_info.value.status_code == 503


def test_connection_error_has_no_status_code(monkeypatch):
    def boom(url, **kw):
        raise requests.exceptions.ConnectionError("unreachable")

    monkeypatch.setattr("eredmine_agent_gateway.client.requests.get", boom)
    client = RedmineClient("https://x.test", "k", 5, 0, 0)
    with pytest.raises(Easy8RequestError) as exc_info:
        client.get("issues.json")
    assert exc_info.value.status_code is None


def test_page_methods_return_items_and_total(monkeypatch):
    payloads = {
        "https://x.test/issues.json": {"issues": [{"id": 1}], "total_count": 7},
        "https://x.test/projects.json": {"projects": [{"id": 2}]},
        "https://x.test/time_entries.json": {
            "time_entries": [],
            "total_count": 0,
        },
        "https://x.test/projects/5.json": {"project": {"id": 5, "name": "P"}},
        "https://x.test/users/current.json": {"user": {"id": 3}},
    }
    monkeypatch.setattr(
        "eredmine_agent_gateway.client.requests.get",
        lambda url, **kw: _Response(200, payloads[url]),
    )
    manager = _manager()

    assert manager.get_issues_page() == ([{"id": 1}], 7)
    assert manager.get_projects_page() == ([{"id": 2}], 1)
    assert manager.get_time_entries_page() == ([], 0)
    assert manager.get_project(5) == {"id": 5, "name": "P"}
    assert manager.get_current_user() == {"id": 3}
