from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

if __name__ == "__main__":
    try:
        ensure_in("幽冥冰窟")
        ensure_in("极北村庄")
        # ensure_in("法相")
        # ensure_in("仙盟")

    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)