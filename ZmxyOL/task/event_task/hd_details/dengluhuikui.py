from AutoScriptor import *
from ZmxyOL import *

from ZmxyOL.task.event_task.hd_registry import hd_task

@hd_task(identifier=T("登陆回馈"))
def task():
    click(I("导航-活动"))
    wait_for_appear(T("签到奖励"))
    
