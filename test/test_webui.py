from threading import Thread
from AutoScriptor import *
from ZmxyOL.nav import *
import traceback
from services.webui.server import run_webui, shutdown_webui
if __name__ == "__main__":
    try:
        thread = Thread(target=run_webui, daemon=True)
        thread.start()
    except Exception as e:
        traceback.print_exc()
    finally:
        shutdown_webui()
        exit(0)