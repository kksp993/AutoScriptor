"""通用表格参数类型。

任务可以声明一个 ``TableParam`` 默认值，前端将以可编辑表格渲染，
后端序列化为 dict-of-dicts 的 JSON 格式便于持久化到 config。

典型用法::

    from AutoScriptor.utils.table_param import TableParam

    @register_task
    def task(
        battle_config: TableParam = TableParam(
            {
                "虎神之崖": {"difficulty": Nandu.不打, "cancel_on_failed": True},
                "苍龙幽谷": {"difficulty": Nandu.不打, "cancel_on_failed": True},
            },
            column_labels={"difficulty": "难度", "cancel_on_failed": "不用点券复活"},
        ),
    ):
        for name, row in battle_config.items():
            ...
"""

from __future__ import annotations

import enum
import importlib
from typing import Any, Iterator


class TableParam:
    """行=字符串键, 列=可配置属性 的表格参数。

    Parameters
    ----------
    data:
        ``{行键: {列键: 值, ...}, ...}``。值可以是 ``enum.Enum``、
        ``bool``、``int``/``float``、``str``。
    column_labels:
        ``{列键: 中文显示名}``，可选。前端在表头使用。
    """

    def __init__(
        self,
        data: dict[str, dict[str, Any]],
        column_labels: dict[str, str] | None = None,
    ) -> None:
        self._data: dict[str, dict[str, Any]] = data
        self._column_labels: dict[str, str] = column_labels or {}
        self._column_meta: dict[str, dict[str, Any]] = self._infer_columns()

    # ------------------------------------------------------------------
    # dict-like access
    # ------------------------------------------------------------------

    def __getitem__(self, key: str) -> dict[str, Any]:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    # ------------------------------------------------------------------
    # Column inference
    # ------------------------------------------------------------------

    def _infer_columns(self) -> dict[str, dict[str, Any]]:
        """从数据行推断各列的类型元信息。"""
        meta: dict[str, dict[str, Any]] = {}
        for row in self._data.values():
            for col_key, val in row.items():
                if col_key in meta:
                    continue
                if isinstance(val, enum.Enum):
                    meta[col_key] = {
                        "type": "enum",
                        "enum": f"{val.__class__.__module__}.{val.__class__.__qualname__}",
                    }
                elif isinstance(val, bool):
                    meta[col_key] = {"type": "bool"}
                elif isinstance(val, (int, float)):
                    meta[col_key] = {"type": "number"}
                else:
                    meta[col_key] = {"type": "string"}
            break  # 只需首行
        return meta

    # ------------------------------------------------------------------
    # Serialization (Python -> JSON config)
    # ------------------------------------------------------------------

    def to_json_data(self) -> dict[str, dict[str, Any]]:
        """将数据序列化为纯 JSON 可写格式（enum -> ``.name``）。"""
        result: dict[str, dict[str, Any]] = {}
        for row_key, row in self._data.items():
            out_row: dict[str, Any] = {}
            for col_key, val in row.items():
                if isinstance(val, enum.Enum):
                    out_row[col_key] = val.name
                else:
                    out_row[col_key] = val
            result[row_key] = out_row
        return result

    # ------------------------------------------------------------------
    # Deserialization (JSON config -> Python with enums)
    # ------------------------------------------------------------------

    @classmethod
    def from_json_data(
        cls,
        data: dict[str, dict[str, Any]],
        column_meta: dict[str, dict[str, Any]],
        column_labels: dict[str, str] | None = None,
    ) -> "TableParam":
        """从 JSON dict + 列元信息还原，把 enum 名字符串恢复为枚举实例。"""
        enum_classes: dict[str, type[enum.Enum]] = {}
        for col_key, col_info in column_meta.items():
            if col_info.get("type") == "enum" and "enum" in col_info:
                enum_classes[col_key] = _import_enum_class(col_info["enum"])

        restored: dict[str, dict[str, Any]] = {}
        for row_key, row in data.items():
            out_row: dict[str, Any] = {}
            for col_key, val in row.items():
                if col_key in enum_classes and isinstance(val, str):
                    ecls = enum_classes[col_key]
                    try:
                        out_row[col_key] = ecls[val]
                    except KeyError:
                        out_row[col_key] = next(iter(ecls))
                else:
                    out_row[col_key] = val
            restored[row_key] = out_row
        return cls(restored, column_labels=column_labels)

    # ------------------------------------------------------------------
    # param_meta generation (for task_register / WebUI)
    # ------------------------------------------------------------------

    def get_param_meta(self) -> dict[str, Any]:
        """返回供 ``task_register`` 存入 ``param_meta`` 的结构。"""
        return {
            "type": "table",
            "columns": dict(self._column_meta),
            "column_labels": dict(self._column_labels),
        }

    # ------------------------------------------------------------------
    # repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        rows = list(self._data.keys())
        return f"TableParam(rows={rows!r}, cols={list(self._column_meta.keys())!r})"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_enum_cache: dict[str, type[enum.Enum]] = {}


def _import_enum_class(dotted_path: str) -> type[enum.Enum]:
    """``'module.ClassName'`` -> enum 类。"""
    if dotted_path in _enum_cache:
        return _enum_cache[dotted_path]
    module_path, _, cls_name = dotted_path.rpartition(".")
    mod = importlib.import_module(module_path)
    cls = getattr(mod, cls_name)
    _enum_cache[dotted_path] = cls
    return cls
