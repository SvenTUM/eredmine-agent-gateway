from __future__ import annotations

import time
from typing import Any

import requests
from requests.exceptions import (
    ConnectionError,
    HTTPError,
    JSONDecodeError,
    RequestException,
    Timeout,
)

from .config import ALLOW_WRITE_ENV_VAR, resolve_allow_write
from .exceptions import Easy8RequestError, Easy8WriteDisabledError


class RedmineClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: int,
        max_retries: int,
        retry_backoff_seconds: float,
    ):
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-Redmine-API-Key": api_key}
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff_seconds

    @property
    def base_url(self) -> str:
        return self._base_url

    def _ensure_write_allowed(self, method: str, url: str) -> None:
        """Block write requests unless enabled by system configuration.

        Evaluated for every request, before any network I/O takes place.
        """
        if not resolve_allow_write():
            raise Easy8WriteDisabledError(
                f"{method} request to {url} blocked: write access is disabled. "
                f"Set {ALLOW_WRITE_ENV_VAR}=true to allow write requests."
            )

    def _parse_optional_json_response(
        self, response: requests.Response, method: str, url: str
    ) -> dict[str, Any]:
        if not response.text.strip():
            return {}

        try:
            payload = response.json()
        except JSONDecodeError as error:
            raise Easy8RequestError(
                f"{method} request failed for {url}: "
                "invalid JSON response body"
            ) from error

        if isinstance(payload, dict):

            error_payload = payload.get("errors")
            if error_payload:
                raise Easy8RequestError(
                    f"{method} request failed for {url}: {error_payload}"
                )
            return payload

        return {}

    def get(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        attempts = 0
        last_status_code: int | None = None
        while attempts <= self._max_retries:
            response = None
            try:
                response = requests.get(
                    url,
                    headers=self._headers,
                    params=params,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                return response.json()
            except (HTTPError, ConnectionError, Timeout) as error:
                status_code = (
                    response.status_code if response is not None else None
                )
                if status_code in (429, 500, 502, 503, 504):
                    last_status_code = status_code
                    attempts += 1
                    time.sleep(self._retry_backoff * attempts)
                    continue
                raise Easy8RequestError(
                    f"GET request failed for {url}: {error}",
                    status_code=status_code,
                ) from error
            except RequestException as error:
                raise Easy8RequestError(
                    f"GET request failed for {url}: {error}"
                ) from error

        raise Easy8RequestError(
            f"GET request failed after {self._max_retries} retries: {url}",
            status_code=last_status_code,
        )

    def post(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        self._ensure_write_allowed("POST", url)
        headers = self._headers.copy()
        headers["Content-Type"] = "application/json"
        response = None
        try:
            response = requests.post(
                url, headers=headers, json=data, timeout=self._timeout
            )
            response.raise_for_status()
            return self._parse_optional_json_response(response, "POST", url)
        except RequestException as error:
            raise Easy8RequestError(
                f"POST request failed for {url}: {error}",
                status_code=_status_code_of(response),
            ) from error

    def put(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/{endpoint.lstrip('/')}"
        self._ensure_write_allowed("PUT", url)
        headers = self._headers.copy()
        headers["Content-Type"] = "application/json"
        response = None
        try:
            response = requests.put(
                url, headers=headers, json=data, timeout=self._timeout
            )
            response.raise_for_status()
            return self._parse_optional_json_response(response, "PUT", url)
        except RequestException as error:
            raise Easy8RequestError(
                f"PUT request failed for {url}: {error}",
                status_code=_status_code_of(response),
            ) from error


def _status_code_of(response: requests.Response | None) -> int | None:
    return getattr(response, "status_code", None)
