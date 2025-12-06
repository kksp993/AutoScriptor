import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.nav.envs.login import login
from logzero import logger

@register_task
def login_other_role(character_index=0, character_name="请输入文本"):
    ensure_in("登录")
    login(character_index=character_index, character_name=character_name)
    ensure_in("登录")

if __name__ == "__main__":
    try:
         login_other_role()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)