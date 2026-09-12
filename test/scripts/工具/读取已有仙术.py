from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from AutoScriptor import *
from ZmxyOL import *
from 生成仙术持有表 import skills_to_excel

alignment = [
    # 第一行
    B(256,189,58,26), B(368,190,53,23), B(479,190,53,23), B(590,191,52,23),
    # 第二行
    B(256,295,58,23), B(368,295,54,23), B(479,295,53,23), B(590,295,52,23),
    # 第三行
    B(256,397,58,24), B(368,397,54,24), B(479,397,53,24), B(590,397,52,24),
    # 第四行
    B(256,502,58,25), B(368,502,54,25), B(479,502,54,22), B(590,502,52,22),
]

# 用集合去重，避免重复技能
result = set()  # 存储拥有的仙术
SKILL_NAME_REGION = B(714,173,345,51)

def ensure_in_skills():
    ensure_in("村庄")
    click(I("导航-菜单"), delay=1)
    click(T("技能", box=Box(1162,384,74,56).margin()))
    click(T("仙术书", box=Box(96,250,54,142).margin()))
    click(T("仙术拓印本", box=Box(441,121,133,22).margin()))

def close_skills():
    click(B(1204,23,47,40))
    wait_for_appear(I("导航-菜单"))
    sleep(0.5)
    click(B(0,0))

def detail_swipe():
    swipe_precise(B(305,480), B(305,203))
    sleep(1)
    box = locate(T("已习得", box=Box(236,186,430,390)))
    # 使用 Box.distance_to 比较中心点距离，再计算中心点之间的偏移。
    closest_target = min(alignment, key=lambda target: target.box.distance_to(box))
    closest_center_x, closest_center_y = closest_target.box.center()
    box_center_x, box_center_y = box.center()
    delta = (closest_center_x - box_center_x, closest_center_y - box_center_y)
    swipe(B(305,480), B(305,480 + (delta[1] if delta[1] > 0 else 100 + delta[1])), duration_s=0.2 if delta[1] > 0 else 0.8)

def extract_skill_name() -> str | None:
    info = extract_info(
        SKILL_NAME_REGION,
        post_process=lambda text: ''.join(text.split()).replace('•', '·').replace('・', '·'),
        ensure_not_empty=True,
        mode="text",
        ocr_ttl=0,
        max_retries=1,
    )
    return info or None


def wait_for_skill_name_change(previous_name: str, timeout: float = 2) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current_name = extract_skill_name()
        if current_name and current_name != previous_name:
            return current_name
        sleep(0.03)
    raise TimeoutError(f"点击仙术后名称未在 {timeout}s 内变化，之前为 {previous_name!r}")


def extract(range_list=range(12)) -> list[str]:
    skill_indexes = list(range_list)
    if not skill_indexes:
        return []

    # 第一项可能恰好已被选中；先读取当前名称，后续项再按名称变化闭环等待。
    previous_name = extract_skill_name()
    for skill_position, skill_index in enumerate(skill_indexes):
        click(alignment[skill_index], offset=(0,20))
        if skill_position == 0 and previous_name:
            sleep(0.1)
            info = extract_skill_name()
        elif previous_name:
            info = wait_for_skill_name_change(previous_name)
        else:
            sleep(0.1)
            info = extract_skill_name()

        # set 会自动去重，这里先去除所有空白符并归一化 · 符号
        if info:
            # 去掉所有空白字符（空格、制表符、换行符等），·归一化为半角
            info_cleaned = ''.join(info.split()).replace('·', '·').replace('•', '·').replace('・', '·')
            if info_cleaned:
                result.add(info_cleaned)
            result.add(info_cleaned)
            previous_name = info
    # 覆盖写入txt文件（排序便于查阅）
    with open("skills.txt", "w", encoding="utf-8") as f:
        for skill in sorted(result):
            f.write(skill + "\n")
    print(f"已习得仙术: {len(result)}")

def read_existing_skills() -> None:
    prev_count = -1
    while len(result) != prev_count:
        prev_count = len(result)
        extract()
        detail_swipe()
    extract(range(12,16))


if __name__ == "__main__":
    init(launch_app=True)
    ensure_in_skills()
    try:
        read_existing_skills()
        sleep(1)
    finally:
        skills_to_excel()
        close_skills()
