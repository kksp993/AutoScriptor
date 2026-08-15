"""梵天塔配招测试模板 — 纯手搓，逐个按技能1~6 观察效果。

用法：
  1. 手动进入梵天塔战斗（点完「入劫」、加载完）；
  2. 在 WebUI 直接运行本任务；
  3. 它会逐个按技能1~6（每个间隔 SKILL_INTERVAL 秒）并打日志，
     你观察每个技能对应的实际效果，据此确定细粒度排轴；
  4. 测完按「推进」/ 等战斗结束自动退出。

参数都集中在文件顶部，按需改。
"""
from time import time

from AutoScriptor import *
from ZmxyOL import *
from ZmxyOL.task.task_register import register_task
from AutoScriptor.battle_character.hero import h



@register_task(
    path_cn="自定义任务/测试/梵天塔配招测试",
    description="纯手搓逐个按技能1~5，观察配招效果。",
    task_doc="手动进入梵天塔战斗后运行，逐个按技能并打日志，用于确定细粒度排轴。",
    debug_mode=True,
)
def task():
    click(T("重新挑战", box=Box(594,394,100,50).margin()),offset=(0,-60))
    click(T("确定", box=Box(714,406,171,79).margin()))
    wait_for_disappear(I("加载中"))
    sleep(0.5)
    h.skill(6); sleep(0.1)
    h.prop(ws=False)
    h.huashen(1)
    h.skill(4); sleep(1)
    h.skill(3); sleep(1)
    h.prop(xb=False,fb=False)
    h.skill(6)
    click(I("化身-绝唱"), if_exist=True)
    h.huashen(1)
    for _ in range(10):
        h.prop(xb=False,fb=False)
        h.move_right().sleep(0.1).skill(1); sleep(0.2)   
        h.move_left().sleep(0.1).skill(1); sleep(0.2)   
    click(B(1155,24,102,96))
