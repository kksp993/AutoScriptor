# Ollama 本机 VLM 部署指南

## 概述

AutoScriptor 通过 Ollama 在本机运行 VLM（视觉语言模型），为 `V()` 目标提供 grounding 能力。Ollama 暴露 OpenAI 兼容 API，无需额外依赖。

**推理链路**：`V("目标描述")` → `vlm_locate()` → `VLMAgent` → Ollama API → `UI-Venus-1.5-2B` 模型

## 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 |
| GPU | 推荐 NVIDIA RTX 3060+ (VRAM ≥ 6GB)，CPU 也可运行但较慢 |
| Ollama | ≥ v0.7.0（支持 OpenAI 兼容端点） |
| 模型 | `hf.co/noctrex/UI-Venus-1.5-2B-GGUF`（约 1.5GB） |

## 安装步骤

### 1. 安装 Ollama

从官网下载并安装：https://ollama.com/download

安装后验证：

```powershell
ollama --version
# 应输出 ollama version 0.x.x
```

### 2. 拉取模型

```powershell
ollama pull hf.co/noctrex/UI-Venus-1.5-2B-GGUF
```

首次拉取约需下载 1.5GB，之后会缓存在本地。

### 3. 使用部署脚本（可选）

项目提供了一键检查和拉取脚本：

```powershell
conda activate zmxy

# 检查 Ollama 状态 + 自动拉取模型
python tools/setup_ollama.py

# 仅检查状态，不拉取
python tools/setup_ollama.py --check

# 指定其他模型
python tools/setup_ollama.py --model qwen2.5-vl:3b
```

脚本会依次检查：
1. Ollama 是否运行
2. OpenAI 兼容端点是否可用
3. 目标模型是否已下载

### 4. 配置 config.json

确保 `config.json` 的 `llm` 部分如下：

```json
{
    "llm": {
        "use_agent": true,
        "url": "http://localhost:11434/v1",
        "model": "hf.co/noctrex/UI-Venus-1.5-2B-GGUF"
    }
}
```

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `use_agent` | 是否启用 VLM 功能 | `false` |
| `url` | Ollama 的 OpenAI 兼容端点 | `http://localhost:11434/v1` |
| `model` | 使用的模型标识 | `hf.co/noctrex/UI-Venus-1.5-2B-GGUF` |

> **注意**：`use_agent` 默认为 `false`，需要手动改为 `true` 才会启用 VLM 功能。

## 验证部署

### 命令行验证

```powershell
# 确认 Ollama 正在运行
curl http://localhost:11434/api/version

# 确认 OpenAI 兼容端点
curl http://localhost:11434/v1/models

# 测试推理（简单文本）
curl http://localhost:11434/v1/chat/completions -d '{
  "model": "hf.co/noctrex/UI-Venus-1.5-2B-GGUF",
  "messages": [{"role": "user", "content": "hello"}]
}'
```

### 脚本验证

```powershell
python tools/setup_ollama.py --check
```

输出示例：

```
==================================================
  Ollama + VLM 部署检查
==================================================
[OK] Ollama 已运行，版本: 0.9.2
[OK] OpenAI 兼容端点可用，可用模型: ['hf.co/noctrex/UI-Venus-1.5-2B-GGUF:latest']
[OK] 模型 hf.co/noctrex/UI-Venus-1.5-2B-GGUF 已就绪 (1.4 GB)

所有检查通过！VLM 已就绪。
```

## 配置映射关系

```
config.json                     → AutoScriptor 内部
─────────────────────────────────────────────────
llm.url                         → VLM_CONFIG["api_url"] (+ "/chat/completions")
llm.model                       → VLM_CONFIG["model_name"]
llm.use_agent                   → RuntimeContext.init_vlm() 的启用开关
```

`AutoScriptor/vlm/config.py` 负责从 `cfg["llm"]` 读取并生成 `VLM_CONFIG` 字典，供 `VLMAgent` 使用。

## 更换模型

如需更换为其他模型（如 Qwen2.5-VL），只需：

1. 拉取新模型：`ollama pull qwen2.5-vl:3b`
2. 修改 `config.json`：`"model": "qwen2.5-vl:3b"`
3. 重启程序

只要模型支持 vision（图文混合输入），均可通过 Ollama 的 OpenAI 兼容端点接入。

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| `VLM grounding failed: Connection refused` | Ollama 未启动，运行 `ollama serve` |
| `Model not found` | 模型未拉取，运行 `ollama pull <model>` |
| 推理极慢（>5s） | 检查 GPU 是否被正确利用：`ollama ps` 查看模型加载状态 |
| `use_agent` 为 true 但 VLM 不工作 | 检查 `url` 是否正确（默认 `http://localhost:11434/v1`） |

## 相关文件

| 文件 | 说明 |
|------|------|
| `config template.json` | 配置模板（llm 部分） |
| `AutoScriptor/vlm/config.py` | VLM 配置读取与映射 |
| `tools/setup_ollama.py` | 部署检查与模型拉取脚本 |
| `test/test_refactor_v3v4/test_ollama_config.py` | 配置测试 |
