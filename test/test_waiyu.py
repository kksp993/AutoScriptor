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

if __name__ == "__main__":
    try:
        ensure_in("荒古万界")
        ensure_in("村庄")
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)