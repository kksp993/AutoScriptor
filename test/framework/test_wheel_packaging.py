"""钉住两个 wheel 的打包契约。

仓库有两种运行姿态：源码位（在仓库里直接跑）和安装位（pip/uv 装 whl 后跑）。
这个文件保证安装位真的能写代码，而不是只在源码位碰巧能用。

真实事故，也就是这些断言存在的理由：

- ZmxyOL 的战斗实现原本只从 ``data/character/hero.py`` 读。仓库外没有这棵树，
  装 whl 后 ``from ZmxyOL import *`` 必然 ImportError。所以打包把该文件作为默认
  实现放进 ``ZmxyOL/character/_default_impl/``，导入时优先用可编辑副本。
- ``ZmxyOL`` 重导出 ``tasks.register_task``，而 ``tasks/task_register.py`` 又跑
  ``from ZmxyOL import *``：两者互相依赖，只装其中一个都导入失败，所以它们属于
  同一个发行体。
- ``autoscriptor`` 是框架层且不 import 游戏层，所以它的 wheel 里只能有
  ``AutoScriptor/``；多带了就是把分层装反。

导入探针会真的起一个子进程。默认参与全量测试（约 15 秒），不想跑时设
``AUTOSCRIPTOR_SKIP_WHEEL_PROBE=1``。
"""
from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts import build_wheels


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKIP_PROBE_ENVIRONMENT_VARIABLE = "AUTOSCRIPTOR_SKIP_WHEEL_PROBE"

# 在仓库外跑、只用安装树。输出 PROBE_OK / PROBE_FAIL 行，最后一行给结论。
_PROBE_SCRIPT = '''
import os
import sys
from pathlib import Path

site_directory = Path(sys.argv[1]).resolve()
data_directory = Path(sys.argv[2]).resolve()
data_directory.mkdir(parents=True, exist_ok=True)
os.environ["AUTOSCRIPTOR_DATA_DIR"] = str(data_directory)

failures = []


def check(label, condition, detail=""):
    print("PROBE_" + ("OK" if condition else "FAIL") + " " + label + (" :: " + str(detail) if detail else ""))
    if not condition:
        failures.append(label)


def came_from_install(path):
    return site_directory in Path(path).resolve().parents


import AutoScriptor
import ZmxyOL
import tasks

check("framework_from_install", came_from_install(AutoScriptor.__file__), AutoScriptor.__file__)
check("game_layer_from_install", came_from_install(ZmxyOL.__file__), ZmxyOL.__file__)
check("task_surface_from_install", came_from_install(tasks.__file__), tasks.__file__)

from AutoScriptor import *
from ZmxyOL import *

framework_names = ("Box", "B", "T", "I", "cfg", "logger", "click", "locate", "init", "sleep")
check("framework_exports", not [n for n in framework_names if n not in globals()],
      str([n for n in framework_names if n not in globals()]))

game_names = ("Hero", "h", "battle_plan", "flow", "mm", "path", "register_task",
              "get_task_table", "LOC_ENV")
check("game_layer_exports", not [n for n in game_names if n not in globals()],
      str([n for n in game_names if n not in globals()]))

import ZmxyOL.character.hero as hero_entry

implementation = Path(hero_entry.__file__).resolve()
check("hero_uses_shipped_copy",
      implementation.parent.name == "_default_impl" and came_from_install(implementation),
      str(implementation))

from AutoScriptor.utils.paths import get_assets_dir, get_config_path

assets = get_assets_dir().resolve()
check("assets_from_install", came_from_install(assets) and assets.name == "assets", str(assets))
check("ui_map_present", (assets / "config" / "ui_map.csv").is_file())
reference_images = list((assets / "pic").glob("*.png"))
check("reference_images_present", len(reference_images) > 300, str(len(reference_images)) + " png")
check("data_root_honours_env", Path(get_config_path()).parent == data_directory, str(get_config_path()))

check("frame_size", getFrameSize() == (1280, 720), str(getFrameSize()))
box = Box(1, 2, 3, 4)
check("box_fields", (box.left, box.top, box.width, box.height) == (1, 2, 3, 4), repr(tuple(box)))
text_target = T("关闭")
check("text_target_reads_the_ui_map", "关闭" in repr(text_target), repr(text_target))
box_target = B("关闭")
check("box_target_reads_the_ui_map", repr(box_target).startswith("B("), repr(box_target))
grid = make_box_grid(Box(0, 0, 10, 10), Box(0, 0, 30, 30), row=2, col=2)
check("box_grid_helpers", indexof(grid, Box(20, 20, 10, 10)) == (1, 1), repr(grid))

leftovers = sorted(p.name for p in site_directory.iterdir() if p.name in ("logs", "data", "config.json"))
check("install_directory_untouched", not leftovers, str(leftovers))

print("PROBE_RESULT " + ("ok" if not failures else "failed"))
sys.exit(1 if failures else 0)
'''


def build_into(output_directory: Path) -> dict[str, Path]:
    """Build both wheels into ``output_directory``; return distribution -> path."""
    original_output_directory = build_wheels.DIST_DIR
    build_wheels.DIST_DIR = output_directory
    try:
        version = build_wheels.read_project_version()
        framework_spec, game_layer_spec = build_wheels.build_specs(version)
        built: dict[str, Path] = {}
        for spec in (framework_spec, game_layer_spec):
            wheel_path, _ = build_wheels.write_wheel(spec, version)
            built[spec.distribution] = wheel_path
        return built
    finally:
        build_wheels.DIST_DIR = original_output_directory


def read_member(wheel_path: Path, member: str) -> bytes:
    with zipfile.ZipFile(wheel_path) as archive:
        return archive.read(member)


def record_entries(wheel_path: Path, dist_info: str) -> dict[str, tuple[str, int]]:
    """Parse ``RECORD`` into archive path -> (hash, size). Missing hash is ''."""
    parsed: dict[str, tuple[str, int]] = {}
    for line in read_member(wheel_path, f"{dist_info}/RECORD").decode("utf-8").splitlines():
        if not line.strip():
            continue
        archive_path, digest, size = line.rsplit(",", 2)
        parsed[archive_path] = (digest, int(size) if size else 0)
    return parsed


class DistributionDeclarationTest(unittest.TestCase):
    """两个发行体各自声明了什么，以及为什么这样切分。"""

    def test_version_comes_from_pyproject(self) -> None:
        declared_version = build_wheels.read_project_version()
        self.assertRegex(declared_version, r"^\d+\.\d+\.\d+$")
        self.assertIn(f'version = "{declared_version}"', (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_requirements_are_read_without_comment_text(self) -> None:
        requirements = build_wheels.read_project_dependencies()
        self.assertIn("adbutils==1.2.15", requirements)
        self.assertIn("setuptools<81", requirements)
        self.assertNotIn("Levenshtein", requirements, "注释里的反引号片段不能被当成依赖")
        self.assertTrue(all(" " not in requirement for requirement in requirements))

    def test_framework_distribution_carries_only_the_framework(self) -> None:
        framework_spec, _ = build_wheels.build_specs("1.0.3")
        self.assertEqual(framework_spec.packages, ("AutoScriptor",))

    def test_game_layer_distribution_carries_the_mutually_dependent_pair(self) -> None:
        _, game_layer_spec = build_wheels.build_specs("1.0.3")
        self.assertEqual(game_layer_spec.packages, ("ZmxyOL", "tasks"))

    def test_game_layer_declares_the_framework_dependency(self) -> None:
        _, game_layer_spec = build_wheels.build_specs("1.0.3")
        self.assertIn("autoscriptor==1.0.3", game_layer_spec.requires_dist)


class BuiltWheelTest(unittest.TestCase):
    """真的构建一次，然后检查产物。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(prefix="autoscriptor_wheels_")
        cls.output_directory = Path(cls._temporary_directory.name) / "dist"
        cls.version = build_wheels.read_project_version()
        cls.wheels = build_into(cls.output_directory)
        cls.framework_wheel = cls.wheels["autoscriptor"]
        cls.game_layer_wheel = cls.wheels["zmxyol"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary_directory.cleanup()

    def framework_members(self) -> list[str]:
        with zipfile.ZipFile(self.framework_wheel) as archive:
            return archive.namelist()

    def game_layer_members(self) -> list[str]:
        with zipfile.ZipFile(self.game_layer_wheel) as archive:
            return archive.namelist()

    def test_both_wheels_are_readable_with_the_declared_name(self) -> None:
        for distribution, wheel_path in self.wheels.items():
            with self.subTest(distribution=distribution):
                self.assertTrue(wheel_path.is_file())
                self.assertEqual(
                    wheel_path.name,
                    f"{distribution}-{self.version}-py3-none-any.whl",
                )
                self.assertIsNone(zipfile.ZipFile(wheel_path).testzip())

    def test_wheel_metadata_declares_a_pure_python_tag(self) -> None:
        for distribution, wheel_path in self.wheels.items():
            with self.subTest(distribution=distribution):
                wheel_metadata = read_member(
                    wheel_path, f"{distribution}-{self.version}.dist-info/WHEEL"
                ).decode("utf-8")
                self.assertIn("Tag: py3-none-any", wheel_metadata)
                self.assertIn("Root-Is-Purelib: true", wheel_metadata)

    def test_framework_wheel_ships_no_game_layer_code(self) -> None:
        members = self.framework_members()
        self.assertIn("AutoScriptor/__init__.py", members)
        self.assertEqual([m for m in members if m.startswith("ZmxyOL/")], [])
        self.assertEqual([m for m in members if m.startswith("tasks/")], [])

    def test_game_layer_wheel_ships_the_hero_default_implementation(self) -> None:
        shipped = read_member(
            self.game_layer_wheel, "ZmxyOL/character/_default_impl/hero.py"
        )
        editable = REPOSITORY_ROOT / "data" / "character" / "hero.py"
        self.assertEqual(shipped, editable.read_bytes(), "随包默认实现必须与可编辑副本一致")

    def test_game_layer_wheel_ships_the_ui_map_and_reference_images(self) -> None:
        members = self.game_layer_members()
        self.assertIn("ZmxyOL/assets/config/ui_map.csv", members)
        reference_images = [m for m in members if m.startswith("ZmxyOL/assets/pic/") and m.endswith(".png")]
        editable_images = list((REPOSITORY_ROOT / "ZmxyOL" / "assets" / "pic").glob("*.png"))
        self.assertEqual(len(reference_images), len(editable_images))
        self.assertGreater(len(reference_images), 300)

    def test_game_layer_wheel_carries_both_import_packages(self) -> None:
        members = self.game_layer_members()
        self.assertIn("ZmxyOL/__init__.py", members)
        self.assertIn("tasks/__init__.py", members)
        self.assertIn("ZmxyOL/character/pros/liuli.py", members, "内置职业要随包")

    def test_archive_paths_are_posix_and_free_of_build_leftovers(self) -> None:
        for distribution, wheel_path in self.wheels.items():
            with self.subTest(distribution=distribution):
                with zipfile.ZipFile(wheel_path) as archive:
                    members = archive.namelist()
                self.assertFalse([m for m in members if "\\" in m], "归档路径必须用正斜杠")
                self.assertFalse([m for m in members if "__pycache__" in m or m.endswith(".pyc")])
                self.assertFalse([m for m in members if m.startswith("/") or ":" in m.split("/")[0]])

    def test_record_hashes_match_every_payload_file(self) -> None:
        """安装器按 RECORD 校验，写错就会装出损坏的包。"""
        for distribution, wheel_path in self.wheels.items():
            dist_info = f"{distribution}-{self.version}.dist-info"
            with self.subTest(distribution=distribution):
                with zipfile.ZipFile(wheel_path) as archive:
                    members = archive.namelist()
                    record = record_entries(wheel_path, dist_info)
                    self.assertEqual(
                        sorted(record), sorted(members), "RECORD 必须逐条列出归档里的文件"
                    )
                    for archive_path, (digest, size) in record.items():
                        if archive_path.endswith(".dist-info/RECORD"):
                            self.assertEqual(digest, "", "RECORD 自身不写哈希")
                            continue
                        content = archive.read(archive_path)
                        expected = base64.urlsafe_b64encode(
                            hashlib.sha256(content).digest()
                        ).rstrip(b"=").decode("ascii")
                        self.assertEqual(digest, f"sha256={expected}", archive_path)
                        self.assertEqual(size, len(content), archive_path)

    def test_building_twice_produces_identical_bytes(self) -> None:
        second_output_directory = Path(self._temporary_directory.name) / "dist_again"
        rebuilt = build_into(second_output_directory)
        for distribution, first_path in self.wheels.items():
            with self.subTest(distribution=distribution):
                self.assertEqual(
                    first_path.read_bytes(),
                    rebuilt[distribution].read_bytes(),
                    "同样的源码必须构建出同样的字节",
                )


class InstalledLayoutImportTest(unittest.TestCase):
    """把 wheel 摊成一个安装树，再用子进程从仓库外导入。"""

    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get(SKIP_PROBE_ENVIRONMENT_VARIABLE):
            raise unittest.SkipTest(
                f"{SKIP_PROBE_ENVIRONMENT_VARIABLE} 已设置，跳过安装位导入探针"
            )
        cls._temporary_directory = tempfile.TemporaryDirectory(prefix="autoscriptor_install_")
        temporary_root = Path(cls._temporary_directory.name)
        cls.site_directory = temporary_root / "site"
        cls.data_directory = temporary_root / "data"
        cls.working_directory = temporary_root / "workspace"
        cls.working_directory.mkdir(parents=True, exist_ok=True)

        built = build_into(temporary_root / "dist")
        for wheel_path in built.values():
            with zipfile.ZipFile(wheel_path) as archive:
                archive.extractall(cls.site_directory)

        probe_path = cls.working_directory / "probe.py"
        probe_path.write_text(_PROBE_SCRIPT, encoding="utf-8")

        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(cls.site_directory)
        cls.probe = subprocess.run(
            [sys.executable, "-X", "utf8", str(probe_path), str(cls.site_directory), str(cls.data_directory)],
            cwd=str(cls.working_directory),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_temporary_directory"):
            cls._temporary_directory.cleanup()

    def test_probe_reports_success(self) -> None:
        failed = [line for line in self.probe.stdout.splitlines() if line.startswith("PROBE_FAIL")]
        self.assertEqual(failed, [], f"探针失败项:\n{chr(10).join(failed)}\n{self.probe.stderr}")
        self.assertIn("PROBE_RESULT ok", self.probe.stdout)
        self.assertEqual(self.probe.returncode, 0, self.probe.stderr)

    def probe_detail(self, label: str) -> str:
        for line in self.probe.stdout.splitlines():
            if line.startswith(f"PROBE_OK {label} ::"):
                return line.split("::", 1)[1].strip()
        self.fail(f"探针没有报告 {label}")

    def test_probe_actually_imported_from_the_install_tree(self) -> None:
        """防呆：探针万一被仓库里的同名包满足，这条会抓到。"""
        for label in ("framework_from_install", "game_layer_from_install", "task_surface_from_install"):
            with self.subTest(label=label):
                reported = os.path.normcase(self.probe_detail(label))
                self.assertTrue(
                    reported.startswith(os.path.normcase(str(self.site_directory))),
                    f"{label} 解析到了 {reported}，不在安装树 {self.site_directory} 里",
                )


if __name__ == "__main__":
    unittest.main()
