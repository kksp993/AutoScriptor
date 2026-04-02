"""
TaskManager: 任务执行管理器
===========================
负责单任务执行、重试、错误恢复、配置更新。
不管理调度——调度由 Scheduler 负责。
"""

import datetime
import enum
import importlib
import inspect
import os
import sys
import traceback
from typing import List, Tuple
from threading import Event, RLock

import dpath
from AutoScriptor.utils.cancel import TaskCancelled, bind_cancel_event
from AutoScriptor.utils.logger import logger

from ZmxyOL import *
from AutoScriptor import *
import AutoScriptor.core.api as _core_api
from AutoScriptor.utils.constant import cfg
from AutoScriptor.utils.task_registry import task_registry
from AutoScriptor import TaskRequireReTry
from AutoScriptor.utils.logger import set_current_task
from services.core.runtime_context import runtime_ctx


# ── 下次执行时间计算 ──

class NextDate(enum.Enum):
    past = "past"
    today = "today"
    tomorrow = "tomorrow"
    next_week = "next_week"


def calc_next_exec_ts(
    now: datetime.datetime,
    next_date: NextDate = NextDate.today,
    offset_hours: int = 0,
) -> float:
    """根据类别规则计算下次执行的 UNIX 时间戳。"""
    if next_date == NextDate.past:
        return 0
    if next_date == NextDate.tomorrow:
        next_day = (now + datetime.timedelta(days=1 if now.hour >= 5 else 0)).date()
    elif next_date == NextDate.next_week:
        days = (7 - now.weekday()) % 7 or 7
        next_day = (now + datetime.timedelta(days=days if now.hour >= 5 else 0)).date()
    else:
        next_day = (now + datetime.timedelta(hours=offset_hours)).date()
    target_time = datetime.time(5, 0) if offset_hours == 0 else datetime.time(0, 0)
    return datetime.datetime.combine(next_day, target_time).timestamp()


# 任务类别 → NextDate 映射
_CATEGORY_NEXT_DATE = {
    "每日任务": NextDate.tomorrow,
    "活动任务": NextDate.tomorrow,
    "每周任务": NextDate.next_week,
    "自定义任务": NextDate.tomorrow,
}


def parse_sched_window_hours(task_data: dict) -> tuple[int, int] | None:
    """解析 sched_window_hours: [start_h, end_h)，本地时间，左闭右开。"""
    sw = task_data.get("sched_window_hours")
    if sw is None or len(sw) != 2:
        return None
    try:
        return int(sw[0]), int(sw[1])
    except (TypeError, ValueError):
        return None


def parse_allowed_weekdays(task_data: dict) -> list[int] | None:
    """解析 allowed_weekdays: [1..7] 表示周一至周日（与 cfg['weekday'] 一致）。"""
    aw = task_data.get("allowed_weekdays")
    if aw is None or not isinstance(aw, list) or not aw:
        return None
    try:
        return [int(x) for x in aw]
    except (TypeError, ValueError):
        return None


def calc_next_allowed_weekday_ts(now: datetime.datetime, allowed: list[int]) -> float:
    """当前不在允许日时，返回「下一个允许日」本地 5:00 的时间戳（从次日开始找）。"""
    allowed_set = set(allowed)
    for i in range(1, 15):
        d = now.date() + datetime.timedelta(days=i)
        wd = d.weekday() + 1
        if wd in allowed_set:
            return datetime.datetime.combine(d, datetime.time(5, 0)).timestamp()
    return (now + datetime.timedelta(days=7)).timestamp()


def clamp_to_sched_window(ts: float, start_h: int, end_h: int) -> float:
    """将时间戳映射到最近的 [start_h, end_h) 窗口起点（本地时间）。若已在窗口内则原样返回。"""
    t = datetime.datetime.fromtimestamp(ts)
    m = t.hour * 60 + t.minute
    if start_h * 60 <= m < end_h * 60:
        return ts
    if m < start_h * 60:
        return t.replace(hour=start_h, minute=0, second=0, microsecond=0).timestamp()
    next_day = t.date() + datetime.timedelta(days=1)
    return datetime.datetime.combine(next_day, datetime.time(start_h, 0)).timestamp()


class TaskManager:
    """管理任务执行、重试、错误恢复。"""

    def __init__(self):
        self._cancel_event = Event()
        bind_cancel_event(self._cancel_event)
        self._cfg_lock = RLock()

    # ── 公共接口 ──

    def request_cancel(self):
        self._cancel_event.set()

    def _reset_cancel(self):
        self._cancel_event.clear()

    def execute_tasks(self, tasks: List[str]) -> Tuple[int, int]:
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
            if self._execute_single_task(task):
                success += 1
            else:
                failed += 1
        return success, failed

    def reload_tasks(self, security_key: str = None):
        """重新加载任务和配置。"""
        with self._cfg_lock:
            try:
                saved_game = cfg._config.get('game', {}).copy()
                cfg.load_config(security_key)
                # 清除 ZmxyOL 子模块缓存，强制重新导入
                for name in [m for m in sys.modules if m.startswith('ZmxyOL.')]:
                    sys.modules.pop(name, None)
                try:
                    import ZmxyOL
                    importlib.reload(ZmxyOL)
                except Exception:
                    pass
                # 重新发现并注册任务（不再由 import 自动触发）
                from ZmxyOL.task import force_reload_tasks
                force_reload_tasks()
                if not security_key:
                    cfg._config['game'] = saved_game
                logger.info("✅ 任务重新加载完成")
            except Exception as e:
                logger.error(f"❌ 任务重新加载失败: {e}")
                raise
            finally:
                bg.clear(clear_signals=True)

    # ── 核心执行 ──

    def _execute_single_task(self, task: str) -> bool:
        """执行单个任务（含重试）。返回是否成功。"""
        max_retry = cfg["app"].get("max_retry", 0)

        for attempt in range(max_retry + 1):
            if self._cancel_event.is_set():
                return False

            set_current_task(task.rsplit("/", 1)[-1])
            try:
                try:
                    fn, kwargs = self._prepare_task(task)
                except KeyError:
                    logger.error(f"❌ 任务函数未注册: {task}，跳过")
                    return False

                assert runtime_ctx.mixctrl is not None, "mixctrl 未初始化，请先调用 runtime_ctx.init()"
                runtime_ctx.mixctrl.release_all_keys()
                fn(**kwargs)
                logger.info(f"▶️  执行成功: {task}")
                with self._cfg_lock:
                    self._update_next_exec_time(task)
                return True

            except TaskRequireReTry as e:
                if attempt < max_retry:
                    logger.info(f"🔄 任务请求重试: {task} ({attempt + 1}/{max_retry})，原因: {e}")
                    continue
                logger.warning(f"⚠️ 重试次数已满: {task}，原因: {e}")
                return False

            except RequestHumanTakeover as e:
                logger.error(f"❌ 需要人工操作: {task}，原因: {e}")
                # 人工接管属预期分支，不写入 logs/errors，避免与真实异常混淆
                with self._cfg_lock:
                    self._update_next_exec_time(task)
                return False

            except KeyboardInterrupt:
                raise

            except TaskCancelled:
                logger.info("⏹ 任务已终止: %s", task)
                return False

            except Exception as e:
                logger.error("❌ 执行失败: %s，错误: %r", task, e)
                self._archive_error(task, e)
                traceback.print_exc()
                if not self._try_recover_app(attempt):
                    return False
                if attempt < max_retry:
                    logger.info(f"🔄 重试 ({attempt + 1}/{max_retry})")
                    continue
                return False

            finally:
                set_current_task(None)
                logger.info(f"Task [END] {task}")

        return False

    # ── 任务准备 ──

    def _prepare_task(self, task: str):
        """读取任务函数和参数快照（锁内）。"""
        with self._cfg_lock:
            task_data = dpath.get(cfg["tasks"], task)
            logger.info(f"▶️  正在执行: {task}")
            fn = task_registry.get_fn(task)
            if fn is None:
                raise KeyError("fn")
            return fn, self._resolve_params(task, task_data, fn)

    def _resolve_params(self, task_path: str, task_data: dict, fn) -> dict:
        """解析任务参数（枚举恢复）。"""
        raw = task_data.get('params', {})
        meta = task_registry.get_param_meta(task_path)
        sig = inspect.signature(fn)
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        params = {}
        for k, v in raw.items():
            if not has_var_kw and k not in sig.parameters:
                continue
            enum_cls = self._get_enum_class(k, meta, sig)
            params[k] = self._coerce_enum(v, enum_cls) if enum_cls else v
        return params

    @staticmethod
    def _meta_enum_path(meta_val):
        if isinstance(meta_val, dict):
            return meta_val.get("enum") or meta_val.get("path")
        return meta_val

    @staticmethod
    def _get_enum_class(key: str, meta: dict, sig: inspect.Signature):
        """尝试获取参数对应的枚举类。"""
        if key in meta:
            path = TaskManager._meta_enum_path(meta[key])
            if not path:
                return None
            mod_name, cls_name = path.rsplit('.', 1)
            return getattr(importlib.import_module(mod_name), cls_name)
        ann = getattr(sig.parameters.get(key), 'annotation', None)
        if isinstance(ann, type) and issubclass(ann, enum.Enum):
            return ann
        return None

    @staticmethod
    def _coerce_enum(value, enum_cls):
        """将值转换为枚举（支持单值和列表）。"""
        if isinstance(value, list):
            return [enum_cls[i] for i in value]
        if isinstance(value, str):
            return enum_cls[value]
        return value

    # ── 执行后更新 ──

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
        for prefix, nd in _CATEGORY_NEXT_DATE.items():
            if task.startswith(prefix):
                return calc_next_exec_ts(now, nd)
        if task.startswith("一般任务"):
            dpath.set(cfg["tasks"], task + "/on", False)
        return None

    # 向后兼容
    _update_task_post_execution = _update_next_exec_time

    # ── 错误恢复 ──

    def _try_recover_app(self, retry_count: int) -> bool:
        """尝试恢复应用到可执行状态。"""
        if not cfg["app"].get("restart_on_error"):
            return False
        app_name = cfg["app"]["app_to_start"]
        from AutoScriptor.utils.perf import mumu_safe_subprocess
        with mumu_safe_subprocess():
            try:
                runtime_ctx.mixctrl.app.close(app_name)
                self._wait_app_stopped(app_name)
                if retry_count >= 1:
                    self._restart_adb_and_wait()
                if not self._wait_app_running(app_name):
                    return False
                # if not dismiss_floating_window(max_retries=40, debug=False):
                #     logger.warning("🔄 悬浮窗关闭失败，尝试完全重启模拟器")
                #     return self._full_emulator_restart(app_name)
                sleep(5)
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

    def _full_emulator_restart(self, app_name: str) -> bool:
        """完全重启模拟器（最后手段）。"""
        try:
            if runtime_ctx.mixctrl is not None:
                try:
                    runtime_ctx.mixctrl.app.close(app_name)
                    sleep(2)
                except Exception as e:
                    logger.debug("🔄 关闭应用失败(可忽略): %s", e)

            runtime_ctx._release_nemu_ipc()

            from AutoScriptor.control.MumuAdaptor.mumu import Mumu
            mumu = Mumu().select(cfg["emulator"]["index"])
            mumu.power.shutdown(wait=True, timeout=30)

            runtime_ctx.mixctrl = None
            runtime_ctx.mumu = None

            sleep(3)
            runtime_ctx.refresh()
            sleep(5)
            mm.set_region("登录")
            return True
        except Exception as e:
            logger.error(f"🔄 模拟器重启失败: {e}")
            return False

    def _restart_adb_and_wait(self):
        """重启 ADB 并验证连接。"""
        import subprocess
        import threading
        import time as _time
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
            t.join(5)
            if not t.is_alive() and result.get("ok"):
                logger.info("✅ ADB重启完成，点击测试成功")
                return
            _time.sleep(interval)
        raise RuntimeError("ADB重启后仍无法控制(点击测试失败)")

    # ── 工具 ──

    def _archive_error(self, task: str, exc: Exception):
        from AutoScriptor.utils.log_archiver import archive_error
        try:
            archive_error(task, exc, mixctrl=runtime_ctx.mixctrl, include_click_screenshots=True)
        except Exception as e:
            logger.error(f"归档错误失败: {e}")

    @staticmethod
    def _clean_debug_dir():
        d = os.path.join(os.getcwd(), 'logs', 'debug_screenshot')
        if not os.path.isdir(d):
            return
        for f in os.listdir(d):
            fp = os.path.join(d, f)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass


