from ZmxyOL.nav.api import locate_region
from ZmxyOL.nav.envs.decorators import HAS_SHEZHI
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.battle_character.hero import h


@register_task(
    path_cn="每日任务/本命空间/本命空间",
    description="完成本命空间每日流程，领取任务奖励，合成本命法宝。",
)
def task(clear_all=False, lianbao=False):
    ensure_in(HAS_SHEZHI)
    while ui_F(T("仙盟",box=Box(16,30,924,400)), 3):
        click(I("导航-按钮收缩"))
        sleep(4)
    click(T("本命空间", box=Box(25,15,882,328).margin()))
    wait_for_appear(T("升级"))
    click(T("空间任务"))
    click(B(860,250,60,60),repeat=3)
    click(B(300,100))
    if clear_all and (tgt:=locate(T("一键完成",box=Box(579,591,136,55),color="绿色"), timeout=3)):
        click(B(*tgt))
        sleep(2)
        click(T("确定"), until=lambda: ui_F(T("确定")))
        sleep(1)
    click(B(1200,30,30,30))
    if lianbao:
        click(T("本命法宝"))
        tgt = wait_for_appear(T("炼宝", box=Box(580,610,130,85)))
        click(B(795,545,30,30))
        click(B(*tgt))
        sleep(2)
        click(T("确定"), if_exist=True)
    # TODO: 这里有概率 T("空间任务") 检测不到，看看跳到哪个界面了优化下
    click(B(50,30,30,30),until=lambda: ui_T(T("空间任务")))
    click(T("回家"))
    locate_region()
