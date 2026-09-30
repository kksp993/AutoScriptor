"""龙宫速刷号：按「速刷1」流程把角色练到 91 级。

开号是分步手动的长流程，这里只固定最常用的那个组合；其余步骤在
``_开号流程.py`` 里按需调用。
"""
from AutoScriptor import *
from ZmxyOL import *

from tasks.一般任务.开号._开号流程 import longgong1
from tasks.一般任务.开号._创号战斗流程 import register_account_battle_flow


@register_task(
    description="按速刷1流程把龙宫角色练到 91 级",
    task_doc="需要角色已进入游戏。按「速刷1」战斗流程练级，到 91 级停止。",
)
def task():
    register_account_battle_flow()
    longgong1(91, ensure_drug=False, flow_name="速刷1")
