# AutoScriptor 自定义脚本生成

生成可运行自定义任务时，优先写成 AutoScriptor 项目方言里的“短流程脚本”，像把人工操作录像转成代码。

- 文件放在 `data/custom_task/`。
- 必须使用 `@register_task(path_cn="自定义任务/...")`，并提供 `description`。
- 任务参数写在函数签名默认值中，例如 `redeem_code: str = "1111"`。
- 默认结构是：导入 -> `@register_task` -> 一个 `task()` 函数 -> 一行一个操作。
- 普通 UI 流程通常控制在 10-30 行；不要为了猜测所有异常状态写上百行状态机。
- 主路径优先使用 `ensure_in()`、`click()`、`swipe()`、`sleep()`、`wait_for_appear()`、`ui_T/ui_F()`、`input()`、`key_event()`、`extract_info()`。
- 纯坐标或 ROI 是正常写法：`B(x, y, w, h)`、`T("文字", box=Box(...).margin())`。
- 最终脚本不能包含 `V(...)`。生成阶段看到的视觉 grounding 结果，要转写成稳定文字目标、图片目标、坐标或 ROI。
- 使用 `sleep()`，不要用 `time.sleep()` 等不可取消等待。
- 使用 `TaskRequireReTry` 表示临时 UI/网络失败，使用 `RequestHumanTakeover` 表示需要人工配置或账号状态不满足。
- 任务有业务返回时，写入 `set_task_status("result", value)` 或明确进度状态。
- 输入框可能残留旧文本；点击字段后可按多次 `KEYCODE_DEL` 清空，再输入目标值，最后 `KEYCODE_ENTER` 收起输入层。
- 不要把用户现场的真实 endpoint、模型名、账号、角色名、token、兑换码或截图中的私人文本写进脚本；需要参数时放到函数默认参数或让用户在 WebUI 配置。
- 提交前至少跑 `py_compile`；能在线验证时，要保存截图并确认每一步页面变化。

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

从未知任务生成脚本时，按这个动态流程思考：

1. 找入口：优先 `ensure_in("村庄")` 或其他已知位置，再点击入口文字/图标/坐标。
2. 找目标页：用 1-3 个关键 `click()` / `swipe()` 表达路径，必要时加 `if ui_F(...): swipe(...)`。
3. 输入或选择：用 `click(B(...))` 聚焦，用 `input()` 和 `key_event()` 完成输入。
4. 提交：点击明确按钮；消耗/购买/删除/交易类动作必须先识别确认文案。
5. 返回结果：有提示就 `extract_info(B(...), ensure_not_empty=False, max_retries=1)`，并 `set_task_status("result", result)`。

视觉模型给出的坐标或描述只用于“选点”和“确定 ROI”，不要原样生成自然语言视觉目标。

避免在正式脚本里默认生成：

- `V(...)`、`click(V(...))`、`locate(V(...))`。
- `core_api.mixctrl.screenshot()`、`ocr_for_box()`、`time.monotonic()`。
- 大量 `_helper()`、复杂状态判断、toast 离线帧缓存。
- 对每个点击都写自定义 retry 包装。

这些重型逻辑只用于调试探针，或在短流程脚本在线失败后再局部补一两行。
