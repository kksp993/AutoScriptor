import tkinter as tk
from tkinter import messagebox, simpledialog  # 新增 simpledialog 导入
import sys
import traceback  # 新增导入
import time  # 新增导入倒计时
import logging  # 新增导入 logging
from logzero import logger  # 新增 logzero logger 导入
from AutoScriptor import *

# def log_flush(msg):
#     """使用 logzero 在控制台打印 msg，不写入文件，并支持无终止符刷新"""
#     # 临时移除所有 FileHandler
#     file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
#     for fh in file_handlers:
#         logger.removeHandler(fh)
#     try:
#         # 动态更新，不换行
#         handler = next(h for h in logger.handlers if hasattr(h, 'terminator'))
#         original_terminator = getattr(handler, 'terminator', '\n')
#         handler.terminator = ''
#         logger.info(msg)
#         handler.terminator = original_terminator
#     finally:
#         # 恢复 FileHandler
#         for fh in file_handlers:
#             logger.addHandler(fh)

def countdown(mins, secs):
    """在终端显示分钟:秒倒计时"""
    total = mins * 60 + secs
    for remaining in range(total, 0, -1):
        m, s = divmod(remaining, 60)
        log_flush(f"倒计时 {m:02d}:{s:02d}")
        time.sleep(1)
    # 倒计时结束，打印 00:00
    logger.info("倒计时 00:00")

def main():
    """交互式循环：弹窗输入倒计时，运行后弹窗确认是否重试"""
    try:
        while True:
            # 弹窗输入倒计时
            root_input = tk.Tk()
            root_input.withdraw()
            root_input.attributes('-topmost', True)
            mins = simpledialog.askinteger("倒计时设置", "请输入分钟数：", parent=root_input, minvalue=0)
            if mins is None:
                root_input.destroy()
                break
            secs = simpledialog.askinteger("倒计时设置", "请输入秒数：", parent=root_input, minvalue=0, maxvalue=59)
            if secs is None:
                root_input.destroy()
                break
            root_input.destroy()
            # 执行倒计时
            countdown(mins, secs)
            # 倒计时结束提示并询问
            root_msg = tk.Tk()
            root_msg.withdraw()
            root_msg.attributes('-topmost', True)
            again = messagebox.askyesno("信息提示", "倒计时结束，是否再次运行？", parent=root_msg)
            root_msg.destroy()
            if not again:
                break
    except Exception as e:
        traceback.print_exc()
        sys.exit(1)
    finally:
        bg.stop()
        sys.exit(0)

if __name__ == "__main__":
    main()