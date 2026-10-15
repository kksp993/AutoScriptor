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
from ZmxyOL.character import Hero, battle_plan

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
@register_task(debug=True)
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

## 网格页面的坐标

商店、背包这类**多列网格**里，固定偏移是最大的坑。真实事故（混沌炼狱塔的妖魄商铺）：

- 价格框写成「商品名中心 + 220px」。这个偏移只在列表**顶行**成立，商品名落到下面几行时
  价格框直接跑到屏幕外，那件商品被静默跳过——同一行里只买了其中一个。
- 三列按钮左边界是 `503 / 687 / 872`，却写成 `502 / 686 / 939`：第三个用了那一列的**中心**，
  读价整体右移 67px 落到卡片外。更早的写法「名称中心 x + 45 再比阈值」会让第 1 列掉进
  第 2 列区间，两个商品读到同一个价格。**按名称中心就近吸附到列边界**，不要用偏移后比阈值。
- 余额/数量这类数字框要量够宽：82px 宽会把 `330000` 读成 `33000`，判「买得起」直接反掉。
  宁可框宽一点——OCR 会忽略框内多余背景。

网格里还有一条通用规则：**商品名是文本、图标和价格是位图**，其中价格按钮的颜色往往就是
「还能不能买」的状态（本任务是粉红=有额度、灰=已兑完）。把按钮当唯一判据，比「读兑换次数
还剩几次」稳得多：次数文本可能粘连、可能换行。

### 列表滚动

一屏放不下时，**必须边滚边判**：商品名落在下半屏时它的按钮在屏幕外，看一眼就下结论必然漏。
滚动本身有两点要注意：

- **用 `swipe_precise` 而不是 `swipe`**。`swipe` 的轨迹带随机偏移、松手还有惯性，实测同一句
  代码的位移在 159~376px 之间跳。`swipe_precise` 走固定直线，拖 120px 位移约 107px 稳定。
- **步长要小于可操作带**。本任务里「商品名在上、按钮完整可见」的窗口约 150px；步长超过它，
  商品会从「还没滚到」直接跳到「滚过头」，整件漏掉。用 120px 配 26 次上限覆盖整个列表。

顺带一个观察：这个商店**每次购买后会自己把列表滚回顶部**。所以「买 → 重新扫描」的循环能
自然从顶部重新开始；但这意味着**不能**假设「买完还在原地」。
