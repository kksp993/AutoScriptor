"""
VLM 前端接口
"""

from .vlm import VLMAgent, call_vllm_chat_completion, extract_vllm_text

__all__ = [
    "VLMAgent",
    "call_vllm_chat_completion",
    "extract_vllm_text",
]