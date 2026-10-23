"""冒烟测试用的 WebUI 启动器（不是测试文件，discover 不会收集它）。

正式入口 ``backend/webui/gui.py`` 会加单实例锁、固定占用 5000 端口并尝试打开
浏览器；测试需要能并行、能指定端口、能隔离数据目录，所以这里用 uvicorn 直接
起同一个 ``app``。数据目录由 ``AUTOSCRIPTOR_DATA_DIR`` 指定，端口由
``AUTOSCRIPTOR_TEST_PORT`` 指定。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import uvicorn


def main() -> int:
    from backend.webui.port import read_configured_port, resolve_listening_port
    from backend.webui.server import app

    # 冒烟测试用 AUTOSCRIPTOR_TEST_PORT 指定端口；这里把它并到真实契约上，
    # 让测试跑的就是用户会用到的同一套解析逻辑。
    if not os.environ.get("AUTOSCRIPTOR_PORT") and os.environ.get("AUTOSCRIPTOR_TEST_PORT"):
        os.environ["AUTOSCRIPTOR_PORT"] = os.environ["AUTOSCRIPTOR_TEST_PORT"]

    port, notice = resolve_listening_port(read_configured_port())
    if notice:
        print(notice, flush=True)
    print(f"test server on http://127.0.0.1:{port}", flush=True)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level=os.environ.get("AUTOSCRIPTOR_TEST_UVICORN_LOG", "warning"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
