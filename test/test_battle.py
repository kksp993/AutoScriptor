from AutoScriptor import *
from ZmxyOL import *
from timeit import timeit
import traceback
if __name__ == "__main__":
    try:
        from ZmxyOL.battle.character.hero import h
        h.battle_loop()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
