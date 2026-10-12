"""领取 4399 游戏盒里当前可领的优惠券。

操作的是游戏盒 App 而不是游戏本体，所以全程使用竖屏 720x1280 区域；区域显式声明
``frame_size``，不改共享进程的默认裁剪尺寸。

点击/滑动强制走 ADB 通道：竖屏下 NemuIpc 注入点击无效（见 ``task()`` 内注释），
截图仍走 NemuIpc；任务结束后恢复默认通道。
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

    # 4399 游戏盒是竖屏 App，而 NemuIpc 注入在竖屏下点击无效：2026-10-10 实机对照，
    # 同一个 (646,1234)「我」标签，nemu 点击 20 次页面纹丝不动，切 ADB 点击一次即
    # 切换成功。整个任务因此强制走 ADB 点击/滑动；截图仍走 NemuIpc（与 ADB 无关）。
    # 结束后恢复默认通道，后续游戏任务不受影响。
    switch_base("mumu")
    try:
        close_app(GAMECENTER_PACKAGE)
        launch_app(GAMECENTER_PACKAGE)

        if ui_T(T("零流量", box=full_screen), timeout=5):
            # Box 是 namedtuple：直接传给 click 会被当成多目标元组，必须用 B() 包成区域目标。
            click(B(portrait(Box(522, 381, 43, 43))), if_exist=True, timeout=2)

        # 先等 App 真正加载完，再开始点「我的」。
        # 冷启动会先显示「4399游戏大全」闪屏（2026-10-06 实测持续 26 秒以上），这期间的
        # 点击全被闪屏吃掉。那次失败就是这样：20 次点击的预算整段花在闪屏上，首页刚出来
        # 就报「我的」页超时——看着像被弹窗挡住，其实是加载慢。
        # 顺带点掉开屏广告的「跳过」：每期活动都换广告，但跳过按钮固定在右上角。
        bottom_bar = portrait(Box(0, 1210, 720, 70))
        skip_button = portrait(Box(540, 20, 180, 90))
        for _ in range(45):
            if ui_T((
                T("首页", box=bottom_bar),
                T("找游戏", box=bottom_bar),
                T("福利", box=bottom_bar),
            )):
                break
            if ui_T(T("跳过", box=skip_button)):
                click(B(skip_button))
                sleep(1)
            sleep(1)
        else:
            raise RuntimeError(
                "4399 游戏盒 45 秒内没显示首页（底部「首页/找游戏/福利」标签都没出现），"
                "请确认游戏盒能正常启动。"
            )

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

        # 等「我的」页图标出现再点：登录刚完成时页面还在刷新，盲点会落到旧版式的位置上。
        # 「我的」页 2026-09 改版后图标整体上移：模板在 258,585 上仍能逐像素命中（置信度
        # 0.99），而原来写死的 258,664 只剩 0.19 的噪声。这里用一条竖带，图标落在带内任一
        # 高度都算命中，改版再来一次也不用重截模板。
        wait_for_appear(I("我的优惠券", box=portrait(Box(238, 555, 70, 120))), timeout=10)
        click(I("我的优惠券", box=portrait(Box(238, 555, 70, 120))))
        # 等优惠券页真正就绪（底部「领取更多优惠券」出现）再点：该按钮紧贴屏幕底边，
        # OCR 框在两帧之间会轻微抖动，默认的 assure_stable 会一直等不到稳定结果而超时；
        # 在页面切换动画里盲点，也容易点到别的入口（2026-10-10 实机：盲点后页面跑去了
        # 「活动中心」，30 秒后报「领取更多优惠券」定位失败）。
        wait_for_appear(T("领取更多优惠券", box=portrait(Box(277, 1231, 166, 23))), timeout=15)
        click(T("领取更多优惠券", box=portrait(Box(277, 1231, 166, 23))), assure_stable=False)

        # 券列表在两屏里，逐屏领完。
        # 这一页状态变化很多：卡片会从「领取」变成「去使用」、点完会弹提示框、
        # 右缘还有只露出半截的按钮；而且 T() 是子串匹配，「领取」还会命中
        # 「领取更多优惠券」。所以不用「定位一个 → 点一个 → 再定位」的串行写法：
        # 页面一动，第二次定位就卡在稳定性重试里等到超时直接抛错（2026-10-10 实机
        # 失败就是 ui_T 通过后 click 等不到稳定帧）。改成每轮用 click_all 在一帧
        # 冻结结果上把当前屏所有「领取」一次点完，点完统一关提示框，再找下一批。
        coupon_area = portrait(Box(0, 700, 720, 580))
        claim_button = T("领取", box=coupon_area)
        popup_close = T("关闭", box=portrait(Box(175, 799, 46, 25)))
        claimed = 0
        for _ in range(2):
            for _ in range(4):
                # 先清掉上一批的领取结果提示框，它们会挡住卡片。
                for _ in range(3):
                    if not ui_T(popup_close, timeout=1):
                        break
                    click(popup_close, timeout=1, assure_stable=False)
                    sleep(0.5)
                clicked_count = click_all(
                    claim_button,
                    if_exist=True,
                    timeout=2,
                    assure_stable=False,
                    interval=0.6,   # 逐个点开，别把「领取」当连点器用
                )
                if clicked_count == 0:
                    break
                claimed += clicked_count
                sleep(1)   # 等提示框弹出，下一轮关闭
            swipe(B(360, 1150), B(360, 700), duration_s=1)
            sleep(1)
        logger.info("本轮共点击「领取」%d 次" + ("（没有可领的券，可能今天已领完）" if claimed == 0 else ""), claimed)
    finally:
        close_app(GAMECENTER_PACKAGE)
        go_home()
        switch_base("nemu")
