from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

if __name__ == "__main__":
    try:
        ensure_in("幽冥冰窟")
        print(mm.get_region())
        ensure_in("极北村庄")
        print(mm.get_region())
        ensure_in("法相")
        print(mm.get_region())
        ensure_in("仙盟")
        print(mm.get_region())

    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)