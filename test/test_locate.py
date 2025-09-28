from timeit import timeit
from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

if __name__ == "__main__":
    # print(locate(T("村庄",box=Box(964,542,94,120))))
    # print(get_colors(T("进入游戏")))
    # print(locate((T("极光天诏"),T("背景")),10))
    # print(locate(I("极北-关卡奖励")))
    # print(locate((T(key="战斗-离开关卡"), I(key="倍战"), I(key="返回地图"))))
    # print(locate((T(key="战斗-离开关卡"), I(key="倍战"), I(key="返回地图"))))
    # print(locate(T("同意并登录",color="青色", box=Box(160,707,442,95))))
    # print(locate(T("仙盟",box=Box(16,30,924,400)), timeout=10, assure_stable=True))
    try:
        # print(timeit(lambda: print(locate(I("导航-寻宝"))), number=1))
        # print(timeit(lambda: print(locate(I("小小木绝"))), number=1))
        # print(timeit(lambda: print(locate(T("天魔禁忌",box=Box(732,342,77,27)))), number=1))
        # print(timeit(lambda: print(locate(T("挑战",box=Box(920,475,300,200)))), number=1))
        # print(timeit(lambda: print(locate(I("梵天塔-天魔挑战"))), number=1))
        print(timeit(lambda: print(locate(T("前往新一层"))), number=1))
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)

