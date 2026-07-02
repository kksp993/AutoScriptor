import enum

from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.table_param import TableParam


class JhsyNandu(str, enum.Enum):
    """灵域 = 参与灵狱阶段（灵气翻倍）的匹配候选；打不过时改为其它项可从候选中移除。"""

    不打 = "不打"
    普通 = "普通"
    困难 = "困难"
    噩梦 = "噩梦"
    灵域 = "灵域"


class LingQi(str, enum.Enum):
    """极寒深渊灵气；与 check_linggen 归一后的字符一致。"""

    金 = "金"
    木 = "木"
    水 = "水"
    火 = "火"
    土 = "土"
    雷 = "雷"
    月 = "月"
    时 = "时"
    天 = "天"


_DEFAULT_LINGQI_PRIORITY: tuple[LingQi, ...] = (
    LingQi.雷,
    LingQi.金,
    LingQi.天,
    LingQi.时,
    LingQi.火,
    LingQi.月,
    LingQi.土,
    LingQi.水,
    LingQi.木,
)

_DEFAULT_BATTLE_CONFIG = TableParam(
    {
        "岩貉星宫": {"difficulty": JhsyNandu.灵域, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        "犬神星宫": {"difficulty": JhsyNandu.灵域, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        "狼王星宫": {"difficulty": JhsyNandu.灵域, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        "虎王星宫": {"difficulty": JhsyNandu.灵域, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        "獐王星宫": {"difficulty": JhsyNandu.灵域, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        "犴神星宫": {"difficulty": JhsyNandu.灵域, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        "兔神星宫": {"difficulty": JhsyNandu.灵域, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        "猪王星宫": {"difficulty": JhsyNandu.灵域, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
    },
    column_labels={"difficulty": "难度", "cancel_on_failed": "不用点券复活", "battle_flow": "战斗招式"},
)


@register_task(
    description="根据配置挑战极寒深渊副本。",
    path_cn="每日任务/极北/极寒深渊/极渊副本",
)
def task(
    lingqi_priority: tuple[LingQi, ...] = _DEFAULT_LINGQI_PRIORITY,
    battle_config: TableParam = _DEFAULT_BATTLE_CONFIG,
    **kwargs,
):
    _ = kwargs
    from ZmxyOL.battle.procedure.chaos import sort_stage_lingqi_pairs
    from ZmxyOL.battle.tasks import JHSY_CHAOS_TABLE, get_task_table

    lingqi_order = [e.value for e in (lingqi_priority or _DEFAULT_LINGQI_PRIORITY)]

    nandu_map = {name: row["difficulty"] for name, row in battle_config.items()}

    def _phase2_expect_difficulty(nandu: JhsyNandu) -> str:
        if nandu == JhsyNandu.灵域:
            return JhsyNandu.噩梦.value
        return nandu.value

    def _after_no_remains():
        click(B(1200, 30, 30, 30))
        wait_for_appear(T("回家", box=Box(29, 613, 77, 88).margin()))

    def _run_battle(name: str, is_lingyu: bool):
        row = battle_config[name]
        row_cancel = row.get("cancel_on_failed", True)
        row_flow = getattr(row.get("battle_flow"), "value", None)
        bonus_x = extract_info(B(290, 570, 100, 30), lambda x: 1 if x.strip() == "普通" else int(x.strip()[-1]))
        repeat = (3 - bonus_x) % 3
        click(B(430, 570, 30, 30), repeat=repeat)
        click(T("开始挑战"))
        if is_lingyu:
            h.set(has_cd=True, speed_x=3).battle_task(
                crash_suddenly=True, bonus_x=3,
                cancel_on_failed=row_cancel, flow_name=row_flow,
                check_pioneer=True,
            )
        else:
            h.set(has_cd=True, speed_x=3).battle_task(
                bonus_x=3,
                has_loading_after_battle=True,
                exit_loc=get_task_table(name)["exit_loc"],
                cancel_on_failed=row_cancel, flow_name=row_flow,
                check_pioneer=True,
            )

    # ── 阶段一：灵气匹配关卡打灵狱（共享3次，只打1个本） ──
    logger.info("====极寒深渊-灵狱====")
    ensure_in("极寒深渊")
    Weather = h.check_linggen()
    logger.info(f"当前灵气: {Weather}")
    lingyu_candidates = [n for n in JHSY_CHAOS_TABLE if nandu_map.get(n) == JhsyNandu.灵域]
    task_list_for_lingyu = lingyu_candidates if lingyu_candidates else list(JHSY_CHAOS_TABLE)
    logger.info(f"灵狱匹配候选: {task_list_for_lingyu}")
    same_linggen_chaos, stage_lingqi_pairs = h.chaos_select(
        task_list=task_list_for_lingyu, Weather=Weather, task_type="极寒深渊"
    )
    logger.info(f"关卡↔灵气映射: {stage_lingqi_pairs}")
    logger.info(f"与当前灵气匹配的关卡: {same_linggen_chaos}")
    sorted_by_prio = sort_stage_lingqi_pairs(stage_lingqi_pairs, priority=lingqi_order)
    if same_linggen_chaos:
        cur_task = same_linggen_chaos
    elif sorted_by_prio:
        cur_task = sorted_by_prio[0][0]
        logger.info(f"无灵气匹配，按灵气优先级 fallback: {cur_task}（序: {lingqi_order}）")
    else:
        cur_task = task_list_for_lingyu[0]
        logger.info(f"无映射数据，fallback 候选首项: {cur_task}")
    remains = h.task_way_to_diff(task=cur_task, expect_difficulty="灵狱", task_type="极寒深渊")
    logger.info(f"剩余次数: {remains}")
    phase1_battled = False
    if remains > 0:
        logger.info(f"开始挑战(灵狱): {cur_task}")
        _run_battle(cur_task, is_lingyu=True)
        phase1_battled = True
    else:
        _after_no_remains()

    # ── 阶段二：其余关卡按配置难度打 ──
    logger.info("====极寒深渊-各关卡====")
    for name in JHSY_CHAOS_TABLE:
        if name == cur_task and phase1_battled:
            continue
        nandu = nandu_map.get(name, JhsyNandu.不打)
        if nandu == JhsyNandu.不打:
            logger.info(f"{name} 不打")
            continue
        diff2 = _phase2_expect_difficulty(nandu)
        remains = h.task_way_to_diff(task=name, expect_difficulty=diff2, task_type="极寒深渊")
        logger.info(f"{name} 剩余次数: {remains}")
        if remains > 0:
            logger.info(f"开始挑战: {name} ({diff2})")
            _run_battle(name, is_lingyu=False)
        else:
            _after_no_remains()
