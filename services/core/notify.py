"""
通知推送模块
============
基于 onepush 库的多渠道通知推送。
支持微信、QQ、Telegram、自定义 HTTP 等。
配置通过 cfg["notify.config_yaml"] 获取 YAML 格式的 provider 配置。
"""
from __future__ import annotations

from AutoScriptor.utils.logger import logger


def handle_notify(config_yaml: str, title: str = "", content: str = "") -> bool:
    """
    发送通知推送。

    Args:
        config_yaml: YAML 格式的 onepush 配置字符串，至少包含 provider 字段
        title: 通知标题
        content: 通知内容

    Returns:
        bool: 是否发送成功
    """
    try:
        import yaml
        from onepush import get_notifier
        from onepush.core import Provider
        from onepush.providers.custom import Custom
    except ImportError:
        logger.warning("onepush 未安装，跳过通知推送 (pip install onepush)")
        return False

    try:
        config = {}
        for item in yaml.safe_load_all(config_yaml):
            if item:
                config.update(item)
    except Exception:
        logger.error("通知配置解析失败，跳过发送")
        return False

    try:
        provider_name = config.pop("provider", None)
        if not provider_name:
            return False

        notifier: Provider = get_notifier(provider_name)
        required = notifier.params.get("required", [])

        config["title"] = title
        config["content"] = content

        for key in required:
            if key not in config:
                logger.warning(f"通知 {notifier.name} 缺少必需参数 '{key}'")

        if isinstance(notifier, Custom):
            if config.get("method", "post") == "post":
                config["datatype"] = "json"
            if "data" not in config or not isinstance(config.get("data"), dict):
                config["data"] = {}
            config["data"]["title"] = title
            config["data"]["content"] = content

        if provider_name.lower() == "gocqhttp":
            access_token = config.get("access_token")
            if access_token:
                config["token"] = access_token

        resp = notifier.notify(**config)

        if hasattr(resp, "status_code"):
            if resp.status_code != 200:
                logger.warning(f"通知推送失败: HTTP {resp.status_code}")
                return False
            if provider_name.lower() == "gocqhttp":
                data = resp.json()
                if data.get("status") == "failed":
                    logger.warning(f"通知推送失败: {data.get('wording', '')}")
                    return False

    except Exception as e:
        logger.error(f"通知推送异常: {e}")
        return False

    logger.info("通知推送成功")
    return True


def notify_from_config(title: str, content: str) -> bool:
    """从全局配置读取通知设置并发送"""
    try:
        from AutoScriptor.utils.constant import cfg
        if not cfg.get("notify.enabled", False):
            return False
        config_yaml = cfg.get("notify.config_yaml", "provider: null")
        return handle_notify(config_yaml, title=title, content=content)
    except Exception as e:
        logger.debug(f"notify_from_config 失败: {e}")
        return False
