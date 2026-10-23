"""No module may read a name it neither defines, imports, nor inherits from builtins.

This is the check that catches the failure mode a test suite usually misses: a
name that is *used* but no longer imported still imports fine and only raises
when the code path finally runs. Moving handlers between modules is exactly when
that happens, and `scripts/check_undefined_names.py` is what found it.

A module that star-imports is skipped -- `from AutoScriptor import *` binds
names statically unknowable -- so the scan covers the layers that use explicit
imports.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.check_undefined_names import collect_unresolved, has_star_import  # noqa: E402
import ast  # noqa: E402


SCAN_ROOTS = ("backend", "orchestrator", "tasks", "ZmxyOL", "AutoScriptor")
SKIP_PARTS = {"__pycache__", ".venv", ".venv-gpu-ocr", "refs", "vendor", "node_modules"}


class TestNoUndefinedNames(unittest.TestCase):
    def test_every_cross_layer_module_resolves_its_names(self):
        offenders: list[str] = []
        scanned = 0

        for root_name in SCAN_ROOTS:
            for path in sorted((ROOT / root_name).rglob("*.py")):
                if any(part in SKIP_PARTS for part in path.parts):
                    continue
                try:
                    source = path.read_text(encoding="utf-8-sig")
                    if has_star_import(ast.parse(source, str(path))):
                        continue
                except (OSError, UnicodeDecodeError, SyntaxError):
                    continue
                scanned += 1
                for line, name in collect_unresolved(source, str(path)):
                    offenders.append(f"{path.relative_to(ROOT)}:{line} {name}")

        self.assertGreater(scanned, 100, "scan covered too few files to be meaningful")
        self.assertEqual(
            offenders,
            [],
            "names used but never defined/imported:\n  " + "\n  ".join(offenders),
        )

    def test_the_scan_script_itself_runs_clean(self):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "check_undefined_names.py")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
