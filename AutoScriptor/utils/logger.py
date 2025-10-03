from logzero import logger
import logging
import inspect
import os
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
