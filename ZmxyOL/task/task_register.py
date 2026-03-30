    
import inspect
import os
import traceback
from ZmxyOL import *
import enum
from AutoScriptor.utils.constant import cfg
from AutoScriptor.utils.task_registry import task_registry
from AutoScriptor.utils.logger import logger
from ZmxyOL.task.translations import normalize_to_cn
from ZmxyOL.nav.api import locate_region

# 在模块顶端添加全局计数器
registration_counter = 0

 


def register_task(func=None, *, default_offset_hours=None, **task_kwargs):
    """
    装饰器：根据函数所在文件路径（'task' 目录下的子路径）注册任务。

    注册数据分两处存储：
      - cfg["tasks"]（用户配置，持久化到 JSON）：on、next_exec_time、params、next_exec_offset_hours
      - TaskRegistry（运行时数据，不持久化）：fn、order、param_meta

    支持以下可选参数（仅对指定任务生效）：
      - default_offset_hours (int): 任务执行后延迟 N 小时再调度
      - sched_window_hours (tuple[int,int]): 本地时间可执行时段 [start, end)，如 (10, 22)；
        调度器在时段外不会执行该任务，执行后 next_exec_time 也会落在时段内
      - allowed_weekdays (list[int]): 仅在这些星期可执行，cfg 约定 1=周一 … 7=周日（如 [6,7] 为周六日）；
        到期但不在允许日时，调度器会推迟 next_exec_time 至下一允许日的 5:00
      - 其他任意元数据参数 (key=value): 写入 cfg 配置节点

    用法示例：
      @register_task(default_offset_hours=10)
      def task():
          ...
    """
    if func is None:
        def wrapper(f):
            return register_task(f, default_offset_hours=default_offset_hours, **task_kwargs)
        return wrapper
    global registration_counter  # 引入全局计数器
    registration_counter += 1
    reg_order = registration_counter  # 当前注册顺序
    try:
        module = inspect.getmodule(func)
        if module is not None:
            # 注入导航相关的符号
            if not hasattr(module, 'ensure_in'):
                try:
                    from ZmxyOL.nav import ensure_in as _ensure_in
                    from ZmxyOL.nav.envs.decorators import LOC_ENV
                    from ZmxyOL.battle.character.hero import h
                    from ZmxyOL.battle.tasks import get_task_table
                    setattr(module, 'ensure_in', _ensure_in)
                    setattr(module, 'LOC_ENV', LOC_ENV)
                    setattr(module, 'h', h)
                    setattr(module, 'get_task_table', get_task_table)
                    setattr(module, 'locate_region', locate_region)
                except Exception:
                    pass
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

        # 6. Traverse cfg["tasks"], creating nested dicts for the path.
        current_level = cfg["tasks"]
        for key in keys[:-1]:
            current_level = current_level.setdefault(key, {})

        # 7. cfg["tasks"] 只存用户配置（on、next_exec_time、params 等）
        last_key = keys[-1]
        if last_key not in current_level:
            current_level[last_key] = {'on': True, 'next_exec_time': 0}
        else:
            current_level[last_key].setdefault('on', True)
            current_level[last_key].setdefault('next_exec_time', 0)
        if default_offset_hours is not None:
            current_level[last_key]['next_exec_offset_hours'] = default_offset_hours
        for key, value in task_kwargs.items():
            current_level[last_key][key] = value

        # 解析函数签名，提取参数默认值和枚举元数据
        sig = inspect.signature(func)
        defaults = {}
        param_meta = {}
        for name, param in sig.parameters.items():
            if param.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL):
                continue
            default = param.default if param.default is not inspect._empty else None
            if isinstance(default, enum.Enum):
                defaults[name] = default.name
                enum_path = default.__class__.__module__ + '.' + default.__class__.__qualname__
                param_meta[name] = {"enum": enum_path, "multiple": False}
            elif isinstance(default, (list, tuple)) and default and all(isinstance(item, enum.Enum) for item in default):
                defaults[name] = [item.name for item in default]
                enum_path = default[0].__class__.__module__ + '.' + default[0].__class__.__qualname__
                param_meta[name] = {"enum": enum_path, "multiple": True}
            else:
                defaults[name] = default

        # params 是用户可编辑配置，留在 cfg
        task_cfg = current_level[last_key]
        existing_params = task_cfg.get('params', {})
        merged_params = defaults.copy()
        merged_params.update(existing_params)
        task_cfg['params'] = merged_params

        # 8. fn / order / param_meta 注册到 TaskRegistry（运行时数据，不写入 JSON）
        task_path = "/".join(keys)
        task_registry.register(task_path, task_wrapper(func), reg_order, param_meta)
        # print(f"✅ 【{'/'.join(keys)}】 => {a}")
    except Exception as e:
        logger.error(f"An error occurred during registration for {func.__name__}: {e}，{traceback.format_exc()}")

    # The decorator must return the original function
    return func


def task_wrapper(func):
    def wrapper(*args, **kwargs):
        from AutoScriptor.core.background import bg
        bg.clear(clear_signals=True)

        # 每个任务开始前清空调试截图目录，确保截图都属于当前任务
        from AutoScriptor.utils.tracer import clear_debug_screenshots
        clear_debug_screenshots()

        # 在任务执行前注入必要的导航符号到函数的全局命名空间
        func_globals = func.__globals__
        if 'ensure_in' not in func_globals:
            try:
                from ZmxyOL.nav import ensure_in
                from ZmxyOL.nav.envs.decorators import LOC_ENV
                from ZmxyOL.battle.character.hero import h
                from ZmxyOL.battle.tasks import get_task_table
                func_globals['ensure_in'] = ensure_in
                func_globals['LOC_ENV'] = LOC_ENV
                func_globals['h'] = h
                func_globals['get_task_table'] = get_task_table
                func_globals['locate_region'] = locate_region
            except Exception:
                pass

        return func(*args, **kwargs)
    return wrapper
