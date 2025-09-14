from AutoScriptor import *
import time
import getpass
from logzero import logger

def login(account: str=None, password: str=None, character_name: str=None, character_index: int=0):
    """
        character_index = 1~8, 0为默认角色, 1~5为第一页, 6~8为第二页
    """
    logger.info("等待启动完毕")
    while ui_F((T("进入游戏"), T("已阅读并同意"))):
        time.sleep(0.5)
    if ui_T(T("已阅读并同意")):
        if not account or not password:
            cfg.load_config(getpass.getpass("请输入安全密码: "))
            account = cfg["game"].get("account", None)
            password = cfg["game"].get("password", None)
            character_name = cfg["game"].get("character_name", None) if not character_name else character_name
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
    if character_index:
        sleep(1)
        if character_index <=5:
            click(B(104,63+70*(character_index-1),149,54))
        else:
            click(B(104,516,63,26))
            sleep(1)
            click(B(104,63+70*(character_index-6),149,54))
    else:
        if character_name: click(T(character_name),delay=1)
        else:
            if not cfg["game"].get("character_name", None):
                raise ValueError("请先配合完成安全密码验证")
            click(T(cfg["game"].get("character_name", None)),delay=1)
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


