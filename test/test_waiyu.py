from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

if __name__ == "__main__":
    try:
        print(locate(T("外域区域")))
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)