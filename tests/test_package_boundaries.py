import importlib
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def test_public_api_is_narrow_and_contains_only_easy8_manager():
    src_path = SRC_ROOT
    sys.path.insert(0, str(src_path))
    package = importlib.import_module("eredmine_agent_gateway")

    assert getattr(package, "__all__", []) == ["Easy8Manager"]
    sys.path.remove(str(src_path))


def test_no_reminder_or_job_modules_exist_in_package():
    package_root = SRC_ROOT / "eredmine_agent_gateway"
    module_names = {path.stem for path in package_root.glob("*.py")}
    assert "manager" in module_names, "package path does not resolve"

    forbidden_fragments = ("reminder", "job", "runner")
    assert all(
        fragment not in name
        for name in module_names
        for fragment in forbidden_fragments
    )
