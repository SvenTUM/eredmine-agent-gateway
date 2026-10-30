"""Configuration helpers for eredmine-agent-gateway.

Settings resolve in this order: explicit argument (where offered),
environment variable, per-user configuration file, built-in default. The
built-in defaults are neutral examples; the values of a real Easy8
installation belong in the configuration file, outside of any repository.
"""

from __future__ import annotations

import configparser
import json
import logging
import os
from pathlib import Path

from .constants import DEFAULT_BASE_URL
from .exceptions import Easy8ConfigurationError

logger = logging.getLogger(__name__)

ALLOW_WRITE_ENV_VAR = "ERAG_ALLOW_WRITE"
ALLOW_WRITE_TRUE_VALUES: frozenset[str] = frozenset({"true", "1", "yes"})

BASE_URL_ENV_VAR = "ERAG_BASE_URL"
CLOSED_STATUS_IDS_ENV_VAR = "ERAG_CLOSED_STATUS_IDS"
PRIORITY_MAP_ENV_VAR = "ERAG_PRIORITY_MAP"
CONFIG_FILE_ENV_VAR = "ERAG_CONFIG"

CONFIG_SECTION = "easy8"
CONFIG_KEYS: frozenset[str] = frozenset(
    {"base_url", "closed_status_ids", "priority_map"}
)

# Neutral defaults modelled on Redmine's standard data: the statuses
# "Closed" (5) and "Rejected" (6) count as closed.
EASY8_CLOSED_STATUS_IDS_DEFAULT: frozenset[int] = frozenset({5, 6})
# Neutral defaults modelled on Redmine's standard issue priorities.
EASY8_PRIORITY_MAP_DEFAULT: dict[int, str] = {
    1: "Low",
    2: "Normal",
    3: "High",
    4: "Urgent",
    5: "Immediate",
}


def resolve_api_key(explicit_api_key: str | None = None) -> str:
    """Resolve Redmine API key from argument or environment."""
    if explicit_api_key:
        return explicit_api_key

    api_key = os.getenv("REDMINE_API_KEY")
    if not api_key:
        raise Easy8ConfigurationError(
            "Missing REDMINE_API_KEY. Provide api_key or set REDMINE_API_KEY."
        )

    return api_key


def resolve_allow_write() -> bool:
    """Return whether write requests (POST/PUT) to Easy8 are allowed.

    Writes are disabled unless the `ERAG_ALLOW_WRITE` environment variable
    is set to `true`, `1` or `yes` (case-insensitive). Any other value keeps
    writes disabled. There is intentionally no programmatic override: the
    system configuration is the single source of truth.
    """
    raw = os.getenv(ALLOW_WRITE_ENV_VAR)
    if raw is None:
        return False
    return raw.strip().lower() in ALLOW_WRITE_TRUE_VALUES


def default_config_path() -> Path:
    """Return the default location of the per-user configuration file."""
    return Path.home() / ".erag" / "config.ini"


def resolve_config_path() -> Path:
    """Return the path of the per-user configuration file.

    `ERAG_CONFIG` overrides `default_config_path()`. An empty value counts
    as unset.
    """
    raw = (os.getenv(CONFIG_FILE_ENV_VAR) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return default_config_path()


def read_config_file() -> dict[str, str]:
    """Return the settings of the `[easy8]` section of the configuration file.

    A missing file at the default location yields no settings. A file named
    by `ERAG_CONFIG` must exist. Unknown keys and a missing `[easy8]`
    section are ignored with a warning.

    Raises:
        Easy8ConfigurationError: If the file named by `ERAG_CONFIG` does
            not exist, or the file cannot be read or parsed.
    """
    path = resolve_config_path()
    if not path.is_file():
        if (os.getenv(CONFIG_FILE_ENV_VAR) or "").strip():
            raise Easy8ConfigurationError(
                f"Configuration file {path} (set in {CONFIG_FILE_ENV_VAR}) "
                "does not exist."
            )
        return {}

    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8-sig") as handle:
            parser.read_file(handle)
    except (OSError, UnicodeDecodeError, configparser.Error) as exc:
        raise Easy8ConfigurationError(
            f"Cannot read configuration file {path}: {exc}"
        ) from exc

    if not parser.has_section(CONFIG_SECTION):
        logger.warning(
            "Configuration file %s has no [%s] section and is ignored.",
            path,
            CONFIG_SECTION,
        )
        return {}

    settings = dict(parser.items(CONFIG_SECTION))
    unknown = sorted(set(settings) - CONFIG_KEYS)
    if unknown:
        logger.warning(
            "Ignoring unknown keys in section [%s] of %s: %s",
            CONFIG_SECTION,
            path,
            ", ".join(unknown),
        )
    return {key: value for key, value in settings.items() if key in CONFIG_KEYS}


def _setting(env_var: str, key: str) -> tuple[str, str] | None:
    """Return the raw value of a setting and a description of its source.

    The environment variable takes precedence over the configuration file.
    Returns None if neither provides the setting.
    """
    raw = os.getenv(env_var)
    if raw is not None:
        return raw, env_var
    value = read_config_file().get(key)
    if value is not None:
        return value, f"'{key}' in {resolve_config_path()}"
    return None


def resolve_base_url(explicit_base_url: str | None = None) -> str:
    """Resolve the Easy8 base URL.

    Precedence: explicit argument, `ERAG_BASE_URL`, `base_url` in the
    configuration file, `DEFAULT_BASE_URL`. Empty values count as unset.

    Raises:
        Easy8ConfigurationError: If the resolved URL does not start with
            `http://` or `https://` or has no host.
    """
    candidate, source = (explicit_base_url or "").strip(), "argument"
    if not candidate:
        candidate = (os.getenv(BASE_URL_ENV_VAR) or "").strip()
        source = BASE_URL_ENV_VAR
    if not candidate:
        candidate = read_config_file().get("base_url", "").strip()
        source = f"'base_url' in {resolve_config_path()}"
    if not candidate:
        candidate, source = DEFAULT_BASE_URL, "built-in default"

    lowered = candidate.lower()
    scheme_prefix = next(
        (p for p in ("https://", "http://") if lowered.startswith(p)), None
    )
    if scheme_prefix is None or not candidate[len(scheme_prefix):].strip("/"):
        raise Easy8ConfigurationError(
            f"Invalid Easy8 base URL {candidate!r} from {source}. "
            "Expected an http:// or https:// URL "
            "(e.g. 'https://easy8.example.com')."
        )
    return candidate.rstrip("/")


def resolve_closed_status_ids() -> frozenset[int]:
    """Resolve the issue status IDs that count as closed.

    Precedence: `ERAG_CLOSED_STATUS_IDS`, `closed_status_ids` in the
    configuration file, `EASY8_CLOSED_STATUS_IDS_DEFAULT`. The value is a
    comma-separated list of integers (e.g. '5,6').

    Raises:
        Easy8ConfigurationError: If the value is empty or not a
            comma-separated list of integers.
    """
    setting = _setting(CLOSED_STATUS_IDS_ENV_VAR, "closed_status_ids")
    if setting is None:
        return EASY8_CLOSED_STATUS_IDS_DEFAULT
    raw, source = setting

    cleaned = raw.strip()
    if not cleaned:
        raise Easy8ConfigurationError(f"{source} cannot be empty when set.")

    try:
        parts = cleaned.split(",")
        ids = set()
        for item in parts:
            item_str = item.strip()
            if not item_str:
                raise ValueError(f"Empty item in {raw!r}")
            ids.add(int(item_str))
        return frozenset(ids)
    except ValueError as exc:
        raise Easy8ConfigurationError(
            f"Invalid {source}: {raw!r}. "
            "Expected comma-separated integers (e.g. '5,6')."
        ) from exc


def resolve_priority_map() -> dict[int, str]:
    """Resolve the mapping of issue priority IDs to display names.

    Precedence: `ERAG_PRIORITY_MAP`, `priority_map` in the configuration
    file, a copy of `EASY8_PRIORITY_MAP_DEFAULT`. The value is either a
    comma-separated key-value list (e.g. '1=Low,2=Normal,3=High') or a JSON
    object (e.g. '{"1": "Low", "2": "Normal"}').

    Raises:
        Easy8ConfigurationError: If the value is empty or cannot be parsed
            into integer IDs and non-empty names.
    """
    setting = _setting(PRIORITY_MAP_ENV_VAR, "priority_map")
    if setting is None:
        return EASY8_PRIORITY_MAP_DEFAULT.copy()
    raw, source = setting

    cleaned = raw.strip()
    if not cleaned:
        raise Easy8ConfigurationError(f"{source} cannot be empty when set.")

    if cleaned.startswith("{"):
        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("JSON must be a non-empty object")
            mapping: dict[int, str] = {}
            for k, v in parsed.items():
                prio_id = int(k)
                if v is None:
                    raise ValueError(f"Null priority name for key {k!r}")
                prio_name = str(v).strip()
                if not prio_name:
                    raise ValueError(f"Empty priority name for key {k!r}")
                mapping[prio_id] = prio_name
            return mapping
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise Easy8ConfigurationError(
                f"Invalid JSON in {source}: {raw!r}. "
                "Expected JSON object mapping integer IDs to names."
            ) from exc

    try:
        mapping: dict[int, str] = {}
        for part in cleaned.split(","):
            part_str = part.strip()
            if not part_str:
                raise ValueError(f"Empty pair in {raw!r}")
            if "=" in part_str:
                k_str, v_str = part_str.split("=", 1)
            elif ":" in part_str:
                k_str, v_str = part_str.split(":", 1)
            else:
                raise ValueError(f"Missing '=' or ':' in pair {part_str!r}")
            prio_id = int(k_str.strip())
            prio_name = v_str.strip()
            if not prio_name:
                raise ValueError(f"Empty priority name in pair {part_str!r}")
            mapping[prio_id] = prio_name
        return mapping
    except ValueError as exc:
        raise Easy8ConfigurationError(
            f"Invalid {source}: {raw!r}. "
            "Expected format '1=Low,2=Normal' or JSON object."
        ) from exc
