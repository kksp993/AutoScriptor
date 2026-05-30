# AutoScriptor 自定义脚本生成

生成可运行自定义任务时，优先写成 AutoScriptor 项目方言里的“短流程脚本”，像把人工操作录像转成代码。

## 真实脚本方言

- 文件放在 `data/custom_task/`。
- 必须使用 `@register_task(path_cn="自定义任务/...")`，并提供 `description`。
- 任务参数写在函数签名默认值中，例如 `redeem_code: str = "1111"`。
- 默认结构是：导入 -> `@register_task` -> 一个 `task()` 函数 -> 一行一个操作。
- 自定义任务文件交给加载器执行；不要生成 `if __name__ == "__main__"`、`traceback`、`bg.stop()`、`exit(0)` 这类本地调试尾巴。
- 普通 UI 流程通常控制在 10-45 行；不要为了猜测所有异常状态写上百行状态机。
- 主路径优先使用 `ensure_in()`、`click()`、`swipe()`、`sleep()`、`wait_for_appear()`、`wait_for_disappear()`、`ui_T/ui_F()`、`input()`、`key_event()`、`extract_info()`。
- 纯坐标或 ROI 是正常写法：`B(x, y, w, h)`、`T("文字", box=Box(...).margin())`。不要羞于用已验证坐标。
- 已知图标优先 `I("导航-挑战")` / `ui["导航-挑战"].i`，文字优先 `T("文字")`，稳定坐标优先 `B(...)`。
- 可用 tuple 表示备选目标：`click((I("导航-战令"), T("战令", box=Box(...).margin())))`。
- 可用 `offset` / `resize` 点击文字附近按钮：`click(T("难度15", box=Box(...).margin()), offset=(120, 120), resize=(80, 80))`。
- 最终脚本不能包含 `V(...)`。生成阶段看到的视觉 grounding 结果，要转写成稳定文字目标、图片目标、坐标或 ROI。
- 使用 `sleep()`，不要用 `time.sleep()` 等不可取消等待。
- 使用 `TaskRequireReTry` 表示临时 UI/网络失败，使用 `RequestHumanTakeover` 表示需要人工配置或账号状态不满足。
- 任务有业务返回时，写入 `set_task_status("result", value)` 或明确进度状态。
- 输入框可能残留旧文本；点击字段后可按多次 `KEYCODE_DEL` 清空，再输入目标值，最后 `KEYCODE_ENTER` 收起输入层。
- 不要把用户现场的真实 endpoint、模型名、账号、角色名、token、兑换码或截图中的私人文本写进脚本；需要参数时放到函数默认参数或让用户在 WebUI 配置。
- 示例里的 `...`、`目标入口`、`目标项` 只是文档占位；输出最终脚本时必须替换为真实 `T(...)`、`I(...)`、`B(...)` 或 `Box(...)` 参数，不能留下占位符。
- 提交前至少跑 `py_compile`；能在线验证时，要保存截图并确认每一步页面变化。

## 常见结构

普通领取/点击流：

```python
@register_task(path_cn="自定义任务/分类/任务名", description="一句话说明", debug_mode=True)
def task():
    ensure_in("村庄")
    click(I("导航-挑战"))
    click(T("目标入口", box=Box(...).margin()))
    wait_for_appear(T("页面标题"))
    click(T("领取奖励"), if_exist=True, timeout=2)
    click(B(1200, 30, 30, 30))
```

有一层缺省分支：

```python
if ui_F(T("目标标签", box=Box(...).margin()), 1):
    swipe(B(...), B(...), duration_s=1)
click(T("目标标签", box=Box(...).margin()))
```

列表/页签查找：

```python
cnt = 0
while ui_F(T("目标项")) and cnt < 5:
    swipe(B(315, 600), B(315, 230), duration_s=0.3)
    sleep(0.2)
    cnt += 1
if ui_T(T("目标项")):
    click(T("目标项"))
```

读数并计算点击次数：

```python
price = extract_info(B(523, 300, 300, 60), lambda res: int(res))
repeat = 28888 // price
click(B(820, 400, 40, 40), repeat=repeat)
click(T("确定"))
```

购物/消耗先确认可买：

```python
box = locate(T(item_name), timeout=10)
if box is None:
    return
if first(get_colors(T("购买", box=box + {"offset": (0, 240)}))) == "绿色":
    click(B(box), offset=(0, 240), delay=0.5)
```

输入：

```python
click(T("输入框提示", box=Box(...).margin()))
input(value)
key_event(AndroidKey.KEYCODE_ENTER)
click(T("确定", box=Box(...).margin()))
```

## 参数和复杂任务

- 简单脚本用普通默认参数：`def task(count: int = 3, code: str = "")`。
- 需要 WebUI 下拉时用 `Enum`，函数参数默认枚举成员。
- 多副本/多目标矩阵才用 `TableParam`；不要给一次性 UI 流程上复杂参数模型。
- 战斗脚本暴露 `battle_flow: BattleFlowName = DEFAULT_BATTLE_FLOW`，进入副本后交给 `h.battle_task()` 或 `h.battle_loop()`，不要在任务脚本里展开连招细节。
- `bg.scope()` 主要用于战斗或异步退出信号；普通 UI 点击流不要默认使用。
- helper 只在重复语义片段出现时抽，例如 `buy_item()`、`add_friend()`；不要为了包装每一步点击而抽 helper。

## 生成判断

从未知任务生成脚本时，按这个动态流程思考：

1. 找入口：优先 `ensure_in("村庄")`、`ensure_in("仙盟")`、`ensure_in("极北村庄")` 等已知位置，再点击入口文字/图标/坐标。
2. 找目标页：用 1-3 个关键 `click()` / `swipe()` 表达路径，必要时加 `if ui_F(...): swipe(...)`。
3. 操作主体：一行一个动作，保留用户轨迹顺序；只有页面可能分叉时才加 `if/while`。
4. 输入或选择：用 `click(B(...))` 或 `click(T("提示", box=...))` 聚焦，用 `input()` 和 `key_event()` 完成输入。
5. 提交：点击明确按钮；消耗、购买、删除、交易类动作必须先识别确认文案或颜色。
6. 返回结果：有提示就 `extract_info(B(...), ensure_not_empty=False, max_retries=1)`，并 `set_task_status("result", result)`。
7. 收尾：用右上角 `B(1200, 30, 30, 30)`、`wait_for_appear()` 或 `ensure_in(LOC_ENV)` 回到稳定状态。

推荐输出格式：

```python
from AutoScriptor import *
from ZmxyOL import *

@register_task(path_cn="自定义任务/分类/任务名", description="一句话说明", debug_mode=True)
def task(param: str = "默认值"):
    ensure_in("村庄")
    click(T("入口", box=Box(...).margin()))
    sleep(1)
    click(T("目标", box=Box(...).margin()))
    input(param)
    result = extract_info(B(...), ensure_not_empty=False, max_retries=1) or "未识别"
    set_task_status("result", result)
    return result
```

视觉模型给出的坐标或描述只用于“选点”和“确定 ROI”，不要原样生成自然语言视觉目标。

避免在正式脚本里默认生成：

- `V(...)`、`click(V(...))`、`locate(V(...))`。
- `core_api.mixctrl.screenshot()`、`ocr_for_box()`、`time.monotonic()`。
- 大量 `_helper()`、复杂状态判断、toast 离线帧缓存。
- 对每个点击都写自定义 retry 包装。

这些重型逻辑只用于调试探针，或在短流程脚本在线失败后再局部补一两行。
