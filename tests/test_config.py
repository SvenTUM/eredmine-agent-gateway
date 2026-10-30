"""Tests for eredmine-agent-gateway configuration resolvers."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch
import pytest

from eredmine_agent_gateway.config import (
    EASY8_CLOSED_STATUS_IDS_DEFAULT,
    EASY8_PRIORITY_MAP_DEFAULT,
    read_config_file,
    resolve_api_key,
    resolve_base_url,
    resolve_closed_status_ids,
    resolve_config_path,
    resolve_priority_map,
)
from eredmine_agent_gateway.constants import DEFAULT_BASE_URL
from eredmine_agent_gateway.exceptions import Easy8ConfigurationError


def test_resolve_api_key_explicit() -> None:
    assert resolve_api_key("explicit-key") == "explicit-key"


def test_resolve_api_key_from_env() -> None:
    with patch.dict(os.environ, {"REDMINE_API_KEY": "env-key"}, clear=True):
        assert resolve_api_key() == "env-key"


def test_resolve_api_key_missing_raises() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(
            Easy8ConfigurationError, match="Missing REDMINE_API_KEY"
        ):
            resolve_api_key()


def test_resolve_closed_status_ids_default() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_closed_status_ids() == EASY8_CLOSED_STATUS_IDS_DEFAULT
        assert resolve_closed_status_ids() == frozenset({5, 6})


def test_resolve_closed_status_ids_custom() -> None:
    with patch.dict(
        os.environ, {"ERAG_CLOSED_STATUS_IDS": "2,4"}, clear=True
    ):
        assert resolve_closed_status_ids() == frozenset({2, 4})


def test_resolve_closed_status_ids_custom_with_whitespace() -> None:
    with patch.dict(
        os.environ, {"ERAG_CLOSED_STATUS_IDS": " 2 ,  4 , 6 "}, clear=True
    ):
        assert resolve_closed_status_ids() == frozenset({2, 4, 6})


def test_resolve_closed_status_ids_single_val() -> None:
    with patch.dict(os.environ, {"ERAG_CLOSED_STATUS_IDS": "9"}, clear=True):
        assert resolve_closed_status_ids() == frozenset({9})


@pytest.mark.parametrize(
    "invalid_val",
    [
        "abc",
        "",
        "   ",
        "2,abc",
        "2,,4",
        "2,4,",
        ",2,4",
    ],
)
def test_resolve_closed_status_ids_invalid(invalid_val: str) -> None:
    with patch.dict(
        os.environ, {"ERAG_CLOSED_STATUS_IDS": invalid_val}, clear=True
    ):
        with pytest.raises(Easy8ConfigurationError):
            resolve_closed_status_ids()


def test_resolve_priority_map_default() -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_priority_map() == EASY8_PRIORITY_MAP_DEFAULT
        assert resolve_priority_map() == {
            1: "Low",
            2: "Normal",
            3: "High",
            4: "Urgent",
            5: "Immediate",
        }


def test_resolve_priority_map_custom_key_value() -> None:
    with patch.dict(
        os.environ,
        {"ERAG_PRIORITY_MAP": "1=Low,2=Medium,3=High,4=Urgent"},
        clear=True,
    ):
        assert resolve_priority_map() == {
            1: "Low",
            2: "Medium",
            3: "High",
            4: "Urgent",
        }


def test_resolve_priority_map_custom_colon_and_spaces() -> None:
    with patch.dict(
        os.environ,
        {"ERAG_PRIORITY_MAP": " 1: Low , 2: High "},
        clear=True,
    ):
        assert resolve_priority_map() == {1: "Low", 2: "High"}


def test_resolve_priority_map_custom_json() -> None:
    with patch.dict(
        os.environ,
        {"ERAG_PRIORITY_MAP": '{"1": "Niedrig", "2": "Hoch"}'},
        clear=True,
    ):
        assert resolve_priority_map() == {1: "Niedrig", 2: "Hoch"}


@pytest.mark.parametrize(
    "invalid_val",
    [
        "abc",
        "",
        "   ",
        "1=",
        "=Normal",
        "1=Low,abc",
        "1=Low,,2=High",
        "{invalid json",
        "{}",
        "[]",
        '{"abc": "Normal"}',
        '{"1": null}',
        '{"1": ""}',
    ],
)
def test_resolve_priority_map_invalid(invalid_val: str) -> None:
    with patch.dict(
        os.environ, {"ERAG_PRIORITY_MAP": invalid_val}, clear=True
    ):
        with pytest.raises(Easy8ConfigurationError):
            resolve_priority_map()


# --- configuration file ----------------------------------------------------

SAMPLE_CONFIG = """
# Settings of one installation
[easy8]
base_url = https://tickets.example.org/
closed_status_ids = 7, 8, 9
priority_map = 1=Gering, 2=Mittel, 9=Zurückgestellt
"""


def test_config_file_provides_settings(user_config_file) -> None:
    user_config_file(SAMPLE_CONFIG)
    assert resolve_base_url() == "https://tickets.example.org"
    assert resolve_closed_status_ids() == frozenset({7, 8, 9})
    assert resolve_priority_map() == {
        1: "Gering",
        2: "Mittel",
        9: "Zurückgestellt",
    }


def test_environment_overrides_config_file(user_config_file, monkeypatch):
    user_config_file(SAMPLE_CONFIG)
    monkeypatch.setenv("ERAG_BASE_URL", "https://env.example.org")
    monkeypatch.setenv("ERAG_CLOSED_STATUS_IDS", "1")
    monkeypatch.setenv("ERAG_PRIORITY_MAP", "1=Env")
    assert resolve_base_url() == "https://env.example.org"
    assert resolve_closed_status_ids() == frozenset({1})
    assert resolve_priority_map() == {1: "Env"}


def test_explicit_base_url_overrides_environment_and_file(
    user_config_file, monkeypatch
) -> None:
    user_config_file(SAMPLE_CONFIG)
    monkeypatch.setenv("ERAG_BASE_URL", "https://env.example.org")
    assert (
        resolve_base_url("https://explicit.example.org")
        == "https://explicit.example.org"
    )


def test_empty_base_url_env_falls_back_to_config_file(
    user_config_file, monkeypatch
) -> None:
    user_config_file(SAMPLE_CONFIG)
    monkeypatch.setenv("ERAG_BASE_URL", "  ")
    assert resolve_base_url() == "https://tickets.example.org"


def test_missing_default_config_file_uses_defaults() -> None:
    assert read_config_file() == {}
    assert resolve_base_url() == DEFAULT_BASE_URL
    assert resolve_closed_status_ids() == EASY8_CLOSED_STATUS_IDS_DEFAULT
    assert resolve_priority_map() == EASY8_PRIORITY_MAP_DEFAULT


def test_config_file_location_from_easy8_config(tmp_path, monkeypatch):
    path = tmp_path / "elsewhere.ini"
    path.write_text(
        "[easy8]\nbase_url = https://other.example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("ERAG_CONFIG", str(path))
    assert resolve_config_path() == path
    assert resolve_base_url() == "https://other.example.org"


def test_easy8_config_pointing_to_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ERAG_CONFIG", str(tmp_path / "missing.ini"))
    with pytest.raises(Easy8ConfigurationError, match="does not exist"):
        resolve_base_url()


def test_unparseable_config_file_raises(user_config_file) -> None:
    user_config_file("base_url = https://no-section.example.org\n")
    with pytest.raises(
        Easy8ConfigurationError, match="Cannot read configuration file"
    ):
        resolve_base_url()


def test_config_file_without_easy8_section_is_ignored(
    user_config_file, caplog
) -> None:
    user_config_file("[other]\nbase_url = https://ignored.example.org\n")
    with caplog.at_level(logging.WARNING, logger="eredmine_agent_gateway.config"):
        assert resolve_base_url() == DEFAULT_BASE_URL
    assert "no [easy8] section" in caplog.text


def test_unknown_config_keys_are_ignored_with_warning(
    user_config_file, caplog
) -> None:
    user_config_file("[easy8]\nbase-url = https://typo.example.org\n")
    with caplog.at_level(logging.WARNING, logger="eredmine_agent_gateway.config"):
        assert read_config_file() == {}
    assert "base-url" in caplog.text


def test_invalid_config_value_names_the_file(user_config_file) -> None:
    path = user_config_file("[easy8]\nclosed_status_ids = 5, x\n")
    with pytest.raises(Easy8ConfigurationError) as exc_info:
        resolve_closed_status_ids()
    assert "closed_status_ids" in str(exc_info.value)
    assert str(path) in str(exc_info.value)


def test_empty_config_value_raises(user_config_file) -> None:
    user_config_file("[easy8]\npriority_map =\n")
    with pytest.raises(Easy8ConfigurationError, match="cannot be empty"):
        resolve_priority_map()


def test_config_file_with_byte_order_mark(user_config_file) -> None:
    user_config_file("[easy8]\npriority_map = 1=Hoch\n", encoding="utf-8-sig")
    assert resolve_priority_map() == {1: "Hoch"}
