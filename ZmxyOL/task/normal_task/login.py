from ZmxyOL import *
from AutoScriptor import *
import getpass

@register_task
def task():
    if not cfg["game"].get("character_name", None):
        cfg.load_config(getpass.getpass("请输入安全密码: "))
    ensure_in("村庄")
