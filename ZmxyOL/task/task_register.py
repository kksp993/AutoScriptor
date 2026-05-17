    
import inspect
import os
import traceback
from ZmxyOL import *
import enum
from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.task_registry import task_registry
from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.table_param import TableParam
from ZmxyOL.task.translations import normalize_cfg_key, normalize_to_cn
from ZmxyOL.nav.api import locate_region

# 在模块顶端添加全局计数器
registration_counter = 0

 


def register_task(
    func=None,
    *,
    default_offset_hours=None,
    beta=False,
    path_cn=None,
    task_doc=None,
    description=None,
    debug_mode=False,
    **task_kwargs,
):
    """
    装饰器：根据函数所在文件路径（'task' 目录下的子路径）注册任务。

    注册数据分两处存储：
      - cfg["tasks"]（用户配置，持久化到 JSON）：on、next_exec_time、params、next_exec_offset_hours
      - TaskRegistry（运行时数据，不持久化）：fn、order、param_meta、beta

    支持以下可选参数（仅对指定任务生效）：
      - default_offset_hours (int): 任务执行后延迟 N 小时再调度
      - beta (bool): 为 True 时 WebUI 任务名旁显示 Beta 标记，说明区首行提示实验性任务
      - task_doc (str): 可选。WebUI 中「补充说明」正文；不传则从任务函数 docstring 首段提取
      - description (str): 可选。WebUI 任务简介（一句话）；不传则按任务名自动生成占位简介
      - debug_mode (bool): 调试直跑模式；执行时不强制回登录页重登，失败时不关闭/重启游戏，
        若本轮只执行 debug 任务，也跳过 post_execution 收尾动作。也兼容 debug=True 短写。
      - path_cn (str): **仅 custom_task 目录下脚本必填**。斜杠分隔的 cfg 任务路径（中文键），
        首段一般为「自定义任务」或与目录对应的英文名（如 custom_task 会规范为「自定义任务」）。
        示例：path_cn="自定义任务/示例/hello_custom"
      - sched_window_hours (tuple[int,int]): 本地时间可执行时段 [start, end)，如 (10, 22)；
        调度器在时段外不会执行该任务，执行后 next_exec_time 也会落在时段内
      - allowed_weekdays (list[int]): 仅在这些星期可执行，cfg 约定 1=周一 … 7=周日（如 [6,7] 为周六日）；
        到期但不在允许日时，调度器会推迟 next_exec_time 至下一允许日的 5:00
      - 任务函数若声明参数 battle_flow（BattleFlowName）：执行前由框架注入 get_battle_profile(h)，
        并把所选流程名写入 h.task_context_battle_flow；battle_loop / jjc_battle / battle_task 等
        在未显式传入 flow_name 时将使用该值。WebUI 下拉选项来自 Hero @flow 注册名；若某流程仅带 task= 注册，
        则仅对 cfg 路径最后一级与该 task 名一致的任务显示（见 battle_task_params.battle_flow_allowed_for_task）。
      - 其他任意元数据参数 (key=value): 写入 cfg 配置节点

    用法示例：
      @register_task(default_offset_hours=10)
      def task():
          ...
    """
    if func is None:
        def wrapper(f):
            return register_task(
                f,
                default_offset_hours=default_offset_hours,
                beta=beta,
                path_cn=path_cn,
                task_doc=task_doc,
                description=description,
                debug_mode=debug_mode,
                **task_kwargs,
            )
        return wrapper
    global registration_counter  # 引入全局计数器
    registration_counter += 1
    reg_order = registration_counter  # 当前注册顺序
    debug_mode = bool(debug_mode or task_kwargs.pop("debug", False))
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
        filepath = inspect.getfile(func)

        # 2. Normalize and split path segments
        norm_path = os.path.normpath(filepath)
        path_parts = norm_path.split(os.sep)

        is_custom = False
        # 3a. User scripts under .../custom_task/... → cfg 树顶「自定义任务」
        if "custom_task" in path_parts:
            root_index = path_parts.index("custom_task")
            keys = path_parts[root_index + 1 :]
            is_custom = True
        # 3b. Built-in: .../task/...
        elif "task" in path_parts:
            root_index = path_parts.index("task")
            keys = path_parts[root_index + 1 :]
        else:
            print(
                f"Error: Neither 'custom_task' nor 'task' directory was found in the path for {func.__name__}. Registration failed."
            )
            return func

        # 4. Last segment is filename → stem
        filename = keys[-1]
        task_name, _ = os.path.splitext(filename)
        keys[-1] = task_name

        if is_custom:
            raw_cn = path_cn.strip() if isinstance(path_cn, str) else ""
            if not raw_cn:
                logger.error(
                    "custom_task 下的任务必须传入 path_cn，例如 "
                    '@register_task(path_cn="自定义任务/示例/hello_custom")'
                )
                return func
            keys = [normalize_cfg_key(p) for p in raw_cn.split("/") if p.strip()]
            if not keys:
                logger.error("path_cn 解析后为空: %r", path_cn)
                return func
        else:
            keys = [normalize_to_cn(key) for key in keys]

        # 6. Traverse cfg["tasks"], creating nested dicts for the path.
        current_level = cfg["tasks"]
        for key in keys[:-1]:
            current_level = current_level.setdefault(key, {})

        # 7. cfg["tasks"] 只存用户配置（on、next_exec_time、params 等）
        # 首次写入某任务叶节点时默认关闭，避免新建账号/角色时空任务树被全部点亮
        last_key = keys[-1]
        if last_key not in current_level:
            current_level[last_key] = {'on': False, 'next_exec_time': 0}
        else:
            current_level[last_key].setdefault('on', True)
            current_level[last_key].setdefault('next_exec_time', 0)
        if default_offset_hours is not None:
            current_level[last_key]['next_exec_offset_hours'] = default_offset_hours
        for key, value in task_kwargs.items():
            current_level[last_key][key] = value

        doc_flow = ""
        if task_doc is not None and str(task_doc).strip():
            doc_flow = str(task_doc).strip()
        else:
            raw = inspect.getdoc(func) or ""
            if raw.strip():
                doc_flow = raw.strip().split("\n\n")[0].strip()

        # 解析函数签名，提取参数默认值和枚举元数据
        sig = inspect.signature(func)
        defaults = {}
        param_meta = {}
        for name, param in sig.parameters.items():
            if param.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL):
                continue
            default = param.default if param.default is not inspect._empty else None
            if isinstance(default, TableParam):
                defaults[name] = default.to_json_data()
                param_meta[name] = default.get_param_meta()
            elif isinstance(default, enum.Enum):
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
        # 仅保留当前签名中的参数名，丢弃已迁移的旧键（如独立难度、battle_flow 等）
        task_cfg['params'] = {k: merged_params[k] for k in defaults}

        # 8. fn / order / param_meta 注册到 TaskRegistry（运行时数据，不写入 JSON）
        task_path = "/".join(keys)
        desc = (description or "").strip() if description is not None else ""
        if not desc:
            desc = f"自动执行「{last_key}」相关流程。"
        task_registry.register(
            task_path,
            task_wrapper(func),
            reg_order,
            param_meta,
            param_keys=list(defaults.keys()),
            beta=beta,
            custom=is_custom,
            doc_flow=doc_flow,
            description=desc,
            debug_mode=debug_mode,
        )
        # print(f"✅ 【{'/'.join(keys)}】 => {a}")
    except Exception as e:
        logger.error(f"An error occurred during registration for {func.__name__}: {e}，{traceback.format_exc()}")

    # The decorator must return the original function
    return func


def _apply_task_battle_startup(kwargs: dict) -> None:
    """任务函数执行前：加载配招职业，并把 WebUI 中的 battle_flow 挂到 h 上供 battle_loop 等使用。"""
    try:
        from ZmxyOL.battle.character.hero import h
        from ZmxyOL.task.battle_task_params import get_battle_profile
        get_battle_profile(h)
        h.task_context_battle_flow = getattr(kwargs.get("battle_flow"), "value", None)
    except Exception:
        pass


def _clear_task_battle_startup() -> None:
    try:
        from ZmxyOL.battle.character.hero import h
        h.task_context_battle_flow = None
    except Exception:
        pass


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

        _apply_task_battle_startup(kwargs)
        try:
            return func(*args, **kwargs)
        finally:
            _clear_task_battle_startup()
    return wrapper
