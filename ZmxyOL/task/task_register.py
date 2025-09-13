    
import inspect
import os
import traceback
from ZmxyOL import *
from AutoScriptor.utils.constant import cfg


def register_task(func):
    """
    A decorator that registers a function into the global 'menu' dictionary
    based on its file path relative to a 'task' directory.
    """
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
        else:
            current_level[last_key] = {'fn': func, 'on': True, 'next_exec_time': 0}
        # 为任务添加参数配置
        sig = inspect.signature(func)
        defaults = {}
        for name, param in sig.parameters.items():
            if param.default is inspect._empty:
                defaults[name] = None
            else:
                defaults[name] = param.default
        task_cfg = current_level[last_key]
        existing_params = task_cfg.get('params', {})
        merged_params = defaults.copy()
        merged_params.update(existing_params)
        task_cfg['params'] = merged_params
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
