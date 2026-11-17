from ZmxyOL import *
from AutoScriptor import *
import getpass

@register_task(
    ensure_in=ANYWHERE,
    description="进入登录流程并选择当前配置的角色。",
)
def task():
    # 先准备凭据，再进入游戏；不能在准备前自动导航到村庄。
    if not cfg["game"].get("character_name", None):
        cfg.load_config(getpass.getpass("请输入安全密码: "))
    ensure_in("村庄")
