# -*- coding: utf-8 -*-
"""造梦西游 OL 包名解析：在 app_to_start 为空或未安装时按顺序匹配已安装包，并写回 config.json。"""
from __future__ import annotations

import time
from typing import Any

from AutoScriptor.utils.logger import logger

# 与常见渠道一致；新渠道可追加到此列表（优先靠前的先匹配）
ZMXY_PACKAGE_FALLBACK_ORDER: tuple[str, ...] = (
    "org.yjmobile.zmxy",
    "com.zmxyol.union.uc",
    "com.zmxyol.union.dn",
    "com.sy4399.zmxyol.vivo",
)


def _fetch_installed_with_retry(mumu, max_wait: float = 90.0, interval: float = 2.0) -> list[dict[str, Any]] | None:
    deadline = time.monotonic() + max_wait
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return mumu.app.get_installed()
        except Exception as e:
            last_err = e
            logger.debug("get_installed 暂不可用，%.1fs 后重试: %s", interval, e)
            time.sleep(interval)
    logger.error("多次重试后仍无法获取已安装应用列表: %s", last_err)
    return None


def _normalize_raw(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return str(raw).strip()


def _choose_package(
    installed: list[dict[str, Any]],
    raw: str,
    fallback: tuple[str, ...],
) -> str | None:
    by_pkg = {item["package"]: item for item in installed if item.get("package")}

    # 用户自定义包名（不在默认列表）也允许作为最高优先级
    order: list[str] = []
    if raw:
        order.append(raw)
    for p in fallback:
        if p not in order:
            order.append(p)
    # 其余已安装且包名含 zmxy 的（未来渠道）
    for item in installed:
        p = item.get("package") or ""
        if not p or p in order:
            continue
        if "zmxy" in p.lower():
            order.append(p)

    for pkg in order:
        if pkg in by_pkg:
            return pkg
    return None


def resolve_app_to_start(mumu) -> str:
    """
    根据 cfg['app']['app_to_start'] 与已安装应用解析最终包名。
    - 未填写或仅空白：按 ZMXY_PACKAGE_FALLBACK_ORDER 依次匹配。
    - 已填写：优先该包名；若未安装则继续按上述顺序匹配。
    解析结果与配置不一致时写入 config.json。
    """
    from AutoScriptor.utils.constant import cfg

    raw = _normalize_raw(cfg["app"].get("app_to_start"))
    installed = _fetch_installed_with_retry(mumu)
    if not installed:
        raise RuntimeError(
            "无法读取模拟器已安装应用列表（请确认 MuMu 已启动且 MuMuManager 可用）。"
        )

    chosen = _choose_package(installed, raw, ZMXY_PACKAGE_FALLBACK_ORDER)
    if not chosen:
        raise RuntimeError(
            "未检测到已安装的造梦西游 OL 包。请安装游戏或在 config.json 的 app.app_to_start 中填写正确包名。"
        )

    prev = _normalize_raw(cfg["app"].get("app_to_start"))
    if chosen != prev:
        cfg["app"]["app_to_start"] = chosen
        cfg.save_config()
        logger.info("已自动解析并写入 app_to_start: %s（原: %s）", chosen, prev or "(空)")

    return chosen
