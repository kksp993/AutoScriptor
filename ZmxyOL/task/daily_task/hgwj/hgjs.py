import traceback

from ZmxyOL.nav.api import locate_region
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.battle.character.hero import h

@register_task
def task():
    ensure_in("荒古万界")
    click(T("万界穿梭"));sleep(1)
    click(T("荒古巨兽"),until=lambda: ui_T(T("荒古秘术")))
    if ui_T(T("荒古灵机")):
        click(B(175,285), repeat=3)
    click(B(1000,30))
    click(B(30,30,30,30),until=lambda: ui_T(T("荒古万界"),I("导航-菜单")))
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
