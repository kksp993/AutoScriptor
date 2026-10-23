import importlib.util
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_MODULE_PATH = PROJECT_ROOT / "tasks" / "其他任务" / "特殊功能" / "_仙术表.py"

# 生成器唯一的外部输入就是 skills.txt，所以夹具自带一份，测试不依赖仓库根目录的
# 用户数据。每行「基础名·等级」；基础名都用骨架里已有的名字，不会落入「其他仙术」区。
FIXTURE_SKILLS_TEXT = "\n".join(
    (
        # 龙年仙术/金/主动：下、中、上 三档连号
        "乾坤一掷·下",
        "乾坤一掷·中",
        "乾坤一掷·上",
        # 龙年仙术/水/主动：缺「下」，用来验证只有连号前缀才高亮
        "水华漫天·中",
        "水华漫天·上",
        # 小小英雄/火/主动：只断言技能名来自骨架，等级随意给一档
        "灭烬残炎·下",
        # 马年仙术/木/主动：四档齐全
        "竹影灵侍·下",
        "竹影灵侍·中",
        "竹影灵侍·上",
        "竹影灵侍·绝",
        # 须弥仙术/雷/被动：只有 下/中/上，没有「绝」
        "雷暴·下",
        "雷暴·中",
        "雷暴·上",
    )
)


def load_export_module():
    module_spec = importlib.util.spec_from_file_location(
        "skill_workbook_export",
        EXPORT_MODULE_PATH,
    )
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"无法加载仙术表生成模块: {EXPORT_MODULE_PATH}")
    export_module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(export_module)
    return export_module


class SkillWorkbookExportTest(unittest.TestCase):
    def test_export_marks_owned_skills_and_highlights_only_contiguous_prefixes(self):
        export_module = load_export_module()

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            skills_path = temporary_root / "skills.txt"
            skills_path.write_text(FIXTURE_SKILLS_TEXT, encoding="utf-8")
            output_path = temporary_root / "仙术持有情况.xlsx"
            generated_path = export_module.skills_to_excel(
                skills_path=skills_path,
                output_path=output_path,
            )
            worksheet = load_workbook(generated_path)["Sheet1"]

        self.assertEqual(worksheet["C23"].value, "灭尽残炎")
        self.assertEqual(worksheet["C30"].value, "竹影林侍")
        self.assertEqual(worksheet["J43"].value, "雷爆")

        for coordinate in ("D2", "E2", "F2"):
            self.assertEqual(worksheet[coordinate].value, "✔")
            self.assertTrue(
                (worksheet[coordinate].fill.fgColor.rgb or "").endswith("DDEBF7")
            )
        self.assertIsNone(worksheet["G2"].value)

        self.assertIsNone(worksheet["D4"].value)
        self.assertEqual(worksheet["E4"].value, "✔")
        self.assertNotEqual(worksheet["E4"].fill.fill_type, "solid")

        for coordinate in ("D30", "E30", "F30", "G30", "K43", "L43", "M43"):
            self.assertEqual(worksheet[coordinate].value, "✔")
            self.assertTrue(
                (worksheet[coordinate].fill.fgColor.rgb or "").endswith("DDEBF7")
            )
        # 夹具里「雷暴」只有 下/中/上，没有「绝」档。
        self.assertIsNone(worksheet["N43"].value)

        self.assertIsNone(worksheet["H2"].value)
        self.assertIsNone(worksheet["O29"].value)


if __name__ == "__main__":
    unittest.main()
