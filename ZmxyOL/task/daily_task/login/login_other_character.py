import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from ZmxyOL.nav.envs.login import login
from logzero import logger

@register_task
def login_other_role(character_index=0, character_name="请输入文本", clear_all=False, lianbao=False):
    ensure_in("登录")
    logger.info(f"登录其他角色: {character_index}, {character_name}")
    login(character_index=character_index, character_name=character_name)
    from ZmxyOL.task.daily_task.bmkj.bmkj import task as bmkj_task
    bmkj_task(clear_all=False, lianbao=False)
    ensure_in("登录")

if __name__ == "__main__":
    try:
         login_other_role()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)