"""
TaskManager: 任务执行管理器
===========================
负责单任务执行、重试、错误恢复、配置更新。
不管理调度——调度由 Scheduler 负责。
"""

import datetime
import inspect
import sys
import time
from contextlib import contextmanager
from typing import Any, List, Tuple
from threading import Event, RLock

from AutoScriptor.utils.cancel import TaskCancelled, bind_cancel_event
from AutoScriptor.logging.logger import logger

from AutoScriptor.core.background import bg
from AutoScriptor.errors import TaskRequireReTry
from AutoScriptor.utils.cancel import cancellable_sleep as sleep
from AutoScriptor.utils.app_config import cfg
from tasks.task_register import task_registry
from AutoScriptor.logging.logger import set_current_task
from tasks.task_state import (
    clear_task_status,
    get_task_status,
    progress_incomplete,
    progress_label,
    set_current_task_path,
)
from AutoScriptor.core.runtime_context import runtime_ctx
from AutoScriptor.core.control import clear_action_history
from AutoScriptor.logging.tracer import set_run_capture
from AutoScriptor.logging.task_video_recorder import new_task_video_recorder
from orchestrator.model import (
    clamp_to_sched_window,
    is_task_debug_mode,
    next_exec_ts_for_spec,
    resolve_reschedule,
)


# 连续这么多次「关掉 App 重新拉起仍失败」才升级为重启 MuMu 实例。
APP_START_FAILURE_RESTART_THRESHOLD = 3
# 两次 MuMu 重启之间至少隔这么久。没有这个上限，一次坏会话会变成每几分钟
# 关一次模拟器：没人看着的时候，重启本身比失败更打扰。
MUMU_RESTART_COOLDOWN_SECONDS = 10 * 60


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
        self._app_start_failure_count = 0
        self._last_mumu_restart_at: float | None = None

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
                # 重载分两类：任务脚本（让 @register_task 重跑）和游戏层的纯逻辑模块
                # （nav、战斗流程、包名解析）。两边的保留清单都带原因写在 catalog 里：
                # 持有跨边界对象的模块必须留着，否则会出现第二个 TaskRegistry，或者
                # TableParam 不再是同一个类、任务签名里的表格默认值认不出来。
                from orchestrator.catalog import (
                    is_reloadable_task_module,
                    reload_game_layer_modules,
                )

                for name in [m for m in sys.modules if is_reloadable_task_module(m)]:
                    sys.modules.pop(name, None)
                from ZmxyOL.character.hero import reload_character_modules
                import ZmxyOL

                # 立刻把游戏层重建回来，别把工作留给「谁先 import 谁重建」——那可能是
                # 某个跑到一半的任务。导入错误此刻就炸，比任务执行到中途才炸可控。
                rebuilt = reload_game_layer_modules()
                # 刚丢弃的 tasks 包初始化里绑过这些名字，ZmxyOL 首次访问时也记忆过一份；
                # 不清掉就会继续把重载前的枚举发给重新导入的任务脚本。
                ZmxyOL.drop_cached_exports()
                # 职业脚本要对着重建后的游戏层重跑，所以放在它之后。
                reload_character_modules()
                # 重新发现并注册任务（不再由 import 自动触发）
                from orchestrator import force_reload_tasks
                force_reload_tasks()
                logger.info("✅ 任务重新加载完成（重建 %d 个游戏层模块）", len(rebuilt))
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
        # ``app.max_attempts`` 是「最多尝试几次」，**含第一次**。它以前叫 ``max_retry``
        # 且表示「失败后再来几次」，同一个数字换了含义，所以配置层按 attempts = retry + 1
        # 迁移（见 app_config._migrate_renamed_app_keys）。
        # 调用方可以用 ``max_attempts`` 参数把本次限制得更小；调度器就是这么一次只跑
        # 一遍、再按 ``attempt_offset`` 分轮接着数的。
        total_attempts = max(1, int(cfg["app"].get("max_attempts", 1) or 1))

        if max_attempts is None:
            attempt_numbers = range(0, total_attempts)
        else:
            start = max(0, attempt_offset)
            stop = min(total_attempts, start + max(1, max_attempts))
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
                debug_run = is_task_debug_mode(task)
                # tracer 的运行期抓帧和任务录屏共用同一个开关：两者都是 debug
                # 排障材料，只在这里决定，控制层无权猜。判据是任务注册时的
                # debug_mode，与任务在哪个目录无关。
                set_run_capture(debug_run)
                clear_action_history()
                task_video = new_task_video_recorder(task, debug_run)
                fn(**kwargs)
                if self._task_progress_incomplete(task):
                    label = self._task_progress_label(task)
                    raise TaskRequireReTry(f"任务进度未完成: {label}")
                if task_video:
                    task_video.stop(keep=False)
                    task_video = None
                # 任务真的跑完了，说明 App 这一轮是健康的；否则昨天偶发的一次启动
                # 失败会和今天的一次累加，凭一天一次的偶发也凑够重启阈值。
                self._app_start_failure_count = 0
                logger.info(f"▶️  执行成功: {task}")
                with self._cfg_lock:
                    clear_task_status("progress", task_path=task, save=False)
                    self._clear_human_takeover_state(task)
                    self._update_next_exec_time(task)
                return True

            except TaskRequireReTry as e:
                if attempt + 1 < total_attempts:
                    logger.info(
                        f"🔄 任务请求重试: {task}（第 {attempt + 1}/{total_attempts} 次尝试），原因: {e}"
                    )
                    if has_local_retry:
                        continue
                    return False
                logger.warning(f"⚠️ 尝试次数已满（{total_attempts} 次）: {task}，原因: {e}")
                with self._cfg_lock:
                    self._mark_incomplete_progress_takeover(task, f"尝试次数已满: {e}")
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
                # debug 任务失败即停：不恢复应用、不重试，也不标记人工接管冷却，
                # 否则一次调试会污染后续正常调度。
                if is_task_debug_mode(task):
                    logger.info("🔄 debug_mode: 跳过失败恢复，不关闭/重启游戏: %s", task)
                    return False
                if not self._try_recover_app(attempt):
                    with self._cfg_lock:
                        self._mark_incomplete_progress_takeover(task, f"执行失败: {e}")
                    return False
                if attempt + 1 < total_attempts:
                    logger.info(f"🔄 重试（第 {attempt + 1}/{total_attempts} 次尝试）")
                    if has_local_retry:
                        continue
                    return False
                with self._cfg_lock:
                    self._mark_incomplete_progress_takeover(task, f"尝试次数已满: {e}")
                return False

            finally:
                if task_video:
                    task_video.stop(keep=False)
                # 任务之间没有人在操作设备，停止抓帧；否则任务间隙的空闲
                # 截图会继续填目录，也会把状态留给下一次调用。
                set_run_capture(False)
                self._set_current_task_path_for_runtime(None)
                set_current_task_path(None)
                set_current_task(None)
                logger.info(f"Task [END] {task}")

        return False

    # ── 任务准备 ──

    @staticmethod
    def _task_entry(task_path: str) -> dict | None:
        """该任务的用户配置条目；未注册或没有配置时为 None。

        ``cfg["tasks"]`` 以 id 为键，所以这里做一次路径到身份的换算，调用方继续用显示路径。
        """
        task_data = cfg["tasks"].get(task_registry.id_of(task_path))
        return task_data if isinstance(task_data, dict) else None

    def _prepare_task(self, task: str, *, param_override: dict[str, Any] | None = None):
        """读取任务函数和参数快照（锁内）。"""
        with self._cfg_lock:
            task_data = self._task_entry(task)
            if task_data is None:
                raise KeyError(f"任务没有配置条目: {task}")
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
        task_data = self._task_entry(task)
        if task_data is None:
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
        task_data = self._task_entry(task)
        if task_data is None:
            raise KeyError(f"任务没有配置条目: {task}")
        task_data["human_takeover"] = True
        task_data["human_takeover_error"] = _human_takeover_message(exc)
        task_data["human_takeover_at"] = datetime.datetime.now().timestamp()
        self._update_next_exec_time(task)

    def _update_next_exec_time(self, task: str):
        """执行成功后写入下次执行时间；一次性任务直接关闭。

        调度规则来自任务的 ``reschedule``:用户覆盖优先，其次作者声明，都没有就是一次性。
        窗口约束在这里夹一次；星期约束留给到期判定，因为它还要处理"到点了但不在允许日"
        这种推迟，而不是只在执行后算一次。
        """
        now = datetime.datetime.now()
        task_data = self._task_entry(task)
        if task_data is None:
            raise KeyError(f"任务没有配置条目: {task}")

        spec = resolve_reschedule(task, task_data)
        ts = next_exec_ts_for_spec(now, spec)
        if ts is None:
            task_data["on"] = False   # 一次性任务执行完就关闭
        else:
            if spec["window"] is not None:
                ts = clamp_to_sched_window(ts, *spec["window"])
            task_data["next_exec_time"] = ts
            human = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
            logger.info(f"    - 下次执行: {human}")
        cfg.save_config()

    # ── 错误恢复 ──

    def _try_recover_app(self, retry_count: int) -> bool:
        """尝试恢复应用到可执行状态。

        Only recovery lives here. Whether a task should recover at all is the
        caller's decision, because skipping recovery also skips the takeover
        marking that follows a failed recovery.
        """
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
                self._app_start_failure_count += 1
                logger.warning(
                    "🔄 应用启动失败累计 %d/%d 次",
                    self._app_start_failure_count,
                    APP_START_FAILURE_RESTART_THRESHOLD,
                )
                if self._app_start_failure_count < APP_START_FAILURE_RESTART_THRESHOLD:
                    return False

                logger.warning("🔄 应用连续启动失败达到阈值，准备重启 MuMu 实例")
                self._app_start_failure_count = 0
                return self._restart_mumu_and_launch_app(app_name)

            self._app_start_failure_count = 0
            sleep(5)
            from ZmxyOL.nav.map_manager import mm
            mm.set_region("登录")
            return True
        except Exception as e:
            logger.error("🔄 应用重启失败: %r", e)
            return False

    def _restart_mumu_and_launch_app(self, app_name: str) -> bool:
        """重启卡死的 MuMu 会话，并重新建立控制与游戏启动链。"""
        current_mumu = runtime_ctx.mumu
        if current_mumu is None:
            logger.warning("🔄 MuMu 实例不可用，无法执行模拟器重启回退")
            return False

        now = time.monotonic()
        if (
            self._last_mumu_restart_at is not None
            and now - self._last_mumu_restart_at < MUMU_RESTART_COOLDOWN_SECONDS
        ):
            logger.warning(
                "🔄 距上次重启 MuMu 不足 %d 秒，本轮不再重启；先按应用启动失败处理",
                MUMU_RESTART_COOLDOWN_SECONDS,
            )
            return False
        # 记在尝试之前：重启本身失败时也要吃冷却，否则每次任务失败都会再关一次模拟器。
        self._last_mumu_restart_at = now

        try:
            # 先释放旧 NemuIpc，避免关闭/启动 MuMu 时仍有旧句柄占用实例。
            runtime_ctx.release_session()
            current_mumu.power.restart()
            logger.info("🔄 MuMu 实例已重启，重新建立设备会话")
            runtime_ctx.refresh(
                cancel_check=self._check_cancel_requested,
                launch_app=False,
            )
            if not self._wait_app_running(app_name):
                logger.error("🔄 MuMu 重启后应用仍未启动")
                return False
            logger.info("✅ MuMu 重启回退完成，应用已重新启动")
            self._app_start_failure_count = 0
            return True
        except TaskCancelled:
            raise
        except Exception as e:
            logger.error("🔄 MuMu 重启回退失败: %r", e)
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
            archive_error(task, exc, mixctrl=runtime_ctx.mixctrl, video_path=video_path)
        except Exception as e:
            logger.error(f"归档错误失败: {e}")
