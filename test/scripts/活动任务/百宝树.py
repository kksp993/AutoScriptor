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
        super().__init__("百宝树", T("百宝树", box=Box(220,90,834,127).margin()))

    def do_task(self):
        swipe(B(713,600), B(713,286), duration_s=1)
        swipe(B(734,618), B(734,305), duration_s=1)
        click(T("宝树任务", box=Box(796,362,216,55).margin()))
        for _ in range(3):
            click_all(T("领取", box=Box(909,418,119,216).margin()), if_exist=True)
            swipe(B(845,590), B(847,300), duration_s=1)
        
        click(B(464,272,48,52));sleep(1)
        swipe(B(713,600), B(713,286), duration_s=1)
        swipe(B(734,618), B(734,305), duration_s=1)
        click(T("宝树护理", box=Box(796,427,215,58).margin()))
        swipe(B(713,600), B(713,286), duration_s=1)
        swipe(B(734,618), B(734,305), duration_s=1)

        box = locate(T("当前异常状态"))
        if not box: return logger.warning("当前尚未种植宝树！")
        info = extract_info(box+(80,0), post_process=lambda s: s.replace("：",":").split(":")[1].strip(), ensure_not_empty=True, mode="text")
        click(T("确认", box=box+(Box(929,521,85,50)-Box(555,543,137,29))))
        click(T("确定", box=Box(658,374,144,84).margin()))
        if ui_T(T("数量不足", box=Box(617,322,236,83).margin())):
            self.way_to_open(info)

if __name__ == "__main__":
    print()