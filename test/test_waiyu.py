from calendar import c
from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

def way():
    click(I("导航-世界地图"))
    click(T("荒古万界"),offset=(180,90))
    wait_for_appear(T("万界穿梭"))

def way_exit():
    click(B(30,30,30,30))
    wait_for_appear(T("荒古万界"))
    click(B(1200,30,30,30))

tasks=[
    B(50,83),
    B(15,410),
    B(235,250),
    B(400,550),
    B(570,360),
    B(840,550),
    B(900,250),
    B(1200,90),
    B(1210,400),
]

hg_tasks=[
    "荒古-普通-0",
    "荒古-精英-0",
    "荒古-奖励-0",
    "荒古-普通-1",
    "荒古-精英-1",
    "荒古-奖励-1",
]

if __name__ == "__main__":
    try:
        # boxes_arr = []
        # count_arr = []
        # for task in tasks:
        #     click(task)
        #     sleep(0.3)
        #     boxes = locate([I(key=hg_tasks[i]) for i in range(len(hg_tasks))], is_simplify=False)
        #     print(boxes)
        #     boxes_arr.append(boxes)
        #     count_arr.append(count(boxes_arr[-1]))
        #     click(B(0,0))
        #     sleep(0.3)  
        #     print(boxes_arr[-1], count_arr[-1], sum(count_arr[-1]))
        # bonus_arr = [arr[2] for arr in count_arr]
        # print(bonus_arr)
        # index = bonus_arr.index(max(bonus_arr))
        # click(tasks[index])
        # sleep(0.3)
        # click(B(960,510,90,90))
        # click(T("确定"))
        # wait_for_disappear(I("加载中"))
        def callback():
            bg.set_signal("Pause_battle", True)
            click(T("继续挑战"))
            if ui_T(T("购买"),2):
                bg.set_signal("try_exit", True)
                click(T("取消"),if_exist=True)
                sleep(0.5)
                click(T("确定",color="蓝色"))
                bg.clear()
            else:
                click(T("确定"))
                wait_for_disappear(I("加载中")),
                bg.set_signal("Pause_battle", False),


        from ZmxyOL.battle.character.hero import h
        bg.add(
            name="try_pause",
            identifier=T("继续挑战"),
            callback=callback,
        )
        h.set(True,3)
        h.battle_loop(battle_weight=2)
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)