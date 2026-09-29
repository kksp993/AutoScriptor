"""
TaskManager: 任务执行管理器
===========================
负责单任务执行、重试、错误恢复、配置更新。
不管理调度——调度由 Scheduler 负责。
"""

import datetime
import inspect
import sys
from contextlib import contextmanager
from typing import Any, List, Tuple
from threading import Event, RLock

import dpath
from dpath.exceptions import PathNotFound
from AutoScriptor.utils.cancel import TaskCancelled, bind_cancel_event
from AutoScriptor.logging.logger import logger

from AutoScriptor.core.background import bg
from AutoScriptor.errors import TaskRequireReTry
from AutoScriptor.utils.cancel import cancellable_sleep as sleep
from AutoScriptor.utils.app_config import cfg
from tasks.task_registry import task_registry
from AutoScriptor.logging.logger import set_current_task
from tasks.task_state import (
    clear_task_status,
    get_task_status,
    progress_incomplete,
    progress_label,
    set_current_task_path,
)
from AutoScriptor.utils.paths import get_logs_root
from AutoScriptor.core.runtime_context import runtime_ctx
from AutoScriptor.logging.task_video_recorder import new_task_video_recorder
from orchestrator.model import (
    CATEGORY_NEXT_DATE,
    NextDate,
    calc_next_exec_ts,
    clamp_to_sched_window,
    is_task_debug_mode,
    parse_sched_window_hours,
)


def _is_request_human_takeover(exc: Exception) -> bool:
    cls = exc.__class__
    return cls.__name__ == "RequestHumanTakeover" and "NemuIpc" in cls.__module__


def _human_takeover_message(exc: Exception) -> str:
    text = str(exc).strip()
    return text or repr(exc)


class RequestHumanTakeover(Exception):
    """Lightweight placeholder; real NemuIpc exceptions are detected lazily."""

    pass


class TaskManager:
    """管理任务执行、重试、错误恢复。"""

    def __init__(self):
        self._cancel_event = Event()
        bind_cancel_event(self._cancel_event)
        self._cfg_lock = RLock()
        self._runtime_state_lock = RLock()
        self._current_task_path: str | None = None

    # ── 公共接口 ──

    def request_cancel(self):
        self._cancel_event.set()

    def reset_cancel(self):
        self._reset_cancel()

    def current_task_path(self) -> str | None:
        """Return the task currently being executed for WebUI display only."""
        with self._runtime_state_lock:
            return self._current_task_path

    def _set_current_task_path_for_runtime(self, task_path: str | None) -> None:
        with self._runtime_state_lock:
            self._current_task_path = task_path

    def _reset_cancel(self):
        self._cancel_event.clear()

    def _check_cancel_requested(self):
        if self._cancel_event.is_set():
            raise TaskCancelled("任务已终止")

    @contextmanager
    def config_transaction(self):
        """Serialize config mutations that must not race with task execution."""
        with self._cfg_lock:
            yield

    def switch_character_and_reload(self, server: str, character: str) -> None:
        """Switch the active character and perform a full task registry reload."""
        with self.config_transaction():
            cfg.switch_character(server, character)
            self.reload_tasks()

    def switch_character(self, server: str, character: str) -> None:
        """Switch the active character without rebuilding task modules."""
        with self.config_transaction():
            cfg.switch_character(server, character)

    def execute_tasks(
        self,
        tasks: List[str],
        *,
        max_attempts: int | None = None,
        attempt_offset: int = 0,
        param_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> Tuple[int, int]:
        """执行一组任务。返回 (成功数, 失败数)。"""
        if self._cancel_event.is_set():
            logger.info("⏹ 检测到终止请求，跳过本批任务")
            return 0, 0
        self._clean_debug_dir()
        success = failed = 0
        for task in tasks:
            if self._cancel_event.is_set():
                logger.info("⏹ 检测到终止请求，停止后续任务")
                break
            if self._execute_single_task(
                task,
                max_attempts=max_attempts,
                attempt_offset=attempt_offset,
                param_override=(param_overrides or {}).get(task),
            ):
                success += 1
            else:
                failed += 1
        return success, failed

    def reload_tasks(self, security_key: str = None):
        """重新加载任务和配置。"""
        with self._cfg_lock:
            try:
                cfg.reload_preserving_decrypted_credentials(security_key)
                # 清除 ZmxyOL 与 tasks 子模块缓存，强制重新导入。
                # 任务模块现在住顶层 tasks 包，漏掉它会让重载读到旧任务函数。
                for name in [
                    m for m in sys.modules
                    if m in ("ZmxyOL", "tasks")
                    or m.startswith(("ZmxyOL.", "tasks."))
                ]:
                    sys.modules.pop(name, None)
                from ZmxyOL.character.hero import reload_character_modules

                reload_character_modules()
                # 重新发现并注册任务（不再由 import 自动触发）
                from orchestrator import force_reload_tasks
                force_reload_tasks()
                logger.info("✅ 任务重新加载完成")
            except Exception as e:
                logger.error(f"❌ 任务重新加载失败: {e}")
                raise
            finally:
                bg.clear(clear_signals=True)

    # ── 核心执行 ──

    def _execute_single_task(
        self,
        task: str,
        *,
        max_attempts: int | None = None,
        attempt_offset: int = 0,
        param_override: dict[str, Any] | None = None,
    ) -> bool:
        """执行单个任务（含重试）。返回是否成功。"""
        max_retry = cfg["app"].get("max_retry", 0)

        if max_attempts is None:
            attempt_numbers = range(0, max_retry + 1)
        else:
            start = max(0, attempt_offset)
            stop = min(max_retry + 1, start + max(1, max_attempts))
            attempt_numbers = range(start, stop)

        for attempt in attempt_numbers:
            if self._cancel_event.is_set():
                return False
            has_local_retry = attempt + 1 in attempt_numbers
            task_video = None

            set_current_task(task.rsplit("/", 1)[-1])
            set_current_task_path(task)
            self._set_current_task_path_for_runtime(task)
            try:
                try:
                    fn, kwargs = self._prepare_task(task, param_override=param_override)
                except KeyError:
                    logger.error(f"❌ 任务函数未注册: {task}，跳过")
                    return False

                assert runtime_ctx.mixctrl is not None, "mixctrl 未初始化，请先调用 runtime_ctx.init()"
                runtime_ctx.mixctrl.release_all_keys()
                clear_task_status("progress", task_path=task, save=False)
                record_video = cfg["app"].get("debug_mode") or is_task_debug_mode(task)
                task_video = new_task_video_recorder(task, bool(record_video))
                fn(**kwargs)
                if self._task_progress_incomplete(task):
                    label = self._task_progress_label(task)
                    raise TaskRequireReTry(f"任务进度未完成: {label}")
                if task_video:
                    task_video.stop(keep=False)
                    task_video = None
                logger.info(f"▶️  执行成功: {task}")
                with self._cfg_lock:
                    clear_task_status("progress", task_path=task, save=False)
                    self._clear_human_takeover_state(task)
                    self._update_next_exec_time(task)
                return True

            except TaskRequireReTry as e:
                if attempt < max_retry:
                    logger.info(f"🔄 任务请求重试: {task} ({attempt + 1}/{max_retry})，原因: {e}")
                    if has_local_retry:
                        continue
                    return False
                logger.warning(f"⚠️ 重试次数已满: {task}，原因: {e}")
                with self._cfg_lock:
                    self._mark_incomplete_progress_takeover(task, f"重试次数已满: {e}")
                return False

            except RequestHumanTakeover as e:
                logger.error(f"❌ 需要人工操作: {task}，原因: {e}")
                # 人工接管属预期分支，不写入 logs/errors，避免与真实异常混淆
                with self._cfg_lock:
                    self._mark_human_takeover(task, e)
                return False

            except KeyboardInterrupt:
                raise

            except TaskCancelled:
                logger.info("⏹ 任务已终止: %s", task)
                return False

            except Exception as e:
                if _is_request_human_takeover(e):
                    logger.error(f"❌ 需要人工操作: {task}，原因: {e}")
                    with self._cfg_lock:
                        self._mark_human_takeover(task, e)
                    return False
                logger.error("❌ 执行失败: %s，错误: %r", task, e)
                video_path = task_video.stop(keep=True) if task_video else None
                self._archive_error(task, e, video_path=video_path)
                if task_video:
                    task_video.cleanup_local()
                    task_video = None
                if is_task_debug_mode(task):
                    logger.info("🔄 debug_mode: 跳过失败恢复，不关闭/重启游戏: %s", task)
                    return False
                if not self._try_recover_app(attempt, task=task):
                    with self._cfg_lock:
                        self._mark_incomplete_progress_takeover(task, f"执行失败: {e}")
                    return False
                if attempt < max_retry:
                    logger.info(f"🔄 重试 ({attempt + 1}/{max_retry})")
                    if has_local_retry:
                        continue
                    return False
                with self._cfg_lock:
                    self._mark_incomplete_progress_takeover(task, f"重试次数已满: {e}")
                return False

            finally:
                if task_video:
                    task_video.stop(keep=False)
                self._set_current_task_path_for_runtime(None)
                set_current_task_path(None)
                set_current_task(None)
                logger.info(f"Task [END] {task}")

        return False

    # ── 任务准备 ──

    def _prepare_task(self, task: str, *, param_override: dict[str, Any] | None = None):
        """读取任务函数和参数快照（锁内）。"""
        with self._cfg_lock:
            task_data = dpath.get(cfg["tasks"], task)
            logger.info(f"▶️  正在执行: {task}")
            fn = task_registry.get_fn(task)
            if fn is None:
                raise KeyError("fn")
            return fn, self._resolve_params(task, task_data, fn, param_override=param_override)

    def _resolve_params(
        self,
        task_path: str,
        task_data: dict,
        fn,
        *,
        param_override: dict[str, Any] | None = None,
    ) -> dict:
        """执行参数（枚举恢复，TableParam 重建）由参数自己的 spec 负责。"""
        raw = dict(task_data.get('params', {}) or {})
        if param_override:
            raw.update(param_override)
        specs = task_registry.get_param_specs(task_path)
        has_var_kw = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in inspect.signature(fn).parameters.values()
        )
        params = {}
        for key, value in raw.items():
            if not has_var_kw and key not in specs:
                continue
            spec = specs.get(key)
            params[key] = spec.decode(value) if spec else value
        return params

    # ── 执行后更新 ──

    def _clear_human_takeover_state(self, task: str) -> None:
        """任务成功或用户重新激活后，清掉人工接管冻结标记。"""
        try:
            task_data = dpath.get(cfg["tasks"], task)
        except PathNotFound:
            return
        if not isinstance(task_data, dict):
            return
        for key in ("human_takeover", "human_takeover_error", "human_takeover_at"):
            task_data.pop(key, None)

    @staticmethod
    def _task_progress_value(task: str):
        return get_task_status("progress", None, task_path=task)

    def _task_progress_incomplete(self, task: str) -> bool:
        return progress_incomplete(self._task_progress_value(task))

    def _task_progress_label(self, task: str) -> str:
        return progress_label(self._task_progress_value(task)) or str(self._task_progress_value(task))

    def _mark_incomplete_progress_takeover(self, task: str, reason: str) -> bool:
        if not self._task_progress_incomplete(task):
            return False
        label = self._task_progress_label(task)
        self._mark_human_takeover(task, RequestHumanTakeover(f"{reason}；进度 {label}"))
        return True

    def _mark_human_takeover(self, task: str, exc: Exception) -> None:
        """
        人工接管不是普通异常：WebUI 显示红色未完成，调度器会等到
        next_exec_time 到期后自动重试；任务后续成功会清除该标记。
        """
        task_data = dpath.get(cfg["tasks"], task)
        task_data["human_takeover"] = True
        task_data["human_takeover_error"] = _human_takeover_message(exc)
        task_data["human_takeover_at"] = datetime.datetime.now().timestamp()
        self._update_next_exec_time(task)

    def _update_next_exec_time(self, task: str, next_date: NextDate = None, offset_hours: int = 0):
        """更新任务的 next_exec_time / on 状态。"""
        now = datetime.datetime.now()
        task_data = dpath.get(cfg["tasks"], task)

        # 优先级：显式参数 > 任务自定义 offset > 类别规则
        if next_date or offset_hours:
            ts = calc_next_exec_ts(now, next_date, offset_hours)
        elif (custom := task_data.get("next_exec_offset_hours")) is not None:
            ts = (now + datetime.timedelta(hours=int(custom))).timestamp()
        else:
            ts = self._calc_category_ts(task, now)

        if ts is not None:
            sw = parse_sched_window_hours(task_data)
            if sw is not None:
                ts = clamp_to_sched_window(ts, sw[0], sw[1])
            dpath.set(cfg["tasks"], task + "/next_exec_time", ts)
            human = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
            logger.info(f"    - 下次执行: {human}")
        cfg.save_config()

    def _calc_category_ts(self, task: str, now: datetime.datetime) -> float | None:
        """根据任务类别前缀计算下次执行时间。"""
        for prefix, next_date in CATEGORY_NEXT_DATE.items():
            if task.startswith(prefix):
                return calc_next_exec_ts(now, next_date)
        if task.startswith("一般任务"):
            dpath.set(cfg["tasks"], task + "/on", False)
        return None

    # ── 错误恢复 ──

    def _try_recover_app(self, retry_count: int, task: str | None = None) -> bool:
        """尝试恢复应用到可执行状态。"""
        if task and is_task_debug_mode(task):
            logger.info("🔄 debug_mode: 跳过失败恢复，不关闭/重启游戏: %s", task)
            return False
        if not cfg["app"].get("restart_on_error"):
            return False
        app_name = cfg["app"]["app_to_start"]
        if runtime_ctx.mixctrl is None:
            logger.warning("🔄 mixctrl 不可用，跳过应用重启恢复")
            return False
        try:
            runtime_ctx.mixctrl.app.close(app_name)
            self._wait_app_stopped(app_name)
            if retry_count >= 1:
                self._restart_adb_and_wait()
            if not self._wait_app_running(app_name):
                return False
            sleep(5)
            from ZmxyOL.nav.map_manager import mm
            mm.set_region("登录")
            return True
        except Exception as e:
            logger.error("🔄 应用重启失败: %r", e)
            return False

    def _wait_app_stopped(self, app_name: str, timeout: int = 15):
        """等待应用完全停止后再返回，防止 close 后立即 launch 被忽略。"""
        import time as _time
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            state = runtime_ctx.mixctrl.app.state(app_name)
            if state != "running":
                logger.info("🔄 应用已停止 (state=%s)", state)
                sleep(1)
                return
            sleep(1)
        logger.warning("🔄 等待应用停止超时 (%ds)，强制继续", timeout)

    def _wait_app_running(self, app_name: str, timeout: int = 60) -> bool:
        """启动应用并等待其进入 running 状态。"""
        import time as _time
        runtime_ctx.mixctrl.app.launch(app_name)
        logger.info("🔄 已发送 launch，等待应用启动...")
        deadline = _time.time() + timeout
        retries = 0
        while _time.time() < deadline:
            sleep(2)
            if runtime_ctx.mixctrl.app.state(app_name) == "running":
                logger.info("🔄 应用已启动")
                return True
            retries += 1
            if retries % 5 == 0:
                logger.info("🔄 应用尚未就绪，重试 launch (%ds/%ds)", retries * 2, timeout)
                runtime_ctx.mixctrl.app.launch(app_name)
        logger.error("🔄 应用启动超时 (%ds)", timeout)
        return False

    def _restart_adb_and_wait(self):
        """重启 ADB 并验证连接。"""
        import subprocess
        import threading
        from AutoScriptor.utils.cancel import join_with_cancel, sleep_with_cancel
        adb = cfg["emulator"]["adb_path"]
        addr = str(cfg["emulator"].get("adb_addr", ""))
        subprocess.run([adb, "kill-server"], capture_output=True, text=True)
        subprocess.run([adb, "start-server"], capture_output=True, text=True)
        if addr:
            subprocess.run([adb, "connect", addr], capture_output=True, text=True)
        runtime_ctx.mixctrl.switch_to_mumu()
        for i, interval in enumerate([1, 2, 3, 4, 5, 5, 5], 1):
            result = {}
            def _test():
                try:
                    runtime_ctx.mixctrl.click(2000, 0)
                    result["ok"] = True
                except Exception as e:
                    result["error"] = e
            t = threading.Thread(target=_test, daemon=True)
            t.start()
            join_with_cancel(t, 5, self._check_cancel_requested)
            if not t.is_alive() and result.get("ok"):
                logger.info("✅ ADB重启完成，点击测试成功")
                return
            sleep_with_cancel(interval, self._check_cancel_requested)
        raise RuntimeError("ADB重启后仍无法控制(点击测试失败)")

    # ── 工具 ──

    def _archive_error(self, task: str, exc: Exception, video_path=None):
        from AutoScriptor.logging.log_archiver import archive_error
        try:
            archive_error(task, exc, mixctrl=runtime_ctx.mixctrl, include_click_screenshots=True, video_path=video_path)
        except Exception as e:
            logger.error(f"归档错误失败: {e}")

    @staticmethod
    def _clean_debug_dir():
        d = get_logs_root() / "debug_screenshot"
        if not d.is_dir():
            return
        for fp in d.iterdir():
            if fp.is_file():
                try:
                    fp.unlink()
                except OSError as e:
                    logger.warning("清理 debug 截图失败: %s -> %s", fp, e)
