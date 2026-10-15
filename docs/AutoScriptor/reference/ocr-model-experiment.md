# PP-OCRv6 模型实验

`experiment/pp-ocrv6` 分支用于在不改动识别业务 API 的前提下，对比
PP-OCRv4 与 PP-OCRv6 的游戏文字识别效果。应用层仍使用现有的
`ocr()`、`ocr_for_box()`、`T()` 和数字提取入口；
`AutoScriptor/recognition/paddle_ocr_compat.py` 负责适配 PaddleOCR 2.x/3.x
构造参数和结果结构。

## 依赖和模型

该实验分支使用：

- `paddleocr==3.7.0`
- CPU：`paddlepaddle==3.2.0`，由 `requirements-cpu.txt` 安装；
- GPU：`paddlepaddle-gpu==3.2.2`，由 `requirements-gpu.txt` 从 Paddle
  官方 CUDA 12.9 源安装。

CPU 与 GPU 包都提供 `paddle` 导入，不能在同一 `.venv` 共存。安装脚本会先卸载
两种 Paddle 包，再安装选定变体。

可选模型配置如下：

| 配置值 | 检测模型 | 识别模型 |
| --- | --- | --- |
| `PP-OCRv4` | `PP-OCRv4_mobile_det` | `PP-OCRv4_mobile_rec` |
| `PP-OCRv6_tiny` | `PP-OCRv6_tiny_det` | `PP-OCRv6_tiny_rec` |
| `PP-OCRv6_small` | `PP-OCRv6_small_det` | `PP-OCRv6_small_rec` |
| `PP-OCRv6_medium` | `PP-OCRv6_medium_det` | `PP-OCRv6_medium_rec` |

`data/config.template.json` 默认使用 `PP-OCRv6_small` 处理普通中文文字，
使用 `PP-OCRv6_tiny` 处理数字。也可临时通过环境变量覆盖：

```powershell
$env:AUTOSCRIPTOR_OCR_MODEL = "PP-OCRv4"
$env:AUTOSCRIPTOR_DIGIT_OCR_MODEL = "PP-OCRv6_tiny"
```

模型默认从 Paddle BOS 下载。首次初始化包含模型下载时间，不能把它当作稳定的
OCR 初始化耗时；正式计时前应先完成一次预热。

## 安装实验依赖

项目使用 `uv` 管理无内置 `pip` 的虚拟环境。在实验分支执行：

```powershell
scripts\install.bat python
```

默认安装变体由 `data/config.json -> ocr.use_gpu` 决定，也可明确指定：

```powershell
scripts\install.bat python cpu
scripts\install.bat python gpu
```

普通 OCR、线程局部 OCR 和数字 OCR 共用进程启动时的设备/模型快照。修改
`ocr.use_gpu` 或模型后，应安装匹配的 Paddle 变体并重启 AutoScriptor；运行中不会
热卸载或热切换 Paddle 引擎。GPU 已配置但 Paddle 不含 CUDA，或没有可用 CUDA
设备时，初始化会明确失败，不会静默回退到 CPU。

Git 分支只隔离源码，不隔离 `.venv` 已安装的包。切回 `src` 后若要恢复旧运行时，
应在 `src` 分支重新执行同一安装命令，使虚拟环境重新匹配该分支的
`requirements.txt`。

## 离线同图对照

基准脚本只读取本地图片，不连接模拟器、不点击，也不运行任务。默认分别在独立
子进程中运行 v4 和 v6-small，避免两个模型同时驻留造成内存和时延污染：

```powershell
.venv\Scripts\python.exe -X utf8 scripts\benchmark_ocr_models.py `
  logs\ocr-samples\page.png `
  --target "登录" `
  --target "角色" `
  --repeat 3 `
  --warmup 1
```

测试小字区域时可指定 `left,top,width,height`：

```powershell
.venv\Scripts\python.exe -X utf8 scripts\benchmark_ocr_models.py `
  logs\ocr-samples\page.png `
  --roi 100,200,300,80 `
  --model PP-OCRv4 `
  --model PP-OCRv6_tiny `
  --model PP-OCRv6_small
```

默认报告写入 `logs/ocr-model-benchmark.json`，包含：

- 每个模型的初始化时间、推理中位数和 p95；
- 每张图的文字、置信度和文字框；
- 每个 `--target` 的子串命中结果；
- 实际 PaddleOCR 版本和 CPU/GPU 设备。

这里的 v4 由 PaddleOCR 3.7 管线加载 v4 mobile 模型，用于同运行时模型对照，
不等同于旧 `paddleocr==2.7.0.0` 完整运行栈。若要比较整个旧/新运行栈，应使用
两个独立虚拟环境和相同截图分别运行。

## 已验证 CPU/GPU 差异

在同一张新截取的 `1280x720` 全屏图片上，普通检测加识别管线分别预热 2 次、测量
10 次；CPU 和 GPU 均返回相同的 27 行文字。结果为：

| 设备 | 十次平均耗时 |
| --- | ---: |
| CPU | `1.301301 s` |
| GPU（NVIDIA GeForce RTX 5060） | `0.185395 s` |

该样本中 GPU 约快 `7.02x`，平均延迟降低约 `85.75%`。这只是固定页面的性能基线；
模型准确率仍应按目标文字、ROI 和原始结果逐项验收。

## 验收原则

先比较已验证目标文字的逐项命中率，再比较小字和粘连文字，最后才比较耗时。
任何已验证文字的命中回退都应保留截图、ROI、两端原始识别结果和置信度，不能只看
总体平均准确率。正式接入主线前还需在线截图复验，并按
`docs/agents/online-screenshot-test.md` 执行。
