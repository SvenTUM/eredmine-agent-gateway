from __future__ import annotations


class Easy8Error(Exception):
    """Base exception for eredmine-agent-gateway package errors."""


class Easy8ConfigurationError(Easy8Error):
    """Raised when required runtime configuration is missing or invalid."""


class Easy8RequestError(Easy8Error):
    """Raised for HTTP/API request failures.

    ``status_code`` holds the HTTP status of the failed response, or ``None``
    when no response was received (e.g. connection error or timeout).
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class Easy8WriteDisabledError(Easy8Error):
    """Raised when a write request is attempted while writes are disabled."""
