from AutoScriptor import *
from ZmxyOL.battle.character.hero import *

@combo
def check_linggen(self:Hero):
    from ZmxyOL.nav.api import ensure_in
    ensure_in(["极北","极寒深渊"],[-1,None])
    click(B(50,50,40,40))
    store_as = extract_info(B(245,90,100,30), lambda res: next((char for char in "金寄寒火岩时电月无" if char in res.strip())).replace("电", "雷").replace("岩", "土").replace("无", "天").replace("寄", "木").replace("寒", "水"))
    logger.info(f"今日灵气: {store_as}")
    click(B(50,50,40,40))
    return store_as

@combo
def task_way_to_diff(self:Hero, task: str, expect_difficulty: str, task_type: str)->int:
    # 进入关卡
    from ZmxyOL.battle.tasks import get_task_table
    from ZmxyOL.nav import ensure_in
    ensure_in(*get_task_table(task)["location"])
    click(get_task_table(task)["target"], until=lambda: extract_info(B(648,6,132,78), lambda x: len(x.strip())==2))
    # 开始挑战
    if ui_F("开始挑战"):
        click(B(174,242,931,96))
    # 进入混沌本，获取剩余次数
    click(T("混沌", box=Box(1008,263,73,52)), if_exist=True)
    if expect_difficulty == "灵狱" and task_type == "极寒深渊":
        remains = extract_info(B(922,249,186,43), lambda x: int(x.strip()[-1]))
    else:
        remains = extract_info(B(610,292,120,24), lambda x: int(x.strip()[-2]))
    # 获取难度
    difficulty = extract_info(
        B(222,368,66,56),
        lambda x: ("噩梦" if "梦" in x else x.strip())
    )
    logger.info(f"当前难度: {difficulty}")
    # 调整难度
    expect_index = get_task_table(task)["diff"].index(expect_difficulty)
    cur_index = get_task_table(task)["diff"].index(difficulty)
    repeat = (expect_index - cur_index) % len(get_task_table(task)["diff"])
    click(B(230,380,80,50), repeat=repeat)
    sleep(1)
    print(f"remaining: {remains}")
    return remains

@combo
def chaos_select(self:Hero, task_list:list[str], Weather:str, task_type: str)->str|None:
    same_linggen_chaos = None
    for name in task_list:
        if not same_linggen_chaos:
            remains = self.task_way_to_diff(task=name, expect_difficulty="灵狱", task_type=task_type)
            if remains == 0: return
            cur_linggen = extract_info(B(260,440,80,50), lambda x: x.strip()[0])
            logger.info(f"{name} -> {cur_linggen}")
            if cur_linggen in Weather: same_linggen_chaos = name
            sleep(1)
            click(B(1200,30,30,30))
            wait_for_appear(T("回家", box=Box(18,607,87,109)))
    return same_linggen_chaos