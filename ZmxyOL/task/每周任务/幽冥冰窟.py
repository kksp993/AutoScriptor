import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *

def Shield_handle_bk():
    """默认4号位藤蔓，2-3号位无位移技能"""
    """处理3/6/9波次盾怪"""
    h.prop(fb=False)
    h.skill(4)
def Normal_handle_bk():
    """默认4号位藤蔓，2-3号位无位移技能"""
    h.prop()
    h.skill(2)
    h.skill(3)
def Boss_handle_bk():
    """默认4号位藤蔓，2-3号位无位移技能"""
    h.prop()
    h.skill(2)
    h.skill(1)
    sleep(0.1)
    h.jump()
    h.skill(6)
    h.skill(3)
    sleep(0.05)
def bingku_battle():
    """默认4号位藤蔓，2-3号位无位移技能"""
    bg.clear_signals()
    wait_for_appear(T("特性说明", box=Box(576,159,127,33)))
    click(B(1000,450,10,10),repeat=3)
    sleep(3.5)
    switch_base("nemu")
    for i in range(5):
        h.move_right(110, directly=True) 
    sleep(0.1)
    h.huashen()
    while not (bg.signal("Failed",False) or bg.signal("Exit",False)):
        Wave = extract_info(B(652,85,82,54), lambda x: int(x.strip().split("/")[0]), ensure_not_empty=False)
        if Wave:
            if Wave==12:
                Boss_handle_bk()
            elif Wave%3==0:
                Shield_handle_bk()
            else:
                Normal_handle_bk()
            click(T("确定"),if_exist=True)
        else:
            if ui_T(T("下一轮")): bg.set_signal("Exit",True)
            if ui_T(T("重新挑战")): bg.set_signal("Failed",True)
    switch_base("mumu")

@register_task
def task():
    ensure_in("幽冥冰窟")

    h.set(True,1)
    while ui_F(T("重新挑战")):
        if ui_T(T("下一轮")):
            click(T("下一轮"),delay=1)
        else:
            click(B(363,219,125,195),delay=0.5),
            click(T("确定"), delay=0.5)
        bingku_battle()
    click(T("返回主界面"))



if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)










