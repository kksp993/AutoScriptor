from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

if __name__ == "__main__":
    try:
        for i in range(10):
            ensure_in("联盟")
            ensure_in("村庄")

    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)