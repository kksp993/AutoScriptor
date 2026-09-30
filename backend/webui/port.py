"""WebUI 监听端口的唯一出处。

单独成模块是为了能被轻量导入：``gui.py`` 和测试启动器要在 import 整个 app
之前就校验端口，不能为此拖进 FastAPI、任务注册表和 OCR。

约定只有两条：

- ``AUTOSCRIPTOR_PORT`` 指定端口，缺省 ``5000``；
- Electron 外壳和后端必须用同一个端口，所以外壳先挑好、写进环境变量，后端照办。
"""
from __future__ import annotations

import os
import socket


DEFAULT_PORT = 5000
PORT_ENV = "AUTOSCRIPTOR_PORT"

# 顺延时最多往后试几个端口。够绕开常见的占用，又不至于把端口挑到用户找不到的地方。
PORT_SHIFT_ATTEMPTS = 20


def read_configured_port() -> int:
    """``AUTOSCRIPTOR_PORT`` 的内容；写法非法就报错，不静默退回默认值。

    静默退回会让「我明明设了端口」变成难查的问题，所以非法值一律当成配置错误。
    """
    raw = (os.environ.get(PORT_ENV) or "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(
            f"{PORT_ENV} 必须是 1-65535 之间的整数，当前是 {raw!r}。"
            f"改对后重试，或删掉这个环境变量用默认端口 {DEFAULT_PORT}。"
        ) from None
    if not 1 <= port <= 65535:
        raise ValueError(
            f"{PORT_ENV} 必须在 1-65535 之间，当前是 {port}。"
            f"改对后重试，或删掉这个环境变量用默认端口 {DEFAULT_PORT}。"
        )
    return port


def port_is_free(port: int) -> bool:
    """本机 127.0.0.1 的该端口现在能不能独占绑定。

    这里**不能**设 ``SO_REUSEADDR``：Windows 上它允许绑定别的进程已经在监听的
    端口，探测会一律返回「空闲」，顺延逻辑就形同虚设（真机上表现为 uvicorn 仍然
    去绑旧端口并报 WinError 10048）。不设它才是「这个端口现在归我吗」的答案。
    """
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def resolve_listening_port(preferred: int, *, allow_shift: bool = True) -> tuple[int, str]:
    """实际监听端口，返回 ``(端口, 给用户看的提示)``；没有提示时第二项为空串。

    端口被占用时默认顺延。这类失败最常见的原因就是本机已经有别的软件占了
    5000，而用户并不知道要改哪里；顺延加一句说明比直接报错有用得多。

    ``allow_shift=False`` 留给必须固定端口的调用方（Electron 外壳要按同一个
    端口连后端，换端口会让它连不上），此时直接把出口写清楚。
    """
    if port_is_free(preferred):
        return preferred, ""

    if not allow_shift:
        raise RuntimeError(
            f"端口 {preferred} 已被占用，Electron 需要它才能连上后端。\n"
            f"请先关掉占用该端口的程序；或设置环境变量 {PORT_ENV}=<另一个空闲端口> 再启动。"
        )

    last_attempted = preferred
    for candidate in range(preferred + 1, min(preferred + PORT_SHIFT_ATTEMPTS, 65535) + 1):
        last_attempted = candidate
        if port_is_free(candidate):
            return candidate, (
                f"端口 {preferred} 已被其它程序占用，本次改用 {candidate}。"
                f"要固定端口就设置环境变量 {PORT_ENV}={candidate} 再启动。"
            )

    raise RuntimeError(
        f"端口 {preferred} 被占用，往后试到 {last_attempted} 也都被占用。"
        f"请先释放端口，或用环境变量 {PORT_ENV}=<空闲端口> 指定一个。"
    )
