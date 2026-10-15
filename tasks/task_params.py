"""任务参数的表单契约：任务函数的参数 ↔ JSON 配置 ↔ WebUI 表单。

一个参数在三个地方出现：

1. 注册时写进 ``cfg["tasks"][..]["params"]`` 的 JSON 默认值；
2. WebUI 表单要渲染的控件类型和可选项；
3. 执行前把 cfg 里存的值还原成传给函数的 Python 实参。

这三件事以前各自实现：注册按分支推出「枚举类点分字符串」，执行时再
``importlib`` 把它换回类，后端接口第三次 ``importlib`` 去数成员，前端再按三种
meta 形状各写一套。同一个事实推导四遍，任一处改动都会和其余三处错位。

这里收敛成一个 ``ParamSpec``：``describe_signature(fn)`` 生成一次，之后三处共用。
枚举类和 ``TableParam`` 原型始终以对象形式持在内存里（``TaskRegistry``），
点分字符串不再出现在任何转换链路上。

``describe()`` 是唯一的对外形状，用 ``type`` 判别：

    {"type": "value"}
    {"type": "enum",      "options": [{"value": "成员名", "label": "显示名"}, ...]}
    {"type": "enum_list", "options": [...]}
    {"type": "table", "columns": {列: <enum 描述>}, "column_labels": {列: 中文名}}
"""
from __future__ import annotations

import enum
import inspect
from copy import deepcopy
from typing import Any, Callable

from ZmxyOL.battle.table_param import TableParam


# 枚举 → 可选项的过滤钩子。默认展示全部；需要按任务裁剪的枚举（例如只有部分
# 任务适用的战斗流程）由拥有该概念的模块自己注册，而不是在 HTTP 层特判类名。
_OPTION_FILTERS: dict[type[enum.Enum], Callable[[Any, str | None], bool]] = {}


def set_enum_option_filter(
    enum_class: type[enum.Enum],
    is_allowed: Callable[[Any, str | None], bool],
) -> None:
    """为某个枚举登记「该成员是否适用于这个任务」的判定。"""
    _OPTION_FILTERS[enum_class] = is_allowed


def _enum_options(enum_class: type[enum.Enum], task_path: str | None) -> list[dict[str, str]]:
    is_allowed = _OPTION_FILTERS.get(enum_class)
    options = []
    for member in enum_class:
        if is_allowed is not None and not is_allowed(member, task_path):
            continue
        options.append({"value": member.name, "label": _enum_label(member)})
    return options


def _enum_label(member: enum.Enum) -> str:
    """给成员一个人看的标签：字符串/数字值优先，否则用成员名。"""
    if isinstance(member.value, str):
        return member.value
    if isinstance(member.value, int):
        return str(member.value)
    return member.name


class ParamSpec:
    """一个函数参数在 JSON 边界上的行为。"""

    def __init__(self, name: str):
        self.name = name

    def json_default(self) -> Any:
        """写进 cfg 的默认值，必须是纯 JSON。"""
        raise NotImplementedError

    def describe(self, task_path: str | None = None) -> dict[str, Any]:
        """WebUI 表单用的描述。"""
        raise NotImplementedError

    def decode(self, value: Any) -> Any:
        """cfg 里的值 → 传给函数的实参。"""
        raise NotImplementedError

    def merge_saved(self, default: Any, saved: Any) -> Any:
        """把用户保存过的值合并到当前默认值上。默认就是「用户值优先」。"""
        return saved


class ValueSpec(ParamSpec):
    """普通值：JSON 里怎么写就怎么用。"""

    def __init__(self, name: str, default: Any):
        super().__init__(name)
        self.default = deepcopy(default)

    def json_default(self) -> Any:
        return deepcopy(self.default)

    def describe(self, task_path: str | None = None) -> dict[str, Any]:
        return {"type": "value"}

    def decode(self, value: Any) -> Any:
        return value


class EnumSpec(ParamSpec):
    """枚举参数，单选或多选。持有枚举类本身，不经过点分字符串。"""

    def __init__(self, name: str, enum_class: type[enum.Enum], multiple: bool, default: Any):
        super().__init__(name)
        self.enum_class = enum_class
        self.multiple = multiple
        self.default = default

    def json_default(self) -> Any:
        if self.multiple:
            return [member.name for member in self.default]
        return self.default.name

    def describe(self, task_path: str | None = None) -> dict[str, Any]:
        return {
            "type": "enum_list" if self.multiple else "enum",
            "options": _enum_options(self.enum_class, task_path),
        }

    def decode(self, value: Any) -> Any:
        # 单选存成列表、多选存成单值都可能来自旧配置或表单改动，两种形态都接受。
        if isinstance(value, list):
            return [self._member(item) for item in value]
        return self._member(value)

    def _member(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.enum_class[value]
        return value


class TableSpec(ParamSpec):
    """表格参数。原型带着列信息和枚举类，JSON 侧只是 dict-of-dicts。"""

    def __init__(self, name: str, prototype: TableParam):
        super().__init__(name)
        self.prototype = prototype
        self.column_enum_classes = prototype.column_enum_classes()

    def json_default(self) -> dict[str, dict[str, Any]]:
        return self.prototype.to_json_data()

    def describe(self, task_path: str | None = None) -> dict[str, Any]:
        column_types = self.prototype.get_param_meta()["columns"]
        columns: dict[str, dict[str, Any]] = {}
        for column, column_meta in column_types.items():
            enum_class = self.column_enum_classes.get(column)
            if enum_class is None:
                columns[column] = {"type": column_meta.get("type", "value")}
            else:
                columns[column] = {
                    "type": "enum",
                    "options": _enum_options(enum_class, task_path),
                }
        return {
            "type": "table",
            "columns": columns,
            "column_labels": self.prototype.column_labels(),
        }

    def decode(self, value: Any) -> Any:
        if isinstance(value, TableParam) or not isinstance(value, dict):
            return value
        restored: dict[str, dict[str, Any]] = {}
        for row_key, row in value.items():
            if not isinstance(row, dict):
                continue
            restored[row_key] = {
                column: self._cell(column, cell) for column, cell in row.items()
            }
        return TableParam(restored, column_labels=self.prototype.column_labels())

    def merge_saved(self, default: Any, saved: Any) -> Any:
        """表格按行合并：新增的默认行/列补进来，用户改过的格子保留。"""
        if not isinstance(saved, dict) or not isinstance(default, dict):
            return default
        merged = deepcopy(default)
        for row_key, saved_row in saved.items():
            default_row = merged.get(row_key)
            if isinstance(default_row, dict) and isinstance(saved_row, dict):
                default_row.update(deepcopy(saved_row))
            else:
                merged[row_key] = deepcopy(saved_row)
        return merged

    def _cell(self, column: str, cell: Any) -> Any:
        enum_class = self.column_enum_classes.get(column)
        if enum_class is None or not isinstance(cell, str):
            return cell
        try:
            return enum_class[cell]
        except KeyError:
            return next(iter(enum_class))


def describe_signature(fn) -> dict[str, ParamSpec]:
    """函数的可编辑参数 → 参数名到 ParamSpec 的映射，按签名顺序。"""
    specs: dict[str, ParamSpec] = {}
    for name, parameter in inspect.signature(fn).parameters.items():
        if parameter.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL):
            continue
        default = parameter.default if parameter.default is not inspect.Parameter.empty else None
        specs[name] = _spec_for(name, default)
    return specs


def hydrate_params(specs: dict[str, ParamSpec], saved: dict[str, Any]) -> dict[str, Any]:
    """当前默认值 + 用户已保存的值 → 写进 cfg 的 params。

    只保留仍在签名里的参数名，已迁移的旧键自然消失。
    """
    return {
        name: spec.merge_saved(spec.json_default(), saved[name]) if name in saved else spec.json_default()
        for name, spec in specs.items()
    }


def _spec_for(name: str, default: Any) -> ParamSpec:
    if isinstance(default, TableParam):
        return TableSpec(name, default)
    if isinstance(default, enum.Enum):
        return EnumSpec(name, default.__class__, multiple=False, default=default)
    if (
        isinstance(default, (list, tuple))
        and default
        and all(isinstance(item, enum.Enum) for item in default)
    ):
        return EnumSpec(name, default[0].__class__, multiple=True, default=list(default))
    return ValueSpec(name, default)
