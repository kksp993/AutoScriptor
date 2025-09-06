from AutoScriptor import *
from ZmxyOL import *
EXIT_RADIUS=0  # 退出范围 for safety

TASK_TABLE = {
    "龙宫":{"location":("天庭",4),"target":T("龙宫"),"idx":0, "exit_loc":300-EXIT_RADIUS},
    "九重天":{"location":("天庭",0),"target":T("九重天"),"idx":0, "exit_loc":626-EXIT_RADIUS},
    "南天王殿·精英":{"location":("天庭",0),"target":T("南天王殿"),"idx":0, "exit_loc":416-EXIT_RADIUS},
    "南天王殿·终":{"location":("天庭",0),"target":T("南天王殿"),"idx":1, "exit_loc":416-EXIT_RADIUS},
    "西天王殿·精英":{"location":("天庭",0),"target":T("西天王殿"),"idx":0, "exit_loc":416-EXIT_RADIUS},
    "西天王殿·终":{"location":("天庭",0),"target":T("西天王殿"),"idx":1, "exit_loc":416-EXIT_RADIUS},
    "北天王殿·终":{"location":("天庭",-1),"target":T("北天王殿"),"idx":0, "exit_loc":416-EXIT_RADIUS},
    "御马监":{"location":("天庭",-1),"target":T("北天王殿"),"idx":1, "exit_loc":416-EXIT_RADIUS},
    "彩虹楼":{"location":("天庭",-1),"target":I("彩虹楼"),"idx":1, "exit_loc":416-EXIT_RADIUS},
    "东天王殿":{"location":("天庭",-1),"target":I("彩虹楼"),"idx":0, "exit_loc":476-EXIT_RADIUS},
    "朝会殿":{"location":("天庭",-1),"target":T("朝会殿"),"idx":0, "exit_loc":416-EXIT_RADIUS},
    # 凌霄宝殿 识别不对，用凌宵宝殿代替
    "凌霄宝殿":{"location":("天庭",-2),"target":T("凌宵宝殿"),"idx":0, "exit_loc":416-EXIT_RADIUS},

    "混沌火焰山·噩梦":{"location":("天庭", 0),"target":B(1120,5,20,80),"idx":0, "exit_loc":643-EXIT_RADIUS},
    "混沌五指山·噩梦":{"location":("天庭", 0),"target":B(130,210,1,1),"idx":0, "exit_loc":625-EXIT_RADIUS},
    "混沌盘丝洞·噩梦":{"location":("天庭", 1),"target":B(549,589,212,37),"idx":0, "exit_loc":632-EXIT_RADIUS},
    "混沌地狱官邸·噩梦":{"location":("地狱", 1),"target":B(369,566,225,44),"idx":0, "exit_loc":702-EXIT_RADIUS},

    "心狐星宫":{"location":("极北",-1),"target":B(540,170,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "灵狱"]},
    "壁宿星宫":{"location":("极北",-1),"target":B(950,330,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "灵狱"]},
    "猴圣星宫":{"location":("极北",-1),"target":B(717,424,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "灵狱"]},
    "牛魔星宫":{"location":("极北",-1),"target":B(790,210,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "灵狱"]},
    "豹王星宫":{"location":("极北",-1),"target":B(480,320,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "灵狱"]},
    "猴王星宫":{"location":("极北",-1),"target":B(290,480,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "灵狱"]},
    # 极寒深渊
    "岩貉星宫":{"location":("极寒深渊",0),"target":B(1000,630,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"]},
    "犬神星宫":{"location":("极寒深渊",0),"target":B(850,470,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"]},
    "狼王星宫":{"location":("极寒深渊",0),"target":B(520,270,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"]},
    "虎王星宫":{"location":("极寒深渊",0),"target":B(760,310,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"]},
    "獐王星宫":{"location":("极寒深渊",0),"target":B(620,580,30,30),"idx":0, "exit_loc":330-EXIT_RADIUS,"diff":["普通", "困难", "噩梦", "灵狱"]},
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

JHSY_CHAOS_TABLE=[
    "岩貉星宫",
    "犬神星宫",
    "狼王星宫",
    "虎王星宫",
    "獐王星宫",
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





