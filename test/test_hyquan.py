
from AutoScriptor import *
from ZmxyOL import *
from timeit import timeit
import traceback

from ZmxyOL.battle.utils import find_in_bag,BAG
from ZmxyOL.nav.envs.decorators import LOC_ENV

def test_hyquan():
    find_in_bag(BAG.BAG,"活跃福利券")
    click(I("活跃券"), if_exist=True, delay=0.5, timeout=3)
    sleep(1)
    click(T("使用",color="红色"), if_exist=True, delay=0.5, timeout=2)
    sleep(3)
    ensure_in(LOC_ENV)

if __name__ == "__main__":
    try:
        print(locate(I("活跃券")))
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
