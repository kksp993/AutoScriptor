from timeit import timeit
from turtle import color
from AutoScriptor import *
from AutoScriptor.utils import box
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
        init()
        # print(timeit(lambda: print(locate((I("悬浮窗-上",color="绿色"),I("悬浮窗-下",color="绿色"),I("悬浮窗-左",color="绿色"),I("悬浮窗-右",color="绿色")),timeout=1)), number=1))
        # print(timeit(lambda: print(locate((I("悬浮窗-上")),timeout=1)), number=1))
        print(timeit(lambda: print(click((T("登录", color="绿色")),timeout=1)), number=1))
        # print(timeit(lambda: print(locate((I("悬浮窗-下")),timeout=1)), number=1))
        # print(timeit(lambda: print(locate((I("悬浮窗-左")),timeout=1)), number=1))
        # print(timeit(lambda: print(locate((I("悬浮窗-右")),timeout=1)), number=1))
        # close_targets = [
        #     (I("极北之地-取消"), I("极北之地-取消")),
        #     (I("x"), I("x")),
        #     (I("x-in"), B(1061,178,39,47)),
        #     (I("菜单-宠物"), head -n 3 B(10,10)),
        #     (T("回家", box=Box(29,613,77,88).margin()), T("回家", box=Box(29,613,77,88).margin())),
        #     (T("确认"), T("确认")),
        #     (T("返回地图"), T("返回地图")),
        #     (T("返回大厅"), T("返回大厅")),
        #     (T("我的队伍"), B(1050,50,30,30)),
        #     (I("进入游戏中"), I("进入游戏中")),
        #     (T("进入游戏"), T("进入游戏")),
        # ]
        # tgts = tuple(target for target, _ in close_targets)
        # print(timeit(lambda: print(ui_idx(tgts)), number=1))

    except Exception as e:
        traceback.print_exc()
    finally:
        # bg.stop()
        exit(0)

