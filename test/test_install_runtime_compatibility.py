import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InstallRuntimeCompatibilityContractTests(unittest.TestCase):
    def test_setuptools_constraint_and_legacy_import_probe_stay_aligned(self):
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
        install_script = (PROJECT_ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

        self.assertIn("setuptools<81", requirements)
        self.assertIn('$SetuptoolsUpperBound = "81"', install_script)
        self.assertIn('$SetuptoolsRequirement = "setuptools<$SetuptoolsUpperBound"', install_script)
        self.assertIn("function Test-PythonRuntimeCompatibility", install_script)
        self.assertIn("setuptools_version < Version('$SetuptoolsUpperBound')", install_script)
        self.assertIn("pip install --python $VenvPy $SetuptoolsRequirement", install_script)
        for import_marker in (
            "import pkg_resources",
            "import packaging.tags",
            "import distutils.util",
            "import adbutils",
            "import uiautomator2",
        ):
            with self.subTest(import_marker=import_marker):
                self.assertIn(import_marker, install_script)
        self.assertGreaterEqual(install_script.count("Test-PythonRuntimeCompatibility"), 2)

    def test_importing_mumu_does_not_eagerly_start_ocr(self):
        probe = (
            "import sys; "
            "import AutoScriptor.control.MumuAdaptor.mumu; "
            "assert 'AutoScriptor.recognition.ocr_rec' not in sys.modules"
        )

        # 探针子进程没有 unittest，写盘保护不生效；而导入 MumuAdaptor 会连带加载
        # app_config，其 atexit 会把（未改动的）真实配置原样写回。给子进程一个
        # 临时数据目录，别让它碰真实 data/。
        with tempfile.TemporaryDirectory(prefix="test_mumu_import_probe_") as probe_data_dir:
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", probe],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                env={**os.environ, "AUTOSCRIPTOR_DATA_DIR": probe_data_dir},
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_setuptools_shim_initializes_before_legacy_adb_imports(self):
        nemu_utils = (
            PROJECT_ROOT / "AutoScriptor" / "control" / "NemuIpc" / "device" / "method" / "utils.py"
        ).read_text(encoding="utf-8")

        self.assertLess(nemu_utils.index("import setuptools"), nemu_utils.index("import uiautomator2 as u2"))


if __name__ == "__main__":
    unittest.main()
