"""扫描仙术书，记录当前已习得的仙术并生成持有表。

逐个点开仙术格读取名称，用「名称必须变化」闭环等待渲染，避免把上一格的文字当成
下一格。结果写入项目根的 ``skills.txt``，再由 ``_仙术表.py`` 汇总成 Excel。
"""
from __future__ import annotations

import time

from AutoScriptor import *
from ZmxyOL import *

from tasks.一般任务._仙术表 import DEFAULT_OUTPUT_PATH, DEFAULT_SKILLS_PATH, skills_to_excel


# 仙术书的格子：四行，每行四格
SKILL_CELLS = [
    B(256, 189, 58, 26), B(368, 190, 53, 23), B(479, 190, 53, 23), B(590, 191, 52, 23),
    B(256, 295, 58, 23), B(368, 295, 54, 23), B(479, 295, 53, 23), B(590, 295, 52, 23),
    B(256, 397, 58, 24), B(368, 397, 54, 24), B(479, 397, 53, 24), B(590, 397, 52, 24),
    B(256, 502, 58, 25), B(368, 502, 54, 25), B(479, 502, 54, 22), B(590, 502, 52, 22),
]
SKILL_NAME_REGION = B(714, 173, 345, 51)


def enter_skill_book() -> None:
    ensure_in("村庄")
    click(I("导航-菜单"), delay=1)
    click(T("技能", box=Box(1162, 384, 74, 56).margin()))
    click(T("仙术书", box=Box(96, 250, 54, 142).margin()))
    click(T("仙术拓印本", box=Box(441, 121, 133, 22).margin()))


def leave_skill_book() -> None:
    click(B(1204, 23, 47, 40))
    wait_for_appear(I("导航-菜单"))
    sleep(0.5)
    click(B(0, 0))


def scroll_detail_panel() -> None:
    """详情面板回顶，让「已习得」标记落在可预期的位置。"""
    swipe_precise(B(305, 480), B(305, 203))
    sleep(1)
    found = locate(T("已习得", box=Box(236, 186, 430, 390)))
    nearest = min(SKILL_CELLS, key=lambda cell: cell.box.distance_to(found))
    nearest_x, nearest_y = nearest.box.center()
    found_x, found_y = found.center()
    delta_y = nearest_y - found_y
    swipe(
        B(305, 480),
        B(305, 480 + (delta_y if delta_y > 0 else 100 + delta_y)),
        duration_s=0.2 if delta_y > 0 else 0.8,
    )


def read_cell_name() -> str | None:
    name = extract_info(
        SKILL_NAME_REGION,
        post_process=lambda text: "".join(text.split()).replace("•", "·").replace("・", "·"),
        ensure_not_empty=True,
        mode="text",
        ocr_ttl=0,
        max_retries=1,
    )
    return name or None


def wait_for_name_change(previous_name: str, timeout: float = 2) -> str:
    """点击后等名称真的换了再读，否则会读到上一格的残留文字。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = read_cell_name()
        if current and current != previous_name:
            return current
        sleep(0.03)
    raise TimeoutError(f"点击仙术后名称未在 {timeout}s 内变化，之前为 {previous_name!r}")


def collect_names(owned: set, cells, previous_name: str | None) -> str | None:
    """逐格点开并读取名称，结果并入 ``owned``。"""
    for position, cell in enumerate(cells):
        click(cell, offset=(0, 20))
        if position == 0 and previous_name:
            # 第一格可能已经选中，不需要等变化
            sleep(0.1)
            name = read_cell_name()
        elif previous_name:
            name = wait_for_name_change(previous_name)
        else:
            sleep(0.1)
            name = read_cell_name()
        if name:
            cleaned = "".join(name.split()).replace("•", "·").replace("・", "·").replace("·", "·")
            if cleaned:
                owned.add(cleaned)
                previous_name = name
    return previous_name


def scan_all_skills() -> set:
    acquired: set = set()
    previous_name = read_cell_name()
    # 有些格子是空的，扫到不再更新为止
    previous_count = -1
    while len(acquired) != previous_count:
        previous_count = len(acquired)
        previous_name = collect_names(acquired, SKILL_CELLS, previous_name)
        scroll_detail_panel()
    collect_names(acquired, SKILL_CELLS[12:16], previous_name)
    return acquired


@register_task(
    description="扫描仙术书并生成仙术持有表",
    task_doc=(
        "逐个点开仙术格读取名称并写入 skills.txt，再汇总成 仙术持有情况.xlsx。"
        "需要角色已进入游戏，耗时较长。"
    ),
    debug_mode=True,
)
def task():
    enter_skill_book()
    try:
        acquired = scan_all_skills()
        sleep(1)
    finally:
        with open(DEFAULT_SKILLS_PATH, "w", encoding="utf-8") as handle:
            for skill in sorted(acquired):
                handle.write(skill + "\n")
        logger.info("已习得仙术: %d", len(acquired))
        skills_to_excel(skills_path=DEFAULT_SKILLS_PATH, output_path=DEFAULT_OUTPUT_PATH)
        leave_skill_book()
