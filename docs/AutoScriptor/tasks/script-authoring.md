# Task Script Authoring 当前规则

任务脚本可以继续使用 `from AutoScriptor import *`，但要遵守当前任务注册、状态、调度和 WebUI 投影规则。

## 注册位置

| 类型 | 目录 | 路径规则 |
|------|------|----------|
| 内置任务 | `ZmxyOL/task/` | 推荐在 `@register_task(path_cn="...")` 中给出中文路径；未写时才用 `translations.py` 兼容旧脚本 |
| 自定义任务 | `data/custom_task/` | 必须在 `@register_task(path_cn="...")` 中给出中文路径 |

```python
from ZmxyOL.task.task_register import register_task
from AutoScriptor import *

@register_task(path_cn="自定义任务/示例/hello", description="示例任务")
def task(count: int = 1):
    for _ in range(count):
        click(T("开始"), if_exist=True)
```

`custom_task` 下未提供 `path_cn` 会注册失败。首段推荐写 `自定义任务`；如果省略首段，例如 `path_cn="背包清空/进阶仙宝"`，后端会自动归一为 `自定义任务/背包清空/进阶仙宝`，以便 WebUI 自定义任务页加载。若旧版本已经把配置写在省略根节点的路径下，注册时会迁移到归一后的路径并清理空旧分支。自定义脚本不能通过 `path_cn` 创建新的顶级任务页。内置脚本的 `path_cn` 可选，但一旦提供就直接决定中文 cfg 路径，不再依赖对应文件名的 `translations.py` 映射；需要跟随项目维护的内置流程应放在 `ZmxyOL/task/`，不要只放在用户 `data/custom_task/`。

WebUI Editor 的“保存脚本”接口 `/api/editor/save-custom-task` 也必须生成同样形态的自定义任务文件：写入 `data/custom_task/`，使用 UTF-8，并带有 `@register_task(path_cn="自定义任务/...")`。保存弹窗提供 `文件名称`（默认 `.py` 后缀）、`脚本名称`（默认前缀为 `自定义任务/`，用户填写后续路径）、`description`、`task_docs` 和参数设置；参数字段包括字段名称、字段类型、字段解释，字段类型支持 `Enum(单选)` 和 `Enum(多选)`，enum 选项使用 `["普通","困难"]` 这类 JSON 数组填写。

编辑器保存裸片段时会按表单生成 `@register_task(path_cn="自定义任务/...", description=..., task_doc=...)`，并把参数设置转换为函数签名、本地 `enum.Enum` 类和默认值；如果传入的是完整自定义任务文件，文件内的 `@register_task` 必须显式提供 `path_cn`，已有装饰器元数据由文件自身负责。只落盘未注册的 Python 片段不会出现在 WebUI 任务树中。

例如兑换码礼品兑换是内置一般任务，注册路径为 `一般任务/活动/兑换豪礼礼品兑换`，源码位于 `ZmxyOL/task/normal_task/huodong/redeem_gift.py`。

## register_task 元数据

| 参数 | 说明 |
|------|------|
| `default_offset_hours` | 成功后按当前时间 + N 小时调度 |
| `beta` | WebUI 显示实验标记 |
| `task_doc` | WebUI 补充说明正文；不传时取函数 docstring 首段 |
| `description` | WebUI 一句话简介；不传时生成占位，内置脚本不再使用集中默认描述表 |
| `debug_mode` / `debug=True` | 调试直跑：跳过自动登录/失败恢复/本轮 post_execution |
| `deprecated` | 弃用隐藏字段；`True` 时源码保留并记录注册元数据，但不写入 `cfg["tasks"]`、不出现在 WebUI/可见任务列表/调度列表 |
| `path_cn` | `data/custom_task` 必填中文路径并归一到 `自定义任务/...`；内置任务可选，提供后替代文件名翻译映射 |
| `sched_window_hours` | 本地可执行窗口 `[start, end)` |
| `allowed_weekdays` | 允许星期，`1=周一 ... 7=周日` |

其他关键字会写入任务叶节点配置，可作为任务默认配置持久化，例如 `last_buy_time`、`sched_window_hours`、`allowed_weekdays`、`next_exec_offset_hours`。运行时元数据如 `fn/order/param_meta/debug_mode/task_doc_flow/description/deprecated` 存在 `TaskRegistry`，不会写入 JSON；其中 `deprecated=True` 的任务连配置叶节点也不会写入。

内置任务一旦使用 `@register_task` 就会进入 WebUI 和调度器候选集，除非显式声明 `deprecated=True`。`【未完成】`、`【bug】` 等只是 `description` 文案，不会隐藏任务；只有 `deprecated=True` 会隐藏且不入 cfg。不要把仍会 `raise Stop here`、打印调试表格、或只作为活动占位的脚本长期注册；这类实验应先放在未注册代码、本地 `data/custom_task/`，或直接删除。

## 参数

默认值会写入 `params`，执行前由 `TaskManager._resolve_params()` 恢复：

- 普通类型：直接保存 JSON 值。
- `enum.Enum`：JSON 存枚举 `.name`，执行前恢复为枚举对象。
- `list[Enum]` / `tuple[Enum]`：保存 name 列表。
- `TableParam`：保存 dict-of-dicts，并通过 `param_meta` 恢复列类型。

```python
import enum
from AutoScriptor.utils.table_param import TableParam

class Difficulty(str, enum.Enum):
    不打 = "不打"
    普通 = "普通"
    困难 = "困难"

@register_task
def task(
    plan: TableParam = TableParam(
        {"第一关": {"difficulty": Difficulty.不打, "revive": False}},
        column_labels={"difficulty": "难度", "revive": "允许复活"},
    ),
):
    for level, row in plan.items():
        ...
```

WebUI 保存任务时会剥离运行时字段，只保存用户配置。活动任务不会因为位于 `活动任务/` 目录外的额外框架字段而默认每日调度；需要窗口、星期或 offset 时，在脚本的 `@register_task(...)` 中显式声明。

## Sleep 与取消

使用：

```python
sleep(1)
```

不要使用：

```python
import time
time.sleep(1)
```

`AutoScriptor.sleep()` 会响应 WebUI 停止按钮。长时间等待、登录、动画、retry 间隔都必须可取消。

## 状态与进度

任务函数返回不等于业务成功。可观测进度要写入当前任务状态：

```python
set_task_status("progress", "5/6")
progress = get_task_status("progress")
```

`progress` 可写成：

- `"5/6"`
- `[5, 6]`
- `{"done": 5, "total": 6}`

执行层会在任务函数返回后检查 `progress`：

1. 完成进度或无进度：任务成功，更新 `next_exec_time`。
2. 未完成进度：转成 `TaskRequireReTry`。
3. retry 耗尽后仍未完成：自动标记 `human_takeover_error`，WebUI 显示红色进度。
4. `next_exec_time` 到期后会自动再试，成功后清除 `progress` 和 `human_takeover*`。

需要清理状态时从 `AutoScriptor.utils.task_state` 导入 `clear_task_status`。

## 错误语义

| 情况 | 推荐做法 |
|------|----------|
| 临时 UI 未出现、网络波动 | 抛 `TaskRequireReTry` 或普通异常，让 retry 处理 |
| 需要人工介入、材料不足、账号状态不满足 | 抛 `RequestHumanTakeover` |
| 自身能力不足但有可观测进度 | 写 `progress`，让执行层在 retry 耗尽后转人工接管 |
| debug 现场验证 | `@register_task(debug_mode=True)` |

普通失败没有未完成进度时不会自动变红，只会按 retry 和连续错误计数处理。

任务文件不保留 `if __name__ == "__main__"` 直跑尾巴，也不要在文件底部包一层 `try/except`、`traceback.print_exc()`、`bg.stop()`、`exit(0)`。现场验证走 WebUI 直接执行或 `debug_mode` 元数据，让同一套调度、日志和停止语义接管。

## 战斗任务

任务函数如果声明 `battle_flow: BattleFlowName`，框架会在任务体前：

1. 根据当前角色 `game.game_profession` 加载职业脚本；职业缺失时使用 `default`。
2. 校验所选 flow 是否属于当前职业；不属于时回到任务默认 flow，避免借用其他职业流程。
3. 写入 `h.task_context_battle_flow`。

任务内调用 `h.battle_loop()` 或 `h.jjc_battle()` 时，不显式传 `flow_name` 会使用该上下文。需要指定战斗策略时传 `battle_flow`/`flow_name`，不要再传旧 `battle_weight` 参数。

## 设备和识别

- 普通任务只调用 `click/locate/swipe/input/key_event/extract_info/get_colors`。
- 不直接调用 MuMuManager subprocess；设备会话由调度器、WebUI 或 runtime context 管。
- 纯坐标点击用 `B(x, y, w, h)`；OCR 语义和业务语义分开处理。
- 多个识别目标必须包成 tuple/list：`(T("A"), T("B"))` 表示任一命中，`[T("A"), T("B")]` 表示全部命中；不要写 `wait_for_appear(T("A"), T("B"))`，第二个位置参数是 `timeout`。
- 在线截图测试应固定同一帧，传 `screenshot` 或 `screenshot_frame`。

## 后台监听

局部监听使用 `bg.scope()`：

```python
with bg.scope("my_task") as watch:
    watch.add("popup", T("知道了"), callback=lambda: click(T("知道了"), if_exist=True), once=False)
    ...
```

不要在任务局部随意 `bg.clear()`，它会清掉其他模块或 `battle_loop` 刚注册的监听。

## 提交前检查

- 任务是否能响应停止按钮。
- `cfg["tasks"]` 是否只保存用户配置。
- 新增参数是否能在 WebUI 保存后恢复类型。
- 任务失败是否区分 retry、人工接管和真实异常。
- 若改了行为或生命周期，同步更新 `docs/AutoScriptor/` 对应文档。
