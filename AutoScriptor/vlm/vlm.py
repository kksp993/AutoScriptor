"""
VLM 调用模块（Agno 封装）
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from agno import agent
import requests
from agno.agent import Agent
from agno.models.vllm import VLLM
from logzero import logger

from AutoScriptor.vlm.config import VLM_CONFIG
from AutoScriptor.vlm.templates import SYSTEM_PROMPT, build_messages
from AutoScriptor.vlm.tools import load_toolkits
from AutoScriptor.vlm.utils import encode_image_to_base64


def _resolve_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = {**VLM_CONFIG}
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def _normalize_base_url(api_url: str) -> str:
    return api_url.rsplit("/chat/completions", 1)[0] if api_url.endswith("/chat/completions") else api_url


def call_vllm_chat_completion(
    question: str,
    screenshot: Optional[str] = None,
    tools: Optional[list] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """调用 vLLM 进行多模态推理"""

    cfg = _resolve_config(overrides)
    image_path = screenshot or cfg.get("default_image")
    base64_image = encode_image_to_base64(image_path)

    payload = {
        "model": cfg["model_name"],
        "messages": build_messages(question, base64_image),
        "max_tokens": cfg["max_tokens"],
        "temperature": cfg["temperature"],
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(
        cfg["api_url"],
        headers=headers,
        json=payload,
        timeout=cfg.get("timeout", 60),
    )
    response.raise_for_status()
    return response.json()


def extract_vllm_text(result: Dict[str, Any]) -> str:
    """提取模型文本输出"""
    choices = result.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "")


class VLMAgent:
    """基于 Agno+vLLM 的智能体包装，仅负责推理调用"""

    def __init__(self, tools: Optional[list] = None, **overrides: Any):
        self.config = _resolve_config(overrides)
        
        # 加载工具：合并内置工具和传入的工具
        agent_tools = load_toolkits()
        if tools:
            agent_tools.extend(tools)
            
        self._agent = Agent(
            model=VLLM(
                id=self.config["model_name"],
                base_url=_normalize_base_url(self.config["api_url"]),
                temperature=self.config["temperature"],
            ),
            instructions=[
                "优先使用工具（如 click, ensure_in）来执行操作，而不是仅输出文本建议。",
                SYSTEM_PROMPT,
                "如果工具返回包含__Screenshot_Required__的字符串，**必须**输出__Screenshot_Required__，并启动第二轮对话。",
            ],
            tools=agent_tools,
            markdown=True,
            add_history_to_context=False,
            debug_mode=True, # 开启调试以观察 Tool Call
        )

    def run(self, prompt: str, screenshot: Optional[str] = None, thinking_mode: bool = False) -> str:
        """使用 Agno Agent 进行推理，支持工具调用"""
        image_path = screenshot or self.config.get("default_image")
        from agno.media import Image
        # 注意：根据 Agent.run 签名，这里应该传 images 列表，而不是 image 参数
        if thinking_mode:
            response_stream = self._agent.run(prompt, images=[Image(filepath=image_path)], stream=True)
        
            chunks = []
            for chunk in response_stream:
                if isinstance(chunk, str):
                    print(chunk, end="", flush=True)
                    chunks.append(chunk)
                elif hasattr(chunk, "content"):
                    print(chunk.content, end="", flush=True)
                    chunks.append(chunk.content)
        else:
            response = self._agent.run(prompt, images=[Image(filepath=image_path)])
            return response.content
        return "".join([str(c) for c in chunks])

    @property
    def agent(self) -> Agent:
        """暴露底层 Agno Agent"""
        return self._agent

