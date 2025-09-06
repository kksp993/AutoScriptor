import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *

@register_task
def upgrade_pet():
    ensure_in(["村庄","仙盟","极北村庄"])
    logger.info("====喂养宠物====")
    click(T("菜单"))
    click(I("菜单-宠物"), delay=0.5)
    click(I("宠物-火灵仙狐"))
    click(T("喂养"))
    click(I("宠物-微型宠物经验药水"))
    click(T("定级喂养"))
    if ui_T(T("经验已满",box=Box(388,336,184,46)),2):
        click(I("宠物-九转还童丹"),delay=2)
        click(T("喂养",box=Box(801,336,127,71)),delay=0.5)
        sleep(2)
        click(I("宠物-微型宠物经验药水"),delay=2)
        click(T("定级喂养",box=Box(682,344,150,57)),delay=0.5)
    click(T("确定"))
    click(T("微型宠物经验药水"))
    click(B(1220,30,30,30))
    click(I("菜单"), delay=0.5)

if __name__ == "__main__":
    try:
        upgrade_pet()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)