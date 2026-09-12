from __future__ import annotations

from re import U
from socket import timeout
import sys
from pathlib import Path




PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCRIPTS_ROOT = PROJECT_ROOT / "test" / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

ACTIVITY_SCRIPTS_ROOT = SCRIPTS_ROOT / "活动任务"
if str(ACTIVITY_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(ACTIVITY_SCRIPTS_ROOT))



from AutoScriptor import *
from ZmxyOL import *
from ZmxyOL.battle.tasks import TASK_TABLE
from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from 创号战斗脚本1 import *

# 没改键位之前的设置

def click00_until(B:Target, appear:bool=True):
    click(B(0,0), until=lambda:ui_T(B) if appear else lambda:not ui_T(B))



def click_until(A:Target, B:Target, appear:bool=True):
    click(A, until=lambda:ui_T(B) if appear else lambda:not ui_F(B))


def click_off(A:Target):
    click(A, until=lambda:not ui_T(A))





def init_role(username: str):
    click(I("创建新角色"))
    while ui_F(T("龙拳圣女", box=Box(49,32,230,64).margin())):
        swipe(B(1149,477), B(1156,362), duration_s=1)
    click(B(690,656));sleep(1)
    click(B(168,64))
    input(username)
    key_event(AndroidKey.KEYCODE_ENTER)
    info = extract_info(B(578,633,230,58), post_process=lambda s: s.strip(), ensure_not_empty=True, mode="text")
    assert info == username
    click(T("创建", box=Box(822,627,123,55).margin()))
    wait_for_disappear(T("(触摸任意处继续)", box=Box(876,181,266,47).margin()))
    logger.info("成功创建角色: %s", username)

def start_newbie_tutorial():
    # """创号结束-> 新手教程九重天-> 结束"""
    click(T("(触摸任意处继续)", box=Box(876,181,266,47).margin()), if_exist=True);sleep(1)
    click(B(1074,535,146,69))
    click(T("(触摸任意处继续)", box=Box(876,181,266,47).margin()), if_exist=True);sleep(3)
    click(T("九重天", box=Box(401,260,188,188).margin()), until=lambda:ui_T(T("九重天", box=Box(210,264,146,42).margin())));sleep(1)
    click(T("九重天", box=Box(210,264,146,42).margin()), until=lambda:ui_T(T("开始挑战", box=Box(532,564,216,85).margin())));sleep(1)
    click(T("开始挑战", box=Box(532,564,216,85).margin()))
    click(T("(触摸任意处继续)", box=Box(876,181,266,47).margin()));sleep(0.5)
    click(RIGHT, long_click_duration_s=1);sleep(1)
    click(LEFT, long_click_duration_s=1);sleep(1)
    click(JUMP);sleep(1)
    click(B(1107,411,159,157));sleep(3)
    while ui_F(T("尝试攻击看看吧", box=Box(338,72,247,53).margin())):
        click(JUMP);sleep(0.5);click(JUMP)
    click(Attack);sleep(1)
    click(Attack);sleep(1)
    click(Attack);sleep(1)
    click(T("(触摸任意处继续)", box=Box(876,181,266,47).margin()));sleep(0.5)
    logger.info("九重天新手教程完成, 开始爬楼梯")
    while not ui_T(T("滑动技能列表，查看可学技能。", box=Box(307,494,513,69).margin())):
        click(RIGHT, long_click_duration_s=1)
        click(JUMP,repeat=2)
    logger.info("爬楼梯完成, 出现boss")
    swipe(B(903,277), B(664,277), duration_s=1)
    swipe(B(664,277), B(903,277), duration_s=1)
    swipe(B(664,277), B(903,277), duration_s=1)
    swipe(B(664,277), B(903,277), duration_s=1)
    while ui_F(T("炎狱堕龙爪", box=Box(632,325,259,34).margin())):
        swipe(B(907,273), B(758,267), duration_s=1)
    click(T("学习", box=Box(892,575,166,73).margin()))
    logger.info("学习炎狱堕龙爪完成");sleep(1)
    swipe(B(257,231), B(393,235), duration_s=1)
    wait_for_appear(T("不少被动技能", box=Box(625,508,215,36).margin()))
    click(T("被动技能", box=Box(415,14,210,107).margin()))
    click(T("(触摸任意处继续)", box=Box(868,628,311,74).margin()));sleep(1)
    click(T("(触摸任意处继续)", box=Box(868,628,311,74).margin()));sleep(0.5)
    h.set(False,1)
    while ui_F(T("站在这里")) and not ui_T(T("弃牌", box=Box(487,335,143,76).margin())):
        h.skill(5);sleep(0.5)
        click(Attack);sleep(0.2)
    if not ui_T(T("弃牌", box=Box(487,335,143,76).margin())):
        click(Attack)
        click(RIGHT, long_click_duration_s=4)
        h.way_to_exit(until=I("加载中"), exit_loc=TASK_TABLE["九重天"]["exit_loc"])
    click(T("(触摸任意处继续)", box=Box(868,628,311,74).margin()), if_exist=True);sleep(0.5)
    click(T("弃牌", box=Box(487,328,143,83).margin()))
    click(T("抽牌", box=Box(501,514,275,106).margin()), until=lambda:not ui_T(T("抽牌", box=Box(501,514,275,106).margin())))
    click(B(564,173,150,231))
    click(T("返回村庄", box=Box(242,490,252,132).margin()), until=lambda: ui_T(T("云中子", box=Box(692,258,78,32).margin())))
    logger.info("新手教程九重天完成，接下来打造兵器")


def make_weapon():
    """打造兵器"""
    box = locate(T("云中子", box=Box(692,258,78,32).margin()))
    click(T("云中子", box=Box(692,258,78,32).margin()), **(Box(689,313,100,181)-box), until=lambda:ui_T(T("到炼丹炉打造界面。", box=Box(517,508,303,36).margin())))
    click(T("(触摸任意处继续)", box=Box(868,628,311,74).margin()));sleep(1)
    click(T("(触摸任意处继续)", box=Box(868,628,311,74).margin()));sleep(0.5)
    click(T("(触摸任意处继续)", box=Box(876,181,266,47).margin()));sleep(0.5)
    click(T("添加", box=Box(441,320,127,119).margin()), delay=1)
    wait_for_appear(T("道具", box=Box(599,68,82,42).margin()))
    click(B(407,126,124,125), delay=1)
    click(T("选择", box=Box(662,403,142,85).margin()), delay=1)
    wait_for_appear(T("万事俱备", box=Box(326,26,395,57).margin()))
    click(T("打造", box=Box(656,607,246,79).margin()), delay=1)
    click(T("确定", box=Box(554,450,195,123).margin()), delay=1)
    click(T("(触摸任意处继续)", box=Box(868,628,311,74).margin()), delay=1, until=lambda:not ui_T(T("(触摸任意处继续)", box=Box(868,628,311,74).margin())))
    wait_for_appear(T("请前往强化界面", box=Box(337,507,251,37).margin()))
    click(T("强化", box=Box(185,35,115,84).margin()), delay=1)
    click(T("添加", box=Box(577,97,123,133).margin()), delay=1)
    wait_for_appear(T("装备", box=Box(600,69,81,41).margin()))
    click(B(411,118,113,133), delay=1)
    click(T("选择", box=Box(670,412,126,72).margin()), delay=1)
    click(T("添加", box=Box(355,426,124,68).margin()), delay=1)
    wait_for_appear(T("道具", box=Box(590,59,91,58).margin()))
    click(B(409,120,121,123), delay=1)
    click(T("选择", box=Box(671,405,125,66).margin()), delay=1)
    wait_for_appear(T("100.00%", box=Box(905,104,136,20).margin()))
    click(T("(触摸任意处继续)", box=Box(904,377,237,34).margin()), delay=1)
    wait_for_appear(T("添加幸运符，", box=Box(321,501,208,43).margin()))
    click(B(343,222,136,117), delay=1)
    wait_for_appear(T("强化的成功率已经很高", box=Box(398,507,402,56).margin()))
    click(B(343,222,136,117), delay=1)
    click(T("(触摸任意处继续)", box=Box(879,647,276,54).margin()), delay=1)
    wait_for_appear(T("强化成功率", box=Box(330,39,254,44).margin()))
    click(T("强化", box=Box(855,580,248,100).margin()), delay=1)
    click(T("确定", box=Box(516,433,276,116).margin()), delay=1)
    click(T("(触摸任意处继续)", box=Box(904,647,237,34).margin()), delay=1)
    wait_for_appear(T("武器或防具", box=Box(585,508,183,36).margin()))
    click(B(262,142,98,108), delay=1)
    click(T("装备", box=Box(351,520,98,91).margin()), delay=1)
    click(T("(触摸任意处继续)", box=Box(904,647,235,34).margin()), delay=1)
    wait_for_appear(T("强力神兵", box=Box(524,47,185,36).margin()))
    click(B(49,469,91,153), delay=1)
    click(T("新的关卡", box=Box(328,30,144,53).margin()), delay=1)
    click(T("天宫道", box=Box(656,282,172,74).margin()), delay=1)
    click(T("天宫道1", box=Box(162,230,285,116).margin()), delay=1)
    click(T("开始挑战", box=Box(527,554,237,102).margin()), delay=1)
    logger.info("进入天宫道")
    click(I("导航-菜单"))
    click(I("菜单-设置"))
    click(T("开始界面"))
    click(T("确定",color="绿色"))


def xiangui(server_name: str, username: str):
    login(server_name=server_name, character_name =username)
    wait_for_appear(T("仙柜系统", box=Box(726,508,176,36).margin()))
    click(T("个人资料", box=Box(1146,179,111,66).margin()), delay=1)
    click(B(229,448,82,85), delay=1)
    click(B(0,0),until=lambda:ui_T(T("神秘力", box=Box(691,508,179,36).margin())), delay=1)
    click(T("协力", box=Box(775,34,93,55).margin()), delay=1)
    click(B(0,0),until=lambda:ui_T(T("属性的主要来源", box=Box(692,508,259,36).margin())), delay=1)

    click(T("嵌入", box=Box(635,147,114,115).margin()), delay=1)
    click(T("X", box=Box(1007,79,104,85).margin()), until=lambda:ui_T(T("幻化系统", box=Box(350,508,133,50).margin())), delay=1)
    click(T("幻化", box=Box(859,34,147,64).margin()), delay=1)
    click(B(0,0),until=lambda:ui_T(T("云中子", box=Box(692,258,78,32).margin())), delay=1)
    ensure_in("登录")
    login(server_name=server_name, character_name=username)


def chenghao(server_name: str, username: str):
    wait_for_appear(T("称号系统", box=Box(728,489,159,55).margin()))
    click(T("个人资料", box=Box(1146,179,111,66).margin()), delay=1)
    click(T("称", box=Box(554,45,89,57).margin()),until=lambda:ui_T(T("应接不暇", box=Box(781,77,162,48).margin())))
    click(B(0,0),until=lambda:ui_T(T("云中子", box=Box(692,258,78,32).margin())), delay=1)

    # 签到
    click(T("活动", box=Box(722,62,58,81).margin()))
    click(T("X", box=Box(1085,25,55,69).margin()))

    ensure_in("登录")


def renqi(server_name: str, username: str, supervisor_server_name: str, supervisor_username: str):
    ensure_in("登录")
    login(server_name=supervisor_server_name, character_name=supervisor_username)
    while ui_F(T("仙盟",box=Box(16,30,130,400)), 3):
        click(I("导航-按钮收缩"))
        if ui_T(T("精彩活动"), 2): click(B(1100, 40, 40, 40))
        sleep(2)
    click(T("好友", box=Box(36,19,880,335).margin()), delay=1)
    click(T("加好友", box=Box(822,578,121,68).margin()), delay=1)
    click(T("输入好友昵称", box=Box(454,288,411,93).margin()), delay=1)
    click(B(341,77), delay=1)
    username = f"{server_name}：{username}"
    input(username)
    key_event(AndroidKey.KEYCODE_ENTER)
    info = extract_info(B(448,297,384,81), post_process=lambda s: s.strip(), ensure_not_empty=True, mode="text")
    assert info == username
    click(T("确定", box=Box(576,423,128,71).margin()), delay=1)
    ui_T(T("添加好友成功", box=Box(472,313,356,99).margin()))
    click(B(911,188,58,78), delay=1, until=lambda: not ui_T(T("输入好友昵称", box=Box(454,288,411,93).margin())))

    click(B(824,245,76,85), delay=1)
    click(T("赠送", box=Box(723,362,116,56).margin()), delay=1)

    click(B(647,249,91,109), delay=1)
    click(T("使用", box=Box(346,479,145,65).margin()), delay=1)
    click(B(860,364,47,92), repeat=49, delay=1)
    click(T("确定", box=Box(627,531,173,110).margin()), delay=1)
    click(B(900,49,75,73), delay=1)
    click(B(941,30,62,87), delay=1, until=lambda: ui_F(T("赠送物品", box=Box(542,64,203,64).margin())))
    click(B(941,41,70,53), delay=1, until=lambda: not ui_T(T("加好友", box=Box(822,578,121,68).margin())))
    ensure_in("登录")
    login(server_name=server_name, character_name=username)
    click(I("导航-菜单"))
    click(T("个人资料", box=Box(1146,179,111,66).margin()), delay=1)
    click(T("称", box=Box(554,45,89,57).margin()), until=lambda: ui_T(T("成就", box=Box(585,81,106,105).margin()), timeout=1))
    click(T("成就", box=Box(585,81,106,105).margin()))
    click(T("装备", box=Box(468,405,102,83).margin()))
    click(B(1056,49,66,68), until=lambda: ui_T(T("称", box=Box(554,45,89,57).margin())))

    # if ui_T(T("添加", box=Box(231,554,105,105).margin())):
    #     click(T("添加", box=Box(231,554,105,105).margin()), delay=1)
    #     click(B(413,147,100,98), delay=1)
    #     click(T("装备", box=Box(526,439,68,70).margin()), delay=1)

    click(B(1182,6,76,77), until=lambda: ui_T(T("个人资料", box=Box(1146,179,111,66).margin())))
    click(B(0,0))

def tiangongdao1():
    """需要手动去打，没有前置教程"""
    ensure_in("天庭")
    click(T("速率", box=Box(1174,539,73,66).margin()), delay=1)
    btns= [
        B(663,161,139,82),
        B(663,275,139,78),
        B(663,385,139,71)
    ]
    for btn in btns:
        info = extract_info(btn, post_process=lambda s: int(s.strip()[-1]), ensure_not_empty=True, mode="text")
        click(btn,repeat=5-info)
    click(B(852,84,46,45))
    ensure_in("天庭")
    click(T("天宫道", box=Box(627,294,170,62).margin()),until=lambda: ui_F(T("九重天", box=Box(401,260,188,188).margin())))
    click(T("天宫道1", box=Box(247,251,136,75).margin()))
    click(T("开始挑战", box=Box(490,565,322,104).margin()))
    h.set(has_cd=False, speed_x=1).heaven_battle(exit_loc=100, flow_name="创号战斗脚本1")


def hecheng():
    """打完天宫道1会刷出这个教程"""
    wait_for_appear(T("炼丹炉开始合成", box=Box(650,41,273,53).margin()))
    click(B(689,313,100,181))
    click(B(0,0), until=lambda: ui_T(T("合成材料有关", box=Box(590,488,220,62).margin())))
    click(B(676,186,142,146), until=lambda: ui_T(T("合成就一定会成功", box=Box(550,32,294,68).margin())))
    click(T("合成", box=Box(654,607,215,60).margin()), delay=1)
    click(B(0,0), until=lambda: ui_T(T("法宝宣花葫芦", box=Box(552,34,222,60).margin())), delay=1)
    click(B(40,463,107,178),until=lambda:ui_T(T("宣花葫芦", box=Box(586,490,151,56).margin())), delay=1)
    click(T("天宫道", box=Box(627,294,170,62).margin()),until=lambda: ui_F(T("九重天", box=Box(401,260,188,188).margin())), delay=1)
    click(T("蟠桃园", box=Box(249,373,106,36).margin()), delay=1)
    click(T("开始挑战", box=Box(490,565,322,104).margin()), delay=1)
    wait_for_appear(T("那个天兵", box=Box(595,73,142,78).margin()))
    click(B(0,0), until=lambda: ui_F(T("那个天兵", box=Box(595,73,142,78).margin())), delay=1)
    while ui_F(T("法宝", box=Box(842,81,83,49).margin())):
        h.skill(5);sleep(0.5)
    while ui_F(T("捕捉成功", box=Box(486,34,134,60).margin())):
        h.prop(fb=True, xb=False, ws=False)
    click(B(0,0), until=lambda: ui_T(T("宠物按钮", box=Box(443,4,164,86).margin())))
    click(T("宠物", box=Box(1151,554,102,113).margin()),until=lambda: ui_T(T("宠物面板", box=Box(473,499,151,52).margin())))
    click(B(0,0), until=lambda: ui_T(T("宠物上阵", box=Box(480,38,144,51).margin())))
    click(T("出战", box=Box(901,599,126,66).margin()))
    click(B(0,0), until=lambda:ui_T(T("请点击赵公明", box=Box(326,28,236,70).margin())), delay=1)
    click(B(247,300,111,194), until=lambda:ui_F(T("请点击赵公明", box=Box(326,28,236,70).margin())), delay=1)
    click(B(0,0), until=lambda: ui_T(T("点券购买商品", box=Box(509,494,228,50).margin())), delay=1)
    click(T("购买", box=Box(249,345,135,51).margin()), delay=1)
    click(T("确定", box=Box(620,539,185,113).margin()), delay=1)
    click(B(0,0),until=lambda:ui_T(T("小灵魂药水", box=Box(488,508,178,35).margin())))
    click(B(252,139,123,112), delay=1)
    click(T("使用", box=Box(390,430,139,79).margin()), delay=1)
    click(T("确定", box=Box(622,526,162,118).margin()), delay=1)
    click(B(0,0), until=lambda:ui_T(T("热血", box=Box(699,313,81,53).margin())), delay=1)
    click(B(0,0),until=lambda:ui_T(T("学习", box=Box(646,541,264,111).margin())))
    click(T("学习", box=Box(646,541,264,111).margin()),until=lambda:ui_T(T("强力技能", box=Box(552,482,147,74).margin())))
    click(B(0,0), until=lambda:ui_T(T("千里眼和顺风耳", box=Box(520,47,247,32).margin())), delay=1)
    click(B(1070,296,119,201), until=lambda:ui_T(T("已接受", box=Box(820,552,190,94).margin())))
    click(B(0,0), until=lambda:ui_T(T("点击关卡名字", box=Box(405,32,222,70).margin())), delay=1)
    click(T("<天宫道·终>", box=Box(797,243,207,64).margin()))
    click(I("导航-菜单"), until=lambda:ui_T(T("宠物", box=Box(616,77,94,51).margin())), interval=1,delay=1)
    click(T("宠物", box=Box(616,77,94,51).margin()), delay=1)
    click(T("休息", box=Box(900,592,128,67).margin()), if_exist=True, delay=1)
    click(B(1195,23,64,45), delay=1)
    click(B(0,0), delay=1)
    h.set(has_cd=False, speed_x=1).heaven_battle(exit_loc=100, flow_name="创号战斗脚本1")


def xinshoumubiao():
    """打完千里眼顺风耳会刷出这个教程"""
    wait_for_appear(T("查看新手目标", box=Box(499,26,236,68).margin()))
    click(T("新手目标", box=Box(1148,597,105,121).margin()))
    click(B(1027,77,62,64),until=lambda:ui_T(T("云中子", box=Box(692,258,78,32).margin())))

def learnskills():
    click(I("导航-菜单"))
    click(T("技能", box=Box(1163,397,78,57).margin()))
    while ui_F(T("游龙舞", box=Box(743,330,67,23).margin())):
        swipe(B(907,273), B(758,267), duration_s=1)
    click(T("学习", box=Box(892,575,166,73).margin()))
    logger.info("学习完成");sleep(1)
    click(B(1182,6,76,77), until=lambda: ui_T(T("个人资料", box=Box(1146,179,111,66).margin())))
    click(B(0,0))

def renwu(stop_task_name: str=None):
    ensure_in("村庄")
    while ui_F(T("任务", box=Box(481,23,80,111).margin()), 3):
        click(I("导航-按钮收缩"))
        if ui_T(T("精彩活动"), 2): click(B(1100, 40, 40, 40))
        sleep(2)
    click((T("任务", box=Box(481,23,80,111).margin()),T("任务", box=Box(242,88,102,29).margin())))
    click(T("经典任务", box=Box(229,389,202,65).margin()))
    while ui_T(T("领取奖励", box=Box(499,170,587,477).margin()), timeout=2):
        click(T("领取奖励", box=Box(499,170,587,477).margin()))
    task_name = extract_info(B(203,214,219,57), post_process=lambda s: s.strip(), ensure_not_empty=True, mode="text")
    logger.info(f"任务名称: {task_name}")
    if task_name == stop_task_name:
        return False
    click(T("<", box=Box(499,170,587,477).margin()),until=lambda:ui_T(I("加载中")))

    def battle_task_handler(task_name):
        wait_for_disappear(I("加载中"))
        with bg.scope("创号任务战斗") as scope:
            scope.add(
                name="无双",
                identifier=T("无双", box=Box(1133,241,129,134).margin()),
                callback=lambda: click(T("无双", box=Box(1133,241,129,134).margin())),
                once=False
            )
            import 创号战斗脚本1
            创号战斗脚本1.cnt = 3
            if task_name == "死守的马天君":
                h.set(has_cd=False, speed_x=1).heaven_battle(exit_loc=900, flow_name="御马监")
            elif task_name in [
                "镇压邪沙僧",
                "镇压邪唐僧",
                "镇压邪悟空",
            ]:
                h.set(has_cd=False, speed_x=1).heaven_battle(exit_loc=500, flow_name="流沙河")
            else:
                h.set(has_cd=False, speed_x=1).heaven_battle(exit_loc=400, flow_name="创号战斗脚本1")
        click((T("回家", box=Box(29, 656, 77, 54).margin()),T("家", box=Box(20,605,93,96).margin())))
    battle_task_handler(task_name)
    return True

def yeli():
    wait_for_appear(T("业力之道", box=Box(595,96,137,25).margin()))
    click(B(0,0), until=lambda: ui_T(T("业力阵", box=Box(404,31,187,59).margin())), delay=1)
    click(B(149,440,76,83), delay=1)
    click(B(0,0), until=lambda: ui_T(T("业力装备", box=Box(624,544,146,55).margin())), delay=1)
    click(B(319,190,121,111),until=lambda: ui_T(T("毕生所学", box=Box(462,37,172,53).margin())), delay=1)
    click(B(496,327,83,87),until=lambda: ui_T(T("天道", box=Box(364,493,83,76).margin())), delay=1)
    click(B(217,197,113,108), until=lambda: ui_T(T("灵魂灌注", box=Box(832,487,160,63).margin())), delay=1)
    click(B(1083,20,58,64), delay=1)
    click(T("灵魂灌注", box=Box(726,540,217,89).margin()),delay=1)
    wait_for_appear(T("灵魂灌注", box=Box(619,504,149,49).margin()))
    click(B(741,118,193,198), until=lambda: ui_T(T("点击业力装备", box=Box(336,31,223,53).margin())), delay=1)
    click(B(187,403,115,118),until=lambda:ui_T(T("云中子", box=Box(692,258,78,32).margin())), delay=1)

def update_equipment():
    ensure_in("登录")
    login(server_name=server_name, character_name=username)
    click(I("导航-菜单"))
    click(T("个人资料", box=Box(1146,179,111,66).margin()), delay=1)
    click(B(134,548,106,117))
    click(T("更换", box=Box(553,535,117,71).margin()))
    click(B(643,137,108,111))
    click(T("装备", box=Box(176,491,128,87).margin()))
    click(B(229,540,111,145))
    click(T("更换", box=Box(666,538,109,59).margin()))
    click(B(638,131,118,115))
    click(T("装备", box=Box(131,531,171,62).margin()))
    click(B(1182,6,76,77), until=lambda: ui_T(T("个人资料", box=Box(1146,179,111,66).margin())))
    click(B(0,0))

def longgong1(exp_lv: int, ensure_drug: bool = False, flow_name: str = "龙宫1"):
    try:
        ensure_in("天庭",4)
        click(T("龙宮", box=Box(263,423,196,93).margin()))
        click(T("龙宫1"))
        click(T("速率设置", box=Box(207,570,144,80).margin()))
        info = extract_info(B(655,324,139,68), post_process=lambda s: int(s.strip()[-1]), ensure_not_empty=True, mode="text")
        click(B(655,324,139,68),repeat=4-info)
        click(B(845,84,41,33))
        click(T("开始挑战", box=Box(538,572,200,70).margin()))
        wait_for_disappear(I("加载中"))
        while extract_info(
            B(14, 98, 111, 45),
            post_process=lambda text: int("".join(character for character in text if character.isdigit())),
            ensure_not_empty=True,
            mode="text",
        )<exp_lv:
            sleep(1)
            if ensure_drug and ui_F(T("EXP", box=Box(148,130,61,38).margin()), timeout=1):
                click(I("导航-菜单"), until=lambda:ui_T(I("菜单-设置")), interval=2)
                click(I("菜单-设置"))
                click(T("村庄"))
                click(T("确定", box=Box(522,367,232,97).margin()))
                eat_drug("三倍")
                return longgong1(exp_lv, ensure_drug=ensure_drug)
            import 创号战斗脚本1
            创号战斗脚本1.cnt = 3
            with bg.scope("龙宫战斗后处理") as scope:
                scope.add(
                    name="战斗失败",
                    identifier=T("198点券"),
                    callback=lambda: [
                        logger.warning("龙宫1检测到战斗失败"),
                        bg.set_signal(BG_SIGNALS.FAILED, True),
                        bg.set_signal(BG_SIGNALS.TRY_EXIT, True),
                    ],
                )
                from threading import Timer
                battle_timeout_timer = Timer(30, lambda: [
                    logger.warning("龙宫1战斗超时，停止战斗并重新挑战"),
                    bg.set_signal(BG_SIGNALS.TRY_EXIT, True),
                    bg.set_signal(BG_SIGNALS.FAILED, True),
                ])
                battle_timeout_timer.daemon = True
                battle_timeout_timer.start()
                try:
                    h.set(has_cd=False, speed_x=4).heaven_battle(exit_loc=100, flow_name=flow_name, exit_after_battle=False)
                finally:
                    battle_timeout_timer.cancel()
                    battle_timeout_timer.join()
                if bg.signal(BG_SIGNALS.FAILED):
                    click(T("取消", box=Box(487,377,135,79).margin()))
                    click(T("重新挑战", box=Box(791,596,234,94).margin()), until=lambda: ui_T(I("加载中")))
                    # 将所有FAILED相关的信号重置为False
                    bg.set_signal(BG_SIGNALS.FAILED, False)
                    bg.set_signal(BG_SIGNALS.TRY_EXIT, False)
                else:
                    click(I("导航-菜单"))
                    click(I("菜单-设置"))
                    click(T("重新挑战", box=Box(963,592,96,41).margin()), until=lambda:ui_T(T("确定", box=Box(522,367,232,97).margin())))
                    click(T("确定", box=Box(522,367,232,97).margin()))
                wait_for_disappear(I("加载中"))
    finally:
        click(I("导航-菜单"), until=lambda:ui_T(I("菜单-设置")), interval=2)
        click(I("菜单-设置"))
        click(T("村庄"))
        click(T("确定", box=Box(522,367,232,97).margin()))


def lingwu():
    """lv.50"""
    wait_for_appear(T("灵物功能已开", box=Box(329,497,233,43).margin()))
    click(T("灵物", box=Box(934,23,103,113).margin()))
    click(B(0,0), until=lambda:ui_T(T("任务", box=Box(487,60,74,52).margin())))

def benmingshen():
    wait_for_appear(T("本命神已经解锁", box=Box(530,507,242,37).margin()))
    click(T("本命神", box=Box(807,4,129,126).margin()))
    click(B(0,0),until=lambda:ui_T(T("属于你自己的本命神", box=Box(657,507,331,37).margin())))
    click(B(169,341,88,62))
    click(T("虚空之境", box=Box(1113,322,166,96).margin()), until= lambda: ui_F(T("虚空之境里", box=Box(655,508,192,35).margin())))
    click(B(0,0),until=lambda:ui_T(T("虚空之境", box=Box(503,5,272,80).margin())))
    click(B(1199,13,70,74))
    wait_for_appear(T("从赵公明那里要了一个", box=Box(628,480,364,74).margin()))
    click(T("虚空之境", box=Box(1137,260,143,141).margin()))
    wait_for_appear(T("快看，虚空大门已经打开！", box=Box(340,509,405,35).margin()))

    click(T("修罗秘境", box=Box(253,272,137,36).margin()), until=lambda:ui_T(T("开始挑战", box=Box(538,572,204,80).margin())))
    click(T("开始挑战", box=Box(538,572,204,80).margin()))
    wait_for_disappear(I("加载中"))
    h.set(has_cd=False, speed_x=1).heaven_battle(exit_loc=300, flow_name="本命神")
        
    wait_for_appear(T("收服本命神", box=Box(481,46,192,48).margin()), delay=1)
    click(T("回家", box=Box(3,597,105,113).margin()), delay=1)
    wait_for_appear(T("本命神的元魂", box=Box(348,508,207,36).margin()), delay=1)
    click(T("背包", box=Box(1156,228,100,107).margin()), delay=1)
    click(B(254,147,111,110), delay=1)
    click(T("装备", box=Box(461,426,101,111).margin()), delay=1)
    wait_for_appear(T("本命神已被唤醒！", box=Box(340,507,261,37).margin()), delay=1)
    click(T("神", box=Box(832,6,85,123).margin()), delay=1)
    click(B(0,0), until=lambda:ui_T(T("云中子", box=Box(692,258,78,32).margin())), delay=1)


def huodong():
    from 活动任务.成长活动 import ChengZhangHuoDong
    ChengZhangHuoDong().run()

def eat_drug(drug_name: str):
    click(B(0,0), repeat=5,delay=1)
    ensure_in("背包")
    click(T("背包", box=Box(106,113,76,122).margin()), delay=1)
    click(T("全部"), delay=1)
    click(T("搜索", box=Box(860,47,111,68).margin()), delay=1)
    click(B(174,79), delay=1)
    input(drug_name)
    key_event(AndroidKey.KEYCODE_ENTER)
    click(B(264,151,99,99), delay=1)
    click(T("使用", box=Box(414,481,107,57).margin()), delay=1)
    click(B(1182,6,76,77), until=lambda: ui_T(T("个人资料", box=Box(1146,179,111,66).margin())), delay=1)
    click(B(0,0), delay=1)

def renwu_special():
    wait_for_appear(T("个特殊任务哦", box=Box(670,272,220,36).margin()))
    click(B(0,0), until=lambda:ui_F(T("特殊任务", box=Box(670,272,220,36).margin())))

def equipment_juexing():
    wait_for_appear(T("觉醒功能", box=Box(472,70,156,55).margin()))
    click(B(583,305,115,208), delay=1)
    click(T("添加", box=Box(568,316,121,143).margin()), delay=1)
    click(B(410,137,132,121), delay=1)
    click(T("选择", box=Box(685,629,109,91).margin()), delay=1)
    click(T("觉醒", box=Box(512,536,228,98).margin()), delay=1)
    click(T("+", box=Box(304,136,64,67).margin()), delay=1)
    click(T("确定", box=Box(591,539,199,96).margin()), delay=1)
    click(T("觉醒", box=Box(504,544,232,96).margin()), delay=1, until=lambda: ui_F(T("觉醒", box=Box(504,544,232,96).margin())))
    click(T("嵌", box=Box(587,115,102,122).margin()), delay=1)
    click(T("Lv1", box=Box(415,124,104,108).margin()), delay=1)
    click(T("嵌入", box=Box(677,594,104,65).margin()), delay=1)
    click(B(567,109,127,130), delay=1)
    click(T("消耗：", box=Box(606,514,94,46).margin()), delay=1)
    click(B(681,215,172,154), delay=1, until=lambda: ui_T(T("升", box=Box(689,222,141,93).margin())))
    click(T("升", box=Box(689,222,141,93).margin()), delay=1, until=lambda: ui_T(T("法术灼烧", box=Box(392,80,127,34).margin())))
    click(T("法术灼烧", box=Box(392,80,127,34).margin()), delay=1)



if __name__ == "__main__":
    register_account_battle_flow()
    init()

    server_name = "十周年3服"
    username = "可莉一"
    supervisor_server_name = "兽神峰"
    supervisor_username = "可莉不知道哦"

    # logger.info("创号脚本开始执行")
    # init_role(username)    
    # logger.info("开始新手教程九重天")
    # start_newbie_tutorial() 
    # logger.info("开始打造兵器")
    # make_weapon()
    # logger.info("返回开始界面")
    # xiangui(server_name, username)
    # logger.info("开始称号系统")
    # chenghao(server_name, username)
    logger.info("赠送500人气")
    # renqi(server_name, username, supervisor_server_name, supervisor_username)
    logger.info("已经装备好称号")
    logger.info("开始天宫道1")
    # tiangongdao1()
    logger.info("合成教程")
    # hecheng()
    logger.info("漫长的任务关卡")
    # xinshoumubiao()
    logger.info("学习位移技能")
    # learnskills()
    # while ui_F(T("业力之道", box=Box(595,96,137,25).margin()),timeout=2):
    #     renwu() # 从天宫道到凌霄宝殿
    # yeli()
    
    # update_equipment()  # 应该从背包换

    # while ui_F(T("业力之道", box=Box(595,96,137,25).margin()),timeout=2):
    #     flag = renwu("突破土行孙") # 土行孙之前
    #     if not flag: break
    # click(B(1203,18,51,40), until=lambda: ui_T(T("经典任务", box=Box(266,403,168,45).margin())))
    # click(B(1204,21,47,42), until=lambda: ui_T(T("云中子", box=Box(696,261,75,28).margin())))
    # longgong1(45)
    # lingwu()
    # longgong1(50)
    # benmingshen()
    # huodong()
    # eat_drug("三倍")
    # longgong1(70, ensure_drug=True)
    # ensure_in("登录");sleep(4)
    # login(server_name=server_name, character_name=username)
    # equipment_juexing()
    # longgong1(75, ensure_drug=True)
    # renwu_special()
    huodong()
    longgong1(85, ensure_drug=True)
