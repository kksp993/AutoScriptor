from AutoScriptor import *
from ZmxyOL.nav import *

if __name__ == "__main__":
    # print(locate(T("村庄",box=Box(964,542,94,120))))

    # print(get_colors(T("进入游戏")))
    # print(locate((T("极光天诏"),T("背景")),10))
    # print(locate(I("极北-关卡奖励")))
    # print(locate((T(key="战斗-离开关卡"), I(key="倍战"), I(key="返回地图"))))
    bg.add(
        name="战斗结束",
        identifier=(T(key="战斗-离开关卡"), I(key="倍战"), I(key="返回地图")),
        callback=lambda: [
            logger.info("战斗结束"),
            bg.set_signal("try_exit", True),
            bg.clear()
        ]
    )
    while not bg.signal("try_exit", False):
        logger.info("战斗结束,尚未触发")
        sleep(1)
    bg.stop()
