from __future__ import annotations

from collections.abc import Sequence

from AutoScriptor import *
from AutoScriptor.battle_character.hero import *

# 灵气优先级默认顺序（与 LingQi 枚举一致）；fallback 选关时序号越小越优先
DEFAULT_LINGQI_PRIORITY_VALUES: tuple[str, ...] = ("金", "木", "水", "火", "土", "雷", "月", "时", "天")


def sort_stage_lingqi_pairs(
    pairs: list[tuple[str, str]],
    *,
    priority: Sequence[str] | None = None,
) -> list[tuple[str, str]]:
    """按灵气优先级排序 (关卡名, 关卡灵气)，未知灵气排在末尾。"""
    order = list(priority) if priority is not None else list(DEFAULT_LINGQI_PRIORITY_VALUES)

    def _key(item: tuple[str, str]) -> int:
        lg = item[1]
        try:
            return order.index(lg)
        except ValueError:
            return len(order)

    return sorted(pairs, key=_key)

@combo
def check_linggen(self:Hero):
    from ZmxyOL.nav.api import ensure_in
    ensure_in(["极北","极寒深渊"],[-1,None])
    click(B(50,50,40,40))
    store_as = extract_info(B(245,90,100,30), lambda res: next((char for char in "金寄寒火岩时电月无" if char in res.strip())).replace("电", "雷").replace("岩", "土").replace("无", "天").replace("寄", "木").replace("寒", "水"))
    logger.info(f"今日灵气: {store_as}")
    click(B(50,50,40,40))
    return store_as

@combo
def task_way_to_diff(self:Hero, task: str, expect_difficulty: str, task_type: str)->int:
    # 进入关卡
    from ZmxyOL.battle.tasks import get_task_table
    from ZmxyOL.nav import ensure_in
    task_info = get_task_table(task)
    ensure_in(*get_task_table(task)["location"])
    click(task_info["target"], until=lambda: extract_info(B(648,6,132,78), lambda x: len(x.strip())==2))
    preview_remains = extract_info(B(619,283,107,43), post_process=lambda s: int(s.strip()[-2]), ensure_not_empty=True)
    # 极寒深渊这条路的预览次数就是灵狱共享次数，预览为 0 可以直接退出；
    # 极北混沌需要先进入并切到目标难度，再读该难度的真实次数。
    if task_type != "极北" and preview_remains == 0:
        return preview_remains
    # 开始挑战
    sleep(1)
    # 进入混沌本，获取剩余次数
    if ui_F(T("开始挑战")): click(B(174,242,931,96))
    click(T("混沌", box=Box(1008,263,73,52)), if_exist=True)
    sleep(1)
    # 获取难度
    difficulty = extract_info(
        B(222,368,66,56),
        lambda x: ("噩梦" if "梦" in x else x.strip())
    )
    logger.info(f"当前难度: {difficulty}")
    # 调整难度
    expect_index = task_info["diff"].index(expect_difficulty)
    cur_index = task_info["diff"].index(difficulty)
    repeat = (expect_index - cur_index) % len(task_info["diff"])
    click(B(230,380,80,50), repeat=repeat)
    sleep(1)
    if expect_difficulty == "灵狱" and task_type == "极寒深渊":
        remains = extract_info(B(922,249,186,43), lambda x: int(x.strip()[-1]))
    else:
        remains = extract_info(B(610,292,120,24), lambda x: int(x.strip()[-2]))
    if not isinstance(remains, int): remains = 0
    logger.info(f"{task}({expect_difficulty}) 剩余次数: {remains}")
    return remains

@combo
def chaos_select(
    self: Hero,
    task_list: list[str],
    Weather: str,
    task_type: str,
) -> tuple[str | None, list[tuple[str, str]]]:
    """遍历 task_list，建立 (关卡名, 关卡灵气) 列表；返回 (与 Weather 匹配的首个关卡, 全表映射)。

    映射按 task_list 顺序累积；若某关 remains==0 则提前返回已收集的映射。
    """
    pairs: list[tuple[str, str]] = []
    same_linggen_chaos: str | None = None
    for name in task_list:
        remains = self.task_way_to_diff(task=name, expect_difficulty="灵狱", task_type=task_type)
        if remains == 0:
            return same_linggen_chaos, pairs
        cur_linggen = extract_info(B(260, 440, 80, 50), lambda x: x.strip()[0])
        logger.info(f"{name} -> {cur_linggen}")
        pairs.append((name, cur_linggen))
        if same_linggen_chaos is None and cur_linggen in Weather:
            same_linggen_chaos = name
        sleep(1)
        click(B(1200, 30, 30, 30))
        wait_for_appear(T("回家", box=Box(29, 613, 77, 88).margin()))
    return same_linggen_chaos, pairs
