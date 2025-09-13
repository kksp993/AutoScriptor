from AutoScriptor import *
import time
import getpass

def login(account: str=None, password: str=None, character_name: str=None):
    logger.info("等待启动完毕")
    while ui_F((T("进入游戏"), T("已阅读并同意"))):
        time.sleep(0.5)
    if ui_F(T("进入游戏")):
        if not account or not password:
            cfg.load_config(getpass.getpass("请输入安全密码: "))
            account = cfg["game"].get("account", None)
            password = cfg["game"].get("password", None)
            character_name = cfg["game"].get("character_name", None)
        click(T("账号登录"), if_exist=True)
        click(T("已阅读并同意"))
        click(B(719, 536, 144, 26))
        click(T("授权并登录"), if_exist=True, timeout=3)
        click(T("添加账号"), if_exist=True)
        locate(T("手机号验证登录"), 10)
        if ui_idx((T("请输入手机号或用户名"),T("账号登录"),T("进入游戏",color="橙色"))) in [0,1]:
            click(T("账号登录"), delay=1, repeat=2)
            click(T("请输入手机号或用户名"))
            input(account)
            click(T("请输入密码"))
            input(password)
            click(T("登录",color="青色"))
            time.sleep(1)
            click(T("同意并登录",color="青色", box=Box(160,707,442,95)))
            click(T("授权并登录"), if_exist=True)
    click(T("开心收下"), if_exist=True)
    click(T(character_name),delay=1) if character_name else None
    click(T("进入游戏",color="橙色"))
    locate(I("活动公告页面"), 30)
    click(B(1240, 5, 40, 60))
    time.sleep(0.5)
    swipe(B(630, 10, 10, 10), B(640, 650, 10, 10), duration_s=1)
    if ui_T(T("隐藏悬浮球"), 5):
        click(B(740, 555, 10, 10))
    if ui_T(T("精彩活动")):
        click(B(1100, 40, 40, 40))
    logger.info("登录完成")


if __name__ == "__main__":
    cfg.load_config(getpass.getpass("请输入安全密码: "))
    login(cfg["game"].get("account", None), cfg["game"].get("password", None), cfg["game"].get("character_name", None))


