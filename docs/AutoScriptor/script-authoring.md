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
