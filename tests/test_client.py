from __future__ import annotations

import sys
from pathlib import Path

import pytest
from requests.exceptions import JSONDecodeError

sys.path.insert(0, str(Path("src").resolve()))

from eredmine_agent_gateway.client import RedmineClient  # noqa: E402
from eredmine_agent_gateway.exceptions import Easy8RequestError  # noqa: E402


class _FakeResponse:
    def __init__(
        self,
        text: str,
        payload=None,
        json_error: Exception | None = None,
    ):
        self.text = text
        self._payload = payload
        self._json_error = json_error

    def raise_for_status(self):

        return None

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


@pytest.fixture
def allow_writes(monkeypatch):
    """Enable write requests; the client blocks them by default."""
    monkeypatch.setenv("ERAG_ALLOW_WRITE", "true")


def _client() -> RedmineClient:
    return RedmineClient(
        base_url="https://example.test",
        api_key="dummy",
        timeout_seconds=5,
        max_retries=0,
        retry_backoff_seconds=0.1,
    )


def test_put_returns_empty_dict_for_empty_body(monkeypatch, allow_writes):
    client = _client()

    def fake_put(*args, **kwargs):
        return _FakeResponse(text="")

    monkeypatch.setattr("eredmine_agent_gateway.client.requests.put", fake_put)

    result = client.put("issues/1.json", {"issue": {"subject": "x"}})

    assert result == {}


def test_post_returns_empty_dict_for_empty_body(monkeypatch, allow_writes):
    client = _client()

    def fake_post(*args, **kwargs):
        return _FakeResponse(text="   ")

    monkeypatch.setattr("eredmine_agent_gateway.client.requests.post", fake_post)

    result = client.post("issues.json", {"issue": {"subject": "x"}})

    assert result == {}


def test_put_raises_for_invalid_non_empty_json_body(monkeypatch, allow_writes):
    client = _client()

    def fake_put(*args, **kwargs):
        return _FakeResponse(
            text="not-json",
            json_error=JSONDecodeError("Expecting value", "not-json", 0),
        )

    monkeypatch.setattr("eredmine_agent_gateway.client.requests.put", fake_put)

    with pytest.raises(Easy8RequestError, match="invalid JSON response body"):
        client.put("issues/1.json", {"issue": {"subject": "x"}})


def test_post_raises_when_errors_present_in_body(monkeypatch, allow_writes):
    client = _client()

    def fake_post(*args, **kwargs):
        return _FakeResponse(
            text='{"errors": ["failed"]}',
            payload={"errors": ["failed"]},
        )

    monkeypatch.setattr("eredmine_agent_gateway.client.requests.post", fake_post)

    with pytest.raises(Easy8RequestError, match="failed"):

        client.post("issues.json", {"issue": {"subject": "x"}})
