# OCR 识别优化

> 阶段二 · 对应模块：`AutoScriptor/recognition/ocr_rec.py`

## 背景

原 `ocr()` 函数存在两个性能瓶颈：

1. **scale fallback 双倍开销**：默认 `scale=0.5` 缩小图像做一次 OCR，若未找到目标则以 `scale=1.0` 再做一次。最坏情况每次定位需要两次完整 PaddleOCR 推理。
2. **无帧级缓存**：同一帧截图被多个 `locate` 调用或不同 target 重复做 OCR，浪费大量 CPU/GPU 算力。

---

## 改动内容

### 1. 去除 scale fallback

| 项目 | 改动前 | 改动后 |
|------|--------|--------|
| 默认 scale | `0.5` | `1.0` |
| fallback 逻辑 | `scale≠1.0` 时未找到目标递归调用 `ocr(..., scale=1.0)` | **已移除** |

改动后 `ocr()` 只执行一次 PaddleOCR 推理，直接使用原始分辨率，准确率更高且避免了无谓的二次调用。

### 2. 帧级 OCR 缓存

新增两个内部函数（不对外暴露，调用方无需关心）：

#### `_frame_fingerprint(img) → tuple`

基于图像的 `shape` + 3 个采样像素（左上、中心、右下）生成快速指纹。时间复杂度 O(1)，不依赖图像大小。

```python
def _frame_fingerprint(img):
    h, w = img.shape[:2]
    return (h, w, bytes(img[0, 0]), bytes(img[h // 2, w // 2]), bytes(img[-1, -1]))
```

#### `_raw_ocr_cached(img_for_ocr, ttl=0.5) → list | None`

包装 PaddleOCR 调用并维护单条缓存（默认 TTL=0.5s）。同一帧图像在 TTL 内多次调用时直接返回上次的原始 OCR 结果。

**缓存策略**：

- **单条缓存**：只保留最近一次的 OCR 结果（适合截图场景：同一轮循环中的 ROI 大多相同）
- **线程安全**：使用 `threading.Lock` 保护缓存读写
- **自动过期**：超过 TTL 后自动失效，防止使用过时数据

**命中条件**（三者同时满足）：

1. 缓存非空
2. 图像指纹与缓存中的一致
3. 当前时间距缓存写入不超过 TTL

---

## 对外接口变化

### `ocr()` 函数

```python
def ocr(frame, target_strings, confidence=0.8, preferred_box=None,
        stride=1, fuzzy_threshold=100, scale=1.0) -> list[list[Box]]
```

| 参数 | 变化 |
|------|------|
| `scale` | 默认值 `0.5` → `1.0` |
| 返回值 | 无变化 |
| fallback | 不再存在 scale 递归回退 |

**兼容性**：函数签名保持向后兼容，现有调用方无需修改。显式传入 `scale=0.5` 仍可正常工作，只是不再有自动 fallback。

---

## 性能预期

| 场景 | 改动前 | 改动后 |
|------|--------|--------|
| OCR 未命中（最坏） | 2 次 PaddleOCR | 1 次 |
| 同帧多次 locate | N 次 PaddleOCR | 1 次（缓存命中） |
| BackgroundMonitor 一轮 | N × screenshot + N × OCR | 1 × screenshot + ≤1 × OCR |

---

## 测试

```powershell
conda activate zmxy
python -m unittest test.test_perf_optimize.test_ocr_cache -v
```

覆盖项：`_frame_fingerprint` 一致性/区分度、`_raw_ocr_cached` 命中/过期/引擎不可用、`ocr()` 签名/无递归 fallback。
