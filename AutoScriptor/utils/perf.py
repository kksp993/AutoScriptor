"""
Windows 性能优化工具模块
==============================
解决的核心问题：
1. 显示器关闭后 Windows 降频/节流导致模拟器卡顿
2. 系统进入低功耗模式导致后台任务变慢
3. Python 进程 & MuMu 模拟器进程调度优先级不足

使用方法：
    from AutoScriptor.utils.perf import boost
    boost()   # 一行搞定：提升进程优先级 + 阻止系统休眠 + 提升 MuMu 优先级

退出保障：
    - 注册 atexit 钩子，正常退出时自动恢复
    - 注册 SIGINT/SIGTERM 信号处理器，异常终止时自动恢复
    - 各入口点 finally 块中也显式调用 unboost() 作为多重保险
"""

import atexit
import contextlib
import ctypes
import ctypes.wintypes
import os
import signal
import threading
from AutoScriptor.utils.logger import logger

# boost/unboost 期间抑制分步 info，只保留各自末尾一条汇总
_perf_info_depth = 0


@contextlib.contextmanager
def _quiet_perf_info():
    global _perf_info_depth
    _perf_info_depth += 1
    try:
        yield
    finally:
        _perf_info_depth -= 1


def _perf_log_info(msg, *args, **kwargs):
    if _perf_info_depth == 0:
        logger.info(msg, *args, **kwargs)

# ==================== Windows 常量 ====================

# --- SetThreadExecutionState flags ---
ES_CONTINUOUS         = 0x80000000
ES_SYSTEM_REQUIRED    = 0x00000001   # 阻止系统休眠
ES_DISPLAY_REQUIRED   = 0x00000002   # 阻止显示器关闭
ES_AWAYMODE_REQUIRED  = 0x00000040   # 启用离开模式（保持后台活动）

# --- Process priority classes ---
NORMAL_PRIORITY_CLASS       = 0x00000020
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
HIGH_PRIORITY_CLASS         = 0x00000080
REALTIME_PRIORITY_CLASS     = 0x00000100

# --- Thread priority levels ---
THREAD_PRIORITY_NORMAL       = 0
THREAD_PRIORITY_ABOVE_NORMAL = 1
THREAD_PRIORITY_HIGHEST      = 2
THREAD_PRIORITY_TIME_CRITICAL = 15

# --- Process access rights ---
PROCESS_SET_INFORMATION   = 0x0200
PROCESS_QUERY_INFORMATION = 0x0400

# --- Thread access rights ---
THREAD_SET_INFORMATION    = 0x0020
THREAD_QUERY_INFORMATION  = 0x0040

# ==================== 内部状态 ====================
_boosted = False
_boost_lock = threading.Lock()
_boosted_pids: list[int] = []          # 记录被提升过优先级的进程 PID（用于恢复）
_original_affinity_mask: int | None = None  # 记录原始 CPU 亲和性掩码（用于恢复）


# ==================== 核心 API ====================

def boost(
    keep_display: bool = False,
    process_priority: int = HIGH_PRIORITY_CLASS,
    boost_mumu: bool = False,
):
    """
    一键性能优化（幂等，多次调用安全）。

    Args:
        keep_display:     True = 同时阻止显示器关闭（一般不需要，关显示器省电更好）
        process_priority: 当前 Python 进程的优先级（默认 HIGH）
        boost_mumu:       是否同时提升 MuMu 模拟器相关进程的优先级（默认关闭，
                          避免干扰同机器上其他使用 MuMu 的程序）
    """
    global _boosted
    with _boost_lock:
        if _boosted:
            return
        _boosted = True

    with _quiet_perf_info():
        # 0) 根据配置限制 CPU 亲和性（防止程序占满所有核心导致电脑卡死）
        _apply_cpu_affinity()

        # 1) 阻止系统休眠 / 显示器关闭
        prevent_sleep(keep_display=keep_display)

        # 2) 提升当前 Python 进程优先级
        my_pid = os.getpid()
        set_process_priority(my_pid, process_priority)
        _boosted_pids.append(my_pid)

        # 3) 提升当前主线程优先级
        set_current_thread_priority(THREAD_PRIORITY_HIGHEST)

        # 4) 提升 MuMu 相关进程
        if boost_mumu:
            boost_mumu_processes()

    logger.info("⚡ 性能优化已启用")


def unboost():
    """
    恢复默认电源 & 优先级状态（幂等，多次调用安全）。
    
    恢复内容：
    1. 清除 SetThreadExecutionState（允许系统正常休眠 / 关闭显示器）
    2. 恢复当前 Python 进程优先级为 NORMAL
    3. 恢复当前线程优先级为 NORMAL
    4. 恢复所有被提升过的 MuMu 进程优先级为 NORMAL
    """
    global _boosted
    with _boost_lock:
        if not _boosted:
            return
        _boosted = False

    with _quiet_perf_info():
        # 0) 恢复 CPU 亲和性
        _restore_cpu_affinity()

        # 1) 清除 SetThreadExecutionState
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception as e:
            logger.warning("恢复电源策略失败: %s", e)

        # 2) 恢复当前 Python 进程优先级
        try:
            set_process_priority(os.getpid(), NORMAL_PRIORITY_CLASS)
        except Exception as e:
            logger.warning("恢复进程优先级失败: %s", e)

        # 3) 恢复当前线程优先级
        try:
            set_current_thread_priority(THREAD_PRIORITY_NORMAL)
        except Exception as e:
            logger.warning("恢复线程优先级失败: %s", e)

        # 4) 恢复所有记录过的 MuMu 进程（尽力而为，进程可能已退出）
        pids = _boosted_pids[:]
        _boosted_pids.clear()
        for pid in pids:
            if pid == os.getpid():
                continue  # 已在步骤 2 处理
            try:
                set_process_priority(pid, NORMAL_PRIORITY_CLASS)
            except Exception:
                pass  # 进程可能已退出，忽略

    logger.info("⚡ 已恢复默认优先级与电源策略")


# ==================== 底层工具函数 ====================

def _apply_cpu_affinity():
    """
    根据 config.json 中 app.cpu_cores 的值限制当前进程可使用的 CPU 核心数。
    
    配置项：app.cpu_cores
        - 正整数：限制使用前 N 个核心（例如 4 表示只用 CPU 0~3）
        - 0 / 负数 / 未设置：不限制，使用所有核心
    
    使用 Windows API SetProcessAffinityMask 实现。
    """
    global _original_affinity_mask

    try:
        from AutoScriptor.utils.constant import cfg
        cpu_cores = cfg.get("app.cpu_cores", 0)
    except Exception:
        cpu_cores = 0

    if not cpu_cores or not isinstance(cpu_cores, int) or cpu_cores <= 0:
        return  # 未配置或无效值，不限制

    total_cores = os.cpu_count() or 1
    # 限制核心数不超过实际核心数
    use_cores = min(cpu_cores, total_cores)
    if use_cores >= total_cores:
        _perf_log_info("⚡ CPU 亲和性: 配置核心数(%d) >= 实际核心数(%d)，无需限制", use_cores, total_cores)
        return

    # 构建亲和性掩码：使用前 N 个核心
    affinity_mask = (1 << use_cores) - 1  # e.g. 4 cores -> 0b1111 = 15

    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION, False, os.getpid()
        )
        if not handle:
            logger.warning("⚡ CPU 亲和性: OpenProcess 失败，无法设置")
            return

        try:
            # 先保存原始亲和性掩码
            proc_mask = ctypes.c_ulonglong(0)
            sys_mask = ctypes.c_ulonglong(0)
            if kernel32.GetProcessAffinityMask(
                handle, ctypes.byref(proc_mask), ctypes.byref(sys_mask)
            ):
                _original_affinity_mask = proc_mask.value

            # 设置新的亲和性掩码
            ok = kernel32.SetProcessAffinityMask(handle, affinity_mask)
            if ok:
                _perf_log_info(
                    "⚡ CPU 亲和性已设置: 限制使用 %d/%d 个核心 (mask=0x%X)",
                    use_cores, total_cores, affinity_mask,
                )
            else:
                logger.warning("⚡ CPU 亲和性: SetProcessAffinityMask 失败")
        finally:
            kernel32.CloseHandle(handle)
    except Exception as e:
        logger.warning("⚡ CPU 亲和性设置异常: %s", e)


def _restore_cpu_affinity():
    """恢复进程的原始 CPU 亲和性掩码。"""
    global _original_affinity_mask

    if _original_affinity_mask is None:
        return  # 没有保存过，说明没修改过

    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION, False, os.getpid()
        )
        if not handle:
            return
        try:
            ok = kernel32.SetProcessAffinityMask(handle, _original_affinity_mask)
            if ok:
                _perf_log_info("⚡ CPU 亲和性已恢复 (mask=0x%X)", _original_affinity_mask)
            else:
                logger.warning("⚡ CPU 亲和性恢复失败")
        finally:
            kernel32.CloseHandle(handle)
    except Exception as e:
        logger.warning("⚡ CPU 亲和性恢复异常: %s", e)
    finally:
        _original_affinity_mask = None


def prevent_sleep(keep_display: bool = False):
    """
    调用 SetThreadExecutionState 阻止系统休眠。
    
    关键：ES_AWAYMODE_REQUIRED 让系统在"关闭显示器"后仍以全速运行，
    而不是进入低功耗的 Connected Standby / Modern Standby。
    """
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
    if keep_display:
        flags |= ES_DISPLAY_REQUIRED
    prev = ctypes.windll.kernel32.SetThreadExecutionState(flags)
    if prev == 0:
        logger.warning("SetThreadExecutionState 调用失败")
    else:
        parts = ["阻止休眠", "离开模式"]
        if keep_display:
            parts.append("保持显示器")
        _perf_log_info("⚡ 电源策略已设置: %s", " + ".join(parts))


def set_process_priority(pid: int, priority_class: int = HIGH_PRIORITY_CLASS) -> bool:
    """
    设置指定进程的优先级。

    Args:
        pid:            进程 ID
        priority_class: 优先级类（HIGH_PRIORITY_CLASS 等）

    Returns:
        bool: 是否设置成功
    """
    label = {
        NORMAL_PRIORITY_CLASS: "NORMAL",
        ABOVE_NORMAL_PRIORITY_CLASS: "ABOVE_NORMAL",
        HIGH_PRIORITY_CLASS: "HIGH",
        REALTIME_PRIORITY_CLASS: "REALTIME",
    }.get(priority_class, hex(priority_class))

    try:
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION, False, pid
        )
        if not handle:
            logger.warning("OpenProcess 失败 (pid=%d), 可能需要管理员权限", pid)
            return False
        try:
            ok = ctypes.windll.kernel32.SetPriorityClass(handle, priority_class)
            if ok:
                _perf_log_info("⚡ 进程优先级已设置: pid=%d -> %s", pid, label)
                return True
            else:
                logger.warning("SetPriorityClass 失败: pid=%d", pid)
                return False
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception as e:
        logger.warning("设置进程优先级异常: pid=%d, %s", pid, e)
        return False


def set_current_thread_priority(level: int = THREAD_PRIORITY_HIGHEST) -> bool:
    """设置当前线程的调度优先级。"""
    try:
        # 方法1：使用 OpenThread 获取真实句柄（更可靠）
        tid = ctypes.windll.kernel32.GetCurrentThreadId()
        handle = ctypes.windll.kernel32.OpenThread(
            THREAD_SET_INFORMATION | THREAD_QUERY_INFORMATION, False, tid
        )
        if handle:
            ok = ctypes.windll.kernel32.SetThreadPriority(handle, level)
            ctypes.windll.kernel32.CloseHandle(handle)
            if ok:
                _perf_log_info("⚡ 当前线程优先级已提升: level=%d (tid=%d)", level, tid)
            else:
                logger.warning("SetThreadPriority 失败 (tid=%d)", tid)
            return bool(ok)
        # 方法2 回退：使用伪句柄
        pseudo = ctypes.windll.kernel32.GetCurrentThread()
        ok = ctypes.windll.kernel32.SetThreadPriority(pseudo, level)
        if ok:
            _perf_log_info("⚡ 当前线程优先级已提升(伪句柄): level=%d", level)
        else:
            logger.warning("SetThreadPriority(伪句柄) 失败")
        return bool(ok)
    except Exception as e:
        logger.warning("设置线程优先级异常: %s", e)
        return False


def set_thread_high_priority(thread_obj: threading.Thread) -> bool:
    """
    设置指定 Python Thread 对象的优先级为 HIGHEST。
    替代 server.py 中原有的 _set_thread_high_priority。
    """
    try:
        tid = getattr(thread_obj, 'native_id', None) or thread_obj.ident
        if not tid:
            logger.warning("无法获取线程 ID")
            return False
        handle = ctypes.windll.kernel32.OpenThread(
            THREAD_SET_INFORMATION | THREAD_QUERY_INFORMATION, False, tid
        )
        if handle:
            ok = ctypes.windll.kernel32.SetThreadPriority(handle, THREAD_PRIORITY_HIGHEST)
            ctypes.windll.kernel32.CloseHandle(handle)
            if ok:
                _perf_log_info("⚡ 线程优先级已提升: tid=%d", tid)
            return bool(ok)
        else:
            logger.warning("OpenThread 失败: tid=%d", tid)
            return False
    except Exception as e:
        logger.warning("设置线程优先级失败: %s", e)
        return False


def boost_mumu_processes(priority_class: int = ABOVE_NORMAL_PRIORITY_CLASS):
    """
    查找并提升 MuMu 模拟器相关进程的优先级。
    
    MuMu 12 主要进程：
    - MuMuPlayer.exe       (模拟器 UI)
    - MuMuVMMSVC.exe       (虚拟机服务)
    - MuMuVMMHeadless.exe  (无头虚拟机)
    - NemuPlayer.exe       (旧版进程名)
    - NemuHeadless.exe     (旧版无头)
    """
    mumu_names = {
        "MuMuPlayer.exe", "MuMuVMMSVC.exe", "MuMuVMMHeadless.exe",
        "NemuPlayer.exe", "NemuHeadless.exe",
        "MuMuPlayerGlobal.exe",
    }

    boosted = []
    try:
        for pid, name in _iter_processes():
            if name in mumu_names:
                if set_process_priority(pid, priority_class):
                    boosted.append(f"{name}(pid={pid})")
                    _boosted_pids.append(pid)
    except Exception as e:
        logger.warning("枚举进程失败: %s", e)

    if boosted:
        _perf_log_info("⚡ 已提升 MuMu 进程优先级: %s", ", ".join(boosted))
    else:
        _perf_log_info("⚡ 未找到 MuMu 进程（模拟器可能尚未启动，将在任务启动后自动重试）")


def _iter_processes():
    """
    使用 Windows API 枚举所有进程，返回 (pid, name) 对。
    不依赖 psutil，纯 ctypes 实现。
    """
    # EnumProcesses 方式
    DWORD = ctypes.wintypes.DWORD
    HMODULE = ctypes.wintypes.HMODULE
    MAX_PATH = 260

    psapi = ctypes.windll.psapi
    kernel32 = ctypes.windll.kernel32

    # 获取所有进程 ID
    arr_size = 4096
    pids = (DWORD * arr_size)()
    cb_needed = DWORD()
    psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(cb_needed))
    count = cb_needed.value // ctypes.sizeof(DWORD)

    PROCESS_QUERY_LIMITED = 0x1000
    PROCESS_VM_READ = 0x0010

    for i in range(count):
        pid = pids[i]
        if pid == 0:
            continue
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED | PROCESS_VM_READ, False, pid)
        if not handle:
            continue
        try:
            mod = HMODULE()
            cb = DWORD()
            name_buf = ctypes.create_unicode_buffer(MAX_PATH)
            if psapi.EnumProcessModulesEx(
                handle, ctypes.byref(mod), ctypes.sizeof(mod), ctypes.byref(cb), 0x03
            ):
                psapi.GetModuleBaseNameW(handle, mod, name_buf, MAX_PATH)
                name = name_buf.value
                if name:
                    yield pid, name
        except Exception:
            pass
        finally:
            kernel32.CloseHandle(handle)


def boost_mumu_deferred(delay: float = 8.0, priority_class: int = ABOVE_NORMAL_PRIORITY_CLASS):
    """
    延迟提升 MuMu 进程优先级（用于模拟器尚未启动的场景）。
    在后台线程中等待指定秒数后再尝试提升。
    """
    def _worker():
        import time
        time.sleep(delay)
        boost_mumu_processes(priority_class)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


# ==================== 全局退出保障 ====================

def _atexit_unboost():
    """atexit 钩子：程序正常退出时自动恢复优先级与电源策略。"""
    try:
        unboost()
    except Exception:
        # atexit 阶段不能再抛异常
        pass

atexit.register(_atexit_unboost)


# 保存原始信号处理器，以便链式调用
_orig_sigint  = signal.getsignal(signal.SIGINT)
_orig_sigterm = signal.getsignal(signal.SIGTERM) if hasattr(signal, 'SIGTERM') else None


def _signal_unboost(signum, frame):
    """信号处理器：收到 SIGINT/SIGTERM 时先恢复优先级，再调用原处理器。"""
    try:
        unboost()
    except Exception:
        pass
    # 链式调用原来的处理器
    orig = _orig_sigint if signum == signal.SIGINT else _orig_sigterm
    if callable(orig) and orig not in (signal.SIG_DFL, signal.SIG_IGN):
        orig(signum, frame)
    elif orig == signal.SIG_DFL:
        # 恢复默认行为并重新发送信号
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)


try:
    signal.signal(signal.SIGINT, _signal_unboost)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _signal_unboost)
except (OSError, ValueError):
    # 在非主线程中注册信号处理器会抛 ValueError，安全忽略
    pass
