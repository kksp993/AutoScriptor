from __future__ import annotations

import os
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import PatternFill


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SKILLS_PATH = PROJECT_ROOT / "skills.txt"
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "仙术已有记录 7.23.xlsx"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "仙术持有情况.xlsx"

GRADE_NAMES = ("下", "中", "上", "绝")
SKILL_TABLE_LAYOUTS = (
    (3, 4),
    (10, 11),
)
TEMPLATE_BASE_NAME_ALIASES = {
    "灭尽残炎": "灭烬残炎",
    "竹影林侍": "竹影灵侍",
    "雷爆": "雷暴",
}
OWNED_CHAIN_FILL = PatternFill(
    fill_type="solid",
    fgColor="DDEBF7",
)
EMPTY_FILL = PatternFill(fill_type=None)


def normalize_skill_name(value: str) -> str:
    """Normalize OCR punctuation and known variant characters for matching."""
    return (
        "".join(value.split())
        .replace("・", "·")
        .replace("•", "·")
        .replace("疊", "叠")
    )


def load_owned_skill_names(skills_path: Path) -> set[str]:
    return {
        normalize_skill_name(line)
        for line in skills_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def clear_generated_cells(worksheet) -> None:
    """Clear old ownership marks, generated fills, and optional-selection notes."""
    for row_number in range(2, worksheet.max_row + 1):
        for column_number in (*range(4, 8), *range(11, 15)):
            cell = worksheet.cell(row_number, column_number)
            cell.value = None
            cell.fill = EMPTY_FILL

    for row_number in range(1, worksheet.max_row + 1):
        for column_number in (8, 15):
            cell = worksheet.cell(row_number, column_number)
            if not isinstance(cell, MergedCell):
                cell.value = None


def fill_skill_ownership(worksheet, owned_skill_names: set[str]) -> tuple[int, int]:
    """Write ownership marks and highlight each continuously owned grade prefix."""
    marked_cell_count = 0
    highlighted_cell_count = 0

    for row_number in range(2, worksheet.max_row + 1):
        for base_name_column, first_grade_column in SKILL_TABLE_LAYOUTS:
            template_base_name = worksheet.cell(row_number, base_name_column).value
            if not isinstance(template_base_name, str) or not template_base_name.strip():
                continue

            matching_base_name = TEMPLATE_BASE_NAME_ALIASES.get(
                template_base_name,
                template_base_name,
            )
            grade_ownership = []
            for grade_name in GRADE_NAMES:
                skill_name = normalize_skill_name(
                    f"{matching_base_name}·{grade_name}"
                )
                grade_ownership.append(skill_name in owned_skill_names)

            for grade_offset, is_owned in enumerate(grade_ownership):
                if not is_owned:
                    continue
                worksheet.cell(
                    row_number,
                    first_grade_column + grade_offset,
                ).value = "✔"
                marked_cell_count += 1

            for grade_offset, is_owned in enumerate(grade_ownership):
                if not is_owned:
                    break
                worksheet.cell(
                    row_number,
                    first_grade_column + grade_offset,
                ).fill = OWNED_CHAIN_FILL
                highlighted_cell_count += 1

    return marked_cell_count, highlighted_cell_count


def skills_to_excel(
    skills_path: str | Path = DEFAULT_SKILLS_PATH,
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    """Generate the skill ownership workbook from ``skills.txt``.

    Skill names displayed in the workbook remain exactly as written in the
    template. Matching alone handles punctuation and known variant names.
    Light-blue fills mark only grades owned continuously from ``下``; they do
    not indicate the next grade to acquire.
    """
    resolved_skills_path = Path(skills_path).resolve()
    resolved_template_path = Path(template_path).resolve()
    resolved_output_path = Path(output_path).resolve()

    if not resolved_skills_path.is_file():
        raise FileNotFoundError(f"找不到仙术记录文件: {resolved_skills_path}")
    if not resolved_template_path.is_file():
        raise FileNotFoundError(f"找不到仙术表格模板: {resolved_template_path}")

    owned_skill_names = load_owned_skill_names(resolved_skills_path)
    workbook = load_workbook(resolved_template_path)
    if "Sheet1" not in workbook.sheetnames:
        raise ValueError("仙术表格模板缺少 Sheet1")

    worksheet = workbook["Sheet1"]
    clear_generated_cells(worksheet)
    marked_cell_count, highlighted_cell_count = fill_skill_ownership(
        worksheet,
        owned_skill_names,
    )

    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output_path = resolved_output_path.with_name(
        f"{resolved_output_path.stem}.tmp{resolved_output_path.suffix}"
    )
    try:
        workbook.save(temporary_output_path)
        os.replace(temporary_output_path, resolved_output_path)
    finally:
        if temporary_output_path.exists():
            temporary_output_path.unlink()

    print(
        f"仙术持有表已生成: {resolved_output_path}，"
        f"持有标记 {marked_cell_count} 项，浅蓝连续持有 {highlighted_cell_count} 项"
    )
    return resolved_output_path


if __name__ == "__main__":
    skills_to_excel()
