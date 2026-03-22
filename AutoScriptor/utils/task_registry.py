"""
TaskRegistry: 任务运行时注册表（与 cfg 解耦）
=============================================
存储任务的运行时数据（fn、order、param_meta），与 cfg["tasks"] 中的
用户配置（on、next_exec_time、params）分离。

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

    def register(self, path: str, fn, order: int, param_meta: dict | None = None):
        self._tasks[path] = {
            "fn": fn,
            "order": order,
            "param_meta": param_meta or {},
        }

    def get_fn(self, path: str):
        entry = self._tasks.get(path)
        return entry["fn"] if entry else None

    def get_order(self, path: str) -> int | float:
        entry = self._tasks.get(path)
        return entry["order"] if entry else float("inf")

    def get_param_meta(self, path: str) -> dict:
        entry = self._tasks.get(path)
        return entry.get("param_meta", {}) if entry else {}

    def set_fn(self, path: str, fn):
        if path in self._tasks:
            self._tasks[path]["fn"] = fn

    def has_task(self, path: str) -> bool:
        return path in self._tasks

    def all_paths(self) -> list[str]:
        return list(self._tasks.keys())

    def items(self):
        return self._tasks.items()

    def clear(self):
        self._tasks.clear()


task_registry = TaskRegistry()
