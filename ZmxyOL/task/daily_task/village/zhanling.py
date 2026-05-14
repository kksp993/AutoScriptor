import traceback
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger

@register_task(next_exec_offset_hours=10)
def task():
    ensure_in("村庄")
    click((I("导航-战令"),T("战令", box=Box(37,237,870,106).margin())))   # 概率失败 （T仅0.75缩放可成）
    if ui_T(T("请添加", box=Box(926,507,136,79).margin())):
        click(B(980,394,34,34))
        click(T("选择", box=Box(759,419,140,83).margin()))
        click(T("开启战令", box=Box(920,557,153,58).margin()));sleep(1)
        click(B(317,277,67,52))
    wait_for_appear(T("购买等级"))
    click(B(105,244,34,124))
    sleep(1)
    while ui_T(T("完成",color="绿色")):
        click(T("完成",color="绿色"),if_exist=True)
        sleep(0.5)
    click(B(1200,30,30,30))



if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)

