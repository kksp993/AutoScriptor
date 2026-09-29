from AutoScriptor import *
from ZmxyOL import *

tasks =[
    "九重天",
    "凌霄宝殿",
    "玲珑塔·李天王",
    "龙宫",
    "白虎之森·终",
    "转轮殿·普通",
    "九重天",
]

@register_task(
    description="完成五光十色活动流程。",
    task_doc="【未完成】完成五光十色活动流程。",
)
def task(battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW):
    from ZmxyOL.character.hero import h
    h.battle_tasks(task_table=tasks[0])
