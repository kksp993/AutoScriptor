# TableParam — 通用表格参数

## 背景

多关卡任务（遗境副本、极寒深渊等）经常需要为每个关卡分别配置难度、是否点券复活、战斗招式等。旧方案把每个关卡拆成独立参数，前端渲染为一系列分散的下拉框，参数密度低且无法为单个关卡独立配置所有属性。

`TableParam` 是一个通用的表格参数类型：行 = 关卡（或任意键），列 = 可配置属性。前端以紧凑的可编辑表格渲染，后端序列化为 dict-of-dicts 的 JSON 格式。

---

## 模块位置

```
AutoScriptor/utils/table_param.py
```

---

## 用法示例

### 任务声明

```python
from AutoScriptor.utils.table_param import TableParam

class YijingNandu(str, enum.Enum):
    不打 = "不打"
    初难 = "初难"
    灾厄 = "灾厄"
    浩劫 = "浩劫"

@register_task
def task(
    battle_config: TableParam = TableParam(
        {
            "虎神之崖": {"difficulty": YijingNandu.不打, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
            "苍龙幽谷": {"difficulty": YijingNandu.不打, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
            "溟海之渊": {"difficulty": YijingNandu.不打, "cancel_on_failed": True, "battle_flow": DEFAULT_BATTLE_FLOW},
        },
        column_labels={"difficulty": "难度", "cancel_on_failed": "不用点券复活", "battle_flow": "战斗招式"},
    ),
):
    for name, row in battle_config.items():
        nandu = row["difficulty"]           # YijingNandu 枚举实例
        cancel = row["cancel_on_failed"]    # bool
        flow = row.get("battle_flow")       # BattleFlowName 枚举实例
        ...
```

### 构造参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `data` | `dict[str, dict[str, Any]]` | 行键 → 列字典。列值可为 `enum.Enum`、`bool`、`int`/`float`、`str` |
| `column_labels` | `dict[str, str] \| None` | 列键 → 中文显示名（前端表头用），可选 |

### 列类型自动推断

`TableParam` 从首行数据自动推断各列的类型：

| Python 类型 | 推断为 | 前端控件 |
|------------|--------|---------|
| `enum.Enum` | `"enum"` | `el-select` 下拉 |
| `bool` | `"bool"` | `el-switch` 开关 |
| `int` / `float` | `"number"` | `el-input-number` |
| `str` | `"string"` | `el-input` 文本框 |

### dict 式访问

`TableParam` 支持像字典一样访问：

```python
table["虎神之崖"]["difficulty"]  # 返回枚举值
len(table)                       # 行数
for name in table:               # 迭代行键
    ...
for name, row in table.items():  # 迭代行键+行数据
    ...
"虎神之崖" in table              # 判断行是否存在
```

---

## JSON 持久化格式

在 `config.json` 中，`TableParam` 存储为 dict-of-dicts，枚举值存为 `.name` 字符串：

```json
{
  "params": {
    "battle_config": {
      "虎神之崖": {"difficulty": "浩劫", "cancel_on_failed": true, "battle_flow": "战斗循环"},
      "苍龙幽谷": {"difficulty": "灾厄", "cancel_on_failed": false, "battle_flow": "竞技场循环"},
      "溟海之渊": {"difficulty": "不打", "cancel_on_failed": true, "battle_flow": "战斗循环"}
    }
  },
  "param_meta": {
    "battle_config": {
      "type": "table",
      "columns": {
        "difficulty": {"type": "enum", "enum": "...hyper_abyss_task.JhsyNandu"},
        "cancel_on_failed": {"type": "bool"},
        "battle_flow": {"type": "enum", "enum": "...battle_task_params.BattleFlowName"}
      },
      "column_labels": {
        "difficulty": "难度",
        "cancel_on_failed": "不用点券复活",
        "battle_flow": "战斗招式"
      }
    }
  }
}
```

---

## 前端渲染

WebUI 编辑任务对话框检测到 `param_meta[key].type === "table"` 时，自动渲染为 `el-table`：

```
| 关卡       | 难度    | 不用点券复活 | 战斗招式      |
|-----------|---------|-----------|-------------|
| 虎神之崖   | [浩劫 ▾] | [✓]      | [战斗循环 ▾]  |
| 苍龙幽谷   | [灾厄 ▾] | [✗]      | [竞技场循环 ▾] |
| 溟海之渊   | [不打 ▾] | [✓]      | [战斗循环 ▾]  |
```

- 行键显示为第一列（关卡名）
- 枚举列渲染为下拉选择器，选项来自 `/api/enum-options`
- `battle_flow` 列支持按任务路径过滤（与独立 `battle_flow` 参数一致）
- 对话框宽度自动适配（有表格时 860px，否则 600px）

---

## 数据流

```
@register_task 签名检测
  │
  ├─ isinstance(default, TableParam) → True
  │    ├─ defaults[name] = table.to_json_data()     → JSON dict（enum → .name）
  │    └─ param_meta[name] = table.get_param_meta()  → {type, columns, column_labels}
  │
  ├─ cfg["tasks"][...]["params"]["battle_config"] = dict-of-dicts (JSON)
  └─ task_registry.param_meta["battle_config"] = {type: "table", ...}

WebUI openEditModal
  │
  ├─ 检测 param_meta.type === 'table'
  ├─ 收集 columns 中的 enum 路径 → /api/enum-options
  ├─ 渲染 el-table
  └─ saveTask 时 array → dict 转回

TaskManager._resolve_params
  │
  ├─ 检测 meta.type === 'table'
  └─ TableParam.from_json_data(data, columns, labels)
       └─ enum 字符串 → 枚举实例
       └─ 返回 TableParam 对象传入任务函数
```

---

## API 参考

### TableParam

| 方法 | 说明 |
|------|------|
| `__init__(data, column_labels=None)` | 构造，自动推断列类型 |
| `to_json_data() → dict` | 序列化为 JSON 格式（enum → `.name`） |
| `get_param_meta() → dict` | 生成 `param_meta` 结构供注册和前端使用 |
| `from_json_data(data, column_meta, column_labels=None)` | 类方法，从 JSON 还原（字符串 → enum 实例） |
| `__getitem__(key)` | 按行键取行 dict |
| `keys()` / `values()` / `items()` | dict 式遍历 |
| `__len__()` / `__contains__(key)` / `__iter__()` | dict 式操作 |

---

## 已迁移的任务

| 任务 | 文件 | 变更 |
|------|------|------|
| 遗境副本 | [`yijingfuben.py`](../../ZmxyOL/task/daily_task/hgwj/yijingfuben.py) | 3 个独立难度 enum + 全局 `cancel_on_failed` + 全局 `battle_flow` → 单个 `battle_config: TableParam` |
| 极寒深渊 | [`hyper_abyss_task.py`](../../ZmxyOL/task/daily_task/hyper/polar_abyss/hyper_abyss_task.py) | 7 个独立难度 enum + 全局 `cancel_on_failed` + 全局 `battle_flow` → 单个 `battle_config: TableParam`（保留 `lingqi_priority` 独立参数） |

---

## 新增任务时使用 TableParam

1. 定义列值的枚举（如难度）
2. 构造 `TableParam` 默认值，指定行键（关卡名）、列键+默认值、`column_labels`
3. 在任务函数签名中声明 `battle_config: TableParam = ...`
4. 函数体内通过 `battle_config.items()` 遍历，每行 `row["column_key"]` 取值
5. 对于 `battle_flow` 列，传 `flow_name=getattr(row.get("battle_flow"), "value", None)` 给 `battle_task` / `battle_loop`

---

## 文件索引

| 文件 | 职责 |
|------|------|
| [`AutoScriptor/utils/table_param.py`](../../AutoScriptor/utils/table_param.py) | `TableParam` 类定义 |
| [`ZmxyOL/task/task_register.py`](../../ZmxyOL/task/task_register.py) | 签名检测 `TableParam`，生成 defaults 和 param_meta |
| [`services/core/task_manager.py`](../../services/core/task_manager.py) | `_resolve_params` 中 `_coerce_table_param` 还原 TableParam |
| [`services/webui/static/js/app.js`](../../services/webui/static/js/app.js) | 前端表格辅助方法、枚举收集、保存转换 |
| [`services/webui/static/index.html`](../../services/webui/static/index.html) | 编辑对话框 `el-table` 渲染模板 |
