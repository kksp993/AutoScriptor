from calendar import c
import datetime
import enum
import importlib
import inspect
from math import e
import os
import traceback
import dpath
import enum
from typing import List, Tuple
from threading import Event, RLock
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.utils.constant import cfg
from AutoScriptor import TaskRequireReTry
from logzero import logger
from AutoScriptor.utils.logger import set_current_task
import sys
from ZmxyOL.nav import ensure_in
from ZmxyOL.nav.envs.decorators import LOC_ENV

class next_date_enum(enum.Enum):
    past = "past"
    today = "today"
    tomorrow = "tomorrow"
    next_week = "next_week"



def get_day_offset(now: datetime.datetime, next_date: next_date_enum) -> int:
    if next_date == next_date_enum.today: return 0
    if next_date == next_date_enum.tomorrow: return 1
    if next_date == next_date_enum.next_week: return 7
    return 0

def next_exec_dt(
    now: datetime.datetime, 
    next_date: next_date_enum=next_date_enum.today, 
    offset_hours: int = 0
) -> float:
    if next_date == next_date_enum.past: return 0
    elif next_date == next_date_enum.tomorrow:
        next_exec_day = (now + datetime.timedelta(days=1 if now.hour >= 5 else 0)).date()
    elif next_date == next_date_enum.next_week:
        days_until_monday = (7 - now.weekday()) % 7 or 7
        next_exec_day = (now + datetime.timedelta(days=days_until_monday if now.hour >= 5 else 0)).date()
    else:
        next_exec_day = (now + datetime.timedelta(hours=offset_hours)).date()
    if offset_hours == 0:
        target_time = datetime.time(hour=5, minute=0, second=0, microsecond=0)
    else:
        target_time = datetime.time(0, 0, 0, 0)
    next_dt = datetime.datetime.combine(next_exec_day, target_time)
    return next_dt.timestamp()

class TaskManager:  

    def __init__(self):
        # 运行期取消信号：/stop 会触发，execute_tasks 在任务边界检查
        self._cancel_event: Event = Event()
        # 配置与任务注册的并发保护：避免重载过程中出现临时缺失 'fn'
        self._cfg_lock: RLock = RLock()

    def _restart_adb_and_wait(self) -> None:
        import subprocess, threading, time
        adb_path = cfg["emulator"]["adb_path"]
        adb_addr = str(cfg["emulator"].get("adb_addr", ""))
        subprocess.run([adb_path, "kill-server"], capture_output=True, text=True)
        subprocess.run([adb_path, "start-server"], capture_output=True, text=True)
        if adb_addr:
            subprocess.run([adb_path, "connect", adb_addr], capture_output=True, text=True)

        mixctrl.switch_to_mumu()
        intervals = [1, 2, 3, 4, 5, 5, 5]
        for i, interval in enumerate(intervals, 1):
            click_result = {}
            def _click_test():
                try:
                    mixctrl.click(2000, 0)
                    click_result["ok"] = True
                except Exception as e:
                    click_result["error"] = e
                    logger.error(f"ADB重启后测试点击失败，第{i}次尝试，第{interval}秒后重试, 错误信息: {e}")
            t = threading.Thread(target=_click_test)
            t.daemon = True
            t.start()
            t.join(5)
            if not t.is_alive() and click_result.get("ok"):
                logger.info("✅ ADB重启完成，点击测试成功。")
                return
            time.sleep(interval)
        raise RuntimeError("ADB重启后仍无法控制(点击测试失败)")

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def _reset_cancel(self) -> None:
        self._cancel_event.clear()

    def _archive_error(self, task: str, exc: Exception) -> None:
        """归档错误日志和截图（使用统一的错误归档服务）"""
        from AutoScriptor.utils.log_archiver import archive_error
        try:
            archive_error(task, exc, mixctrl=mixctrl, include_click_screenshots=True)
        except Exception as e:
            logger.error(f"归档错误失败: {e}")

    def _solve_task_params(self, task_data: dict, real_fn=None) -> dict:
        # 恢复枚举参数：优先使用 param_meta，否则根据注解回退
        raw_params = task_data.get('params', {})
        params = {}
        param_meta = task_data.get('param_meta', {})
        # 优先使用传入的函数引用，避免 task_data 中临时缺失 'fn'
        target_fn = real_fn if real_fn is not None else task_data.get('fn')
        if target_fn is None:
            raise KeyError('fn')
        sig = inspect.signature(target_fn)
        for k, v in raw_params.items():
            if k in param_meta:
                module_name, class_name = param_meta[k].rsplit('.', 1)
                mod = importlib.import_module(module_name)
                EnumClass = getattr(mod, class_name)
                # 支持枚举列表
                if isinstance(v, list):
                    params[k] = [EnumClass[item] for item in v]
                else:
                    params[k] = EnumClass[v]
            else:
                # 注解为枚举时，尝试根据 name 恢复
                param = sig.parameters.get(k)
                ann = getattr(param, 'annotation', None)
                if isinstance(ann, type) and issubclass(ann, enum.Enum):
                    # 支持单值或列表
                    if isinstance(v, list):
                        params[k] = [ann[item] for item in v]
                    elif isinstance(v, str):
                        params[k] = ann[v]
                    else:
                        params[k] = v
                else:
                    params[k] = v
        return params

    def _update_task_post_execution(self, 
        task: str, 
        next_date:next_date_enum=None,
        offset_hours: int = 0
    ) -> None:
        """
        在任务成功执行后，根据类别，同时更新cfg。
        早上5点之后视为第二天。
        支持任务自定义 next_exec_offset_hours 字段：
        - 若任务节点中存在 next_exec_offset_hours（数值），则以当前时间 + N 小时作为下次执行时间
        - 优先级：函数参数 > 任务节点字段 > 默认类别规则
        """
        now = datetime.datetime.now()
        ts = None

        # 检查任务节点是否自定义了 offset_hours
        task_data = dpath.get(cfg["tasks"], task)
        task_custom_offset = task_data.get("next_exec_offset_hours", None)
        if task_custom_offset is not None and not offset_hours and not next_date:
            # 任务自定义：当前时间 + N 小时
            offset_hours = int(task_custom_offset)
            ts = (now + datetime.timedelta(hours=offset_hours)).timestamp()
            dpath.set(cfg["tasks"], task + "/next_exec_time", ts)
        elif not offset_hours and not next_date:
            if task.startswith("每日任务"):
                ts = next_exec_dt(now, next_date_enum.tomorrow, 0)
                dpath.set(cfg["tasks"], task + "/next_exec_time", ts)
            elif task.startswith("每周任务"):
                ts = next_exec_dt(now, next_date_enum.next_week, 0)
                dpath.set(cfg["tasks"], task + "/next_exec_time", ts)
            elif task.startswith("活动任务"):
                # 活动任务视为 24h 刷新，同每日任务
                ts = next_exec_dt(now, next_date_enum.tomorrow, 0)
                dpath.set(cfg["tasks"], task + "/next_exec_time", ts)
            elif task.startswith("一般任务"):
                dpath.set(cfg["tasks"], task + "/on", False)
        else:
            ts = next_exec_dt(now, next_date, offset_hours)
            dpath.set(cfg["tasks"], task + "/next_exec_time", ts)
        if ts is not None:
            human = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
            logger.info(f"    - 状态更新: 下次执行时间设置为 {human}")
        logger.debug("next_exec_time = %s", dpath.get(cfg["tasks"], task + "/next_exec_time"))
        cfg.save_config()
    

    def execute_tasks(
        self,
        tasks: List[str]
    ) -> Tuple[int, int]:
    
        # 每次开始执行前复位取消标记，并清理调试截图目录
        self._reset_cancel()
        try:
            debug_dir = os.path.join(os.getcwd(), 'logs', 'debug_screenshot')
            if os.path.isdir(debug_dir):
                for f in os.listdir(debug_dir):
                    fp = os.path.join(debug_dir, f)
                    if os.path.isfile(fp):
                        os.remove(fp)
        except Exception:
            pass
        failed_count = 0
        success_count = 0
        for task in tasks:
            if self._cancel_event.is_set():
                logger.info("⏹ 检测到终止请求，停止后续任务执行")
                break

            # 设置当前任务名（取路径最后一段中文名），让日志显示任务名称
            task_display = task.rsplit("/", 1)[-1]
            set_current_task(task_display)

            max_retry = cfg["app"].get("max_retry", 0)
            retry_count = 0
            
            while True:
                # 在锁内读取并解析，避免重载过程导致 'fn' 丢失
                with self._cfg_lock:
                    task_data = dpath.get(cfg["tasks"], task)
                    logger.info(f"▶️  正在执行: {task}")
                    logger.debug(f"task: {task_data}")
                    # 先在锁内准备参数与函数引用（快照）
                    fn = task_data.get("fn")
                    if fn is None:
                        raise KeyError("fn")
                    kwargs = self._solve_task_params(task_data, real_fn=fn)
                try:
                    # 释放锁后执行具体任务，避免长时间阻塞其它请求
                    set_current_task(task.split("/")[-1])  # "一般任务/登录" → "登录"
                    fn(**kwargs)
                    logger.info(f"▶️  执行成功: {task}")
                    # 执行完毕后再加锁更新配置
                    with self._cfg_lock:
                        self._update_task_post_execution(task)
                    success_count += 1
                    break
                except Exception as e:
                    logger.error(f"Error executing task: {task} {e}")
                    if isinstance(e, KeyboardInterrupt): raise

                    # TaskRequireReTry: 不归档，不计失败，按 max_retry 重试
                    if isinstance(e, TaskRequireReTry):
                        if retry_count < max_retry:
                            retry_count += 1
                            logger.info(f"🔄 任务请求重试: {task} ({retry_count}/{max_retry})，原因: {e}")
                            continue
                        else:
                            logger.info(f"⚠️ 任务重试次数已满，仍未成功: {task}，原因: {e}")
                            failed_count += 1
                            break

                    logger.error(f"❌ 执行失败: {task}，错误: {e}")
                    # 保存错误截图和日志
                    self._archive_error(task, e)
                    traceback.print_exc()
                    
                    if isinstance(e, RequestHumanTakeover):
                        failed_count += 1
                        with self._cfg_lock:
                            self._update_task_post_execution(task)
                        logger.info(f"需要人工操作完成，跳过")
                        break
                        
                    if cfg["app"]["restart_on_error"]:
                        mixctrl.app.close(cfg["app"]["app_to_start"])
                        sleep(1)
                        if retry_count >= 1:
                            self._restart_adb_and_wait()
                        while mixctrl.app.state(cfg["app"]["app_to_start"]) != "running":
                            mixctrl.app.launch(cfg["app"]["app_to_start"])
                            sleep(1)
                        sleep(5)
                    
                    mm.set_region("登录")

                    if cfg["app"]["restart_on_error"] and retry_count < max_retry:
                        retry_count += 1
                        logger.info(f"🔄 任务失败，正在重试 ({retry_count}/{max_retry})")
                        continue

                    failed_count += 1
                    break
                finally:
                    set_current_task(None)
                    logger.info(f"Task [END] {task}")
            set_current_task(None)  # 任务结束，恢复原始日志格式
        return success_count, failed_count

    def reload_tasks(self, security_key: str=None) -> None:
        """
        重新加载任务和配置：
        1. 保存当前解密的内容（如账号密码）
        security_key: 安全密钥
        2. 清空现有任务注册
        3. 强制重新加载 task_register 与 ZmxyOL.task（其 __init__ 会扫描与排序）
        4. 恢复 game 信息，得到最新的 cfg
        """
        try:
            # 整个重载过程加锁，确保对外部读者的原子性
            self._cfg_lock.acquire()
            # 1. 保存当前解密的内容（如账号密码）
            saved_game_config = cfg._config.get('game', {}).copy()
            # 2. 清空现有任务注册
            cfg.load_config(security_key) 
            # 3. 强制重新加载注册逻辑与任务包
            # 3.1 先移除所有 ZmxyOL.* 子模块，确保后续 import 触发重新执行
            to_delete = [m for m in list(sys.modules.keys()) if m.startswith('ZmxyOL.')]
            for name in to_delete:
                try:
                    del sys.modules[name]
                except Exception:
                    pass
            # 3.2 重新加载整个 ZmxyOL 包，确保导入顺序正确
            try:
                import ZmxyOL
                importlib.reload(ZmxyOL)
            except Exception:
                import ZmxyOL

            # 4. 恢复保存的解密内容
            if not security_key:
                cfg._config['game'] = saved_game_config

            # logger.info("[TASK] END %s", cfg["game"]["character_name"])
            logger.info("✅ 任务重新加载完成")

        except Exception as e:
            logger.error(f"❌ 任务重新加载失败: {e}")
            raise
        finally:
            try:
                bg.clear(clear_signals=True)
                self._cfg_lock.release()
            except Exception:
                pass

if __name__ == "__main__":
    from AutoScriptor.utils.perf import boost, unboost
    try:
        boost()
        task_manager = TaskManager()
        task_manager.execute_tasks([
            '每日任务/天庭/地狱混沌', 
            '每日任务/天庭/天庭混沌', 
            '每日任务/天庭/组队任务', 
            '每日任务/村庄/仙宝挖掘', 
            '每日任务/村庄/仙气消耗', 
            '每日任务/村庄/仙盟建设', 
            '每日任务/村庄/取经', 
            '每日任务/村庄/天选阁', 
            '每日任务/村庄/妖兽', 
            '每日任务/村庄/宠物培养',
            '每日任务/村庄/强化装备', 
            '每日任务/村庄/战令领取', 
            '每日任务/村庄/活跃券', 
            '每日任务/村庄/竞技场', 
            '每日任务/极北/极北地区/一键碾压', 
            '每日任务/极北/极北地区/冰窟探险', 
            '每日任务/极北/极北地区/厄难副本', 
            '每日任务/极北/极北地区/极北混沌', 
            '每日任务/极北/极北地区/梵天塔', 
            '每日任务/极北/极北地区/混沌蛋', 
            '每日任务/极北/极北村庄/仙宝炼化',
            '每日任务/极北/极北村庄/极光天诏', 
            '每日任务/极北/极北村庄/消费点券', 
            '每日任务/极北/极寒深渊/极渊副本', 
            '每日任务/登录/登录其他角色'
        ])
    finally:
        unboost()
        bg.stop()