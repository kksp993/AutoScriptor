from AutoScriptor import *
from ZmxyOL.battle.character.hero import combo
from ZmxyOL.nav.api import ensure_in, try_close_via_x
EXIT_RADIUS=0  # 退出范围 for safety

TASK_TABLE = {
    "龙宫":{"location":("天庭",4),"target":T("龙宫"),"idx":0, "exit_loc":300-50-EXIT_RADIUS,"crash_suddenly":False},
    "九重天":{"location":("天庭",0),"target":T("九重天"),"idx":0, "exit_loc":626-50-EXIT_RADIUS,"crash_suddenly":False},
    "南天王殿·精英":{"location":("天庭",0),"target":T("南天王殿"),"idx":0, "exit_loc":416-50-EXIT_RADIUS,"crash_suddenly":False    },
    "南天王殿·终":{"location":("天庭",0),"target":T("南天王殿"),"idx":1, "exit_loc":416-50-EXIT_RADIUS,"crash_suddenly":False},
    "西天王殿·精英":{"location":("天庭",0),"target":T("西天王殿"),"idx":0, "exit_loc":416-50-EXIT_RADIUS,"crash_suddenly":False},
    "西天王殿·终":{"location":("天庭",0),"target":T("西天王殿"),"idx":1, "exit_loc":416-50-EXIT_RADIUS,"crash_suddenly":False},
    "北天王殿·终":{"location":("天庭",-1),"target":T("北天王殿"),"idx":0, "exit_loc":416-50-EXIT_RADIUS,"crash_suddenly":False},
    "御马监":{"location":("天庭",-1),"target":T("北天王殿"),"idx":1, "exit_loc":416-50-EXIT_RADIUS,"crash_suddenly":False},
    "彩虹楼":{"location":("天庭",-1),"target":I("彩虹楼"),"idx":1, "exit_loc":416-50-EXIT_RADIUS,"crash_suddenly":False},
    "东天王殿":{"location":("天庭",-1),"target":I("彩虹楼"),"idx":0, "exit_loc":476-50-EXIT_RADIUS,"crash_suddenly":False},
    "朝会殿":{"location":("天庭",-1),"target":T("朝会殿"),"idx":0, "exit_loc":416-50-EXIT_RADIUS,"crash_suddenly":False},
    # 凌霄宝殿 识别不对，用凌宵宝殿代替
    "凌霄宝殿":{"location":("天庭",-2),"target":T("凌宵宝殿"),"idx":0, "exit_loc":416-50-EXIT_RADIUS,"crash_suddenly":False},

    "混沌火焰山·噩梦":{"location":("天庭", 0),"target":B(1120,5,20,80),"idx":0, "exit_loc":643-EXIT_RADIUS,"crash_suddenly":False},
    "混沌五指山·噩梦":{"location":("天庭", 0),"target":B(130,210,1,1),"idx":0, "exit_loc":625-EXIT_RADIUS,"crash_suddenly":False},
    "混沌盘丝洞·噩梦":{"location":("天庭", 1),"target":B(549,589,212,37),"idx":0, "exit_loc":632-EXIT_RADIUS,"crash_suddenly":False},
    "混沌地狱官邸·噩梦":{"location":("地狱", 1),"target":B(369,566,225,44),"idx":0, "exit_loc":702-EXIT_RADIUS-40,"crash_suddenly":False},

    "心狐星宫":{"location":("极北",-1),"target":B(540,170,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "灵狱"],"crash_suddenly":False},
    "壁宿星宫":{"location":("极北",-1),"target":B(950,330,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "灵狱"],"crash_suddenly":False},
    "猴圣星宫":{"location":("极北",-1),"target":B(717,424,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "灵狱"],"crash_suddenly":False},
    "牛魔星宫":{"location":("极北",-1),"target":B(790,210,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "灵狱"],"crash_suddenly":False},
    "豹王星宫":{"location":("极北",-1),"target":B(480,320,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "灵狱"],"crash_suddenly":False},
    "猴王星宫":{"location":("极北",-1),"target":B(290,480,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "灵狱"],"crash_suddenly":False},
    # 极寒深渊
    "岩貉星宫":{"location":("极寒深渊",0),"target":T("岩络星宫", box=Box(0,662,1280,35).margin()),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"],"crash_suddenly":False},
    "犬神星宫":{"location":("极寒深渊",0),"target":T("犬神星宫", box=Box(0,519,1280,34).margin()),"idx":0, "exit_loc":230-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"],"crash_suddenly":False},
    "狼王星宫":{"location":("极寒深渊",0),"target":T("狼王星宫", box=Box(0,319,1280,39).margin()),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"],"crash_suddenly":False},   
    "虎王星宫":{"location":("极寒深渊",0),"target":T("虎王星宫", box=Box(0,340,1280,33).margin()),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"],"crash_suddenly":False},
    "獐王星宫":{"location":("极寒深渊",0),"target":T("獐王星宫", box=Box(537,611,159,53).margin()),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"],"crash_suddenly":False},
    "犴神星宫":{"location":("极寒深渊",1),"target":B(970,610,30,30),"idx":0, "exit_loc":230-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"],"crash_suddenly":True},
    "兔神星宫":{"location":("极寒深渊",0),"target":T("兔神星宫", box=Box(0,136,1280,28).margin()),"idx":0, "exit_loc":230-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"],"crash_suddenly":False},
}

TASK_TABLE_LIST = [
    "龙宫",
    # "九重天",
    # "南天王殿·精英",
    "南天王殿·终",
    # "西天王殿·精英",
    # "西天王殿·终",
    "北天王殿·终",
    # "彩虹楼",
    # "东天王殿", 
    # "朝会殿",
    "凌霄宝殿",
]

JIYUAN_TASK_TABLE = [
    "龙宫",
    "九重天",
    "南天王殿·精英",
    "西天王殿·精英",
    "北天王殿",
    "东天王殿",
    "朝会殿",
    "凌霄宝殿",
]

CHAOS_TASK_TABLE = [
    "混沌火焰山·噩梦",
    "混沌五指山·噩梦",
    "混沌盘丝洞·噩梦",
    "混沌地狱官邸·噩梦",
]

JIBEI_CHAOS_TABLE=[
    "心狐星宫",
    "壁宿星宫",
    "猴圣星宫",
    "牛魔星宫",
    "豹王星宫",
    "猴王星宫",
]

# 顺序与各关卡任务参数（YanHao、QuanShen…TuShen）一致，见 polar_abyss/hyper_abyss_task.py
JHSY_CHAOS_TABLE=[
    "岩貉星宫",
    "犬神星宫",
    "狼王星宫",
    "虎王星宫",
    "獐王星宫",
    "犴神星宫",
    "兔神星宫"    #打不过，能打过的自己解开注释
]


def get_task_table(task_name:str|list[str]|tuple[str]):
    if isinstance(task_name, str):
        return TASK_TABLE.get(task_name)
    else:
        return {k:v for k,v in TASK_TABLE.items() if k in task_name}
    

def challenge_task():
    from ZmxyOL.battle.character.hero import h
    h.battle_tasks(set(TASK_TABLE_LIST).union(set(JIYUAN_TASK_TABLE)))


def challenge_task_jiyuan():
    from ZmxyOL.battle.character.hero import h
    h.battle_tasks(JIYUAN_TASK_TABLE)


def challenge_task_daily():
    from ZmxyOL.battle.character.hero import h
    h.battle_tasks(TASK_TABLE_LIST)


@combo
def battle_tasks(self:"Hero", task_table:list[str], speed_x:int=1, flow_name: str | None = None):#type: ignore
    if isinstance(task_table, str): task_table = [task_table]
    if flow_name is None:
        flow_name = getattr(self, "task_context_battle_flow", None) or "战斗循环"
    for v in get_task_table(task_table).values():
        ensure_in(*v["location"])
        click(v["target"])
        wait_for_appear(v["target"].set_box(Box(136,0,988,84)))
        click(B(253,271+100*v["idx"],104,37),delay=1)
        click(T("开始挑战"))
        if ui_T(I("加载中"),3):
            wait_for_disappear(I("加载中"))
            self.set(has_cd=False, speed_x=speed_x).heaven_battle(exit_loc=v["exit_loc"], flow_name=flow_name)
        else:
            click(T("确定",box=Box(658,495,142,82)), if_exist=True)
            click(B(1061,172,47,50), until=lambda: ui_F(T("副本奖励")))

        



