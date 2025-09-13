import pandas as pd
import os
from AutoScriptor.utils.box import Box
import os.path
from AutoScriptor.core.targets import UiEntry
import threading
import time
from logzero import logger
"""
1. ui["登录成功"] => UiEntry
2. ui["登录成功"].box => Box
3. ui["登录成功"].img => ndarray
4. ui["登录成功"].name => "登录成功"
5. ui["登录成功"].text => "登陆成功
"""

class UIMapManager:
    _instance = None
    _lock = threading.Lock()
    _initialized = False
    _init_thread = None
    _ui = {}

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(UIMapManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self._initialized = True
                    self._start_async_init()

    def init_ui(self, app_name: str):
            try:
                logger.info("正在初始化 UI Map，这可能需要一些时间...")
                start_time = time.time()
                csv_path = os.path.join(os.getcwd(), app_name, "assets", 'config', 'ui_map.csv')
                logger.info(f"加载 UI Map 配置文件: {os.path.abspath(csv_path)}")
                
                df = pd.read_csv(csv_path, header=0, encoding='utf-8')
                total_rows = len(df)
                
                for index, row in df.iterrows():
                    key, text_val, l, t, w, h, img_name = row
                    try:
                        l, t, w, h = map(int, (l, t, w, h))
                        box0 = Box(l, t, w, h)
                    except ValueError:
                        box0 = Box(0, 0, 1280, 720)
                    
                    img_path = os.path.abspath(os.path.join(os.getcwd(), app_name, 'assets', 'pic', img_name)) if isinstance(img_name, str) else None
                    self._ui[key] = UiEntry(key, box0, img_path, text_val or None)
                    
                    # 每处理100个条目显示一次进度
                    if (index + 1) % 100 == 0 or index == total_rows - 1:
                        progress = (index + 1) / total_rows * 100
                        logger.info(f"UI Map 加载进度: {progress:.1f}% ({index + 1}/{total_rows})")
                
                elapsed_time = time.time() - start_time
                logger.info(f"UI Map 初始化完成，共加载 {total_rows} 个条目，耗时 {elapsed_time:.2f} 秒")
                
            except FileNotFoundError:
                logger.error(f"UI Map 配置文件未找到: {csv_path}")
                self._ui = {}
            except Exception as e:
                logger.error(f"UI Map 初始化失败: {e}")
                self._ui = {}

    def _start_async_init(self):
        """异步初始化UI Map"""
        self._init_thread = threading.Thread(target=self.init_ui, args=("ZmxyOL",), daemon=True)
        self._init_thread.start()

    def wait_for_initialization(self, timeout=30):
        """等待UI Map初始化完成"""
        if self._init_thread and self._init_thread.is_alive():
            logger.info("等待 UI Map 初始化...")
            self._init_thread.join(timeout)
            if self._init_thread.is_alive():
                logger.warning("UI Map 初始化超时")
                return False
        return True

    def get_ui(self):
        """获取UI Map"""
        if not self.wait_for_initialization():
            raise RuntimeError("UI Map 未初始化完成")
        return self._ui

# 创建全局UI Map管理器实例
ui_manager = UIMapManager()

# 为了保持向后兼容，提供一个ui字典
ui = ui_manager.get_ui()

def backup_ui_csv_and_assets_to_pinyin():
    """
    备份 ui.csv 和 assets 目录，然后将其中的中文文件名转换为汉语拼音，
    并更新 ui.csv 的 img 列。
    """
    import os
    import shutil
    import csv
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        print("未安装 pypinyin，无法进行中文转拼音操作。")
        return

    base_dir = os.path.dirname(__file__)

    # 备份 ui.csv
    csv_path = os.path.join(base_dir, 'ui.csv')
    backup_csv = csv_path + '.bak'
    if os.path.exists(csv_path) and not os.path.exists(backup_csv):
        shutil.copy(csv_path, backup_csv)

    # 备份 assets 目录
    assets_dir = os.path.abspath(os.path.join(base_dir, os.pardir, 'assets'))
    backup_assets = assets_dir + '_backup'
    if os.path.exists(assets_dir) and not os.path.exists(backup_assets):
        shutil.copytree(assets_dir, backup_assets)

    # 重命名 assets 下的文件并记录映射
    mapping = {}
    for fname in os.listdir(assets_dir):
        old_path = os.path.join(assets_dir, fname)
        if not os.path.isfile(old_path):
            continue
        name, ext = os.path.splitext(fname)
        new_name_parts = []
        for ch in name:
            if '\u4e00' <= ch <= '\u9fff':
                new_name_parts.append(lazy_pinyin(ch)[0])
            else:
                new_name_parts.append(ch)
        new_fname = ''.join(new_name_parts) + ext
        new_path = os.path.join(assets_dir, new_fname)
        if new_fname != fname:
            os.rename(old_path, new_path)
        mapping[fname] = new_fname

    # 更新 ui.csv 中的 img 列
    tmp_csv = csv_path + '.tmp'
    if os.path.exists(backup_csv):
        with open(backup_csv, 'r', encoding='utf-8', newline='') as fr, \
                open(tmp_csv, 'w', encoding='utf-8', newline='') as fw:
            reader = csv.reader(fr)
            writer = csv.writer(fw)
            header = next(reader, None)
            if header:
                writer.writerow(header)
                try:
                    img_idx = header.index('img')
                except ValueError:
                    img_idx = len(header) - 1
            for row in reader:
                if len(row) > img_idx and row[img_idx] in mapping:
                    row[img_idx] = mapping[row[img_idx]]
                writer.writerow(row)
        shutil.move(tmp_csv, csv_path)

def get_ui_map(app_name: str):
    """重新加载 UI Map 并返回最新的 UI 映射"""
    # 清空已有的 UI 配置
    ui_manager._ui.clear()
    # 异步初始化新的 UI Map
    ui_manager.init_ui(app_name)    
    return ui_manager._ui
