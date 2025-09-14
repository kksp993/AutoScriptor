import traceback
from ZmxyOL.task.task_register import register_task
from ZmxyOL import *
from AutoScriptor import *
from logzero import logger

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