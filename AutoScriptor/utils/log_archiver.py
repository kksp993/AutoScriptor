"""
日志归档服务：统一处理错误日志和截图归档
支持将错误日志、click_screenshots 目录下的所有截图打包到 logs/errors 目录下
"""
import os
import shutil
import sys
import traceback
import time
import inspect
from datetime import datetime
from typing import Optional, Dict, Any, Set
from logzero import logger, logfile
import cv2

# 默认上下文收集配置
_DEFAULT_CONTEXT_CONFIG = {
    "mm_current_region": True,      # MapManager 中存储的当前 env 和 loc
    "locate_region_result": True,   # locate_region() 实际识别结果（只跑一次）
    "bg_active_callbacks": True,   # BackgroundMonitor 中正在运行的后台任务
    "bg_signals": True,             # BackgroundMonitor 中的信号状态
    "code_coverage": True,          # 代码覆盖率信息（执行过的文件和函数）
    "python_version": True,          # Python 版本
    "timestamp": True,              # 错误发生时间戳
}

# 代码覆盖率跟踪器
_coverage_tracker = {
    "files": {},      # 文件路径 -> {函数名: 调用次数}
    "functions": {},  # 函数全名 -> 调用次数
    "enabled": True
}


def collect_default_context(config: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
    """
    收集默认的上下文信息
    
    Args:
        config: 配置字典，控制哪些信息要收集。如果为 None，使用默认配置。
                可以传入部分配置来覆盖默认值。
    
    Returns:
        包含上下文信息的字典
    
    Examples:
        # 使用默认配置
        context = collect_default_context()
        
        # 自定义配置（只收集部分信息）
        context = collect_default_context({
            "mm_current_region": True,
            "locate_region_result": False,  # 禁用这个
            "bg_active_callbacks": True,
        })
    """
    if config is None:
        config = _DEFAULT_CONTEXT_CONFIG.copy()
    else:
        # 合并配置，未指定的使用默认值
        merged_config = _DEFAULT_CONTEXT_CONFIG.copy()
        merged_config.update(config)
        config = merged_config
    
    context = {}
    
    # 1. MapManager 中存储的当前 env 和 loc
    if config.get("mm_current_region", False):
        try:
            from ZmxyOL.nav.map_manager import mm
            cur_env, cur_loc = mm.get_region()
            context["mm_current_region"] = {
                "env": cur_env,
                "loc": cur_loc
            }
        except Exception as e:
            context["mm_current_region"] = f"获取失败: {e}"
    
    # 2. locate_region() 实际识别结果（只跑一次，避免递归）
    if config.get("locate_region_result", False):
        try:
            from ZmxyOL.nav.api import locate_region
            # 使用 check_only=True 避免在错误处理中再次触发错误或递归
            result = locate_region(cnt=0, check_only=True)
            if isinstance(result, tuple) and len(result) == 2:
                detected_env, detected_loc = result
                context["locate_region_result"] = {
                    "env": detected_env,
                    "loc": detected_loc
                }
            else:
                # check_only=True 时如果找不到位置会返回字符串
                context["locate_region_result"] = f"无法识别: {result}"
        except Exception as e:
            context["locate_region_result"] = f"识别失败: {e}"
    
    # 3. BackgroundMonitor 中正在运行的后台任务
    if config.get("bg_active_callbacks", False):
        try:
            from AutoScriptor.core.background import bg
            # 获取所有活跃的回调名称
            if hasattr(bg, 'get_idfs'):
                active_callbacks = list(bg.get_idfs())
            elif hasattr(bg, '_callbacks'):
                active_callbacks = list(bg._callbacks.keys())
            else:
                active_callbacks = []
            context["bg_active_callbacks"] = active_callbacks
        except Exception as e:
            context["bg_active_callbacks"] = f"获取失败: {e}"
    
    # 4. BackgroundMonitor 中的信号状态
    if config.get("bg_signals", False):
        try:
            from AutoScriptor.core.background import bg
            if hasattr(bg, '_signals'):
                signals = {}
                for key, value in bg._signals.items():
                    signals[key] = _format_variable_value(value, max_length=100)
                context["bg_signals"] = signals
            else:
                context["bg_signals"] = "无法访问信号"
        except Exception as e:
            context["bg_signals"] = f"获取失败: {e}"
    
    # 5. 代码覆盖率信息
    if config.get("code_coverage", False):
        try:
            coverage_info = get_code_coverage()
            if coverage_info:
                context["code_coverage"] = coverage_info
        except Exception as e:
            context["code_coverage"] = f"获取失败: {e}"
    
    # 6. Python 版本
    if config.get("python_version", False):
        context["python_version"] = sys.version.split()[0]
    
    # 7. 错误发生时间戳
    if config.get("timestamp", False):
        context["error_timestamp"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    return context


def set_default_context_config(config: Dict[str, bool]) -> None:
    """
    设置默认上下文收集配置
    
    Args:
        config: 配置字典，控制哪些信息要收集
    
    Examples:
        # 禁用 locate_region_result（避免在错误处理中再次识别）
        set_default_context_config({
            "locate_region_result": False
        })
        
        # 只启用部分信息
        set_default_context_config({
            "mm_current_region": True,
            "bg_active_callbacks": True,
            "locate_region_result": False,
            "bg_signals": False,
            "python_version": False,
            "timestamp": False,
        })
    """
    global _DEFAULT_CONTEXT_CONFIG
    _DEFAULT_CONTEXT_CONFIG.update(config)


def get_default_context_config() -> Dict[str, bool]:
    """
    获取当前默认上下文收集配置
    
    Returns:
        当前配置字典的副本
    """
    return _DEFAULT_CONTEXT_CONFIG.copy()


def _trace_function(frame, event, arg):
    """代码跟踪函数，记录函数调用"""
    if event == 'call':
        filename = frame.f_code.co_filename
        func_name = frame.f_code.co_name
        lineno = frame.f_code.co_firstlineno
        
        # 跳过标准库和第三方库
        if 'site-packages' in filename or filename.startswith('<'):
            return
        
        # 只跟踪项目内的代码
        if 'AutoScriptor' not in filename and 'ZmxyOL' not in filename and 'services' not in filename:
            return
        
        # 获取函数全名（包含类名）
        func_full_name = func_name
        if 'self' in frame.f_locals:
            try:
                class_name = frame.f_locals['self'].__class__.__name__
                func_full_name = f"{class_name}.{func_name}"
            except:
                pass
        
        # 记录文件级别的调用
        if filename not in _coverage_tracker["files"]:
            _coverage_tracker["files"][filename] = {}
        if func_name not in _coverage_tracker["files"][filename]:
            _coverage_tracker["files"][filename][func_name] = 0
        _coverage_tracker["files"][filename][func_name] += 1
        
        # 记录函数级别的调用
        func_key = f"{filename}:{func_full_name}"
        if func_key not in _coverage_tracker["functions"]:
            _coverage_tracker["functions"][func_key] = 0
        _coverage_tracker["functions"][func_key] += 1
    
    return _trace_function


def enable_code_coverage_tracking():
    """
    启用代码覆盖率跟踪
    
    Examples:
        from AutoScriptor.utils.log_archiver import enable_code_coverage_tracking
        enable_code_coverage_tracking()
    """
    global _coverage_tracker
    if not _coverage_tracker["enabled"]:
        sys.settrace(_trace_function)
        _coverage_tracker["enabled"] = True
        _coverage_tracker["files"] = {}
        _coverage_tracker["functions"] = {}
        logger.info("代码覆盖率跟踪已启用")


def disable_code_coverage_tracking():
    """
    禁用代码覆盖率跟踪
    
    Examples:
        from AutoScriptor.utils.log_archiver import disable_code_coverage_tracking
        disable_code_coverage_tracking()
    """
    global _coverage_tracker
    if _coverage_tracker["enabled"]:
        sys.settrace(None)
        _coverage_tracker["enabled"] = False
        logger.info("代码覆盖率跟踪已禁用")


def get_code_coverage() -> Optional[Dict[str, Any]]:
    """
    获取当前的代码覆盖率信息
    
    Returns:
        包含覆盖率信息的字典，格式：
        {
            "enabled": bool,
            "files": {
                "文件路径": {
                    "函数名": 调用次数
                }
            },
            "top_functions": [
                {"function": "函数全名", "calls": 调用次数}
            ]
        }
    """
    global _coverage_tracker
    
    if not _coverage_tracker["enabled"]:
        return {"enabled": False, "message": "代码覆盖率跟踪未启用"}
    
    # 格式化文件覆盖率
    files_coverage = {}
    for filename, funcs in _coverage_tracker["files"].items():
        # 只保留项目内的文件，并简化路径
        if 'AutoScriptor' in filename or 'ZmxyOL' in filename or 'services' in filename:
            # 转换为相对路径或简化路径
            try:
                rel_path = os.path.relpath(filename, os.getcwd())
                if len(rel_path) > 100:
                    # 如果路径太长，只保留最后部分
                    rel_path = "..." + rel_path[-97:]
            except:
                rel_path = os.path.basename(filename)
            
            files_coverage[rel_path] = dict(sorted(funcs.items(), key=lambda x: x[1], reverse=True))
    
    # 获取调用次数最多的函数（Top 20）
    top_functions = sorted(
        _coverage_tracker["functions"].items(),
        key=lambda x: x[1],
        reverse=True
    )[:20]
    
    top_functions_list = [
        {"function": func, "calls": count}
        for func, count in top_functions
    ]
    
    return {
        "enabled": True,
        "total_files": len(files_coverage),
        "total_functions": len(_coverage_tracker["functions"]),
        "files": files_coverage,
        "top_functions": top_functions_list
    }


def reset_code_coverage():
    """
    重置代码覆盖率统计
    
    Examples:
        from AutoScriptor.utils.log_archiver import reset_code_coverage
        reset_code_coverage()
    """
    global _coverage_tracker
    _coverage_tracker["files"] = {}
    _coverage_tracker["functions"] = {}
    logger.info("代码覆盖率统计已重置")


def _format_variable_value(value: Any, max_length: int = 200) -> str:
    """格式化变量值，避免过长或不可序列化的对象"""
    try:
        if value is None:
            return "None"
        if isinstance(value, (str, int, float, bool)):
            str_value = str(value)
            if len(str_value) > max_length:
                return str_value[:max_length] + "..."
            return str_value
        if isinstance(value, (list, tuple)):
            if len(value) == 0:
                return f"{type(value).__name__}([])"
            if len(value) > 10:
                items_str = ", ".join([_format_variable_value(v, 50) for v in value[:5]])
                return f"{type(value).__name__}([{items_str}...], len={len(value)})"
            items_str = ", ".join([_format_variable_value(v, 50) for v in value])
            return f"{type(value).__name__}([{items_str}])"
        if isinstance(value, dict):
            if len(value) == 0:
                return "dict({})"
            if len(value) > 10:
                items = list(value.items())[:5]
                items_str = ", ".join([f"{k!r}: {_format_variable_value(v, 50)}" for k, v in items])
                return f"dict({{{items_str}...}}, len={len(value)})"
            items_str = ", ".join([f"{k!r}: {_format_variable_value(v, 50)}" for k, v in value.items()])
            return f"dict({{{items_str}}})"
        # 对于其他对象，尝试获取其字符串表示
        str_value = repr(value)
        if len(str_value) > max_length:
            return str_value[:max_length] + "..."
        return str_value
    except Exception:
        return f"<无法序列化: {type(value).__name__}>"


def archive_error(
    error_name: str,
    exc: Exception,
    mixctrl=None,
    include_click_screenshots: bool = True,
    extra_context: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    归档错误：将错误日志、截图、click_screenshots 打包到 logs/errors 目录下
    
    Args:
        error_name: 错误标识（如任务名），会用于文件夹命名
        exc: 异常对象
        mixctrl: 可选，用于获取当前截图。如果为None则跳过当前截图
        include_click_screenshots: 是否包含 click_screenshots 目录下的所有截图，默认True
        extra_context: 额外的观测值字典，会被写入错误日志中
    
    Returns:
        返回归档文件夹路径，如果归档失败则返回None
    
    Examples:
        # 基本用法
        archive_error("每日任务/天庭/组队任务", RuntimeError("定位失败"))
        
        # 包含当前截图和额外上下文
        from AutoScriptor import mixctrl
        archive_error("战斗任务", exc, mixctrl=mixctrl, extra_context={
            "current_location": "极北村庄",
            "task_params": {"difficulty": "噩梦"},
            "retry_count": 3
        })
    """
    try:
        # 1. 生成时间戳和安全的文件夹名
        ts = datetime.now().strftime('%y%m%d_%H%M%S')
        safe_name = error_name.replace('/', '_').replace(' -> ', '_').replace('\\', '_')
        folder_name = f"[{ts}][{safe_name}]"
        
        # 2. 创建归档文件夹
        err_base_dir = os.path.join(os.getcwd(), 'logs', 'errors')
        archive_dir = os.path.join(err_base_dir, folder_name)
        os.makedirs(archive_dir, exist_ok=True)
        
        # 3. 获取日志文件的最后100行（如果存在）
        recent_log_lines = []
        try:
            # 尝试从 logzero 的处理器中获取当前日志文件
            current_log_file = None
            for handler in logger.handlers:
                if hasattr(handler, 'baseFilename'):
                    current_log_file = handler.baseFilename
                    break
            
            # 如果没找到，尝试从 logs/log 目录找最新的日志文件
            if not current_log_file or not os.path.exists(current_log_file):
                log_dir = os.path.join(os.getcwd(), 'logs', 'log')
                if os.path.isdir(log_dir):
                    log_files = [f for f in os.listdir(log_dir) if f.endswith('.log')]
                    if log_files:
                        log_files.sort(key=lambda x: os.path.getmtime(os.path.join(log_dir, x)), reverse=True)
                        current_log_file = os.path.join(log_dir, log_files[0])
            
            # 读取最后100行
            if current_log_file and os.path.exists(current_log_file):
                try:
                    with open(current_log_file, 'r', encoding='utf-8', errors='ignore') as lf:
                        all_lines = lf.readlines()
                        recent_log_lines = all_lines[-100:] if len(all_lines) > 100 else all_lines
                except Exception as e:
                    logger.warning(f"读取日志文件失败: {e}")
        except Exception as e:
            logger.warning(f"获取日志文件失败: {e}")
        
        # 4. 保存错误日志（先写最近100行日志，再写错误信息）
        err_log_file = os.path.join(archive_dir, 'error.log')
        with open(err_log_file, 'w', encoding='utf-8') as ef:
            # 写入最近100行日志
            if recent_log_lines:
                ef.write("=" * 80 + "\n")
                ef.write("最近100行日志（来自主日志文件）:\n")
                ef.write("=" * 80 + "\n")
                ef.writelines(recent_log_lines)
                ef.write("\n" + "=" * 80 + "\n")
                ef.write("错误信息:\n")
                ef.write("=" * 80 + "\n\n")
            
            # 写入错误信息
            ef.write(f"[{ts}] {error_name} 执行错误: {exc}\n")
            ef.write(f"异常类型: {type(exc).__name__}\n")
            ef.write(f"异常信息: {str(exc)}\n\n")
            
            # 收集并写入上下文信息
            # 1. 收集默认上下文
            default_context = collect_default_context()
            
            # 2. 合并用户提供的额外上下文（优先级更高）
            if extra_context:
                default_context.update(extra_context)
            
            # 3. 写入上下文信息
            if default_context:
                ef.write("=" * 80 + "\n")
                ef.write("上下文信息:\n")
                ef.write("=" * 80 + "\n")
                for key, value in sorted(default_context.items()):
                    ef.write(f"  {key} = {_format_variable_value(value)}\n")
                ef.write("\n")
            
            # 写入完整堆栈跟踪（包含局部变量）
            ef.write("=" * 80 + "\n")
            ef.write("完整堆栈跟踪（包含局部变量）:\n")
            ef.write("=" * 80 + "\n")
            
            # 使用 TracebackException 捕获局部变量
            try:
                # 优先使用 sys.exc_info() 获取完整的 traceback（如果在异常处理上下文中）
                exc_type, exc_value, exc_tb = sys.exc_info()
                if exc_tb is not None and exc_value is exc:
                    # 使用当前异常的 traceback（在 except 块中调用时）
                    tb_exc = traceback.TracebackException(
                        exc_type, exc_value, exc_tb,
                        capture_locals=True,
                        lookup_lines=True
                    )
                elif hasattr(exc, '__traceback__') and exc.__traceback__ is not None:
                    # 使用异常对象自带的 traceback
                    tb_exc = traceback.TracebackException.from_exception(
                        exc, 
                        capture_locals=True,
                        lookup_lines=True
                    )
                else:
                    # 没有 traceback，使用标准格式
                    raise ValueError("No traceback available")
                # 格式化堆栈跟踪
                stack_lines = []
                for frame_summary in tb_exc.stack:
                    stack_lines.append(f'  File "{frame_summary.filename}:line {frame_summary.lineno}", in {frame_summary.name}\n')
                    if frame_summary.line:
                        stack_lines.append(f'    {frame_summary.line.strip()}\n')
                    # 写入局部变量
                    if frame_summary.locals:
                        stack_lines.append("    局部变量:\n")
                        for var_name, var_value in sorted(frame_summary.locals.items()):
                            # 跳过一些内部变量
                            if not var_name.startswith('__'):
                                try:
                                    formatted_value = _format_variable_value(var_value)
                                    stack_lines.append(f"      {var_name} = {formatted_value}\n")
                                except Exception:
                                    stack_lines.append(f"      {var_name} = <无法格式化>\n")
                ef.write(''.join(stack_lines))
                ef.write(f"\n{type(exc).__name__}: {exc}\n")
            except Exception as e:
                # 如果捕获局部变量失败，回退到标准格式
                logger.warning(f"捕获局部变量失败，使用标准格式: {e}")
                ef.write(traceback.format_exc())
        
        # 5. 保存当前截图和定时截图（如果提供了 mixctrl）
        if mixctrl is not None:
            try:
                # 保存当前截图
                img = mixctrl.screenshot()
                if img is not None:
                    screenshot_file = os.path.join(archive_dir, 'current_screenshot.png')
                    cv2.imwrite(screenshot_file, img)
                    logger.debug(f"已保存当前截图: {screenshot_file}")
                
                # 每隔1秒截图一张，共3张
                for i in range(1, 4):
                    time.sleep(1)
                    try:
                        img = mixctrl.screenshot()
                        if img is not None:
                            timed_screenshot_file = os.path.join(archive_dir, f'timed_screenshot_{i}.png')
                            cv2.imwrite(timed_screenshot_file, img)
                            logger.debug(f"已保存定时截图 {i}/3: {timed_screenshot_file}")
                    except Exception as e:
                        logger.warning(f"保存定时截图 {i}/3 失败: {e}")
            except Exception as e:
                logger.warning(f"保存截图失败: {e}")
        
        # 6. 复制调试点击截图目录下的所有截图
        if include_click_screenshots:
            try:
                click_dir = os.path.join(os.getcwd(), 'logs', 'debug_screenshot')
                if os.path.isdir(click_dir):
                    click_screenshots_dest = os.path.join(archive_dir, 'click_screenshots')
                    os.makedirs(click_screenshots_dest, exist_ok=True)
                    
                    # 复制所有截图文件
                    copied_count = 0
                    for filename in os.listdir(click_dir):
                        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                            src_file = os.path.join(click_dir, filename)
                            dst_file = os.path.join(click_screenshots_dest, filename)
                            try:
                                shutil.copy2(src_file, dst_file)
                                copied_count += 1
                            except Exception as e:
                                logger.warning(f"复制截图 {filename} 失败: {e}")
                    
                    if copied_count > 0:
                        logger.debug(f"已复制 {copied_count} 张点击截图到归档目录")
                        
                        # 归档后清空 click_screenshots 目录，以便下次归档
                        try:
                            for filename in os.listdir(click_dir):
                                file_path = os.path.join(click_dir, filename)
                                if os.path.isfile(file_path) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                                    os.remove(file_path)
                            logger.debug(f"已清空 click_screenshots 目录")
                        except Exception as e:
                            logger.warning(f"清空 click_screenshots 目录失败: {e}")
                    else:
                        # 如果没有截图，删除空文件夹
                        try:
                            os.rmdir(click_screenshots_dest)
                        except:
                            pass
                else:
                    logger.debug(f"click_screenshots 目录不存在: {click_dir}")
            except Exception as e:
                logger.warning(f"复制 click_screenshots 失败: {e}")
        
        logger.info(f"✅ 错误已归档到: {archive_dir}")
        return archive_dir
        
    except Exception as e:
        logger.error(f"归档错误失败: {e}")
        logger.error(traceback.format_exc())
        return None


def archive_error_with_log(
    error_name: str,
    exc: Exception,
    mixctrl=None,
    include_click_screenshots: bool = True,
    extra_context: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    归档错误并切换日志文件（兼容旧接口）
    
    这个函数会：
    1. 调用 archive_error 归档错误
    2. 切换日志文件到 logs/log 目录（兼容 log_manager.dump_error_and_log 的行为）
    
    Args:
        error_name: 错误标识
        exc: 异常对象
        mixctrl: 可选，用于获取当前截图
        include_click_screenshots: 是否包含 click_screenshots，默认True
        extra_context: 额外的观测值字典，会被写入错误日志中
    
    Returns:
        返回归档文件夹路径
    """
    # 归档错误
    archive_dir = archive_error(error_name, exc, mixctrl, include_click_screenshots, extra_context)
    
    # 切换日志文件（兼容旧行为）
    try:
        ts = datetime.now().strftime('%y%m%d_%H%M%S')
        safe_name = error_name.replace(' -> ', '_').replace('/', '_').replace('\\', '_')
        log_dir = os.path.join(os.getcwd(), 'logs', 'log')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"[{ts}][{safe_name}].log")
        logfile(log_file, encoding='utf-8')
    except Exception as e:
        logger.warning(f"切换日志文件失败: {e}")
    
    return archive_dir


def dump_error_and_log(path_str: str, exc: Exception):
    """
    归档错误并切换日志文件（兼容旧接口）
    
    实际调用 archive_error_with_log 进行统一归档
    
    Args:
        path_str: 错误标识（如任务名）
        exc: 异常对象
    """
    try:
        from AutoScriptor import mixctrl
    except:
        mixctrl = None
    archive_error_with_log(path_str, exc, mixctrl=mixctrl, include_click_screenshots=True)
