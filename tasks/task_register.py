"""任务注册：一个任务是什么，以及它注册到哪里。

一个任务就是被 ``@register_task`` 装饰的函数。作者的声明只有五个字段，都是装饰器形参：

- ``id``：身份。``cfg["tasks"]`` 和 ``task_ordering`` 都以它为键，所以用户配置、拖拽顺序
  都跟着它走。不写就取**任务名**（文件名去掉 ``.py``）；**换目录不改变任务名**，所以移动
  任务不需要动它，只有重命名文件才需要写 ``id="旧任务名"`` 把身份钉住。
- ``reschedule``：下次什么时候再来，见 ``tasks.task_schedule``。不写就是一次性。
- ``debug``：调试直跑的默认值，用户在 WebUI 里可以覆盖。
- ``description``：一句话简介。长说明写在函数 docstring 里，不用参数。
- ``deprecated``：系统属性。源码和元数据保留，但不写配置、不进 UI。

声明落在两张表里，边界是「能不能进 JSON」：

- ``cfg["tasks"]``：用户数据。以 ``id`` 为键的平表，条目里只放 ``on``、``next_exec_time``、
  ``params``、用户覆盖的 ``reschedule``/``debug``，以及任务自己的私有字段。
- ``TaskRegistry``：进程内对象。``fn``、参数 spec、``description``、``doc_flow`` 和系统标记，
  不进 JSON，每次任务加载重建。

身份和位置是两件事：身份是任务名，位置（显示路径）是它现在待在哪个目录。内置任务的显示路径
是它在 ``tasks/`` 下的相对路径，自定义任务是它在 ``data/custom_task/`` 下的相对路径，
两者逐段同名，中间没有映射表。目录只是分组，随时可以调整；配置和顺序认的是任务名。
两个任务不允许同名，撞名会在注册时直接报错。
"""
import inspect
import os

from ZmxyOL import *
from AutoScriptor.utils.app_config import cfg
from tasks.task_params import ParamSpec, describe_signature, hydrate_params
from tasks.task_schedule import RescheduleError, normalize_reschedule


class TaskRegistry:
    """任务运行时元数据表：显示路径 -> 该任务的声明。

    表以 ``path`` 为键，因为读它的每一处（调度、投影、WebUI 树）都在说路径。``id``
    存在条目里，是唯一能跨目录移动和文件重命名活下去的东西，用户配置和排序都以它为键，所以
    ``get_id`` / ``get_path`` 是这两套身份之间的桥。

    唯一性由模块级的 ``task_registry`` 实例保证：模块对象在 reload 时被替换，但读者
    始终从 ``tasks.task_register`` 导入同一个实例，所以注册表只有一份。
    """

    def __init__(self):
        self._tasks: dict[str, dict] = {}

    def register(
        self,
        path: str,
        fn,
        param_specs: dict[str, ParamSpec] | None = None,
        *,
        task_id: str | None = None,
        sequence: int = 0,
        custom: bool = False,
        doc_flow: str = "",
        description: str = "",
        reschedule: dict | None = None,
        debug: bool = False,
        deprecated: bool = False,
    ):
        resolved_id = (task_id or path.rsplit("/", 1)[-1]).strip()
        if not resolved_id:
            raise ValueError(f"任务 id 不能为空: path={path!r}")
        owner = self.get_path(resolved_id)
        if owner is not None and owner != path:
            raise ValueError(
                f"任务 id 重复: {resolved_id!r} 同时被 {owner!r} 和 {path!r} 使用"
            )
        self._tasks[path] = {
            "id": resolved_id,
            "fn": fn,
            "sequence": int(sequence),
            "param_specs": dict(param_specs) if param_specs else {},
            "custom": bool(custom),
            "doc_flow": (doc_flow or "").strip(),
            "description": (description or "").strip(),
            "reschedule": reschedule,
            "debug": bool(debug),
            "deprecated": bool(deprecated),
        }

    def get_id(self, path: str) -> str | None:
        """任务路径对应的稳定身份，未注册时为 None。"""
        entry = self._visible_entry(path)
        return entry["id"] if entry else None

    def get_path(self, task_id: str) -> str | None:
        """稳定身份当前的显示路径，未注册时为 None。条目不多，直接扫。"""
        for path, entry in self._tasks.items():
            if entry.get("id") == task_id:
                return path
        return None

    def id_of(self, path: str) -> str:
        """路径 -> 身份，未注册时回落到路径本身。写 cfg 前用它归一键。"""
        return self.get_id(path) or path

    def all_ids(self, include_deprecated: bool = False) -> list[str]:
        return [
            entry["id"]
            for entry in self._tasks.values()
            if include_deprecated or not entry.get("deprecated")
        ]

    def id_to_path_map(self, include_deprecated: bool = True) -> dict[str, str]:
        """身份 -> 当前显示路径，供 overlay 换键用。"""
        return {
            entry["id"]: path
            for path, entry in self._tasks.items()
            if entry.get("id") and (include_deprecated or not entry.get("deprecated"))
        }

    def path_to_id_map(self, include_deprecated: bool = True) -> dict[str, str]:
        """显示路径 -> 身份，供 overlay 换键用。"""
        return {
            path: entry["id"]
            for path, entry in self._tasks.items()
            if entry.get("id") and (include_deprecated or not entry.get("deprecated"))
        }

    def _visible_entry(self, path: str):
        entry = self._tasks.get(path)
        return entry if entry and not entry.get("deprecated") else None

    def get_fn(self, path: str):
        entry = self._visible_entry(path)
        return entry["fn"] if entry else None

    def get_sequence(self, path: str) -> int | float:
        """注册序号。默认顺序就是导入顺序，导入顺序由源码路径排序决定。"""
        entry = self._visible_entry(path)
        return entry["sequence"] if entry else float("inf")

    def get_param_specs(self, path: str) -> dict[str, ParamSpec]:
        """参数名 -> ParamSpec。默认值、表单描述和执行解码都从这里出发。"""
        entry = self._visible_entry(path)
        return dict(entry.get("param_specs", {})) if entry else {}

    def get_param_meta(self, path: str) -> dict:
        """WebUI 表单描述。选项按任务路径裁剪，所以要把路径传下去。"""
        return {
            name: spec.describe(path)
            for name, spec in self.get_param_specs(path).items()
        }

    def get_param_keys(self, path: str) -> list[str]:
        """当前任务函数签名中的参数名（不含 * / **），用于丢弃 cfg 中已迁移的旧键。"""
        return list(self.get_param_specs(path))

    def get_custom(self, path: str) -> bool:
        entry = self._visible_entry(path)
        return bool(entry.get("custom")) if entry else False

    def get_doc_flow(self, path: str) -> str:
        entry = self._visible_entry(path)
        return (entry.get("doc_flow") or "").strip() if entry else ""

    def get_description(self, path: str) -> str:
        entry = self._visible_entry(path)
        return (entry.get("description") or "").strip() if entry else ""

    def get_reschedule_default(self, path: str) -> dict | None:
        """作者声明的调度。用户没覆盖时用它。"""
        entry = self._visible_entry(path)
        return entry.get("reschedule") if entry else None

    def get_debug_default(self, path: str) -> bool:
        """作者声明的 debug 默认值。用户没覆盖时用它。"""
        entry = self._visible_entry(path)
        return bool(entry.get("debug")) if entry else False

    def set_fn(self, path: str, fn):
        if path in self._tasks:
            self._tasks[path]["fn"] = fn

    def has_task(self, path: str) -> bool:
        return self._visible_entry(path) is not None

    def all_paths(self, include_deprecated: bool = False) -> list[str]:
        if include_deprecated:
            return list(self._tasks.keys())
        return [path for path, entry in self._tasks.items() if not entry.get("deprecated")]

    def items(self, include_deprecated: bool = False):
        if include_deprecated:
            return self._tasks.items()
        return ((path, entry) for path, entry in self._tasks.items() if not entry.get("deprecated"))

    def clear(self):
        self._tasks.clear()


task_registry = TaskRegistry()

# 注册顺序计数器
registration_counter = 0

# 自定义任务的显示路径都挂在这个根节点下。
_CUSTOM_TASK_ROOT_KEY = "自定义任务"

# 官方字段：只能出现在装饰器形参里，不许走私有 key=value。
OFFICIAL_TASK_FIELDS = ("id", "reschedule", "debug", "description", "deprecated")

# 用户数据字段：cfg 条目里允许存在的键（系统写或用户在 WebUI 覆盖）。
USER_TASK_FIELDS = ("on", "next_exec_time", "params", "reschedule", "debug")

# 旧版本遗留键：注册时从 cfg 条目里删掉，不让废弃字段继续躺在用户配置里。
LEGACY_TASK_FIELDS = (
    "next_exec_offset_hours",
    "sched_window_hours",
    "allowed_weekdays",
    "debug_mode",
    "beta",
    "order",
    "param_meta",
    "param_keys",
    "task_description",
    "task_doc_flow",
    "fn",
    "_due",
    "progress_display",
)


def register_task(
    func=None,
    *,
    id=None,
    reschedule=None,
    debug=False,
    description=None,
    deprecated=False,
    **task_private,
):
    """
    装饰器：按任务的源码位置注册任务。

    显示路径由源码位置决定：内置任务是它在 ``tasks/`` 下的相对路径，自定义任务是它在
    ``data/custom_task/`` 下的相对路径。例如 ``tasks/每日任务/村庄/宠物培养.py`` 注册为
    ``每日任务/村庄/宠物培养``；自定义任务额外挂在「自定义任务」根节点下。路径逐段同名，
    中间没有映射表。目录只决定显示位置，换目录不影响用户数据。

    作者的声明只有五个字段：
      - id (str): 任务身份，``cfg["tasks"]`` 和 ``task_ordering`` 的键。不传时取任务名
        （文件名去掉 ``.py``），所以新建任务和移动目录都不用写；只有重命名文件时才写
        ``id="旧任务名"`` 把身份钉在旧值上，用户配置、拖拽顺序和运行状态就跟着走。
      - reschedule: 下次什么时候再来。不写 = 一次性（执行成功后关闭）；``"daily"`` = 下个 05:00；
        ``"weekly"`` = 下周一 05:00；整数 = N 小时后；需要窗口或星期时写
        ``{"mode": "daily", "window": (10, 22), "weekdays": [5, 6, 7]}``。
        完整规则见 ``tasks.task_schedule``。用户可在 WebUI 里覆盖。
      - debug (bool): 调试直跑的默认值。执行时不强制回登录页重登，失败时不关闭/重启游戏；
        若本轮只执行 debug 任务，也跳过 post_execution 收尾动作。用户可在 WebUI 里覆盖。
      - description (str): 一句话简介，显示在任务列表。不传时取函数 docstring 首行；
        长说明直接写在函数 docstring 里，不需要额外参数。
      - deprecated (bool): 系统属性。源码和注册元数据保留，但不写配置、不出现在 WebUI 或
        调度列表；已存在的旧条目由加载末尾的 catalog.prune_stale_tasks() 清理。

    其余 key=value 只用于任务私有数据（例如 ``last_buy_time``），原样写进 cfg 条目。
    它不认识官方字段名：写成 ``okder=1`` 这种拼错的官方参数会直接报错，不会静默留在用户配置里。

    用法示例：
      @register_task(reschedule="daily")
      def task():
          ...
    """
    if func is None:
        def wrapper(inner):
            return register_task(
                inner,
                id=id,
                reschedule=reschedule,
                debug=debug,
                description=description,
                deprecated=deprecated,
                **task_private,
            )
        return wrapper

    # 私有字段不许冒用官方或用户字段名：撞名说明参数写错了。
    clashes = sorted(set(task_private) & (set(OFFICIAL_TASK_FIELDS) | set(USER_TASK_FIELDS)))
    if clashes:
        raise TypeError(
            f"@register_task 不认识这些参数: {clashes}；官方字段只有 "
            f"{list(OFFICIAL_TASK_FIELDS)}，其余 key=value 只用于任务私有数据"
        )

    normalized_reschedule = normalize_reschedule(reschedule)   # 非法写法当场报错
    debug_default = bool(debug)
    deprecated = bool(deprecated)

    global registration_counter
    registration_counter += 1   # 注册序号：默认顺序 = 导入顺序 = 源码路径排序

    filepath = inspect.getfile(func)
    path_parts = os.path.normpath(filepath).split(os.sep)

    if "custom_task" in path_parts:
        keys = path_parts[path_parts.index("custom_task") + 1 :]
        keys.insert(0, _CUSTOM_TASK_ROOT_KEY)   # 自定义任务的显示路径统一挂在这个根下
        is_custom = True
    elif "tasks" in path_parts:
        keys = path_parts[path_parts.index("tasks") + 1 :]
        is_custom = False
    else:
        raise ValueError(
            f"任务注册失败: {func.__name__} 不在 tasks/ 或 custom_task/ 目录下: {filepath}"
        )

    keys[-1] = os.path.splitext(keys[-1])[0]
    last_key = keys[-1]
    task_path = "/".join(keys)

    # 身份是任务名，不是路径：换目录不改任务名，所以移动任务不动用户数据。
    task_id = (id.strip() if isinstance(id, str) else "") or last_key

    # cfg["tasks"] 是以 id 为键的平表：只存用户数据。树形只是 UI 视图，由显示路径拼出，
    # 不落盘，所以改名和换分组都不动用户数据。deprecated 任务不写条目；没有任务认领的
    # 残留条目不在这里删，统一交给 catalog.prune_stale_tasks()。
    task_cfg = None
    if not deprecated:
        task_table = cfg["tasks"]
        if not isinstance(task_table, dict):
            raise ValueError(f"cfg['tasks'] 不是字典: {type(task_table).__name__}")
        nested = [key for key, value in task_table.items() if isinstance(value, dict) and "on" not in value]
        if nested:
            raise ValueError(
                f"cfg['tasks'] 仍是树形（{nested[:3]}），注册前要先跑 "
                "orchestrator.catalog.normalize_task_table()"
            )

        entry = task_table.get(task_id)
        if not isinstance(entry, dict) or "on" not in entry:
            # 首次写入某任务时默认关闭，避免新建账号/角色时整表被点亮
            entry = {"on": False, "next_exec_time": 0}
        else:
            entry.setdefault("next_exec_time", 0)
        for legacy_field in LEGACY_TASK_FIELDS:
            entry.pop(legacy_field, None)   # 旧字段就地清掉，废弃参数不留痕
        for key, value in task_private.items():
            entry[key] = value
        task_table[task_id] = entry
        task_cfg = entry

    # 长说明就是函数 docstring；description 是一句话简介，取参数或 docstring 首行。
    doc_flow = (inspect.getdoc(func) or "").strip()
    desc = (description or "").strip() if description is not None else ""
    if not desc:
        desc = doc_flow.split("\n", 1)[0].strip() if doc_flow else f"自动执行「{last_key}」相关流程。"

    # 参数分两处：specs 是运行时契约（表单描述 + 执行解码），params 是用户在 cfg 里的值。
    # 两者的换算全部由 tasks.task_params 承担，这里不按参数类型分支。
    param_specs = describe_signature(func)
    if task_cfg is not None:
        saved_params = task_cfg.get("params")
        task_cfg["params"] = hydrate_params(
            param_specs, saved_params if isinstance(saved_params, dict) else {}
        )

    task_registry.register(
        task_path,
        task_wrapper(func),
        param_specs,
        task_id=task_id,
        sequence=registration_counter,
        custom=is_custom,
        doc_flow=doc_flow,
        description=desc,
        reschedule=normalized_reschedule,
        debug=debug_default,
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

        _apply_task_battle_startup(kwargs)
        try:
            return func(*args, **kwargs)
        finally:
            _clear_task_battle_startup()
    return wrapper
