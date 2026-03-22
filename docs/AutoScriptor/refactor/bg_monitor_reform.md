# 后台监控改革

> 阶段二 · 对应模块：`AutoScriptor/core/background.py`、`AutoScriptor/core/api.py`

## 背景

`BackgroundMonitor` 是后台守护线程，按固定间隔扫描已注册的回调条件（如 UI 元素出现）。原实现存在以下问题：

1. **独立截图**：每个 `ui_T(idf)` 调用内部都会触发 `mixctrl.screenshot()`，N 个回调 = N 次截屏
2. **独立 OCR**：每次截屏后如果是文本目标，还会触发独立的 PaddleOCR 推理
3. **过高频率**：默认 `DEFAULT_INTERVAL = 0.2s`（5Hz），CPU 负载过高

---

## 改动内容

### 1. 共享截图

每轮循环开始时只调用一次 `mixctrl.screenshot()`，将截图通过 `screenshot` 参数传递给所有 `ui_T` 调用：

```python
def run(self):
    from AutoScriptor.core.api import ui_T, mixctrl
    while not self._stop_event.is_set():
        screenshot = mixctrl.screenshot() if mixctrl is not None else None
        for name, info in list(self._callbacks.items()):
            ...
            if not ui_T(idf, screenshot=screenshot):
                continue
            ...
        self._check_concurrent(screenshot=screenshot)
        time.sleep(self._interval)
```

### 2. screenshot 参数透传

在关键 API 函数中新增 `screenshot` 参数，使外部传入的截图能一路传递到 `mixctrl.locate()`：

| 函数 | 参数变化 |
|------|----------|
| `ui_T(target, timeout, *, screenshot=None)` | 新增 keyword-only 参数 |
| `locate(target, timeout, ..., screenshot=None)` | 新增尾部可选参数 |
| `_locate_all(target, *, screenshot=None)` | 已有（无变化） |
| `mixctrl.locate(triples, screenshot=None)` | 已有（无变化） |

**完整调用链**：

```
BackgroundMonitor.run()
  └─ ui_T(idf, screenshot=img)
       └─ locate(target, screenshot=img)
            └─ _locate_all(target, screenshot=img)
                 └─ mixctrl.locate(triples, screenshot=img)
                      └─ locate_on_screen(img, ...)  # 不再重新截屏
```

### 3. 监控间隔调整

| 项目 | 改动前 | 改动后 |
|------|--------|--------|
| `DEFAULT_INTERVAL` | `0.2s`（5Hz） | `1.0s`（1Hz） |

配合帧级 OCR 缓存和模板匹配优先策略，1Hz 的扫描频率足以满足后台弹窗检测需求。可通过 `bg.set_interval()` 按需调整。

### 4. 并发回调处理

| 方法 | 行为 |
|------|------|
| `_check_concurrent(screenshot=None)` | 接受可选截图参数，主循环中复用同一截图 |
| `_concurrent_loop()` | 在主回调执行期间的子线程中运行，**不传入截图**（需要最新画面反映回调执行后的变化） |

---

## 兼容性

- 所有新增参数均有默认值 `None`，不影响现有调用方
- `ui_T` 的 `screenshot` 为 keyword-only 参数，不会与已有的位置参数冲突
- `BackgroundProxy` 代理层无需修改
- `assure_stable` 的稳定性二次检测仍然使用独立截图（不传入共享截图），保证行为正确

---

## 性能预期

| 场景 | 改动前 | 改动后 |
|------|--------|--------|
| N 个回调一轮扫描 | N 次 screenshot + N 次 OCR | 1 次 screenshot + ≤1 次 OCR |
| 扫描频率 | 5Hz | 1Hz |
| CPU 空闲占用 | 高（0.2s 内完成截屏+OCR+匹配） | 低（1s 间隔 + 共享截图） |

---

## 测试

```powershell
conda activate zmxy
python -m unittest test.test_perf_optimize.test_bg_monitor -v
```

覆盖项：`DEFAULT_INTERVAL` 值、`_check_concurrent` 签名、`ui_T`/`locate` 的 `screenshot` 透传、`BackgroundMonitor` 回调 CRUD / signal / interval。
