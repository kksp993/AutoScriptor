
from AutoScriptor.control.MumuAdaptor.constant import AndroidKey
from ZmxyOL.nav.api import ensure_in
from ZmxyOL.nav.envs.decorators import HAS_SHEZHI
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *


@register_task(
    path_cn="自定义任务/背包清空/进阶仙宝",
    description="一键吞噬仙宝，以清空背包",
    task_doc=(
        "【特别注意】：这个过程会吃掉所有B/C级仙宝，此外确保您已经解锁了法相功能"
    ),
)
def test_task(xianbao_idx=1):
    ensure_in("法相")
    click(T("法宝", box=Box(39,214,132,89).margin()));sleep(1)
    tbs=[B(212,646,84,29),B(311,644,84,33),B(410,644,85,33),B(515,640,84,37)]
    click(tbs[xianbao_idx])
    click(T("进阶",box=Box(0,655,720,65)))
    for _ in range(4):
        click(T("批量进阶", box=Box(886,582,152,62).margin()))
        click(T("选择全部", box=Box(578,582,174,62).margin()))
        click(T("确定进阶", box=Box(269,574,240,89).margin()));sleep(2)
        click(B(71,261))
        click(T("取消选择", box=Box(889,576,147,60).margin()))
    click(B(1204,21,47,42),until=lambda:ui_T(T("菜单", box=Box(1151,33,107,83).margin())),interval=1)
    sleep(1)
    click(B(1151,33,107,83))   # type: ignore