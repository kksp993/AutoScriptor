"""领取 4399 游戏盒里当前可领的优惠券。

操作的是游戏盒 App 而不是游戏本体，所以全程使用竖屏 720x1280 区域；区域显式声明
``frame_size``，不改共享进程的默认裁剪尺寸。
"""
from AutoScriptor import *
from ZmxyOL import *


GAMECENTER_PACKAGE = "com.m4399.gamecenter"
PORTRAIT_FRAME = MUMU_SIZE_720_1280


def portrait(box) -> Box:
    """竖屏 App 的区域：显式带帧尺寸，避免影响其他任务的坐标。"""
    return box.margin(frame_size=PORTRAIT_FRAME)


@register_task(
    description="打开 4399 游戏盒，领取我的优惠券",
    task_doc="需要已保存游戏账号密码。全程只操作游戏盒，不进入游戏；结束会关闭游戏盒并回桌面。",
    debug_mode=True,
)
def task():
    full_screen = Box(0, 0, *PORTRAIT_FRAME)

    close_app(GAMECENTER_PACKAGE)
    launch_app(GAMECENTER_PACKAGE)
    try:
        if ui_T(T("零流量", box=full_screen), timeout=5):
            click(portrait(Box(522, 381, 43, 43)), if_exist=True, timeout=2)

        # 等到「我的钱包」出现为止，中途要关掉更新提示
        while ui_F((
            T("我的钱包", box=portrait(Box(42, 464, 84, 23))),
            T("点击登录", box=portrait(Box(133, 140, 157, 85))),
        )):
            if ui_T(T("零流量更新", box=portrait(Box(308, 832, 105, 23)))):
                click(B(522, 381, 43, 40))
                sleep(1)
            click(B(646, 1234))
            sleep(1)

        if ui_T(T("点击登录", box=portrait(Box(133, 140, 157, 85))), timeout=2):
            click(portrait(Box(133, 140, 157, 85)))
            login(
                cfg["game"].get("account"),
                cfg["game"].get("password"),
                cfg["game"].get("character_name"),
                client=LoginClient.HZ4399,
            )

        click(B(615, 669))
        click(I("我的优惠券", box=portrait(Box(258, 664, 30, 35))))
        click(T("我的优惠券", box=portrait(Box(549, 246, 130, 55))), if_exist=True, timeout=2)
        click(T("领取更多优惠券", box=portrait(Box(277, 1231, 166, 23))))

        # 券列表在两屏里，逐屏领完
        for _ in range(2):
            while ui_T(T("领取", box=portrait(Box(0, 463, 720, 38))), timeout=2):
                click(T("领取", box=portrait(Box(0, 463, 720, 38))), timeout=2)
                click(T("关闭", box=portrait(Box(175, 799, 46, 25))), timeout=2)
            swipe(B(550, 393), B(402, 396), duration_s=1)
    finally:
        close_app(GAMECENTER_PACKAGE)
        go_home()
