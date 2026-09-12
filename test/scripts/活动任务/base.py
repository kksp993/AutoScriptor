from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from AutoScriptor import *
from ZmxyOL import *


class EventTaskBase:
    def __init__(self, name:str, target:Target):
        self.name = name
        self.target = target

    def ensure_in(self,):
        """进入活动界面，滑动页面直到找到目标"""
        ensure_in("村庄")
        while ui_F(T("仙盟",box=Box(16,30,130,400)), 3):
            click(I("导航-按钮收缩"))
            if ui_T(T("精彩活动"), 2): click(B(1100, 40, 40, 40))
            sleep(2)
        click(T("活动", box=Box(255,127,103,101).margin()))
        for _ in range(10):
            if ui_T(self.target): break
            swipe(B(989,170), B(345,160), duration_s=1)
        sleep(1)
        click(self.target)
        logger.info(f"找到目标: {self.target}")

    def run(self, *args, **kwargs):
        self.ensure_in()
        logger.info(f"开始执行任务: {self.name}");sleep(1)
        try:
            self.do_task(*args, **kwargs)
            logger.info(f"任务完成: {self.name}");sleep(1)
        finally:
            self.exit()

    def do_task(self, *args, **kwargs):
        pass

    def exit(self):
        logger.info(f"{self.name} 流程结束，退出活动界面。")
        click(B(1092,25,44,48))
