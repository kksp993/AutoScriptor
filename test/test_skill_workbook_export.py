import importlib.util
import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORT_MODULE_PATH = (
    PROJECT_ROOT / "test" / "scripts" / "工具" / "生成仙术持有表.py"
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
            output_path = Path(temporary_directory) / "仙术持有情况.xlsx"
            generated_path = export_module.skills_to_excel(
                skills_path=PROJECT_ROOT / "skills.txt",
                template_path=PROJECT_ROOT / "仙术已有记录 7.23.xlsx",
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

        for coordinate in ("D30", "E30", "F30", "G30", "K43", "L43", "M43", "N43"):
            self.assertEqual(worksheet[coordinate].value, "✔")
            self.assertTrue(
                (worksheet[coordinate].fill.fgColor.rgb or "").endswith("DDEBF7")
            )

        self.assertIsNone(worksheet["H2"].value)
        self.assertIsNone(worksheet["O29"].value)


if __name__ == "__main__":
    unittest.main()
