from ZmxyOL import *
from AutoScriptor import *


@register_task(
    path_cn="每日任务/天庭/地狱混沌",
    description="【弃用】可以扫荡。依次挑战地狱混沌关卡。",
    task_doc="该任务已弃用：当前版本可以直接扫荡，保留脚本仅用于兼容旧配置。",
    deprecated=True,
)
def daily_hell_chaos_task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    from AutoScriptor.battle_character.hero import h
    h.task(task_name="混沌地狱官邸·噩梦")
