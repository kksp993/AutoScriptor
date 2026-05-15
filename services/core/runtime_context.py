"""
RuntimeContext: 运行时对象的集中生命周期管理
=============================================
管理 mixctrl / mumu / bg / vlm_client 的初始化、刷新、关闭，
替代 scheduler.py 中对全局变量的散乱修补。

用法::

    from services.core.runtime_context import runtime_ctx

    # 首次初始化（由 api.py 或 run.py 调用）
    runtime_ctx.init(mixctrl, mumu)

    # 模拟器重启后刷新（替代 Scheduler._refresh_runtime_controls）
    runtime_ctx.refresh()

    # 退出时清理
    runtime_ctx.shutdown()
"""

from __future__ import annotations

import threading
import sys
from typing import Callable, TYPE_CHECKING

from AutoScriptor.utils.cancel import check_cancel_raise
from AutoScriptor.utils.logger import logger

if TYPE_CHECKING:
    from AutoScriptor.core.control import MixControl
    from AutoScriptor.control.MumuAdaptor.mumu import Mumu
    from AutoScriptor.core.background import BackgroundMonitor


class RuntimeContext:
    _instance: RuntimeContext | None = None
    _lock = threading.Lock()

    def __init__(self):
        self.mixctrl: MixControl | None = None
        self.mumu: Mumu | None = None
        self.bg = None
        self.vlm_client = None
        self._initialized = False
        self._refresh_lock = threading.Lock()

    @classmethod
    def instance(cls) -> RuntimeContext:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    # ── 初始化 ──

    def init(self, mixctrl, mumu):
        """Store core runtime objects and sync module-level globals."""
        self.mixctrl = mixctrl
        self.mumu = mumu
        self._sync_globals()
        self._initialized = mixctrl is not None and mumu is not None
        logger.info("RuntimeContext 初始化完成")

    def init_bg(self):
        """Bind the existing BackgroundProxy singleton."""
        if self.bg is not None:
            return
        from AutoScriptor.core.background import bg
        self.bg = bg
        logger.debug("RuntimeContext: bg 已绑定")

    def init_vlm(self):
        """Lazily create a VLM client if llm.use_agent is enabled."""
        if self.vlm_client is not None:
            return
        from AutoScriptor.utils.app_config import cfg
        if not cfg.get("llm.use_agent", False):
            return
        try:
            from AutoScriptor.vlm.vlm import VLMClient
            self.vlm_client = VLMClient()
            logger.info("RuntimeContext: VLM client 初始化完成")
        except Exception as e:
            logger.warning("RuntimeContext: VLM client 初始化失败: %s", e)

    # ── 刷新（模拟器重启后） ──

    def refresh(self, cancel_check: Callable[[], None] | None = None):
        """
        Release old NemuIpc connections, re-create mixctrl/mumu,
        and sync back to module-level globals.
        Returns the new (mixctrl, mumu) pair.
        """
        from AutoScriptor.utils.app_config import cfg
        from AutoScriptor import ensure_app_running

        cancel_check = cancel_check or check_cancel_raise
        with self._refresh_lock:
            cancel_check()
            self._release_nemu_ipc()
            mixctrl, mumu = ensure_app_running(
                cfg["emulator"]["index"],
                cfg["emulator"]["adb_addr"],
                cfg["app"]["app_to_start"],
                start_emulator=True,
                launch_app=True,
                cancel_check=cancel_check,
            )
            self.mixctrl = mixctrl
            self.mumu = mumu
            self._initialized = True
            self._sync_globals()
            logger.info("RuntimeContext 已刷新 (mixctrl/mumu 已替换)")
            return mixctrl, mumu

    # ── 关闭 ──

    def shutdown(self):
        """Release all runtime resources."""
        self._release_nemu_ipc()
        self.mixctrl = None
        self.mumu = None
        self.vlm_client = None
        self._initialized = False
        self._sync_globals()
        logger.info("RuntimeContext 已关闭")

    # ── 内部工具 ──

    def _release_nemu_ipc(self):
        """Release NemuIpc native connections held by current mixctrl."""
        try:
            if self.mixctrl is None:
                return
            nemu_ctrl = getattr(self.mixctrl, "nemu_control", None)
            if nemu_ctrl is None:
                return
            nemu = getattr(nemu_ctrl, "nemu_ipc", None)
            if nemu is None:
                return
            nemu.nemu_ipc_release()
            logger.debug("NemuIpc 连接已释放")
        except Exception as e:
            logger.debug("释放 NemuIpc 连接失败: %s", e)

    def _sync_globals(self):
        """
        Keep module-level globals in sync for backward compatibility.
        Existing code does ``from AutoScriptor import mixctrl`` which binds
        to the module attribute, so we patch both ``AutoScriptor`` and
        ``AutoScriptor.core.api``.
        """
        pkg = sys.modules.get("AutoScriptor")
        core_api = sys.modules.get("AutoScriptor.core.api")

        if core_api is not None:
            core_api.mixctrl = self.mixctrl
            core_api.mumu = self.mumu
        if pkg is not None:
            pkg.mixctrl = self.mixctrl
            pkg.mumu = self.mumu

    # ── 状态查询 ──

    def status_dict(self) -> dict:
        return {
            "initialized": self._initialized,
            "has_mixctrl": self.mixctrl is not None,
            "has_mumu": self.mumu is not None,
            "has_bg": self.bg is not None,
            "has_vlm": self.vlm_client is not None,
        }


runtime_ctx = RuntimeContext.instance()
