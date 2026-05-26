from AutoScriptor import *
from ZmxyOL.battle.character.hero import *



@combo
def battle_task(
    self,
    has_loading_after_battle:bool=True, 
    exit_loc:float=0, 
    crash_suddenly:bool=False, 
    bonus_x:int=0,
    cancel_on_failed:bool=True,
    flow_name: str | None = None,
):
    bg.clear_signals()
    wait_for_disappear((I("加载中"), I("极北-加载中")))
    switch_base("nemu")
    with bg.scope("天庭通用战斗") as scope:
        scope.add(
            name="战斗结束",
            identifier=(T(key="战斗-离开关卡"), T("倍战"), I(key="返回地图")),
            callback=lambda: [
                logger.info("战斗结束"),
                bg.set_signal("try_exit", True),
            ]
        )

        def battle_fail_callback():
            # 必须先 set try_exit，再执行耗时 click；否则 battle_loop 在点「取消」整段期间仍在战斗
            switch_base("mumu")
            logger.info("战斗失败")
            bg.set_signal("Failed", True)
            if cancel_on_failed:
                bg.set_signal("try_exit", True)
                bg.set_signal("bonus_x", 0)
                bg.set_signal("failed", True)
                switch_base("mumu")
                click(T("取消"), delay=4, repeat=3)
            else:
                switch_base("mumu")
                click(T("确定"), delay=4, repeat=3)

        scope.add(
            name="战斗失败",
            identifier=((T("198点券"), T("159点券"), T("复活"), T("取消"))),
            callback=battle_fail_callback,
        )
        sleep(0.5)
        # 战斗结束不执行
        if flow_name is None:
            flow_name = getattr(self, "task_context_battle_flow", None) or "战斗循环"
        self.battle_loop(flow_name=flow_name)
    # bonus=0 不执行
    if bg.signal("bonus_x", bonus_x) > 1:
        _ = 0
        while _ < bg.signal("bonus_x", bonus_x) or ui_T(I("极北-关卡奖励")):
            _ += 1
            click(I("极北-关卡奖励"), delay=1)
            sleep(1)
            click(T("确定"))
        click(B(1050, 60, 10, 10))
    switch_base("mumu")
    # 失败不执行
    if not bg.signal("failed", False):
        if not crash_suddenly:
            self.travel()
            logger.info("到达最右侧")
            switch_base("nemu")
            if not has_loading_after_battle:
                _home = T("回家", box=Box(29, 613, 77, 88).margin())
                self.way_to_exit(until=_home, exit_loc=exit_loc)
            else:
                self.way_to_exit(until=(I("加载中"), I("极北-加载中"), T("还有")), exit_loc=exit_loc)
        else:
            wait_for_appear((I("返回地图"), T("回家", box=Box(29,613,77,88).margin())))
            if ui_T((I("返回地图"),T("返回地图"))): click((I("返回地图"),T("返回地图")), until=lambda:ui_F((I("返回地图"),T("返回地图"))))
    wait_for_appear(T("回家", box=Box(29,613,77,88).margin()))
    switch_base("mumu")

@combo
def heaven_draw_card_exit(self:Hero):
    """抽牌后直到返回地图/队伍界面"""
    click(T("抽牌",box=Box(514,513,253,97)), until=lambda:ui_F(T("抽牌",box=Box(514,513,253,97))))
    sleep(3)
    click(B(Box(182,232,904,102)),repeat=3)
    sleep(1)
    click(B(Box(10,10,0,0)))
    click(T("返回"),repeat=2)
    wait_for_appear((T("我的队伍"), T("回家", box=Box(29,613,77,88).margin())))



@combo
def heaven_battle(
    self,
    exit_loc:float=100,
    flow_name: str | None = None,
):
    """天庭战斗"""
    try:
        with bg.scope("天庭战斗") as scope:
            scope.add(
                name="战斗结束",
                identifier=I("战斗结束"),
                callback=lambda: [
                    bg.set_signal("Pause_battle", True),
                    logger.info("检测到战斗结束"),
                    self.way_to_exit(until=(T("抽牌", box=Box(514,513,253,97)), T("还有")), exit_loc=exit_loc),
                    self.heaven_draw_card_exit(),
                    switch_base("mumu"),
                    bg.set_signal("try_exit", True),
                    sleep(4),
                ]
            )
            scope.add(
                name="稍后",
                identifier=(I("稍后"),T("稍后")),
                callback=lambda: [
                    click((I("稍后"),T("稍后")), delay=0, repeat=3, timeout=5, if_exist=True)
                ],
                once=False
            )
            if flow_name is None:
                flow_name = getattr(self, "task_context_battle_flow", None) or "战斗循环"
            self.battle_loop(flow_name=flow_name, battle_weight=2, delay=2)
    finally:
        bg.set_signal("try_exit", False)
        bg.set_signal("Pause_battle", False)

@combo
def task(self, task_name:str):
    from ZmxyOL.battle.tasks import get_task_table
    from ZmxyOL.nav.api import ensure_in
    from ZmxyOL.battle.character.hero import h
    ensure_in(*get_task_table(task_name)["location"])
    logger.info(f"===={task_name}====")
    box = Box(174,253+100*get_task_table(task_name)["idx"],930,75)
    click(get_task_table(task_name)["target"], until=lambda:ui_T(T("每日1次",box=box)))
    if ui_F(T("0次",box=box)):
        if ui_F(T("开始挑战")):
            click(B(box),delay=1)
        click(T("开始挑战"))
        h.set(True,3).battle_task(has_loading_after_battle=False, exit_loc=get_task_table(task_name)["exit_loc"])
    else: click(B(1200,30,30,30))
    sleep(2)
    # # 增加稳定性，防止战斗结束后，没有返回地图
    # ensure_in(*get_task_table(task_name)["location"])
