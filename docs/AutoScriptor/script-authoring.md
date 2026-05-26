# Script Authoring Rules

任务脚本可以继续用熟悉的 `from AutoScriptor import *` 写法，但需要遵守几条运行期约定。

## Sleep

使用:

```python
sleep(1)
```

不要使用:

```python
import time
time.sleep(1)
```

原因:

- `AutoScriptor.sleep()` 会响应 WebUI 停止按钮。
- 长时间 `time.sleep()` 会让“终止执行”看起来卡住。
- 导航、登录、等待动画这类高频路径必须可取消。

## 配置与任务状态

- 不要直接写账号 JSON 文件。
- 任务执行后状态更新走 `TaskManager._update_next_exec_time()`。
- WebUI 保存任务会剥离 `fn/order/param_meta/_due` 等运行时字段，脚本不要依赖这些字段被持久化。

## 设备控制

- 普通脚本只使用 `click/locate/swipe/input/key_event/extract_info`。
- 不直接调用 MuMuManager subprocess。
- 需要诊断设备时使用 WebUI“启动诊断”，不要在任务脚本里自行探测多个底层通道。

## 颜色判断

- 旧写法 `color="绿色"` 仍然保留，适合历史脚本。
- 新写法可直接传 RGB，例如 `B(100, 200, 30, 30, color=(80, 210, 90))`。
- 如果你想更宽松一点，可以传字典：

```python
B(100, 200, 30, 30, color={"rgb": (80, 210, 90), "tolerance": 28, "min_ratio": 0.45})
```

- 纯色块、按钮高亮、状态灯这类判断优先用 RGB 快路径，速度通常比 OCR/模板识别快很多。
- 想调阈值时可以先看统计：

```python
get_rgb_stats(B(100, 200, 30, 30), (80, 210, 90))
```
