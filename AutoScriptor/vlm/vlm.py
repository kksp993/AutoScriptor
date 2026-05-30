"""VLM client adapters for Ollama and OpenAI-compatible servers.

The local project historically used Ollama's native ``/api/chat`` image
format for grounding. Newer vLLM deployments expose vision models through the
OpenAI ``/v1/chat/completions`` image_url format. This client keeps both paths
available behind the same API.
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
    """Remove Qwen-style thinking blocks/tags from model output."""
    stripped = _THINK_RE.sub("", text or "")
    return stripped.replace("<think>", "").replace("</think>", "").strip()


def _strip_known_suffix(url: str) -> str:
    clean = url.rstrip("/")
    for suffix in ("/v1", "/api/chat", "/chat/completions", "/v1/chat/completions"):
        if clean.endswith(suffix):
            return clean[: -len(suffix)]
    return clean


def _ollama_base(api_url: str) -> str:
    """Derive Ollama base, e.g. ``http://host:11434``."""
    return _strip_known_suffix(api_url)


def _openai_base(api_url: str) -> str:
    """Derive OpenAI-compatible base URL ending in ``/v1``."""
    clean = api_url.rstrip("/")
    if clean.endswith("/v1"):
        return clean
    if clean.endswith("/chat/completions"):
        return clean[: -len("/chat/completions")]
    return _strip_known_suffix(clean) + "/v1"


def _infer_api_format(api_url: str, configured: str | None) -> str:
    """Return ``ollama`` or ``openai`` for image requests."""
    value = (configured or "auto").strip().lower()
    if value in {"openai", "vllm"}:
        return "openai"
    if value == "ollama":
        return "ollama"
    clean = api_url.rstrip("/")
    if "/api/chat" in clean or ":11434" in clean:
        return "ollama"
    return "openai"


class VLMClient:
    """Lightweight VLM wrapper for grounding, VQA, chat, and tool loops."""

    _GROUND_SYSTEM_QWEN = (
        "You are a UI grounding assistant. Find the requested UI element. "
        "Return only the center point as (x,y), using normalized coordinates "
        "in the 0-999 range. Do not explain."
    )

    _GROUND_SYSTEM_UITARS = (
        "You are a UI grounding assistant. "
        "Return click(start_box='<|box_start|>(x,y)<|box_end|>') "
        "for the target element."
    )

    def __init__(self, **overrides: Any):
        cfg = {**VLM_CONFIG, **{k: v for k, v in overrides.items() if v is not None}}
        raw_url: str = cfg["api_url"]

        self._ollama_base = _ollama_base(raw_url)
        self._openai_base = _openai_base(raw_url)
        self._api_format = _infer_api_format(raw_url, cfg.get("api_format"))
        self._client = OpenAI(
            base_url=self._openai_base,
            api_key=cfg.get("api_key", "ollama"),
        )
        self._model = cfg["model_name"]
        self._max_tokens = cfg.get("max_tokens", 512)
        self._temperature = cfg.get("temperature", 0.1)
        self._timeout = cfg.get("timeout", 30)

    @staticmethod
    def _downscale_for_ground(screenshot_path: str) -> str:
        """Downscale image to <= _GROUND_MAX_DIM on the longest side as JPEG."""
        img = cv2.imread(screenshot_path)
        if img is None:
            with open(screenshot_path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        h, w = img.shape[:2]
        if max(w, h) > _GROUND_MAX_DIM:
            scale = _GROUND_MAX_DIM / max(w, h)
            img = cv2.resize(
                img,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )
        _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buf.tobytes()).decode()

    @property
    def _is_uitars(self) -> bool:
        return bool(_UITARS_RE.search(self._model))

    def _openai_vision_messages(self, prompt: str, b64_jpeg: str, *, system: str) -> list[dict]:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_jpeg}"},
                },
            ],
        })
        return messages

    def ground(
        self,
        description: str,
        screenshot_path: str,
        *,
        width: int = 1280,
        height: int = 720,
    ) -> tuple[int, int] | None:
        """Locate a UI element by natural-language description."""
        if self._api_format == "ollama":
            return self._ground_ollama(description, screenshot_path, width=width, height=height)
        return self._ground_openai(description, screenshot_path, width=width, height=height)

    def _ground_ollama(
        self,
        description: str,
        screenshot_path: str,
        *,
        width: int,
        height: int,
    ) -> tuple[int, int] | None:
        b64 = self._downscale_for_ground(screenshot_path)
        is_uitars = self._is_uitars
        system = self._GROUND_SYSTEM_UITARS if is_uitars else self._GROUND_SYSTEM_QWEN
        user_content = description if is_uitars else f"Find: {description}"
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
                "options": {"temperature": 0.0, "num_predict": num_predict},
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        msg = resp.json().get("message", {})
        raw = _strip_thinking(msg.get("content", "") or msg.get("thinking", "") or "")
        return self._parse_grounding(raw, width=width, height=height)

    def _ground_openai(
        self,
        description: str,
        screenshot_path: str,
        *,
        width: int,
        height: int,
    ) -> tuple[int, int] | None:
        b64 = self._downscale_for_ground(screenshot_path)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=self._openai_vision_messages(
                f"Find: {description}",
                b64,
                system=self._GROUND_SYSTEM_QWEN,
            ),
            max_tokens=min(int(self._max_tokens), 384),
            temperature=0,
            timeout=self._timeout,
        )
        raw = _strip_thinking(resp.choices[0].message.content or "")
        return self._parse_grounding(raw, width=width, height=height)

    @staticmethod
    def _parse_grounding(raw: str, *, width: int, height: int) -> tuple[int, int] | None:
        if not raw:
            return None
        try:
            return parse_qwen_vl_coordinates(raw, width=width, height=height)
        except (ValueError, IndexError):
            return None

    def ask(
        self,
        question: str,
        screenshot_path: str,
        *,
        system: str = "",
        num_predict: int = 256,
    ) -> str | None:
        """Look at a screenshot and answer a free-form question."""
        if self._api_format == "ollama":
            return self._ask_ollama(question, screenshot_path, system=system, num_predict=num_predict)
        return self._ask_openai(question, screenshot_path, system=system, num_predict=num_predict)

    def _ask_ollama(
        self,
        question: str,
        screenshot_path: str,
        *,
        system: str,
        num_predict: int,
    ) -> str | None:
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
                "options": {"temperature": 0.0, "num_predict": num_predict},
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        msg = resp.json().get("message", {})
        raw = _strip_thinking(msg.get("content", "") or msg.get("thinking", "") or "")
        return raw or None

    def _ask_openai(
        self,
        question: str,
        screenshot_path: str,
        *,
        system: str,
        num_predict: int,
    ) -> str | None:
        b64 = self._downscale_for_ground(screenshot_path)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=self._openai_vision_messages(
                question,
                b64,
                system=system or "回答简洁，只输出关键信息，不要解释。",
            ),
            max_tokens=num_predict,
            temperature=0,
            timeout=self._timeout,
        )
        raw = _strip_thinking(resp.choices[0].message.content or "")
        return raw or None

    def run_with_tools(
        self,
        prompt: str,
        screenshot_path: str,
        tools: dict[str, dict],
        *,
        system: str = "",
        max_rounds: int = 5,
    ) -> str:
        """Standard OpenAI tool-calling loop."""
        from AutoScriptor.vlm.templates import build_system_prompt

        sys_prompt = system or build_system_prompt()
        b64 = encode_image_to_base64(screenshot_path)
        messages: list[dict] = [
            {"role": "system", "content": sys_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            },
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


VLMAgent = VLMClient
