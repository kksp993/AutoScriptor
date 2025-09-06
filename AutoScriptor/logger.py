import logging
import sys
from datetime import datetime

# ANSI 转义序列，用于添加颜色
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

# 禁用根日志记录器的传播
logging.getLogger().propagate = False

# 创建或获取一个 logger 实例
logger = logging.getLogger("mumu")
logger.setLevel(logging.DEBUG)
logger.propagate = False  # 禁用传播

# 移除所有现有的处理器
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# 创建 Formatter 对象，格式为：时间 │ 日志消息
formatter = logging.Formatter(
    '%(asctime)s │ %(message)s',
    datefmt='%H:%M:%S.%f'
)

# 重写 formatTime 方法，将微秒截断为毫秒
def format_time(record, datefmt=formatter.datefmt):
    return datetime.fromtimestamp(record.created).strftime(datefmt)[:-3]
formatter.formatTime = format_time

# 添加控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 添加文件处理器，将日志写入文件
file_handler = logging.FileHandler('mumu.log', encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# 将 logger 的常用方法暴露为模块变量
debug = logger.debug
info = logger.info
warn = logger.warning
warning = logger.warning
error = logger.error
exception = logger.error
critical = logger.error

class MumuLogger:
    def __init__(self):
        self.logger = logger  # 使用同一个logger实例

    def info(self, message, task=None):
        # info 信息不加颜色，直接显示 [info]
        prefix = '[info]'
        if task:
            self.logger.info(f'[Task] {task} | {prefix} {message}')
        else:
            self.logger.info(f'{prefix} {message}')

    def debug(self, message, task=None):
        # debug 信息用黄色显示
        prefix = f'{YELLOW}[debug]{RESET}'
        if task:
            self.logger.debug(f'[Task] {task} | {prefix} {message}')
        else:
            self.logger.debug(f'{prefix} {message}')

    def warning(self, message, task=None):
        # warning 信息保持原样，不作颜色处理
        if task:
            self.logger.warning(f'[Task] {task} | {message}')
        else:
            self.logger.warning(message)

    def error(self, message, task=None, exc_info=False):
        # error 信息用红色显示
        prefix = f'{RED}[error]{RESET}'
        if task:
            if exc_info:
                self.logger.error(f'[Task] {task} | {prefix} {message}', exc_info=True)
            else:
                self.logger.error(f'[Task] {task} | {prefix} {message}')
        else:
            if exc_info:
                self.logger.error(f'{prefix} {message}', exc_info=True)
            else:
                self.logger.error(f'{prefix} {message}')


logger = MumuLogger()
