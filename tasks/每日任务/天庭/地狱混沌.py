from ZmxyOL import *
from AutoScriptor import *


@register_task(
    description="【弃用】可以扫荡。依次挑战地狱混沌关卡。",
    deprecated=True,
    reschedule="daily",
)
def daily_hell_chaos_task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    """该任务已弃用：当前版本可以直接扫荡，保留脚本仅用于兼容旧配置。"""
    from ZmxyOL.character.hero import h
    h.task(task_name="混沌地狱官邸·噩梦")
