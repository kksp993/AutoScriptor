from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from AutoScriptor import *
from ZmxyOL import *
from base import EventTaskBase

class ChengZhangHuoDong(EventTaskBase):
    def __init__(self):
        super().__init__("成长活动", T("成长活动", box=Box(220,90,834,127).margin()))

    def do_task(self):
        click(T("开服冲级迎大礼", box=Box(203,269,250,66).margin()))
        for _ in range(10):
            click_all(T("领取", box=Box(879,302,190,367).margin()), if_exist=True)
            swipe(B(845,590), B(847,300), duration_s=1)
        click(T("冲战力赢奖励", box=Box(187,339,238,87).margin()))
        for _ in range(6):
            click_all(T("领取", box=Box(879,302,190,367).margin()), if_exist=True)
            swipe(B(845,590), B(847,300), duration_s=1)
        click(T("飞升奖励", box=Box(214,446,203,70).margin()))
        for _ in range(2):
            click_all(T("领取", box=Box(879,302,190,367).margin()), if_exist=True)
            swipe(B(845,590), B(847,300), duration_s=1)



if __name__ == "__main__":
    init()
    ChengZhangHuoDong().run()
