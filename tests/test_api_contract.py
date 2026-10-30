import importlib
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def _with_src_on_path():
    src_path = SRC_ROOT
    sys.path.insert(0, str(src_path))
    return src_path


def test_public_import_contract_exposes_easy8_manager():
    src_path = _with_src_on_path()
    package = importlib.import_module("eredmine_agent_gateway")

    assert hasattr(package, "Easy8Manager")
    assert "Easy8Manager" in getattr(package, "__all__", [])
    sys.path.remove(str(src_path))


def test_importing_package_does_not_require_redmine_api_key():
    src_path = _with_src_on_path()
    package = importlib.import_module("eredmine_agent_gateway")

    assert package is not None
    sys.path.remove(str(src_path))
