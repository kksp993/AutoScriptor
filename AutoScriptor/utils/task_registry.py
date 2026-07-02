"""
TaskRegistry: 任务运行时注册表（与 cfg 解耦）
=============================================
存储任务的运行时数据（fn、order、param_meta、param_keys、beta、
custom、doc_flow、description、debug_mode、deprecated），与 cfg["tasks"] 中的用户配置
（on、next_exec_time、params）分离。

cfg["tasks"] 仅保存可序列化的用户配置，TaskRegistry 保存不可序列化的
运行时数据。两者通过 slash 分隔的任务路径关联。

路径格式: "每日任务/村庄/宠物培养"
"""


class TaskRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tasks = {}
        return cls._instance

    def register(
        self,
        path: str,
        fn,
        order: int,
        param_meta: dict | None = None,
        *,
        param_keys: list[str] | None = None,
        beta: bool = False,
        custom: bool = False,
        doc_flow: str = "",
        description: str = "",
        debug_mode: bool = False,
        deprecated: bool = False,
    ):
        self._tasks[path] = {
            "fn": fn,
            "order": order,
            "param_meta": param_meta or {},
            "param_keys": list(param_keys) if param_keys else [],
            "beta": bool(beta),
            "custom": bool(custom),
            "doc_flow": (doc_flow or "").strip(),
            "description": (description or "").strip(),
            "debug_mode": bool(debug_mode),
            "deprecated": bool(deprecated),
        }

    def _visible_entry(self, path: str):
        entry = self._tasks.get(path)
        return entry if entry and not entry.get("deprecated") else None

    def get_fn(self, path: str):
        entry = self._visible_entry(path)
        return entry["fn"] if entry else None

    def get_order(self, path: str) -> int | float:
        entry = self._visible_entry(path)
        return entry["order"] if entry else float("inf")

    def get_param_meta(self, path: str) -> dict:
        entry = self._visible_entry(path)
        return entry.get("param_meta", {}) if entry else {}

    def get_param_keys(self, path: str) -> list[str]:
        """当前任务函数签名中的参数名（不含 * / **），用于丢弃 cfg 中已迁移的旧键。"""
        entry = self._visible_entry(path)
        return list(entry.get("param_keys", [])) if entry else []

    def get_beta(self, path: str) -> bool:
        entry = self._visible_entry(path)
        return bool(entry.get("beta")) if entry else False

    def get_custom(self, path: str) -> bool:
        entry = self._visible_entry(path)
        return bool(entry.get("custom")) if entry else False

    def get_doc_flow(self, path: str) -> str:
        entry = self._visible_entry(path)
        return (entry.get("doc_flow") or "").strip() if entry else ""

    def get_description(self, path: str) -> str:
        entry = self._visible_entry(path)
        return (entry.get("description") or "").strip() if entry else ""

    def get_debug_mode(self, path: str) -> bool:
        entry = self._visible_entry(path)
        return bool(entry.get("debug_mode")) if entry else False

    def get_deprecated(self, path: str) -> bool:
        entry = self._tasks.get(path)
        return bool(entry.get("deprecated")) if entry else False

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
