import datetime
import os
import traceback
from logzero import logfile

def dump_error_and_log(path_str: str, exc: Exception):
    ts = datetime.datetime.now().strftime('%y%m%d_%H%M%S')
    safe = path_str.replace(' -> ', '_')
    err_dir = os.path.join(os.getcwd(), 'logs', 'errors')
    log_dir = os.path.join(os.getcwd(), 'logs', 'log')
    os.makedirs(err_dir, exist_ok=True); os.makedirs(log_dir, exist_ok=True)
    err_file = os.path.join(err_dir, f"[{ts}][{safe}].log")
    log_file = os.path.join(log_dir, f"[{ts}][{safe}].log")
    with open(err_file, 'w', encoding='utf-8') as ef:
        ef.write(f"[{ts}] {path_str} 执行错误: {exc}\n")
        ef.write(traceback.format_exc())
    logfile(log_file, encoding='utf-8')