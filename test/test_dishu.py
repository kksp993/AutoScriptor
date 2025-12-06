from timeit import timeit
from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

if __name__ == "__main__":
    try:
        while True: click(I("地鼠", color="蓝色"))
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)

