from AutoScriptor import *
from AutoScriptor.core.api import mixctrl
import traceback

if __name__ == "__main__":
    try:
        mixctrl.app.close(cfg["app"]["app_to_start"])
        sleep(1)
        mixctrl.app.launch(cfg["app"]["app_to_start"])
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)
