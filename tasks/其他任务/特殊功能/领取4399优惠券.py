"""领取 4399 游戏盒里当前可领的优惠券。

操作的是游戏盒 App 而不是游戏本体，所以全程使用竖屏 720x1280 区域；区域显式声明
``frame_size``，不改共享进程的默认裁剪尺寸。
"""
from AutoScriptor import *
from ZmxyOL import *


GAMECENTER_PACKAGE = "com.m4399.gamecenter"
PORTRAIT_FRAME = MUMU_SIZE_720_1280


def portrait(box) -> Box:
    """竖屏 App 的区域：显式带帧尺寸，避免影响其他任务的坐标。

    返回裸 Box，给 ``T``/``I`` 的 ``box=`` 用；要当点击目标时再包一层 ``B(...)``。
    """
    return box.margin(frame_size=PORTRAIT_FRAME)


@register_task(
    description="打开 4399 游戏盒，领取我的优惠券",
    debug=True,
)
def task():
    """需要已保存游戏账号密码。全程只操作游戏盒，不进入游戏；结束会关闭游戏盒并回桌面。"""
    full_screen = Box(0, 0, *PORTRAIT_FRAME)

    close_app(GAMECENTER_PACKAGE)
    launch_app(GAMECENTER_PACKAGE)
    try:
        if ui_T(T("零流量", box=full_screen), timeout=5):
            # Box 是 namedtuple：直接传给 click 会被当成多目标元组，必须用 B() 包成区域目标。
            click(B(portrait(Box(522, 381, 43, 43))), if_exist=True, timeout=2)

        # 等到「我的钱包」出现为止，中途要关掉更新提示。必须有次数上限：
        # 输入通道失灵时页面永远不变，无上限的 while 会一直点下去而不报错。
        for _ in range(20):
            if ui_T((
                T("我的钱包", box=portrait(Box(42, 464, 84, 23))),
                T("点击登录", box=portrait(Box(133, 140, 157, 85))),
            )):
                break
            if ui_T(T("零流量更新", box=portrait(Box(308, 832, 105, 23)))):
                click(B(522, 381, 43, 40))
                sleep(1)
            click(B(646, 1234))
            sleep(1)
        else:
            raise RuntimeError(
                "等待游戏盒「我的」页超时：已点击底部「我的」20 次，「我的钱包」和「点击登录」都没出现。"
                "请确认游戏盒能正常打开、没有被弹窗挡住。"
            )

        if ui_T(T("点击登录", box=portrait(Box(133, 140, 157, 85))), timeout=2):
            click(B(portrait(Box(133, 140, 157, 85))))
            login(
                cfg["game"].get("account"),
                cfg["game"].get("password"),
                cfg["game"].get("character_name"),
                client=LoginClient.HZ4399,
            )

        click(B(615, 669))
        # 「我的」页改版后图标整体上移：模板在 258,585 上仍能逐像素命中（置信度 0.99），
        # 而原来写死的 258,664 只剩 0.19 的噪声。这里改用一条竖带，图标落在带内任一
        # 高度都算命中，改版再来一次也不用重截模板。
        click(I("我的优惠券", box=portrait(Box(238, 555, 70, 120))))
        click(T("我的优惠券", box=portrait(Box(549, 246, 130, 55))), if_exist=True, timeout=2)
        click(T("领取更多优惠券", box=portrait(Box(277, 1231, 166, 23))))

        # 券列表在两屏里，逐屏领完。领取按钮排成整行，不在固定的一条扫描线上：
        # 实测原来的 y=463 横带里一个「领取」都没有，循环空转两轮就报成功，券一张没领。
        # 改成搜整片券区（避开顶部活动图），并用计数上限兜住按钮不变化时的重复点击。
        coupon_area = portrait(Box(0, 700, 720, 580))
        for _ in range(2):
            claimed = 0
            while claimed < 12 and ui_T(T("领取", box=coupon_area), timeout=2):
                click(T("领取", box=coupon_area), timeout=2)
                click(T("关闭", box=portrait(Box(175, 799, 46, 25))), if_exist=True, timeout=2)
                claimed += 1
            swipe(B(360, 1150), B(360, 700), duration_s=1)
    finally:
        close_app(GAMECENTER_PACKAGE)
        go_home()
