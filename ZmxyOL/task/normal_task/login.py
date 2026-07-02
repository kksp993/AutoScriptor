from ZmxyOL import *
from AutoScriptor import *
import getpass

@register_task(
    path_cn="一般任务/登录",
    description="进入登录流程并选择当前配置的角色。",
)
def task():
    if not cfg["game"].get("character_name", None):
        cfg.load_config(getpass.getpass("请输入安全密码: "))
    ensure_in("村庄")
