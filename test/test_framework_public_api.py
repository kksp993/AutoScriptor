"""框架层对外发布面的契约：README 的 API 表、requirements、``__all__`` 三者不许漂移。

这些断言存在的理由：框架层要作为 wheel 独立发布，

- ``pyproject.toml`` 的 ``readme`` 指向 ``AutoScriptor/README.md``，构建时写进 METADATA，
  成为发行体的正文。README 少写一个导出，用户就不知道它存在；多写一个不存在的名字，
  用户会照着报错。
- ``AutoScriptor/requirements.txt`` 与 ``pyproject.toml`` 的 ``[project].dependencies``
  是同一份依赖的两种写法（前者给从源码装的人，后者是打包时的唯一出处），漂移会让
  从源码装的人少装依赖。
- ``__all__`` 是「对外公布这一部分 API」的清单本身，必须与 ``_EXPORTS`` 一一对应，
  且不能有重复项。

真机验收（只装 wheel、跑点击/识别/4399 部分操作）在 ``release_probe/``，不在这里。
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import AutoScriptor
from AutoScriptor.utils import ui_map
from scripts import build_wheels


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPOSITORY_ROOT / "AutoScriptor" / "README.md"
REQUIREMENTS_PATH = REPOSITORY_ROOT / "AutoScriptor" / "requirements.txt"


def readme_api_names() -> set[str]:
    """README「## 公共 API」表里列出的名字（第二列的反引号标识符）。"""
    text = README_PATH.read_text(encoding="utf-8")
    section = text.split("## 公共 API", 1)[1].split("\n## ", 1)[0]
    names: set[str] = set()
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 2 or set(cells[0]) <= set("-: "):
            continue
        names.update(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", cells[1]))
    return names


def requirements_file_entries() -> set[str]:
    """``AutoScriptor/requirements.txt`` 里的依赖条目（忽略注释与索引选项）。"""
    entries: set[str] = set()
    for line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        entries.add(stripped)
    return entries


class PublishedApiSurfaceTest(unittest.TestCase):
    """对外公布的那一份 API 清单：README、``__all__``、``_EXPORTS`` 必须一致。"""

    def test_readme_lists_exactly_the_public_exports(self):
        documented = readme_api_names()
        exported = set(AutoScriptor.__all__)

        self.assertEqual(
            sorted(exported - documented), [],
            "README 的公共 API 表漏了这些导出；对外公布的面必须写全",
        )
        self.assertEqual(
            sorted(documented - exported), [],
            "README 的公共 API 表里有不在 __all__ 里的名字，用户会照着报错",
        )

    def test_all_has_no_duplicates_and_is_fully_mapped(self):
        self.assertEqual(
            len(AutoScriptor.__all__), len(set(AutoScriptor.__all__)),
            "__all__ 里有重复项，发布面清单不该自相矛盾",
        )
        unmapped = sorted(name for name in AutoScriptor.__all__ if name not in AutoScriptor._EXPORTS)
        self.assertEqual(unmapped, [], "这些名字在 __all__ 里，但 _EXPORTS 不知道该从哪解析")
        self.assertEqual(
            sorted(set(AutoScriptor._EXPORTS) - set(AutoScriptor.__all__)), [],
            "_EXPORTS 里有没进 __all__ 的名字：要么补进发布面，要么删掉死导出",
        )

    def test_every_public_name_resolves(self):
        """星号导入会逐个解析这些名字；任何一个解析不了都会让 ``import *`` 失败。"""
        for name in AutoScriptor.__all__:
            with self.subTest(name=name):
                self.assertTrue(hasattr(AutoScriptor, name), f"{name} 解析不到")


class FrameworkReadmeAndRequirementsTest(unittest.TestCase):
    """README 与 requirements 是发行体的一部分，必须与打包配置同源。"""

    def test_pyproject_readme_points_at_the_package_readme(self):
        declared = build_wheels.read_project_readme_path()

        self.assertEqual(declared, "AutoScriptor/README.md")
        self.assertTrue((REPOSITORY_ROOT / declared).is_file(), declared)

    def test_requirements_file_matches_pyproject_dependencies(self):
        declared = set(build_wheels.read_project_dependencies())
        listed = requirements_file_entries()

        self.assertEqual(sorted(declared - listed), [], "requirements.txt 少写了依赖")
        self.assertEqual(sorted(listed - declared), [], "requirements.txt 多写了依赖")

    def test_wheel_metadata_carries_the_long_description(self):
        """没有正文的 wheel 在索引页上是一片空白，发布能力要连这一条一起看。"""
        version = build_wheels.read_project_version()
        framework, _game_layer = build_wheels.build_specs(version)

        metadata = build_wheels.render_metadata(framework, version)

        self.assertIn("Description-Content-Type: text/markdown", metadata)
        self.assertIn("# AutoScriptor", metadata)
        self.assertIn("Author: ", metadata)
        self.assertIn("Project-URL: ", metadata)
        self.assertEqual(framework.long_description, README_PATH.read_text(encoding="utf-8"))


class StandaloneFrameworkFallbackTest(unittest.TestCase):
    """框架层单独安装时缺的那两样东西（游戏层资产、配置模板）要能优雅降级。"""

    def test_missing_ui_map_starts_empty_and_explains_the_reason(self):
        """没有 ``ui_map.csv`` 时按空表启动；按 key 的目标要给出可执行的替代写法。"""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ui_map, "get_assets_dir", lambda: Path(tmp)):
                manager = ui_map.UIMapManager()

            self.assertEqual(manager.get_ui(), {})
            with self.assertRaises(KeyError) as caught:
                manager.get_ui()["首页"]
            self.assertIn("ui_map.csv", str(caught.exception))

    def test_missing_config_template_still_supplies_hard_subscripted_keys(self):
        """没有 ``config.template.json`` 时，框架硬下标读的键必须有默认值。

        真实事故：框架层 wheel 装好后第一次 ``init()``，``cfg["emulator"]["emu_path"]``
        直接抛裸 KeyError，看不出该怎么配（2026-10-12 独立安装探针）。
        """
        from AutoScriptor.utils.app_config import cfg

        manager = cfg._mgr                      # AutoConfig 上的配置管理器
        original_path = manager.config_path
        with tempfile.TemporaryDirectory() as tmp:
            manager.config_path = Path(tmp) / "config.json"   # 同目录下没有模板文件
            try:
                defaults = manager._load_default_global_config()
            finally:
                manager.config_path = original_path

        required_keys = {
            "app": {"app_to_start", "run_in_background"},
            "emulator": {"index", "adb_addr", "mumu_folder", "emu_path", "adb_path"},
        }
        for section, keys in required_keys.items():
            with self.subTest(section=section):
                self.assertTrue(
                    keys <= set(defaults[section]),
                    f"{section} 段缺 {sorted(keys - set(defaults[section]))}",
                )


if __name__ == "__main__":
    unittest.main()
