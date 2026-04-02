import traceback
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.logger import logger

# @register_task
# def task():
#     pass


if __name__ == "__main__":
    try:
        pass # task()
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)