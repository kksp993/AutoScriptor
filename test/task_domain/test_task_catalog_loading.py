"""Load real task scripts in isolation, then verify dependencies survive reload.

A missing game-layer export once stopped discovery at the tree task. Later
scripts never registered, so equipment selling reported an unknown dungeon
predecessor even though that dungeon's source file still existed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SELL_EQUIPMENT_ID = "\u51fa\u552e\u5316\u8eab\u88c5\u5907"
DUNGEON_ID = "\u5384\u96be\u526f\u672c"
TREE_ID = "\u5929\u9053\u6811"


def verify_catalog_load_and_reload() -> None:
    """Child-process entrypoint: register scripts, but never execute a task."""
    from orchestrator import catalog
    from orchestrator.model import resolve_planning_specs
    from orchestrator.task_manager import TaskManager
    from tasks.task_register import task_registry

    saved_dependencies = {SELL_EQUIPMENT_ID: {"after_tasks": [DUNGEON_ID]}}
    try:
        catalog.load_tasks()
    except Exception as error:
        _, diagnostics = resolve_planning_specs(saved_dependencies)
        raise AssertionError(
            f"Catalog import failed: {error}; dependency diagnostics: {diagnostics}"
        ) from error

    initial_task_ids = set(task_registry.all_ids())
    assert {SELL_EQUIPMENT_ID, DUNGEON_ID, TREE_ID} <= initial_task_ids

    def verify_dependencies() -> None:
        import ZmxyOL
        from ZmxyOL.nav.envs import decorators
        from ZmxyOL.nav.map_manager import mm

        for export_name in ("HAS_SHEZHI", "HAS_SHIJIEDITU"):
            assert export_name in ZmxyOL.__all__, export_name
            assert getattr(ZmxyOL, export_name) is getattr(decorators, export_name)
        specifications, diagnostics = resolve_planning_specs(
            saved_dependencies, locations=set(mm.locs),
        )
        assert not diagnostics, diagnostics
        assert specifications[SELL_EQUIPMENT_ID].after_tasks == (DUNGEON_ID,)
        assert DUNGEON_ID in specifications

    verify_dependencies()
    TaskManager().reload_tasks()
    assert set(task_registry.all_ids()) == initial_task_ids
    verify_dependencies()
    print(f"Catalog startup and reload verified: {len(initial_task_ids)} visible tasks")


class TestTaskCatalogLoading(unittest.TestCase):
    def test_real_catalog_load_and_reload_resolve_saved_predecessors(self):
        with tempfile.TemporaryDirectory(prefix="as_task_catalog_") as directory:
            data_root = Path(directory)
            shutil.copy2(PROJECT_ROOT / "data/config.template.json", data_root / "config.json")
            shutil.copytree(PROJECT_ROOT / "data/character", data_root / "character")
            environment = {
                **os.environ,
                "AUTOSCRIPTOR_DATA_DIR": str(data_root),
                "PYTHONIOENCODING": "utf-8",
            }
            result = subprocess.run(
                [
                    sys.executable, "-X", "utf8", "-c",
                    "from test.task_domain.test_task_catalog_loading import "
                    "verify_catalog_load_and_reload; verify_catalog_load_and_reload()",
                ],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=90,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
