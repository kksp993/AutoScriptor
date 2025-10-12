    
import inspect
import os
import traceback
from ZmxyOL import *
import enum
from AutoScriptor.utils.constant import cfg
from logzero import logger
from ZmxyOL.task.translations import normalize_to_cn

# 在模块顶端添加全局计数器
registration_counter = 0

 


def register_task(func):
    """
    A decorator that registers a function into the global 'menu' dictionary
    based on its file path relative to a 'task' directory.
    """
    global registration_counter  # 引入全局计数器
    registration_counter += 1
    reg_order = registration_counter  # 当前注册顺序
    try:
        # 1. Get the full path of the file where the function is defined
        #    e.g., 'C:\\Users\\...\\task\\日常任务\\天庭\\宠物培养.py'
        filepath = inspect.getfile(func)

        # 2. Normalize the path for cross-platform compatibility (e.g., handle \ vs /)
        #    and split it into components.
        #    e.g., ['C:', 'Users', ..., 'task', '日常任务', '天庭', '宠物培养.py']
        norm_path = os.path.normpath(filepath)
        path_parts = norm_path.split(os.sep)

        # 3. Find the index of the 'task' directory, which acts as our root.
        try:
            task_index = path_parts.index('task')
        except ValueError:
            print(f"Error: The 'task' directory was not found in the path for {func.__name__}. Registration failed.")
            return func

        # 4. Get all the parts after 'task' to use as keys.
        #    e.g., ['日常任务', '天庭', '宠物培养.py']
        keys = path_parts[task_index + 1:]

        # 5. The last key is the filename. Remove the '.py' extension.
        #    e.g., '宠物培养.py' -> '宠物培养'
        filename = keys[-1]
        task_name, _ = os.path.splitext(filename)
        keys[-1] = task_name

        # 将路径片段统一归一为中文键（兼容英文目录/文件名）
        keys = [normalize_to_cn(key) for key in keys]

        # 6. Traverse the 'menu' dictionary, creating nested dictionaries if they don't exist.
        current_level = cfg["tasks"]
        for key in keys[:-1]: # Go up to the second-to-last key
            # setdefault is perfect here: it gets the value of the key if it exists,
            # otherwise it sets it to a new empty dict {} and returns that new dict.
            current_level = current_level.setdefault(key, {})

        # 7. At the final level, add the function and its status.
        last_key = keys[-1]
        if last_key in current_level:
            current_level[last_key]["fn"] = task_wrapper(func)
            current_level[last_key].setdefault('next_exec_time', 0)
            current_level[last_key]['order'] = reg_order  # 保存注册顺序
        else:
            current_level[last_key] = {'fn': func, 'on': True, 'next_exec_time': 0}
            current_level[last_key]['order'] = reg_order  # 保存注册顺序
        # 为任务添加参数配置
        sig = inspect.signature(func)
        defaults = {}
        param_meta = {}
        for name, param in sig.parameters.items():
            default = param.default if param.default is not inspect._empty else None
            # 枚举类型处理
            if isinstance(default, enum.Enum):
                # 单选枚举：存储枚举成员名称并记录类型元数据
                defaults[name] = default.name
                enum_path = default.__class__.__module__ + '.' + default.__class__.__qualname__
                param_meta[name] = enum_path
            # 多选枚举：列表中都是枚举成员
            elif isinstance(default, (list, tuple)) and default and all(isinstance(item, enum.Enum) for item in default):
                # 多选枚举（列表或元组中都是枚举成员），存储成员名称列表并记录类型元数据
                defaults[name] = [item.name for item in default]
                enum_path = default[0].__class__.__module__ + '.' + default[0].__class__.__qualname__
                param_meta[name] = enum_path
            else:
                # 其他类型或空列表
                defaults[name] = default
        task_cfg = current_level[last_key]
        existing_params = task_cfg.get('params', {})
        merged_params = defaults.copy()
        merged_params.update(existing_params)
        task_cfg['params'] = merged_params
        # 如果有枚举参数，保存类型元数据
        if param_meta:
            task_cfg['param_meta'] = param_meta
        a = {k:v for k,v in current_level[last_key].items() if k!= 'fn'}
        print(f"✅ 【{'/'.join(keys)}】 => {a}")
    except Exception as e:
        print(f"An error occurred during registration for {func.__name__}: {e}，{traceback.format_exc()}")

    # The decorator must return the original function
    return func


def task_wrapper(func):
    def wrapper(*args, **kwargs):
        from AutoScriptor.core.background import bg
        bg.clear(signals_clear=True)
        return func(*args, **kwargs)
    return wrapper
