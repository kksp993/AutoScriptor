from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

if __name__ == "__main__":
    try:
        swipe(I("法宝-戮仙剑"),I("炼丹炉-进阶-添加装备"),duration_s=2)
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)