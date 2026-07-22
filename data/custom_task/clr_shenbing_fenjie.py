from AutoScriptor import *
from ZmxyOL.nav.api import *
from ZmxyOL.nav.envs.decorators import *
from ZmxyOL.task.task_register import register_task


@register_task(
    path_cn='自定义任务/背包清空/神兵分解',
    description='分解普通、精良、史诗品质神兵以清空背包',
    task_doc='会依次选择普通、精良、史诗品质神兵并执行批量分解，请确认背包中没有需要保留的神兵。',
)
def task():
    ensure_in("荒古村庄")
    idx = ui_idx((T('莫邪'),T('干将')),timeout=2)
    if idx == 0:
        click(T('莫邪'),offset=(430,140),resize=(0,0))
    else:
        click(T('干将'),offset=(25,140),resize=(0,0))
    click(T("分解", box=Box(413,49,142,53).margin()),delay=0.5)
    for quality in ["普通","精良","史诗"]:
        wait_for_appear(T("分解", box=Box(589,171,127,49).margin()))
        click(B(259,226,89,90))
        wait_for_appear(T("神兵选择", box=Box(543,31,248,67).margin()))
        click(B(892,114,41,45),delay=0.5)
        click(T(quality, box=Box(752,171,133,239).margin()))
        click(T("键选择", box=Box(464,565,152,56).margin()))
        count = 15
        for _ in range(10):
            if count % 15 != 0 or count <= 0: break
            swipe(B(868,327), B(418,327), duration_s=1)
            click(T("取消选择", box=Box(459,557,168,69).margin()))
            click(T("键选择", box=Box(464,565,152,56).margin()))
            sleep(1)
            count = extract_info(
                B(684,518,222,51),
                post_process=lambda s: int(s.strip().replace("：",":").split(":")[1]),
                ensure_not_empty=True
            )
            logger.info(f"count: {count}")
        if count == 0:
            click(B(933,51,61,58))
            continue
       
        click(T("确认", box=Box(687,556,164,70).margin()))
        click(T("分解", box=Box(547,557,205,69).margin()))
        click(T("空白处", box=Box(569,578,174,31).margin()))
    wait_for_appear(T("分解", box=Box(589,171,127,49).margin()))
    click(B(1087,91,61,51));sleep(1)
    click(B(17,439,71,55))
