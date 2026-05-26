from AutoScriptor.utils.app_config import cfg


def _get_llm_cfg(key, default=None):
    try:
        return cfg["llm"][key]
    except (KeyError, TypeError):
        return default


VLM_CONFIG = {
    "api_url": _get_llm_cfg("url", "http://localhost:11434/v1"),
    "model_name": _get_llm_cfg("model", "hf.co/bartowski/UI-TARS-2B-SFT-GGUF"),
    "max_tokens": 512,
    "temperature": 0.1,
    "timeout": 30,
}
