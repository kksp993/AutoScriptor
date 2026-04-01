"""
VLM Tool Registry — OpenAI function-calling schema format
=========================================================
Tools are registered via ``@register_tool`` and stored in ``TOOL_REGISTRY``.
Each entry contains an OpenAI-compatible function schema and a handler callable.
"""

from typing import Any, Callable, Dict

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_tool(*, name: str, description: str,
                  parameters: dict | None = None) -> Callable:
    """Decorator that registers a tool with an OpenAI function-calling schema.

    Usage::

        @register_tool(
            name="click",
            description="Click at normalised coordinates (0-1000).",
            parameters={
                "type": "object",
                "properties": {
                    "coordinates": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Normalised (x, y) in 0-1000 range",
                    }
                },
                "required": ["coordinates"],
            },
        )
        def click_tool(coordinates):
            ...
    """
    def decorator(func: Callable) -> Callable:
        TOOL_REGISTRY[name] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters or {"type": "object", "properties": {}},
                },
            },
            "handler": func,
        }
        return func
    return decorator


_TOOL_MODULES = [
    "AutoScriptor.vlm.tools.api_tools",
    "AutoScriptor.vlm.tools.nav_tools",
]


def load_toolkits() -> Dict[str, Dict[str, Any]]:
    """Return the full tool registry (imports tool modules on first call)."""
    if not TOOL_REGISTRY:
        import importlib
        for mod_name in _TOOL_MODULES:
            importlib.import_module(mod_name)
    return TOOL_REGISTRY


def get_tool(name: str) -> Dict[str, Any] | None:
    return TOOL_REGISTRY.get(name)
