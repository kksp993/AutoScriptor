from timeit import timeit
from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

if __name__ == "__main__":
    try:
       from ZmxyOL.battle.character.hero import h
       h.set(has_cd=False, speed_x=3)
       h.jump(2).move_right(125, directly=True)
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)

