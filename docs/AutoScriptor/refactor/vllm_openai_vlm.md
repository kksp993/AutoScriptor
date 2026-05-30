# vLLM / OpenAI VLM 接入

`AutoScriptor.vlm.VLMClient` 支持两类视觉模型接口：

- Ollama 原生图像接口：`/api/chat`。
- OpenAI 兼容图文接口：`/v1/chat/completions`，适用于 vLLM 等服务。

配置示例：

```json
{
  "llm": {
    "use_agent": true,
    "url": "https://YOUR_VLM_HOST/v1",
    "model": "YOUR_VLM_MODEL",
    "api_format": "vllm",
    "skills": [
      "autoscriptor_api",
      "safe_task_execution",
      "vision_grounding_patterns",
      "custom_task_authoring"
    ]
  }
}
```

`api_format` 可取值：

- `auto`：默认。`:11434` 或 `/api/chat` 走 Ollama，其余走 OpenAI 图文格式。
- `ollama`：强制使用 Ollama `/api/chat`。
- `openai` / `vllm`：强制使用 OpenAI `image_url` 图文格式。

Agent skills 位于 `AutoScriptor/vlm/agent_skills/`，由 `load_agent_skills()` 注入系统提示词。默认 skills 只放通用脚本生成规范；具体任务经验不要默认注入，避免小模型过拟合某个活动路径。

文档、测试、skills 和生成脚本都不要写入用户现场的真实内网地址、端口、模型部署名、账号、兑换码或截图内容。示例统一使用 `YOUR_*` 或 `example.invalid` 占位符。

生成最终脚本时，视觉模型只用于生成阶段的观察和定位。脚本运行环境不依赖视觉模型，因此脚本中禁止输出 `V(...)`、`click(V(...))` 或 `locate(V(...))`，必须转写为 `T(...)`、`I(...)`、`B(...)`、`extract_info(B(...))` 等运行时 API。

当前内置 skills：

- `autoscriptor_api`：教模型使用 `locate/click/input/ensure_in` 等 API。
- `safe_task_execution`：保守执行、失败停机、不可逆操作保护。
- `vision_grounding_patterns`：ROI grounding、toast 连续截图、输入层处理。
- `custom_task_authoring`：自定义任务目录、注册格式、参数、状态和验证规则。

任务专用复盘材料应留在调试记录或普通文档中，不应进入默认 skills。
