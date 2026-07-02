from ZmxyOL import *
from AutoScriptor import *

@register_task(
    path_cn="每日任务/村庄/战令领取",
    description="每隔一段时间领取可完成的战令任务奖励。",
    task_doc="每隔一段时间完成战令任务（仅领取不帮助完成）。",
    default_offset_hours=10,
)
def task():
    ensure_in("村庄")
    click((I("导航-战令"),T("战令", box=Box(37,237,870,106).margin())))   # 概率失败 （T仅0.75缩放可成）
    wait_for_appear((T("购买等级"), T("请添加", box=Box(926,507,136,79).margin())))
    if ui_T(T("请添加", box=Box(926,507,136,79).margin())):
        click(B(980,394,34,34))
        click(T("选择", box=Box(759,419,140,83).margin()))
        click(T("开启战令", box=Box(920,557,153,58).margin()));sleep(1)
        click(B(317,277,67,52))
    click(B(105,244,34,124))
    sleep(1)
    while ui_T(T("完成",color="绿色")):
        click(T("完成",color="绿色"),if_exist=True)
        sleep(0.5)
    click(B(1200,30,30,30))
