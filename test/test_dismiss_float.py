from AutoScriptor import *
from ZmxyOL.nav import *
import traceback

if __name__ == "__main__":
    try:
        mixctrl.app.close(cfg["app"]["app_to_start"])
        sleep(1)
        mixctrl.app.launch(cfg["app"]["app_to_start"])
        while not dismiss_floating_window(max_retries=1, debug=False):
            sleep(1)
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)