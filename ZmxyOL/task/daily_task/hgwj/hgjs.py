from calendar import weekday
import datetime
import traceback

from logzero import logger

from ZmxyOL.nav.api import locate_region
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.battle.character.hero import h
def get_week_number():
    today = datetime.date.today()
    epoch = datetime.date(1, 1, 1)
    delta_days = (today - epoch).days
    week_number = delta_days // 7 + 1  # 第一周是1
    return week_number

def get_weekday_number():
    today = datetime.date.today()
    weekday_num = today.weekday() + 1 # Monday is 1, Sunday is 7
    return weekday_num


@register_task
def task():
    if not(get_week_number() %2 == 0 and get_weekday_number() <= 4):
        logger.info(f"今天不是双周的周一至周四，不进行荒古巨兽奖励领取挑战")
        return 
    ensure_in("荒古万界")
    click(T("万界穿梭"));sleep(1)
    click(T("荒古巨兽"),until=lambda: ui_T(T("荒古秘术")))
    if ui_T(T("荒古灵机")):
        click(B(175,285), repeat=3)
    click(B(1000,30))
    click(B(30,30,30,30),until=lambda: ui_T((T("荒古万界"),I("导航-菜单"),T("世界地图"))))
    click(B(1200,30,30,30))
    locate_region()


if __name__ == "__main__":
    try:
        task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
