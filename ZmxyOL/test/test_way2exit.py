from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

if __name__ == "__main__":
    try:
        from ZmxyOL.battle.character.hero import h
        h.way_to_exit(until=lambda:ui_T((I("加载中"), I("极北-加载中"))), exit_loc=100)
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)