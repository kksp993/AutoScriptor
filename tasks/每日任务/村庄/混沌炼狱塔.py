from datetime import datetime
from AutoScriptor import *
from ZmxyOL.nav import *
from ZmxyOL import register_task

from tasks.time import next_Mon, next_month


# ── 妖魄商铺的几何（2026-10-07 在 1280x720 实机上量）──
#
# 每张卡片自上而下是：商品名 → 图标(x数量) → 兑换次数 x/y → 价格按钮。
# 价格按钮既是「本期还有没有额度」的指示（粉红=可买、灰=已兑完），也是购买入口，
# 所以整段逻辑按按钮工作，不再「拿商品名盒子加一个固定偏移去猜价格框」——那个偏移
# 只在列表顶行成立，商品名落到下面几行时价格框会跑到屏幕外，整件商品被静默跳过。
BUY_BUTTON_LEFTS = (503, 687, 872)          # 三列价格按钮的左边界
BUY_BUTTON_SIZE = (135, 50)
NAME_TO_BUTTON_CENTER_DY = 230              # 商品名中心 → 价格按钮中心
SHOP_NAME_AREA = Box(380, 170, 660, 420)    # 商品名可能出现的位置（三列网格）
SHOP_CONTENT_BOTTOM = 590                   # 内容区下沿：按钮底边超过它就是没完整显示
# 余额框。原来只有 82px 宽，330000 会被读成 33000，「买得起」判断跟着一起错。
BALANCE_BOX = Box(580, 138, 200, 30)
# 一次滚动一步，用 swipe_precise 而不是 swipe：swipe 的轨迹带随机偏移、松手还有惯性，
# 实测同样一次滑动位移在 159~376px 之间跳（远超「可买带」约 150px），商品会被整件跳过。
# swipe_precise 走固定直线，实测拖 120px 位移约 107px，稳定落在带内。
SHOP_SCROLL_STEP_PX = 120
SHOP_SCROLL_DURATION_S = 0.8


def _positive_int(text):
    """OCR 文本转正整数；夹带别的字符就当作没读到，宁可不买也不猜错价格。"""
    raw = str(text or "").strip().replace(",", "")
    return int(raw) if raw.isdigit() else None


def _price_button_of(name_box) -> Box:
    """商品名所在卡片的价格按钮。

    列由名称中心 x 就近判定：名称在卡片里居中，中心 x 稳定；名称长短只改变左右边界。
    原来的判定用的是「中心 x + 45」再去比阈值，第 1 列会落进第 2 列的区间，于是
    列 1 的商品读到了列 2 的价格，取舍整个反掉。
    """
    center_x, center_y = name_box.center()
    column_left = min(
        BUY_BUTTON_LEFTS,
        key=lambda left: abs(left + BUY_BUTTON_SIZE[0] // 2 - center_x),
    )
    top = center_y + NAME_TO_BUTTON_CENTER_DY - BUY_BUTTON_SIZE[1] // 2
    return Box(column_left, top, *BUY_BUTTON_SIZE)


def _has_redeem_quota(button: Box) -> bool:
    """粉红 = 本期还有兑换额度；灰色 = 已兑完。"""
    colors = get_colors([B(*button)])
    return bool(colors) and bool(colors[0]) and "红色" in (colors[0][0] or "")


def _buy_shop_items() -> int:
    """把列表里能买的功绩 / 6级灵玉 / 化身·封魂仙符买掉，返回购买次数。

    列表一屏只显示一张半卡片，不能「看一眼就开始买」：商品名落在下半屏时，它的价格
    按钮在屏幕外，读不到价格也点不到。改成小步下滚 + 每步重判，让每件商品都经过
    「名称在上、按钮完整可见」的位置，路过时买掉，额度没买完的下一轮接着买。
    """
    # 回到列表顶部，之后只往下滚。走到头再回来是常态：列表约 8 行、一屏只看得到 2 行。
    for _ in range(14):
        swipe_precise(
            B(700, 250), B(700, 520),
            duration_s=SHOP_SCROLL_DURATION_S, ensure_stable_after_swipe=False,
        )
        sleep(0.35)
    sleep(0.5)

    bought = 0
    idle_scrolls = 0
    for _ in range(80):
        found = locate([
            T("功绩", box=SHOP_NAME_AREA),
            T("6级灵玉", box=SHOP_NAME_AREA),
            T("化身·封魂仙符", box=SHOP_NAME_AREA),
        ], is_simplify=False)
        names = [B(*hit) for group in found if group for hit in group]

        balance = extract_info(
            BALANCE_BOX, post_process=_positive_int,
            ensure_not_empty=True, save_screenshot=False,
        )
        affordable = []
        for name in names:
            button = _price_button_of(name.box)
            if button.top + button.height > SHOP_CONTENT_BOTTOM:
                continue                 # 按钮没完整显示，等它滚上来再判
            if not _has_redeem_quota(button):
                continue                 # 灰按钮 = 本期额度已用完
            price = extract_info(B(*button), post_process=_positive_int, save_screenshot=False)
            if price is None:
                logger.warning("混沌炼狱塔：读不到价格，跳过 %s", button)
                continue
            if balance is None or price > balance:
                continue                 # 买不起；余额读不到也不买，避免超额
            affordable.append((price, button, name))

        if affordable:
            # 便宜的先买：贵的一次把余额吃光，后面的就都买不起了
            price, button, name = min(affordable, key=lambda item: item[0])
            logger.info(
                "混沌炼狱塔：买 %d 妖魄（余额 %s，位置 %s）", price, balance, name.box
            )
            click(B(*button), delay=0.5)
            confirm = locate(T("确定"), timeout=5)
            if confirm is None:
                logger.warning("混沌炼狱塔：点价格后没出现购买对话框，跳过这件")
                continue
            # 购买数量保持默认的 1：把滑条拉满会按「剩余额度」下单，额度大时总价可能
            # 超过余额而半途失败。一次一件最可预测，外层循环会一直买到额度用完或买不起。
            click(B(*confirm))
            wait_for_disappear(T("购买成功"))
            if ui_T(T("购买数量")):       # 没买成（余额不足等）：关掉对话框免得卡住
                logger.warning("混沌炼狱塔：购买对话框没有关闭，取消后继续")
                click(T("取消"), if_exist=True, timeout=3)
                sleep(0.5)
            bought += 1
            idle_scrolls = 0
            continue

        idle_scrolls += 1
        if idle_scrolls > 26:            # 整个列表滚完也没得买
            break
        swipe_precise(
            B(700, 520), B(700, 520 - SHOP_SCROLL_STEP_PX),
            duration_s=SHOP_SCROLL_DURATION_S, ensure_stable_after_swipe=False,
        )
        sleep(0.5)

    if bought:
        logger.info("混沌炼狱塔：本轮共购买 %d 次", bought)
    return bought


@register_task(
    description="领取混沌炼妖塔挂机奖励并按周期购买商店物品。",
    last_buy_time=0,
    reschedule="daily",
)
def hundunlianyaota():
    """领取混沌炼妖塔挂机奖励，并且自动购置功绩、6级灵域。"""
    ensure_in("联盟")
    click(T("魔渊之界"))
    click((I("混沌炼狱塔"),T("确定")))
    shop_tmp = wait_for_appear(T("妖魄商铺",box=Box(20,230,120,50)))
    click(B(160,600));sleep(1)
    click(B(0,0), repeat=3, interval=1)
    # cfg["tasks"] 是以任务名为键的平表，装饰器里的 last_buy_time=0 就落在条目顶层。
    # 这里原来写的是 "tasks.每日任务.村庄.混沌炼狱塔.last_buy_time"：旧树形路径在平表上
    # 走一遍，会凭空造出 每日任务.村庄.混沌炼狱塔 这棵子树来存值——两个后果：
    # ① 买的排期永远读到默认 0，于是「周一/每月才买」变成每天都买；
    # ② 那棵树写进了用户的账号文件，之后每次任务重载，register_task 都会因为
    #    「cfg['tasks'] 仍是树形」对所有任务抛异常。
    last_buy_time = cfg.get("tasks.混沌炼狱塔.last_buy_time", 0)
    if datetime.now().timestamp() > min(next_Mon(now=last_buy_time), next_month(now=last_buy_time)):
        click(B(*shop_tmp),until=lambda: ui_T(T("拥有")))
        yy_tmp = wait_for_appear(T("拥有"))
        _buy_shop_items()
        click(B(1080,40,30,30))
        cfg.set("tasks.混沌炼狱塔.last_buy_time", datetime.now().timestamp())
        wait_for_disappear(T("拥有",box=yy_tmp.margin()))
    sleep(1)
    click(B(30,30,30,30))
    wait_for_appear(I("混沌炼狱塔"))
    click(B(30,30,30,30))
