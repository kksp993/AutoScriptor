"""创号脚本专用的临时战斗流程。

本文件不会在 AutoScriptor 启动时自动加载。创号入口脚本需要显式调用
``register_account_battle_flow()``，流程才会在当前进程中生效。
"""
from __future__ import annotations

from AutoScriptor.battle_character.hero import Hero
from AutoScriptor import *
RIGHT = B(190,562,159,151)
LEFT = B(33,558,153,161)
JUMP = B(1107,411,159,157)
Attack = B(1058,581,119,128)
cnt = 4



def account_battle_flow(h: Hero):
    """执行创号阶段的一轮战斗。

    这里先沿用 Hero 的通用战斗逻辑；如果创号角色需要专用技能顺序，
    只需在本函数内替换为 ``hero.skill(...).sleep(...).move_right(...)``
    等链式操作即可，不需要修改 data/battle_character 下的常驻职业文件。
    """
    global cnt

    for _ in range(cnt):
        click(RIGHT, long_click_duration_s=1)
        click(JUMP,repeat=2)
    while not bg.signal(BG_SIGNALS.TRY_EXIT) and ui_F(T("前进", box=Box(513, 253, 260, 86).margin())):
        click(LEFT)
        h.skill(5);sleep(0.5)

def liushahe(h: Hero):
    """执行创号阶段的一轮战斗。

    这里先沿用 Hero 的通用战斗逻辑；如果创号角色需要专用技能顺序，
    只需在本函数内替换为 ``hero.skill(...).sleep(...).move_right(...)``
    等链式操作即可，不需要修改 data/battle_character 下的常驻职业文件。
    """
    global cnt

    for _ in range(cnt):
        click(RIGHT, long_click_duration_s=1)
        click(JUMP,repeat=2)
    while not bg.signal(BG_SIGNALS.TRY_EXIT, False) and not bg.signal(BG_SIGNALS.BUILTIN_ADVANCE, False) and ui_F(T("前进", box=Box(513, 253, 260, 86).margin())):
        click(RIGHT)
        h.skill(5);sleep(0.5)
        cnt = 1

def yumajian(h:Hero):
    global cnt

    for _ in range(cnt):
        click(RIGHT, long_click_duration_s=1)
        click(JUMP,repeat=2)
    while (
        not bg.signal(BG_SIGNALS.TRY_EXIT, False)
        and not bg.signal(BG_SIGNALS.BUILTIN_ADVANCE, False)
    ):  
        click(LEFT) 
        h.skill(5);sleep(0.5)
        h.skill(5);sleep(0.5)
        h.skill(6).sleep(0.5).skill(6).sleep(0.5).skill(6).sleep(0.5)
        h.skill(6).sleep(0.5).skill(6).sleep(0.5).skill(6).sleep(0.5)
        cnt=7
        if bg.signal(BG_SIGNALS.TRY_EXIT, False) or bg.signal(BG_SIGNALS.BUILTIN_ADVANCE, False): break
        click(RIGHT)
        h.skill(5);sleep(0.5)
        sleep(1)
        h.skill(5);sleep(0.5)
        if bg.signal(BG_SIGNALS.TRY_EXIT, False) or bg.signal(BG_SIGNALS.BUILTIN_ADVANCE, False): break
        sleep(1)
        h.skill(5);sleep(0.5)
        if bg.signal(BG_SIGNALS.TRY_EXIT, False) or bg.signal(BG_SIGNALS.BUILTIN_ADVANCE, False): break
        click(RIGHT)
        h.skill(6).sleep(0.5).skill(6).sleep(0.5).skill(6).sleep(0.5)
        h.skill(6).sleep(0.5).skill(6).sleep(0.5).skill(6).sleep(0.5)
        cnt=4

def longgong_1_4x(h:Hero):
    global cnt
    if cnt>2:
        h.skill(5);sleep(0.1)
        h.skill(6).sleep(0.2).skill(6).sleep(0.2).skill(6);sleep(0.1)
    if cnt>1:
        click(LEFT)
    while not bg.signal(BG_SIGNALS.TRY_EXIT, False) and not bg.signal(BG_SIGNALS.BUILTIN_ADVANCE, False):
        h.skill(5).skill(5).skill(5).skill(5).skill(5).skill(5)
    cnt-=1  
    if cnt == 1:
        click(LEFT, long_click_duration_s=0.3)
        # h.move_right()
        # h.skill(6).sleep(0.5)
    h.prop()

def benmingshen(h:Hero):
    click(B(0,0))
    h.skill(6).sleep(0.2).skill(6).sleep(0.2).skill(6);sleep(0.1)
    while not bg.signal(BG_SIGNALS.TRY_EXIT, False) and not bg.signal(BG_SIGNALS.BUILTIN_ADVANCE, False):
        h.skill(5)


def sushua1(h:Hero):
    while not bg.signal(BG_SIGNALS.TRY_EXIT, False) and not bg.signal(BG_SIGNALS.BUILTIN_ADVANCE, False):
        h.skill(1)

def register_account_battle_flow() -> None:

    """仅在调用方明确要求时注册创号专用流程。"""
    Hero.register_flow("创号战斗脚本1", account_battle_flow)
    Hero.register_flow("御马监", yumajian)
    Hero.register_flow("流沙河", liushahe)
    Hero.register_flow("龙宫1", longgong_1_4x)
    Hero.register_flow("本命神", benmingshen)
    Hero.register_flow("速刷1", sushua1)
