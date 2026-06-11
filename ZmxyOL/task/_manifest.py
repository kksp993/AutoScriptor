"""
任务模块显式清单
================
列出所有需要在启动时导入的任务模块。
Nuitka 编译后无法通过 rglob("*.py") 发现模块，必须使用显式列表。

新增任务时，在此文件中添加对应的模块路径即可。
"""

TASK_MODULES = [
    # ── daily_task / village ──
    "ZmxyOL.task.daily_task.village.tianxuange",
    "ZmxyOL.task.daily_task.village.zhanling",
    "ZmxyOL.task.daily_task.village.yaoshou",
    "ZmxyOL.task.daily_task.village.huoyuequan",
    "ZmxyOL.task.daily_task.village.hundunlianyaota",
    "ZmxyOL.task.daily_task.village.qujing",
    "ZmxyOL.task.daily_task.village.xianqi_consume",
    "ZmxyOL.task.daily_task.village.alliance_build",
    "ZmxyOL.task.daily_task.village.equip_upgrade",
    "ZmxyOL.task.daily_task.village.jjc_task",
    "ZmxyOL.task.daily_task.village.pet_upgrade",
    "ZmxyOL.task.daily_task.village.xianbao_dig",
    "ZmxyOL.task.daily_task.village.lianmengxuanshang",

    # ── daily_task / heaven ──
    "ZmxyOL.task.daily_task.heaven.kunlunshan",
    "ZmxyOL.task.daily_task.heaven.team_task",
    "ZmxyOL.task.daily_task.heaven.heaven_chaos",
    "ZmxyOL.task.daily_task.heaven.hell_chaos",

    # ── daily_task / hyper / hyperborea ──
    "ZmxyOL.task.daily_task.hyper.hyperborea.hyper_chaos",
    "ZmxyOL.task.daily_task.hyper.hyperborea.brahma_tower",
    "ZmxyOL.task.daily_task.hyper.hyperborea.quick_clear",
    "ZmxyOL.task.daily_task.hyper.hyperborea.bingku_explore",
    "ZmxyOL.task.daily_task.hyper.hyperborea.chaos_egg",
    "ZmxyOL.task.daily_task.hyper.hyperborea.enan_task",

    # ── daily_task / hyper / hyper_village ──
    "ZmxyOL.task.daily_task.hyper.hyper_village.dianquan_consume",
    "ZmxyOL.task.daily_task.hyper.hyper_village.xianbao_destory",
    "ZmxyOL.task.daily_task.hyper.hyper_village.jiguangtianzhao",

    # ── daily_task / hyper / polar_abyss ──
    "ZmxyOL.task.daily_task.hyper.polar_abyss.hyper_abyss_task",

    # ── daily_task / hgwj ──
    "ZmxyOL.task.daily_task.hgwj.wanjiefuben",
    "ZmxyOL.task.daily_task.hgwj.yijingfuben",
    "ZmxyOL.task.daily_task.hgwj.hgjs",

    # ── daily_task / bmkj ──
    "ZmxyOL.task.daily_task.bmkj.bmkj",

    # ── weekly_task ──
    "ZmxyOL.task.weekly_task.rongyao_battle",
    "ZmxyOL.task.weekly_task.shituoling",
    "ZmxyOL.task.weekly_task.youming_bingku",
    "ZmxyOL.task.weekly_task.bingku_shop",

    # ── event_task ──
    "ZmxyOL.task.event_task.kunlunshan_task",
    "ZmxyOL.task.event_task.jiyuan",
    "ZmxyOL.task.event_task.luzi",
    "ZmxyOL.task.event_task.tengshefeisheng",
    "ZmxyOL.task.event_task.huodong",
    "ZmxyOL.task.event_task.wuguangshise",
    "ZmxyOL.task.event_task.hd_registry",
    "ZmxyOL.task.event_task.hd_details.dengluhuikui",
    "ZmxyOL.task.event_task.hd_details.lingnengshizhuang",

    # ── normal_task ──
    "ZmxyOL.task.normal_task.login",
    "ZmxyOL.task.normal_task.battle",
    "ZmxyOL.task.normal_task.back_to_login",
    "ZmxyOL.task.normal_task.brahma_tower",
    "ZmxyOL.task.normal_task.huodong.redeem_gift",
]
