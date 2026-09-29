import inspect
import os
from copy import deepcopy
from ZmxyOL import *
import enum
from AutoScriptor.utils.app_config import cfg
from tasks.task_registry import task_registry
from AutoScriptor.logging.logger import logger
from ZmxyOL.battle.table_param import TableParam
from tasks.translations import normalize_cfg_key
from tasks.task_params import describe_signature, hydrate_params
from ZmxyOL.nav.api import locate_region

# 在模块顶端添加全局计数器
registration_counter = 0
_CUSTOM_TASK_ROOT_KEY = normalize_cfg_key("custom_task")


def _find_cfg_leaf(root: dict, keys: list[str]) -> tuple[dict | None, dict | None]:
    node = root
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            return None, None
        node = child
    leaf = node.get(keys[-1]) if keys else None
    if isinstance(leaf, dict) and "on" in leaf:
        return node, leaf
    return None, None


def _remove_empty_cfg_branches(root: dict, keys: list[str]) -> None:
    stack = []
    node = root
    for key in keys:
        child = node.get(key)
        if not isinstance(child, dict):
            return
        stack.append((node, key, child))
        node = child
    for parent, key, child in reversed(stack):
        if child:
            break
        del parent[key]


def _migrate_cfg_leaf(legacy_keys: list[str] | None, normalized_keys: list[str]) -> None:
    """Move saved config from a task's former path onto its current path.

    Task paths change over time -- renames, regrouping -- while the config leaf
    holds user state that has to survive the move: the enabled flag, params,
    next_exec_time. A path still claimed by a live task is left alone, which is
    what makes migrating here, at registration time, safe to run on every load.
    """
    if not legacy_keys or legacy_keys == normalized_keys:
        return
    legacy_path = "/".join(legacy_keys)
    if task_registry.has_task(legacy_path):
        return

    tasks = cfg["tasks"]
    legacy_parent, legacy_leaf = _find_cfg_leaf(tasks, legacy_keys)
    if legacy_parent is None or legacy_leaf is None:
        return

    target_parent = tasks
    for key in normalized_keys[:-1]:
        target_parent = target_parent.setdefault(key, {})
    target_key = normalized_keys[-1]
    target_leaf = target_parent.get(target_key)
    if isinstance(target_leaf, dict) and "on" in target_leaf:
        for key, value in legacy_leaf.items():
            target_leaf.setdefault(key, deepcopy(value))
    else:
        target_parent[target_key] = deepcopy(legacy_leaf)

    del legacy_parent[legacy_keys[-1]]
    _remove_empty_cfg_branches(tasks, legacy_keys[:-1])




def register_task(
    func=None,
    *,
    default_offset_hours=None,
    beta=False,
    path_cn=None,
    legacy_path_cn=None,
    task_doc=None,
    description=None,
    debug_mode=False,
    deprecated=False,
    **task_kwargs,
):
    """
    装饰器：根据函数所在文件路径（'task' 目录下的子路径）注册任务。

    注册数据分两处存储：
      - cfg["tasks"]（用户配置，持久化到 JSON）：on、next_exec_time、params、next_exec_offset_hours 等
      - TaskRegistry（运行时数据，不持久化）：fn、order、param_meta、param_keys、beta、custom、doc_flow、description、debug_mode、deprecated

    内置任务的 cfg 路径由源码路径推导：目录名逐段翻译（daily_task → 每日任务、
    village → 村庄），文件名就是中文显示名，所以内置脚本不写 path_cn。

    支持以下可选参数（仅对指定任务生效）：
      - default_offset_hours (int): 任务执行后延迟 N 小时再调度
      - beta (bool): 为 True 时 WebUI 任务名旁显示 Beta 标记，说明区首行提示实验性任务
      - task_doc (str): 可选。WebUI 中「补充说明」正文；不传则从任务函数 docstring 首段提取
      - description (str): 可选。WebUI 任务简介（一句话）；不传则按任务名自动生成占位简介
      - debug_mode (bool): 调试直跑模式；执行时不强制回登录页重登，失败时不关闭/重启游戏，
        若本轮只执行 debug 任务，也跳过 post_execution 收尾动作。也兼容 debug=True 短写。
      - deprecated (bool): 弃用任务。源码和注册元数据保留，但不写入 cfg、不出现在 WebUI 或调度列表。
        已经存在的旧配置叶子由加载末尾的 catalog.prune_stale_tasks() 统一清理。
      - path_cn (str): **仅 custom_task 目录下脚本必填**，因为自定义脚本的文件名不受项目命名约定约束。
        斜杠分隔的 cfg 任务路径（中文键），custom_task 脚本最终都会归一到「自定义任务」根节点；
        省略首段时会自动补齐。示例：path_cn="自定义任务/示例/hello_custom"
        内置任务写了 path_cn 会覆盖推导结果，只在目录结构与树形不一致时才需要。
      - legacy_path_cn (str): 可选。任务改名/重组前使用的 cfg 路径。注册时会把该路径上已保存的
        用户配置（开关、参数、next_exec_time）搬到当前路径并删除旧节点，避免用户状态丢失；
        这是任务改名的唯一表述方式，加载流程里没有别的迁移通道。
        示例：legacy_path_cn="每日任务/荒古万界/每日任务"
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
                legacy_path_cn=legacy_path_cn,
                task_doc=task_doc,
                description=description,
                debug_mode=debug_mode,
                deprecated=deprecated,
                **task_kwargs,
            )
        return wrapper
    global registration_counter  # 引入全局计数器
    registration_counter += 1
    reg_order = registration_counter  # 当前注册顺序
    debug_mode = bool(debug_mode or task_kwargs.pop("debug", False))
    deprecated = bool(deprecated)
    module = inspect.getmodule(func)
    if module is not None and not hasattr(module, "ensure_in"):
        # 注入导航相关的符号
        from ZmxyOL.nav import ensure_in as _ensure_in
        from ZmxyOL.nav.envs.decorators import LOC_ENV
        from ZmxyOL.character.hero import h
        from ZmxyOL.battle.tasks import get_task_table
        setattr(module, "ensure_in", _ensure_in)
        setattr(module, "LOC_ENV", LOC_ENV)
        setattr(module, "h", h)
        setattr(module, "get_task_table", get_task_table)
        setattr(module, "locate_region", locate_region)

    filepath = inspect.getfile(func)
    path_parts = os.path.normpath(filepath).split(os.sep)

    is_custom = False
    if "custom_task" in path_parts:
        root_index = path_parts.index("custom_task")
        keys = path_parts[root_index + 1 :]
        is_custom = True
    elif "tasks" in path_parts:
        root_index = path_parts.index("tasks")
        keys = path_parts[root_index + 1 :]
    else:
        raise ValueError(
            f"任务注册失败: {func.__name__} 不在 tasks/ 或 custom_task/ 目录下: {filepath}"
        )

    filename = keys[-1]
    task_name, _ = os.path.splitext(filename)
    keys[-1] = task_name

    raw_cn = path_cn.strip() if isinstance(path_cn, str) else ""

    # 路径解析。源码树只提供默认值，path_cn 是唯一的显式声明入口；
    # legacy_keys 记录「这个任务以前在哪」，由 _migrate_cfg_leaf 在写入叶子前搬配置。
    legacy_keys = None
    if is_custom:
        if not raw_cn:
            raise ValueError(
                "custom_task 下的任务必须传入 path_cn，例如 "
                '@register_task(path_cn="自定义任务/示例/hello_custom")'
            )
        keys = [normalize_cfg_key(p) for p in raw_cn.split("/") if p.strip()]
        if not keys:
            raise ValueError(f"path_cn 解析后为空: {path_cn!r}")
        if keys[0] != _CUSTOM_TASK_ROOT_KEY:
            # 省略「自定义任务」根节点的写法：补上根节点后，写法里的路径就是前身。
            legacy_keys = list(keys)
            keys.insert(0, _CUSTOM_TASK_ROOT_KEY)
    elif raw_cn:
        keys = [normalize_cfg_key(p) for p in raw_cn.split("/") if p.strip()]
        if not keys:
            raise ValueError(f"path_cn 解析后为空: {path_cn!r}")
    else:
        # 目录名逐段翻成中文分类/分组，文件名本身已是中文显示名
        keys = [normalize_cfg_key(key) for key in keys]

    if legacy_path_cn:
        legacy_keys = [normalize_cfg_key(p) for p in str(legacy_path_cn).split("/") if p.strip()]

    last_key = keys[-1]
    task_path = "/".join(keys)

    # cfg["tasks"] 只存用户配置（on、next_exec_time、params 等），结构由注册声明产生：
    # deprecated 任务不写叶子，改名任务先把前身路径上的用户状态搬过来。
    # 没有任务认领的残留叶子不在这里删——统一交给 catalog.prune_stale_tasks()。
    task_cfg = None
    if not deprecated:
        if legacy_keys:
            _migrate_cfg_leaf(legacy_keys, keys)
        current_level = cfg["tasks"]
        for key in keys[:-1]:
            current_level = current_level.setdefault(key, {})

        # 首次写入某任务叶节点时默认关闭，避免新建账号/角色时空任务树被全部点亮
        if last_key not in current_level:
            current_level[last_key] = {"on": False, "next_exec_time": 0}
        else:
            current_level[last_key].setdefault("on", True)
            current_level[last_key].setdefault("next_exec_time", 0)
        if default_offset_hours is not None:
            current_level[last_key]["next_exec_offset_hours"] = default_offset_hours
        for key, value in task_kwargs.items():
            current_level[last_key][key] = value
        task_cfg = current_level[last_key]

    doc_flow = ""
    if task_doc is not None and str(task_doc).strip():
        doc_flow = str(task_doc).strip()
    else:
        raw = inspect.getdoc(func) or ""
        if raw.strip():
            doc_flow = raw.strip().split("\n\n")[0].strip()

    # 参数分两处：specs 是运行时契约（表单描述 + 执行解码），params 是用户在 cfg 里的值。
    # 两者的换算全部由 tasks.task_params 承担，这里不按参数类型分支。
    param_specs = describe_signature(func)
    if task_cfg is not None:
        saved_params = task_cfg.get("params")
        task_cfg["params"] = hydrate_params(
            param_specs, saved_params if isinstance(saved_params, dict) else {}
        )

    # fn / order / param_meta 注册到 TaskRegistry（运行时数据，不写入 JSON）
    desc = (description or "").strip() if description is not None else ""
    if not desc:
        desc = f"自动执行「{last_key}」相关流程。"
    task_registry.register(
        task_path,
        task_wrapper(func),
        reg_order,
        param_specs,
        beta=beta,
        custom=is_custom,
        doc_flow=doc_flow,
        description=desc,
        debug_mode=debug_mode,
        deprecated=deprecated,
    )

    # The decorator must return the original function
    return func


def _apply_task_battle_startup(kwargs: dict) -> None:
    """任务函数执行前：加载配招职业，并把 WebUI 中的 battle_flow 挂到 h 上供 battle_loop 等使用。"""
    from ZmxyOL.character.hero import h
    from tasks.battle_task_params import get_battle_profile, resolve_battle_flow_for_profile
    get_battle_profile(h)
    h.task_context_battle_flow = resolve_battle_flow_for_profile(
        h,
        getattr(kwargs.get("battle_flow"), "value", None),
    )


def _clear_task_battle_startup() -> None:
    from ZmxyOL.character.hero import h
    h.task_context_battle_flow = None


def task_wrapper(func):
    def wrapper(*args, **kwargs):
        from AutoScriptor.core.background import bg
        bg.clear(clear_signals=True)

        # 每个任务开始前清空调试截图目录，这样归档里的 debug_screenshots/
        # 只属于失败的那个任务，而不是整批任务混在一起。
        from AutoScriptor.logging.tracer import clear_debug_screenshots
        clear_debug_screenshots()

        # 在任务执行前注入必要的导航符号到函数的全局命名空间
        func_globals = func.__globals__
        if 'ensure_in' not in func_globals:
            from ZmxyOL.nav import ensure_in
            from ZmxyOL.nav.envs.decorators import LOC_ENV
            from ZmxyOL.character.hero import h
            from ZmxyOL.battle.tasks import get_task_table
            func_globals['ensure_in'] = ensure_in
            func_globals['LOC_ENV'] = LOC_ENV
            func_globals['h'] = h
            func_globals['get_task_table'] = get_task_table
            func_globals['locate_region'] = locate_region

        _apply_task_battle_startup(kwargs)
        try:
            return func(*args, **kwargs)
        finally:
            _clear_task_battle_startup()
    return wrapper
