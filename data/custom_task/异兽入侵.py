from AutoScriptor import *
from ZmxyOL.nav.api import *
from ZmxyOL.nav.envs.decorators import *
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
@register_task(
    path_cn='自定义任务/编辑器保存/异兽入侵',
    description='从编辑器保存的自定义脚本',
    task_doc='',
)
def task():
    ensure_in("荒古万界")
    click(T("万界穿梭"));sleep(1)
    click(T("异兽入侵", box=Box(192,656,111,53).margin()))
    wait_for_appear(T("异兽入侵", box=Box(533,23,214,55).margin()))
    click(T("荒古·邪·相柳", box=Box(362,222,224,308).margin()));sleep(1)
    for i in range(7):
        click(B(525,137,258,455));sleep(0.2)
    click(T("前往阻击", box=Box(952,524,222,108).margin()))
    wait_for_disappear(I("加载中"))
    while not ui_T(T("阻击成功", box=Box(488,138,306,100).margin())):
        h.skill(6)
    click(T("确认", box=Box(540,545,199,58).margin()))
    wait_for_disappear(I("加载中"))
    click(B(869,601,49,51));sleep(0.2)
    click(B(1032,605,41,47));sleep(0.2)
    click(B(1187,601,49,48));sleep(0.2)
    click(B(19,19,52,52));sleep(0.2)
    click(B(19,19,52,52));sleep(0.2)
