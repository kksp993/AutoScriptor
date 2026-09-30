# Task Script Authoring 当前规则

任务脚本可以继续使用 `from AutoScriptor import *`；造梦导航、登录、战斗和任务公共符号优先使用 `from ZmxyOL import *`。只有聚合 API 尚未提供的内部能力才直达子模块，同时应评估是否应补到公共出口。任务仍须遵守当前注册、状态、调度和 WebUI 投影规则。

独立脚本可直接 `init()`。操作配置游戏以外的 App 时用 `init(launch_app=False)`，并通过 `launch_app()`、`close_app()`、`go_home()` 操作当前设备。竖屏脚本可调用 `setFrameSize(MUMU_SIZE_720_1280)`，随后统一使用 `Box(...).margin()`；共享 WebUI/调度进程中的任务更适合继续为每个区域显式传入 `frame_size`，避免改变其他任务的默认裁剪尺寸。

任务之间共享的代码放在同一目录下的下划线开头文件里（例如 `tasks/其他任务/活动脚本/活动任务/_活动流程.py`），用完整包路径导入：
`from tasks.其他任务.活动脚本.活动任务._活动流程 import run_activity`。下划线前缀表示它是模块而不是任务，注册表不会为它生成任务项。

## 注册位置

| 类型 | 目录 | 路径规则 |
|------|------|----------|
| 内置任务 | `tasks/` | 显示路径就是它在 `tasks/` 下的源码路径：目录名和文件名都是中文路径段 |
| 自定义任务 | `data/custom_task/` | 显示路径 = `自定义任务/` + 它在 `custom_task/` 下的相对路径 |

```python
from tasks.task_register import register_task   # 或 from ZmxyOL import *
from AutoScriptor import *

@register_task(description="示例任务")
def 每日签到(count: int = 1):
    for _ in range(count):
        click(T("开始"), if_exist=True)
```

内置任务的显示路径完全由源码位置决定，而且逐段同名，中间没有任何映射表：

```text
tasks/每日任务/村庄/宠物培养.py   →  每日任务/村庄/宠物培养
      分类    分组   文件名            逐段相同
```

- **分类与分组目录**：目录名直接用中文，逐段成为任务的显示路径层级，例如 `每日任务`、`村庄`。新建目录只要名字是中文，就会原样进入 WebUI 任务树，不需要再登记到任何表里。
- **任务名**：文件名去掉 `.py` 就是路径最后一段，所以文件名要写中文显示名，例如 `宠物培养.py` 而不是 `pet_upgrade.py`。

目录与文件名共同决定**显示路径**，而文件名单独决定两件事：任务身份 `id`（未显式声明时取文件名去掉 `.py`），以及 WebUI 里的任务名。用户配置以 `id` 为键存储，所以**换目录只改显示位置**；只有重命名文件才需要钉住 `id`，见 [排序与路径身份](#排序与路径身份)。

自定义任务的形态和内置任务完全一样：

```python
@register_task(description="示例任务")
def task(count: int = 1):
    for _ in range(count):
        click(T("开始"), if_exist=True)
```

自定义任务没有路径参数：它被放在哪，它的路径就是什么。上面这段代码保存到
`data/custom_task/示例/hello.py`，就注册为 `自定义任务/示例/hello`。所以自定义任务页里的
「脚本名称」既是列表里的名字，也是它落在哪个子目录。需要跟随项目维护的内置流程应放在 `tasks/`，
不要只放在用户 `data/custom_task/`。

WebUI Editor 的“保存脚本”接口 `/api/editor/save-custom-task` 也生成同样形态的自定义任务文件：按「脚本名称」在 `data/custom_task/` 下建好子目录，写入 UTF-8 Python 文件，装饰器只带 `description`，补充说明写成函数 docstring。保存弹窗只有 `脚本名称` 一个命名入口（默认前缀 `自定义任务/`，最后一段就是文件名与任务身份）、`description`、`task_docs` 和参数设置；参数字段包括字段名称、字段类型、字段解释，字段类型支持 `Enum(单选)` 和 `Enum(多选)`，enum 选项使用 `["普通","困难"]` 这类 JSON 数组填写。

Editor 操作录制区的“工具 > 导航到...”按 `ZmxyOL.nav.envs` 的环境和位置层级展示导航目标。点击环境或位置会在当前代码目标中插入 `ensure_in("目标名称")`；位置名可包含 `天庭#1` 等索引后缀。

Editor 操作录制区的“定位 > 区域识别 > 匹配目标（match）”会根据当前选区生成 `B/T/I` 目标，并在当前代码目标中插入 `match(...)`。复杂的 tuple（OR）或 list（AND）目标可在插入后继续编辑。

图片编辑器顶部的“生成对象”会将当前选区生成的 `B/T/I` 目标插入录制区或函数编辑窗口的当前光标/选区。“判断存在/判断不在”同样在光标处生成；“操作 > 点击 > 直到出现/直到消失”先生成带空 `ui_T()` / `ui_F()` 的 `until=lambda:` 条件并将光标放在括号内，可重新框选条件目标后点击“生成对象”补入。“下一步直到”使用当前目标生成 `click(B(0,0), until=lambda: ui_T(...))`。

编辑器保存裸片段时会按表单生成 `@register_task(description=...)` 加函数 docstring（补充说明正文），并把参数设置转换为函数签名、本地 `enum.Enum` 类和默认值；路径由文件写入位置决定。如果传入的是完整自定义任务文件，它自己的装饰器元数据由文件负责。只落盘未注册的 Python 片段不会出现在 WebUI 任务树中。

自定义任务导入失败会记录到 WebUI 公开配置的 `custom_task_load_errors`，并在本轮加载中跳过 stale 任务条目清理和 `cfg.save_config()`。修复脚本语法或导入错误后重新加载即可恢复；不要因为任务临时消失就手动清空 `自定义任务` 配置分支。

例如兑换码礼品兑换是内置任务，显示路径为 `其他任务/活动脚本/兑换豪礼礼品兑换`，源码位于 `tasks/其他任务/活动脚本/兑换豪礼礼品兑换.py`。

## 排序与路径身份

一个任务有两个字符串，别混：

| 名字 | 是什么 | 谁在用 |
|------|--------|--------|
| `id` | 身份。默认取任务名（文件名去掉 `.py`），可在 `@register_task(id=...)` 里显式指定 | `cfg["tasks"]` 的键、`task_ordering` 的键 |
| `path` | 显示位置，逐段中文，例如 `每日任务/村庄/宠物培养` | WebUI 树、执行顺序、参数标签 |

所以**换目录免费**：目录随便挪，`id` 不变，用户配置、拖拽顺序和运行状态都跟着走，UI 里换个分组而已。只有重命名**文件**才改变默认身份，这时把 `id` 钉在旧任务名上。

```python
# 文件从 每日任务/村庄/宠物培养.py 改名为 每日任务/村庄/灵宠培养.py 后：
@register_task(id="宠物培养")
def task():
    ...
```

不写 `id=` 就是「新任务」，从默认配置开始，旧条目会被加载末尾的 prune 清掉。`id` 必须唯一；两个任务声明同一个 `id` 会在注册时直接报错。

用户拖拽顺序存在全局 `task_ordering` 覆盖层，**同样以 `id` 为键**；任务脚本不要把用户显示顺序写进源码目录或账号 JSON。

- 默认顺序来自注册顺序，也就是源码路径排序；没有 per-task 的顺序参数。用户拖拽排序存在 `task_ordering`，与源码顺序无关。
- `items` 是当前持久化的用户分组顺序，支持任务节点和嵌套分组；`user_order` 是后端由 `items` 展平生成的兼容投影和旧数据导入 seed。有效顺序先把存储里的 `id` 键换成显示路径，再递归展开 `items`，最后回退到当前注册顺序和路径字典序。
- 旧版 `hard_edges`、`layout`、`group_order` 会被后端规范化忽略，不再表达偏序关系或画布布局。
- 只在改名且没钉 `id` 时，旧排序键才在 WebUI 诊断中显示为 stale；用户可拖拽后重新保存。

## register_task 元数据

作者的声明只有五个字段，其余都属于用户数据或运行时数据：

| 参数 | 类型与取值 | 说明 |
|------|-----------|------|
| `id` | str | 任务身份，`cfg["tasks"]` 和 `task_ordering` 的键。不传时取任务名（文件名去掉 `.py`）；换目录不用写，重命名文件时写 `id="旧任务名"` 就能保住用户配置、拖拽顺序和运行状态 |
| `reschedule` | `None` / `"daily"` / `"weekly"` / int / dict | 下次什么时候再来，取值见下节。不写 = 一次性。用户在 WebUI 里可以覆盖 |
| `debug` | bool | 调试直跑的默认值：跳过自动登录、失败恢复和本轮 post_execution。用户可以在 WebUI 里覆盖 |
| `description` | str | 一句话简介；不传时取函数 docstring 首行 |
| `deprecated` | bool | 系统属性。源码和注册元数据保留，但不写 cfg、不出现在 WebUI 和调度列表；已存在的旧条目由加载末尾的 prune 清理 |

**长说明就是函数 docstring**，没有对应参数。其余 `key=value` 只用于任务私有数据（例如
`last_buy_time`），原样写进 cfg 条目；官方字段名写错会直接 `TypeError`，不会静默留在用户配置里。

`debug` 的生效值 = `cfg` 里用户设的值（有就用）→ 作者声明的默认值。判据只有这一处，
跨角色登录、任务前重启、失败恢复、本轮重试与 post_execution 都以它为准，录屏和运行期抓帧也由它开启。
`cfg["app"]` 里没有 debug 开关，任务是否放在 `data/custom_task/` 下也不影响判定。

## reschedule：唯一的调度字段

```python
@register_task()                                   # 不写 = 一次性：执行成功后关闭 on
@register_task(reschedule="daily")                 # 下一个 05:00（当天 5 点前算今天）
@register_task(reschedule="weekly")                # 下周一 05:00
@register_task(reschedule=10)                      # 10 小时后
@register_task(reschedule={"mode": "daily", "window": (10, 22), "weekdays": [5, 6, 7]})
```

- `window` 是本地时间可执行时段 `[start, end)`；到点但不在时段内会推迟到时段起点。
- `weekdays` 用 `1=周一 … 7=周日`；到点但不在允许日会推迟到下一个允许日的 05:00。
- 非法写法（拼错的 mode、越界的 window、空 weekdays）在注册时直接报错。

生效值同样是「用户在 cfg 里覆盖 → 作者声明 → 一次性」，由 `tasks/task_schedule.py` 的
`normalize_reschedule()` 归一，调度侧只认这一个字段，不再看任务目录名。

内置任务一旦使用 `@register_task` 就会进入 WebUI 和调度器候选集，除非显式声明 `deprecated=True`。`【未完成】`、`【bug】` 等只是 `description` 文案，不会隐藏任务；只有 `deprecated=True` 会隐藏且不入 cfg。不要把仍会 `raise Stop here`、打印调试表格、或只作为活动占位的脚本长期注册；这类实验应先放在未注册代码、本地 `data/custom_task/`，或直接删除。

## 参数

任务函数的参数就是 WebUI 表单，两者的换算只有一个出处：`tasks/task_params.py`。

`describe_signature(fn)` 由函数签名生成 `ParamSpec`，之后三件事共用同一份 spec：

| 用途 | 方法 |
|------|------|
| 写进 `cfg["tasks"][..]["params"]` 的 JSON 默认值 | `json_default()` |
| WebUI 表单的控件类型和可选项（投影为 `param_meta`） | `describe()` |
| 执行前还原成传给函数的实参 | `decode()` |

`describe()` 是唯一的对外形状，用 `type` 判别；枚举选项随描述一起下发，没有单独的取选项接口：

```json
{"type": "value"}
{"type": "enum",      "options": [{"value": "灾厄", "label": "灾厄"}]}
{"type": "enum_list", "options": [...]}
{"type": "table", "columns": {"difficulty": {"type": "enum", "options": [...]}},
                  "column_labels": {"difficulty": "难度"}}
```

新增参数类型只要加一个 `ParamSpec` 子类，注册、表单、执行三处自动一致。需要按任务裁剪选项的枚举（例如只对部分任务适用的战斗流程），由拥有该概念的模块用 `set_enum_option_filter()` 登记规则。

各类默认值在 JSON 里的存法与恢复方式：

| 参数类型 | `params` 里的形态 | 执行时 |
|----------|------------------|--------|
| 普通值 | 原样 JSON | 原样传入 |
| `enum.Enum` | 枚举 `.name` | 恢复为枚举对象 |
| `list[Enum]` / `tuple[Enum]` | `.name` 列表 | 恢复为枚举对象列表 |
| `TableParam` | dict-of-dicts | 重建 `TableParam`，并按列恢复枚举 |

表格参数在注册阶段逐行合并新默认值：新增的默认行、列会补齐，用户改过的格子保留，避免旧账号看不到新配置项。

```python
import enum
from ZmxyOL.battle.table_param import TableParam


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
WebUI 保存任务时会剥离运行时字段，只保存用户配置。调度只由 `reschedule` 决定——作者在 `@register_task(...)` 里声明默认值，用户在 WebUI 里可以覆盖；任务位于哪个目录不影响它的调度。

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

需要清理状态时从 `tasks.task_state` 导入 `clear_task_status`。

## 错误语义

| 情况 | 推荐做法 |
|------|----------|
| 临时 UI 未出现、网络波动 | 抛 `TaskRequireReTry` 或普通异常，让 retry 处理 |
| 需要人工介入、材料不足、账号状态不满足 | 抛 `RequestHumanTakeover` |
| 自身能力不足但有可观测进度 | 写 `progress`，让执行层在 retry 耗尽后转人工接管 |
| debug 现场验证 | `@register_task(debug=True)` |

普通失败没有未完成进度时不会自动变红，只会按 retry 和连续错误计数处理。

任务文件不保留 `if __name__ == "__main__"` 直跑尾巴，也不要在文件底部包一层 `try/except`、`traceback.print_exc()`、`bg.stop()`、`exit(0)`。现场验证走 WebUI 直接执行或 `debug` 设置，让同一套调度、日志和停止语义接管。

## 战斗任务

任务函数如果声明 `battle_flow: BattleFlowName`，框架会在任务体前：

1. 根据当前角色 `game.game_profession` 加载职业脚本；职业缺失时使用 `default`。
2. 校验所选 flow 是否属于当前职业；不属于时回到任务默认 flow，避免借用其他职业流程。
3. 写入 `h.task_context_battle_flow`。

任务内调用 `h.battle_loop()` 或 `h.jjc_battle()` 时，不显式传 `flow_name` 会使用该上下文。需要指定战斗策略时传 `battle_flow`/`flow_name`，不要再传旧 `battle_weight` 参数。

## 设备和识别

- 普通任务只调用 `click/click_all/locate/match/swipe/input/key_event/extract_info/get_colors/coloris`。同屏多个相同按钮使用 `click_all(target)`；`click(..., repeat=N)` 只用于重复点击同一个命中位置。
- 需要实时盯进度条/走条时用 `screenshot_region(target)` 只取目标区域，配合 `finger_down/finger_move/finger_up` 做「按住升、松开降」闭环；不要在全帧截图上循环做 OCR。多指同按用 `multi_finger_down([(1, x, y), (2, x, y)])`。
- `finger_*` 使用编号手指（1..10），与 `click/swipe` 的触点互相独立；实时循环只在状态翻转时发按下/松开边沿，且必须在 `finally` 里调用 `release_all_fingers()` 兜底，避免任务失败后手指保持按住。
- 内置游戏任务的截图、模板、`B/Box` 和点击坐标都按 `1280x720` 横屏绝对像素编写；`B(x, y, width, height)` 使用左上角与宽高，不编写相对坐标或静默缩放逻辑。
- 内置游戏截图尺寸不符合合同时运行时只会节流 warning 并继续任务，不会自动缩放；应修正 MuMu 分辨率。明确操作竖屏外部应用时可使用其原生坐标；独立脚本先调用 `setFrameSize(...)` 后可直接使用 `.margin()`，共享进程任务则应显式传 `frame_size=(width, height)`。执行方向必须与录制方向一致。
- 任务脚本只依赖现有公共识别 API，不导入或依赖内部 `RecognitionResult` 追踪结构。
- `extract_info(..., mode=...)` 使用 `digital_only`（仅数字）、`text`（仅 OCR 文本）、`img`（仅返回 `ui_map` 图片 key）或 `both`（逐格优先图片，未命中再 OCR）；Box 列表和二维网格会保持返回形状。`post_process` 解析失败会继续重试，最终仍失败时返回 `None`，任务逻辑不要把原始 OCR 文本当作已解析业务值使用。
- 不直接调用 MuMuManager subprocess；设备会话由调度器、WebUI 或 runtime context 管。
- 纯坐标点击用 `B(x, y, w, h)`；OCR 语义和业务语义分开处理。
- 多个识别目标必须包成 tuple/list：`(T("A"), T("B"))` 表示任一命中，`[T("A"), T("B")]` 表示全部命中；`locate()`、`match()`、`coloris()` 均沿用这套组合语义。不要写 `wait_for_appear(T("A"), T("B"))`，第二个位置参数是 `timeout`。
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
