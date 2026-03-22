# VLMTarget 视觉定位接口

## 概述

`VLMTarget` 是第四种 Target 类型，通过视觉语言模型（VLM）以自然语言描述定位屏幕上的 UI 元素。适用于模板匹配和 OCR 均无法覆盖的场景（动态 UI、未知布局等）。

**定位优先级链**：`I()` 模板匹配（< 50ms） → `T()` OCR（100-300ms） → `V()` VLM Grounding（500-800ms）

## 快速上手

```python
from AutoScriptor import V, Box

# 最简用法：全屏范围内 VLM 定位
click(V("确认按钮"))

# 指定 ROI 区域，缩小搜索范围，提升速度和精度
click(V("关闭图标", box=Box(900, 0, 380, 100)))

# 与其他 Target 类型混用（元组 = 任一匹配即可）
result = locate((V("开始游戏"), T("开始游戏"), I("开始按钮")), timeout=10)
```

## API 参考

### `VLMTarget` 类

```python
class VLMTarget(Target):
    def __init__(self, description: str, box: Box = None)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `description` | `str` | 必填 | 自然语言描述目标元素 |
| `box` | `Box` | `Box(0,0,1280,720)` | ROI 区域，VLM 只分析此范围内的截图 |

**属性**：
- `description: str` — 目标描述
- `box: Box` — ROI 区域

**继承关系**：`VLMTarget` → `Target`（与 `ImageTarget`/`TextTarget`/`BoxTarget` 平级）

### `V()` 工厂函数

```python
def V(description: str, *, box: Box = None) -> VLMTarget
```

简写工厂函数，等价于 `VLMTarget(description, box)`。

### `vlm_locate()` 识别函数

```python
# AutoScriptor/recognition/rec.py
def vlm_locate(
    haystack_frame,         # ndarray, BGR 全屏截图
    description: str,       # 自然语言描述
    roi_box: Box = None,    # ROI 区域（可选）
) -> list[Box] | None
```

底层识别函数，通常不直接调用。由 `api.py::_locate_all` 在检测到 `VLMTarget` 时自动路由。

**流程**：
1. 裁剪 ROI（如果指定了 `box`）
2. 保存临时截图到 `%TEMP%/_vlm_locate.png`
3. 调用 VLMAgent 进行 grounding（`use_tools=False`）
4. 解析 VLM 返回的坐标 → 转换为 Box
5. 返回 `[Box]` 或 `None`

## 内部路由机制

`_locate_all` 函数在 `api.py` 中对目标列表进行分流：

```
target list: [T("文本"), V("VLM目标"), I("图片")]
                ↓                ↓              ↓
         mixctrl.locate    vlm_locate      mixctrl.locate
         (OCR 路径)        (VLM 路径)       (模板匹配路径)
                ↓                ↓              ↓
         merge results → [box/None, box/None, box/None]
```

VLMTarget 与其他 Target 类型完全隔离，不会干扰现有识别路径。

## 使用建议

1. **优先用 I() 和 T()**：VLM 推理耗时约 500-800ms，只在传统方式无法识别时使用
2. **尽量指定 ROI**：缩小 box 范围可以显著提升 VLM 定位的速度和准确度
3. **描述要具体**：`V("红色的确认按钮")` 比 `V("按钮")` 更精确
4. **混合使用**：可在元组中同时放 `V()` 和 `T()`/`I()`，利用元组的 OR 语义做 fallback

## 配置依赖

VLM grounding 依赖 Ollama 本机推理服务。需确保：
- `config.json` 中 `llm.use_agent = true`
- Ollama 已安装并运行（参见 [Ollama 部署指南](ollama_deploy.md)）
- 模型已拉取（`hf.co/noctrex/UI-Venus-1.5-2B-GGUF`）

## 相关文件

| 文件 | 变更内容 |
|------|----------|
| `AutoScriptor/core/targets.py` | 新增 `VLMTarget` 类和 `V()` 函数 |
| `AutoScriptor/recognition/rec.py` | 新增 `vlm_locate()` 函数 |
| `AutoScriptor/core/api.py` | `_locate_all` 增加 VLM 分支路由 |
| `AutoScriptor/core/__init__.py` | 导出 `V` |
| `AutoScriptor/__init__.py` | 导出 `V` |
| `test/test_refactor_v3v4/test_vlm_target.py` | VLMTarget 单元测试 |
| `test/test_refactor_v3v4/test_locate_all_vlm_branch.py` | 路由集成测试 |
