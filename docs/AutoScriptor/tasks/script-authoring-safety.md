# 脚本安全约定

本文记录任务脚本、后台监听和战斗 flow 的风险边界。详细注册规则见 [script-authoring.md](script-authoring.md)，战斗体系见 [battle-flows.md](battle-flows.md)。

## 后台监听

优先使用 `bg.scope()` 表达生命周期：

```python
from AutoScriptor import *

with bg.scope("team") as watch:
    watch.add(
        "entered",
        I("加载中"),
        callback=lambda: bg.set_signal("组队进图", True),
    )
    bg.wait_signal("组队进图", True, timeout=60)
```

规则：

- 用 `BG_SIGNALS` 代替手写内置信号字符串。
- 局部任务不要随手 `bg.clear()`。
- `battle_loop()` 内部有 `bg.protect_clear()`；外部线程的 clear 会被忽略，避免误删战斗监听。
- 需要随时响应的弹窗可 `allow_concurrent=True`，会修改共享状态的流程回调保持普通回调。

## 可取消等待

所有任务等待用 `AutoScriptor.sleep()`。直接 `time.sleep()` 会让 WebUI 停止按钮、调度器停止、retry 中断都变慢。

## 战斗 Flow

职业战斗逻辑优先写成 `battle_plan` 类属性：

```python
from AutoScriptor.battle_character import Hero, battle_plan

class LiuLi(Hero):
    profession = "琉离"

    default_battle_flow = battle_plan("战斗循环146") \
        .first("huashen", 4) \
        .at(50, "zhenwu", fast=30) \
        .every(60, "huashen", fast=30) \
        .combo("146")
```

`profession` 必须显式声明，并与 WebUI 角色职业一致。未声明 `profession` 的辅助子类不会进入职业注册表。

只有非常特殊的逻辑才使用旧 `@flow` 函数。普通循环不要把连招细节塞回任务脚本。

## 调试直跑

```python
@register_task(debug_mode=True)
def task():
    ...
```

debug 任务：

- 不强制回登录页重新登录角色。
- 失败后不关闭/重启游戏。
- 本轮只执行 debug 任务时跳过 `post_execution`。

用于现场验证，不应长期给正式任务全部打开。

任务模块本身不保留文件底部直跑入口。不要把 `if __name__ == "__main__"`、大包围 `try/except`、`traceback.print_exc()`、`bg.stop()`、`exit(0)` 当成调试模板；这些会绕开 WebUI/调度器的停止、日志和 retry 语义。

未完成实验不要通过 `@register_task` 暴露成正式内置任务。尤其不要保留 `raise Stop here`、裸 `print()` 调试输出、不可达正式流程这类占位代码；确认不在主线时直接删掉。

## 进度和人工接管

任务有阶段性业务完成度时写 `progress`。不要把函数正常返回直接当成功。

```python
set_task_status("progress", "5/6")
```

生命周期：

```text
黄色待执行
  -> 写 progress=3/6
  -> 返回但 progress=5/6，进入 retry
  -> retry 耗尽，自动 human_takeover_error，显示红色 5/6
  -> next_exec_time 到期后自动再试
```

材料不足、账号状态需要人处理等可直接抛 `RequestHumanTakeover`。普通异常没有进度时仍按 retry/连续错误处理。

## 配置写入

- 不直接写账号 JSON。
- 不把 `fn/order/param_meta/_due` 当成持久字段。
- 需要改任务状态时用 `set_task_status()` / `get_task_status()`。
- 需要改用户配置时走 WebUI、`cfg` 或已有生命周期服务，避免与调度器运行中保存竞争。
