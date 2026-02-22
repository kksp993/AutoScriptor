from logzero import logger
import logzero
import logging
import inspect
import os
import threading

# ── 任务名注入：让日志的 module:lineno 位置显示当前任务中文名 ──
_task_ctx = threading.local()

def set_current_task(name: str | None):
    """设置当前线程正在执行的任务名称（None 表示清除）"""
    _task_ctx.name = name

class _TaskAwareFormatter(logzero.LogFormatter):
    """继承 logzero 彩色 Formatter，有任务时在 level 和时间之间插入任务名"""
    _FMT = '%(color)s[%(levelname)1.1s %(task_prefix)s%(asctime)s %(module)s:%(lineno)d]%(end_color)s %(message)s'

    def __init__(self):
        super().__init__(fmt=self._FMT, datefmt='%y%m%d %H:%M:%S')

    def format(self, record):
        task_name = getattr(_task_ctx, 'name', None)
        record.task_prefix = f"{task_name} " if task_name else ""
        return super().format(record)

def setup_task_aware_logging():
    """应用任务感知的日志格式（在 logfile 配置之后调用）"""
    logzero.formatter(_TaskAwareFormatter())

last_msg = ""
def log_flush(msg):
    """使用 logzero 在控制台打印 msg，不写入文件，并支持无终止符刷新"""
    global last_msg
    # 组装与当前 formatter 一致的前缀，例如: [I 250930 09:15:44 background:70]
    # 1) 找到控制台 handler
    console_handlers = [h for h in logger.handlers if hasattr(h, 'stream')]
    if not console_handlers:
        return
    ch = console_handlers[0]
    stream = ch.stream

    # 2) 查找调用方（跳过当前模块栈帧）
    frame = inspect.currentframe()
    frame = frame.f_back  # 跳过 log_flush 自身
    this_file = os.path.normcase(os.path.abspath(__file__))
    while frame and os.path.normcase(os.path.abspath(frame.f_code.co_filename)) == this_file:
        frame = frame.f_back
    if frame is None:
        pathname, lineno = this_file, 0
    else:
        pathname, lineno = frame.f_code.co_filename, frame.f_lineno

    # 3) 使用 LogRecord 和已有 formatter 生成“前缀”，不包含 message
    record = logging.LogRecord(logger.name, logging.INFO, pathname, lineno, "", None, None)
    prefix = ch.format(record).rstrip()
    out = prefix + " " + msg
    if last_msg != out:
        last_msg = out
        print(out, end="\r")
