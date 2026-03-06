    
import inspect
import os
import traceback
from ZmxyOL import *
import enum
from AutoScriptor.utils.constant import cfg
from logzero import logger
from ZmxyOL.task.translations import normalize_to_cn
from ZmxyOL.nav.api import locate_region

# 在模块顶端添加全局计数器
registration_counter = 0

 


def register_task(func=None, *, default_offset_hours=None, **task_kwargs):
    """
    装饰器：根据函数所在文件路径（'task' 目录下的子路径）将任务注册到全局 cfg["tasks"]。

    支持以下可选参数（仅对指定任务生效）：
      - default_offset_hours (int): 任务执行后延迟 N 小时再调度，写入 next_exec_offset_hours。
      - 其他任意元数据参数 (key=value): 会原样写入到任务的配置节点，方便扩展。

    保留 cfg 中的任务字段（自动管理，无需手动指定）：
      - fn: 任务函数（内部包装）
      - on: 是否启用（布尔）
      - next_exec_time: 下次执行的 Unix 时间戳
      - order: 注册顺序（整数，控制菜单排序）

    扩展字段：
      - next_exec_offset_hours: 自定义冷却时长（小时）
      - 其他自定义字段：在装饰器中以 key=value 形式传入并存储

    用法示例：
      @register_task(default_offset_hours=10, priority="high", category="village")
      def task():
          ...
    """
    if func is None:
        # Decorator called with arguments
        def wrapper(f):
            return register_task(f, default_offset_hours=default_offset_hours)
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
        if default_offset_hours is not None:
            current_level[last_key]['next_exec_offset_hours'] = default_offset_hours
        # 存储其他自定义参数
        for key, value in task_kwargs.items():
            current_level[last_key][key] = value
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
