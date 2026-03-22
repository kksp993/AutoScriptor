"""
VLM Client — Ollama 原生 API (grounding) + OpenAI SDK (tool-calling / chat)
===========================================================================
grounding 使用 Ollama /api/chat，自动根据模型名选择 prompt 模板：
  - UI-TARS 系列: 极简 prompt，~0.05s eval，无 thinking 开销
  - qwen3-vl 系列: 含 thinking 阶段，~2-4s eval
图片统一降采样至 _GROUND_MAX_DIM 减少视觉 token。
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

import cv2
import requests as _http
from openai import OpenAI

from AutoScriptor.vlm.config import VLM_CONFIG
from AutoScriptor.vlm.utils import encode_image_to_base64, parse_qwen_vl_coordinates

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

_GROUND_MAX_DIM = 640

_UITARS_RE = re.compile(r"ui[_-]?tars", re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks (Qwen3 thinking mode)."""
    return _THINK_RE.sub("", text).strip()


def _ollama_base(api_url: str) -> str:
    """Derive Ollama base (e.g. http://host:11434) from any configured URL."""
    url = api_url.rstrip("/")
    for suffix in ("/v1", "/api/chat", "/chat/completions", "/v1/chat/completions"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url


class VLMClient:
    """Lightweight VLM wrapper — Ollama native for grounding, OpenAI SDK for the rest."""

    def __init__(self, **overrides: Any):
        cfg = {**VLM_CONFIG, **{k: v for k, v in overrides.items() if v is not None}}
        raw_url: str = cfg["api_url"]

        self._ollama_base = _ollama_base(raw_url)

        oai_base = self._ollama_base + "/v1"
        self._client = OpenAI(base_url=oai_base, api_key=cfg.get("api_key", "ollama"))
        self._model = cfg["model_name"]
        self._max_tokens = cfg.get("max_tokens", 512)
        self._temperature = cfg.get("temperature", 0.1)
        self._timeout = cfg.get("timeout", 30)

    # ── grounding (Ollama native /api/chat) ──

    _GROUND_SYSTEM_QWEN = (
        "You are a UI grounding assistant. "
        "Return the center point of the target as (x,y) with range 0-999. "
        "Output ONLY the coordinates, nothing else."
    )

    _GROUND_SYSTEM_UITARS = (
        "You are a UI grounding assistant. "
        "Return click(start_box='<|box_start|>(x,y)<|box_end|>') "
        "for the target element."
    )

    @staticmethod
    def _downscale_for_ground(screenshot_path: str) -> str:
        """Downscale image to ≤ _GROUND_MAX_DIM on longest side, return base64 JPEG."""
        img = cv2.imread(screenshot_path)
        if img is None:
            with open(screenshot_path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        h, w = img.shape[:2]
        if max(w, h) > _GROUND_MAX_DIM:
            scale = _GROUND_MAX_DIM / max(w, h)
            img = cv2.resize(img, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_AREA)
        _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buf.tobytes()).decode()

    @property
    def _is_uitars(self) -> bool:
        return bool(_UITARS_RE.search(self._model))

    def ground(self, description: str, screenshot_path: str,
               *, width: int = 1280, height: int = 720) -> tuple[int, int] | None:
        """Pure grounding via Ollama native API for minimum latency.

        Auto-selects prompt template by model name:
          - UI-TARS: ~0.05 s eval, 8 tokens, no thinking
          - qwen3-vl: ~2-4 s eval, 208-384 tokens (mandatory thinking)
        """
        b64 = self._downscale_for_ground(screenshot_path)
        is_uitars = self._is_uitars

        system = self._GROUND_SYSTEM_UITARS if is_uitars else self._GROUND_SYSTEM_QWEN
        user_content = description if is_uitars else f"找到: {description}"
        num_predict = 64 if is_uitars else 384

        resp = _http.post(
            f"{self._ollama_base}/api/chat",
            json={
                "model": self._model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content, "images": [b64]},
                ],
                "options": {
                    "temperature": 0.0,
                    "num_predict": num_predict,
                },
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", {})

        raw = msg.get("content", "") or ""
        raw = _strip_thinking(raw)

        if not raw:
            thinking = msg.get("thinking", "") or ""
            raw = _strip_thinking(thinking)

        if not raw:
            return None

        try:
            return parse_qwen_vl_coordinates(raw, width=width, height=height)
        except (ValueError, IndexError):
            return None

    # ── visual question-answering (Ollama native /api/chat) ──

    def ask(self, question: str, screenshot_path: str,
            *, system: str = "", num_predict: int = 256) -> str | None:
        """Look at a screenshot and answer a free-form question.

        Uses the same Ollama native API and image downscaling as ``ground()``,
        but returns raw text instead of parsed coordinates.
        """
        b64 = self._downscale_for_ground(screenshot_path)
        sys_msg = system or "回答简洁，只输出关键信息，不要解释。"

        resp = _http.post(
            f"{self._ollama_base}/api/chat",
            json={
                "model": self._model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": question, "images": [b64]},
                ],
                "options": {
                    "temperature": 0.0,
                    "num_predict": num_predict,
                },
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        msg = resp.json().get("message", {})

        raw = msg.get("content", "") or ""
        raw = _strip_thinking(raw)

        if not raw:
            thinking = msg.get("thinking", "") or ""
            raw = _strip_thinking(thinking)

        return raw or None

    # ── tool-calling agent loop (OpenAI SDK) ──

    def run_with_tools(self, prompt: str, screenshot_path: str,
                       tools: dict[str, dict], *,
                       system: str = "", max_rounds: int = 5) -> str:
        """Standard OpenAI tool-calling loop.

        *tools* maps tool name → {"schema": <openai function schema>, "handler": <callable>}.
        """
        from AutoScriptor.vlm.templates import build_system_prompt
        sys_prompt = system or build_system_prompt()

        b64 = encode_image_to_base64(screenshot_path)
        messages: list[dict] = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                }},
            ]},
        ]
        tool_schemas = [v["schema"] for v in tools.values()]

        for _ in range(max_rounds):
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tool_schemas or None,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                timeout=self._timeout,
            )
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                return _strip_thinking(msg.content or "")

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                handler = tools.get(fn_name, {}).get("handler")
                if handler is None:
                    result = json.dumps({"error": f"unknown tool: {fn_name}"})
                else:
                    try:
                        args = json.loads(tc.function.arguments)
                        result = str(handler(**args))
                    except Exception as e:
                        result = json.dumps({"error": str(e)})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return messages[-1].get("content", "")

    # ── simple text completion (no vision) ──

    def chat(self, prompt: str, *, system: str = "") -> str:
        """Plain text chat without vision or tools."""
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            timeout=self._timeout,
        )
        return _strip_thinking(resp.choices[0].message.content or "")


# Backward-compat alias used by rec.py vlm_locate
VLMAgent = VLMClient
