"""
VLM 调用模块（Agno 封装）
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agno.agent import Agent
from agno.models.vllm import VLLM

from AutoScriptor.vlm.config import VLM_CONFIG
from AutoScriptor.vlm.templates import SYSTEM_PROMPT
from AutoScriptor.vlm.tools import load_toolkits


def _resolve_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = {**VLM_CONFIG}
    if overrides:
        cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


def _normalize_base_url(api_url: str) -> str:
    return api_url.rsplit("/chat/completions", 1)[0] if api_url.endswith("/chat/completions") else api_url


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
                SYSTEM_PROMPT,
            ],
            tools=agent_tools,
            markdown=True,
            add_history_to_context=False,
            debug_mode=False, # 开启调试以观察 Tool Call
        )
        self._agent_no_tools = Agent(
            model=VLLM(
                id=self.config["model_name"],
                base_url=_normalize_base_url(self.config["api_url"]),
                temperature=self.config["temperature"],
            ),
            instructions=[
                """
输入：
- `I(...)` 图片目标（ImageTarget），可设置信心阈值或颜色过滤
- `T(...)` 文本目标（TextTarget），可选正则匹配
- `B(...)` 区域目标（BoxTarget），直接使用坐标盒
                """,
                """
输出：
如果不存在目标，请**必须**返回None。
返回坐标 {'x': <x>, 'y': <y>}。不要解释或其他文字。<x>和<y>是归一化坐标，范围0-1000。
                """,
            ],
            markdown=True,
            add_history_to_context=False,
            debug_mode=False, # 开启调试以观察 Tool Call
        )

    def run(self, prompt: str, screenshot: Optional[str] = None, thinking_mode: bool = False, use_tools: bool = True) -> str:
        """使用 Agno Agent 进行推理，支持工具调用"""
        image_path = screenshot or self.config.get("default_image")
        from agno.media import Image
        # 注意：根据 Agent.run 签名，这里应该传 images 列表，而不是 image 参数
        if thinking_mode and use_tools:
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
            agent = self._agent if use_tools else self._agent_no_tools
            response = agent.run(prompt, images=[Image(filepath=image_path)])
            return response.content
        return "".join([str(c) for c in chunks])

    @property
    def agent(self) -> Agent:
        """暴露底层 Agno Agent"""
        return self._agent

