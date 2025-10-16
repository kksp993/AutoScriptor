from copy import deepcopy
import inspect
import traceback
from AutoScriptor import *
from services.core.task_manager import TaskManager
from ZmxyOL import *
from flask import Flask, render_template, jsonify, send_from_directory, request, stream_with_context
from flask_socketio import SocketIO, emit
import importlib
import json, os
import logging
import time
from logzero import  logger, setup_logger
import dpath
from queue import Queue, Empty
from threading import Thread
import ctypes

app = Flask(__name__, template_folder='.', static_folder='.', static_url_path='')
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins='*')

# 高性能日志通道：使用内存队列减少磁盘 IO 与轮询延迟
console_handlers_for_setup = [h for h in logger.handlers if hasattr(h, 'stream')]

# 仍然保留文件日志（用于历史追溯），但降低级别以减少写入量
sse_log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'logs'))
os.makedirs(sse_log_dir, exist_ok=True)
sse_log_path = os.path.join(sse_log_dir, 'webui_sse.log')
file_handler = logging.FileHandler(sse_log_path, encoding='utf-8')
file_handler.setLevel(logging.INFO)
if console_handlers_for_setup:
    file_handler.setFormatter(console_handlers_for_setup[0].formatter)
logger.addHandler(file_handler)

# 队列日志处理器（供 SSE 实时推送，捕获 DEBUG+ 级别，零拷贝到前端）
log_queue: Queue[str] = Queue(maxsize=10000)

class QueueHandler(logging.Handler):
    def __init__(self, q: Queue, level=logging.DEBUG):
        super().__init__(level)
        self.q = q
    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            # 无阻塞入队，满了就丢弃最旧的数据，确保不阻塞业务线程
            try:
                self.q.put_nowait(msg)
            except Exception:
                try:
                    _ = self.q.get_nowait()
                except Exception:
                    pass
                try:
                    self.q.put_nowait(msg)
                except Exception:
                    pass
        except Exception:
            pass

queue_handler = QueueHandler(log_queue, level=logging.DEBUG)
if console_handlers_for_setup:
    queue_handler.setFormatter(console_handlers_for_setup[0].formatter)
logger.addHandler(queue_handler)

CONFIG=cfg
ORDER_MAP={}
TASK_MANAGER = TaskManager()
RUN_THREAD = None

def read_config():
    global CONFIG,ORDER_MAP
    ordered_paths = get_ordered_paths(CONFIG['tasks'])
    ORDER_MAP = {path: i for i, path in enumerate(ordered_paths)}
    return CONFIG, ORDER_MAP

def get_ordered_paths(data_dict, prefix=''):
    """
    递归遍历字典，生成有序的任务路径列表。
    """
    paths = []
    for key, value in data_dict.items():
        current_path = f"{prefix}/{key}" if prefix else key
        # 如果值是字典且不包含 'next_exec_time'，则认为是中间节点，继续递归
        if isinstance(value, dict) and 'next_exec_time' not in value:
            paths.extend(get_ordered_paths(value, prefix=current_path))
        else:
            # 否则认为是叶子节点（一个具体的任务）
            paths.append(current_path)
    return paths

def make_public_config():
    """生成对前端安全可用的配置（去除函数与敏感项）。"""
    config_data = deepcopy(cfg._config)
    for pattern in ["**/fn","**/encryption","**/weekday","**/month","**/day","**/year","**/account","**/password"]:
        try: dpath.delete(config_data, pattern)
        except: pass
    return config_data

@app.route('/')
def index():
    # 将 AutoConfig 实例转换为原生 dict 供模板序列化
    return render_template('app.html', config=make_public_config())

def get_log_prefix(msg):
    # 2) 查找调用方（跳过当前模块栈帧）
    frame = inspect.currentframe()
    frame = frame.f_back  # 跳过 log_flush 自身
    this_file = os.path.normcase(os.path.abspath(__file__))
    while frame and os.path.normcase(os.path.abspath(frame.f_code.co_filename)) == this_file:
        frame = frame.f_back
    if frame is None:
        pathname, lineno = this_file, 0
    else:
        pathname, lineno = frame.f_code.co_filename, frame.f_lineno

    # 3) 使用 LogRecord 和已有 formatter 生成“前缀”，不包含 message
    record = logging.LogRecord(logger.name, logging.INFO, pathname, lineno, "", None, None)
    console_handlers = [h for h in logger.handlers if hasattr(h, 'stream')]
    ch = console_handlers[0]
    prefix = ch.format(record).rstrip()
    return prefix + " " + msg

def _ws_log_emitter():
    """
    后台任务：从日志队列批量取出并通过 WebSocket 推送。
    采用 socketio.start_background_task 启动，不阻塞主线程，每1秒查询一次，避免线程与 greenlet 混用带来的 greenlet.error。
    """
    while True:
        try:
            # 等待最多1s取出日志
            line = log_queue.get(timeout=1.0)
            batch = [line]
            # 快速排空缓冲，合并为一次消息
            while True:
                try:
                    batch.append(log_queue.get_nowait())
                except Empty:
                    break
            socketio.emit('log_message', { 'data': "\n".join(batch) })
        except Empty:
            # 未有日志时，每1秒检查一次
            socketio.sleep(1.0)

@socketio.on('connect')
def _on_connect():
    emit('log_message', { 'data': '... Connection established ...' })

# 服务 favicon
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(app.static_folder, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

# 枚举可选项查询：输入枚举类路径列表，返回每个路径的成员名列表
@app.route('/enum-options', methods=['POST'])
def enum_options():
    try:
        data = request.get_json(silent=True) or {}
        paths = data.get('paths', [])
        if not isinstance(paths, list):
            return jsonify({'error': 'paths must be a list'}), 400
        result = {}
        for p in paths:
            try:
                module_name, class_name = p.rsplit('.', 1)
                mod = importlib.import_module(module_name)
                EnumClass = getattr(mod, class_name)
                # 取 name 列表
                result[p] = [m.name for m in EnumClass]
            except Exception as e:
                result[p] = []
        return jsonify(result)
    except Exception as e:
        logger.error("enum_options error: %s", e)
        return jsonify({'error': str(e)}), 500

@app.route('/config', methods=['POST'])
def save_config():
    data = request.get_json()
    cfg["app"] = data["app"]
    cfg["emulator"] = data["emulator"]
    cfg["ocr"] = data["ocr"]
    cfg.save_config()
    return '', 204

@app.route('/tasks', methods=['POST'])
def save_tasks():
    """保存前端提交的任务配置并重载任务注册。
    前端通常提交精简后的 tasks（无 fn 等运行期字段），此处直接覆盖 cfg._config['tasks']，
    写盘时会由 AutoConfig.save_config 清理不需要的键。随后重载任务以恢复 fn/order 等运行期信息。
    返回最新可公开配置，便于前端同步。
    """
    try:
        payload = request.get_json(silent=True) or {}
        tasks = payload.get('tasks', payload)
        if not isinstance(tasks, dict):
            return jsonify({"error": "invalid tasks payload"}), 400
        # 原子化更新：在锁内写入磁盘并重载，避免并发读取到无 fn 的中间状态
        try:
            TASK_MANAGER._cfg_lock.acquire()
            cfg._config.setdefault('tasks', {})
            cfg._config['tasks'] = tasks
            cfg.save_config()
            # 重载任务注册，恢复运行期字段（fn/order 等）
            TASK_MANAGER.reload_tasks()
        finally:
            try:
                TASK_MANAGER._cfg_lock.release()
            except Exception:
                pass
        # 同步排序映射
        read_config()
        return jsonify(make_public_config()), 200
    except Exception as e:
        logger.error("save_tasks error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route('/refresh', methods=['GET'])
def refresh_config():
    """返回最新清洗后配置"""
    try:
        TASK_MANAGER.reload_tasks()
        logger.info("refresh config success")
        # 同步更新排序映射，确保 /run 的排序与最新配置一致
        read_config()
        return jsonify(make_public_config()), 200
    except Exception as e:
        logger.error("refresh error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route('/run', methods=['POST'])
def run_tasks():
    global ORDER_MAP, RUN_THREAD
    tasks = request.get_json()
    logger.debug("Received tasks: %s", tasks)
    sorted_tasks = sorted(tasks, key=lambda x: ORDER_MAP.get(x, float('inf')))
    # 后台线程执行，立即返回，避免阻塞请求线程
    def _run(ts):
        try:
            TASK_MANAGER.execute_tasks(ts)
            logger.info("========== 所有任务执行完成 ==========")
        except KeyboardInterrupt:
            try:
                bg.clear(signals_clear=True)
            except Exception:
                pass
            logger.info("========== 任务执行已被中断 ==========")
        except Exception as e:
            logger.error("background run error: %s", e)
    RUN_THREAD = Thread(target=_run, args=(sorted_tasks,), daemon=True)
    RUN_THREAD.start()
    return jsonify({'status': 'ok', 'tasks': sorted_tasks}), 200

@app.route('/stop', methods=['POST'])
def stop_tasks():
    """请求终止当前后台执行。尽量在任务边界生效。"""
    global RUN_THREAD
    try:
        # 优先尝试异步抛出 KeyboardInterrupt 以“立即中断”
        def _async_raise(tid, exctype):
            if not isinstance(exctype, type):
                raise TypeError("Only types can be raised (not instances)")
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), ctypes.py_object(exctype))
            if res == 0:
                return False
            if res != 1:
                # 清理异常注入状态
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)
                return False
            return True

        alive = RUN_THREAD.is_alive() if RUN_THREAD else False
        if alive and RUN_THREAD.ident:
            ok = _async_raise(RUN_THREAD.ident, KeyboardInterrupt)
            if not ok:
                # 回退到温和取消标记
                TASK_MANAGER.request_cancel()
        else:
            TASK_MANAGER.request_cancel()
        return jsonify({'status': 'stopping' if alive else 'idle'}), 200
    except Exception as e:
        logger.error("stop error: %s", e)
        return jsonify({'error': str(e)}), 500

@app.route('/verify', methods=['POST'])
def verify_account():
    data = request.get_json(silent=True) or {}
    security_key = data.get('security_key', '')

    TASK_MANAGER.reload_tasks(security_key)
    cfg._config.setdefault('game', {})
    cfg._config['game']['character_name'] = cfg["game"].get("character_name", "")
    return jsonify({"character_name": cfg["game"].get("character_name", "")})

@app.route('/ocr-status', methods=['GET'])
def ocr_status():
    try:
        import paddle
        try:
            from AutoScriptor.recognition.ocr_rec import ocr_manager
        except Exception:
            ocr_manager = None
        compiled_with_cuda = False
        gpu_count = 0
        current_device = "unknown"
        try:
            compiled_with_cuda = paddle.device.is_compiled_with_cuda()
        except Exception:
            pass
        try:
            gpu_count = paddle.device.cuda.device_count()
        except Exception:
            pass
        try:
            current_device = paddle.get_device()
        except Exception:
            pass
        cfg_use_gpu = False
        try:
            # 兼容两种访问方式
            cfg_use_gpu = bool(cfg["ocr"].get("use_gpu", cfg.get("ocr.use_gpu", False)))
        except Exception:
            try:
                cfg_use_gpu = bool(cfg.get("ocr.use_gpu", False))
            except Exception:
                cfg_use_gpu = False
        engine_ready = False
        try:
            engine_ready = ocr_manager.is_ready() if ocr_manager else False
        except Exception:
            engine_ready = False
        return jsonify({
            "cfg_use_gpu": cfg_use_gpu,
            "compiled_with_cuda": compiled_with_cuda,
            "gpu_count": gpu_count,
            "current_device": current_device,
            "engine_ready": engine_ready
        }), 200
    except Exception as e:
        logger.error("ocr_status error: %s", e)
        return jsonify({"error": str(e)}), 500

@app.route('/account', methods=['POST'])
def add_account():
    data = request.get_json(silent=True) or {}
    account = data.get('account', '')
    password = data.get('password', '')
    character_name = data.get('character_name', '')
    security_key = data.get('security_key', '')
    # 按需求：仅打印
    logger.info("[ADD_ACCOUNT] account=%s, password=%s, character_name=%s, security_key=%s", account, password, character_name, security_key)
    # 将敏感数据按现有逻辑写入加密字段，保持 cfg 前后一致
    try:
        from AutoScriptor.crypto.config_manager import ConfigManager
        cfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config.json'))
        cm = ConfigManager(cfg_path)
        cm.update_game_config(account, password, character_name, security_key)
        # 立即尝试用提供的 key 解密，回显角色名
        decrypted = cm.decrypt_config(security_key) or {}
        character_name = decrypted.get('character_name', character_name)
        # 同步到运行态 cfg（仅内存）
        cfg._config.setdefault('game', {})
        cfg._config['game']['character_name'] = character_name
    except Exception as e:
        logger.error("add_account error: %s", e)
    return jsonify({"character_name": character_name})

if __name__ == '__main__':
    try:
        read_config()
        # 启动日志推送后台任务
        socketio.start_background_task(target=_ws_log_emitter)
        # 使用 Socket.IO 服务器以支持 WebSocket
        socketio.run(app, debug=False, use_reloader=False)
    except Exception as e:
        logger.error("Error: %s", e)
        traceback.print_exc()
        logger.info("程序已退出")
    finally:
        try:
            bg.stop()
        except Exception:
            pass
