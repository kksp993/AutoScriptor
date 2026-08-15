from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger

def buy_item(item_name: str):
    box = locate(T(item_name),timeout=10)
    if box is None: return
    if first(get_colors(T("购买", box=box + {"offset": (0, 240)}))) == "绿色":
        click(B(box),offset=(0,240),delay=0.5)
        sleep(4)

@register_task(
    path_cn="每日任务/村庄/活跃券",
    description="通过荣耀商店购置并使用活跃福利券。",
    task_doc="通过荣耀商店购置活跃券。【bug】活跃券使用可能有异常，建议自行确认是否使用成功。",
)
def task():
    logger.info("====活跃券====")
    ensure_in(["村庄"])
    click(I("导航-菜单")); sleep(1)
    if ui_F(I("菜单-荣誉勋章")): click(I("导航-菜单")); sleep(1)
    click(I("菜单-荣誉勋章"))
    click(T("荣誉商店", box=Box(200,545,203,76).margin()))
    buy_item("至尊成长礼包")
    switch_base("nemu")
    for i in range(3):
        swipe(B(600,450,10,10), B(600,100,10,10), duration_s=1, ensure_stable_after_swipe=False)
    sleep(1)
    buy_item("活跃福利券")
    click(B(1200,30,30,30))
    sleep(1)
    click(B(1200,30,30,30))
    click(B(1200,30,30,30))
    click(B(1200,30,30,30))
    ensure_in(["背包"])
    from ZmxyOL.battle.utils import BAG,find_in_bag
    find_in_bag(BAG.BAG,"活跃福利券")
    click(I("活跃券"), if_exist=True, delay=0.5, timeout=3)
    sleep(1)
    click(T("使用",color="红色"), if_exist=True, delay=0.5, timeout=2)
    sleep(3)
    ensure_in(LOC_ENV)

