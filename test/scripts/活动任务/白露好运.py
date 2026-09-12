from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from AutoScriptor import *
from ZmxyOL import *
from base import EventTaskBase

class BaiLuHaoYun(EventTaskBase):
    def __init__(self):
        super().__init__("白露好运", T("白露好运", box=Box(220,90,834,127).margin()))

    def do_task(self):
        swipe(B(713,600), B(713,286), duration_s=1)
        swipe(B(734,618), B(734,305), duration_s=1)
        click(T("白露任务", box=Box(493,427,215,58).margin()))
        for _ in range(3):
            click_all(T("领取", box=Box(909,418,119,216).margin()), if_exist=True)
            swipe(B(845,590), B(847,300), duration_s=1)


if __name__ == "__main__":
    init()
    BaiLuHaoYun().run()
