import csv
import time
from pathlib import Path

from AutoScriptor.core.targets import UiEntry
from AutoScriptor.core.box import Box
from AutoScriptor.logging.logger import logger
from AutoScriptor.utils.paths import get_assets_dir


class UiTable(dict):
    """``ui`` 表的类型：缺 key 时把原因说清楚。

    框架层可以单独安装，那时数据根下没有游戏层资产（``ui_map.csv`` 与参考图），
    表就是空的。裸 ``KeyError`` 看不出「你没装游戏层资产」，只会让人以为键名写错，
    所以在这里直接给出可执行的替代写法。
    """

    def __missing__(self, key):
        raise KeyError(
            f"UI map 里没有 {key!r}。按 key 的目标（I(键名)、B(键名)）需要游戏层的 "
            f"assets/config/ui_map.csv；框架层单独安装时不含这份资产。"
            f'可以改用 T("文字") 或 B(x, y, w, h) 直接给区域，'
            f"或用 set_assets_root() 指向自己的资产树。"
        )


class UIMapManager:
    def __init__(self):
        self._ui: UiTable = UiTable()
        # 建表时用的资产根。``get_ui()`` 靠它发现「资产根后来才被注册」——
        # 游戏层是在自己的包导入时才 ``set_assets_root()`` 的，而本模块可能在那之前
        # 就被 import（例如某个测试模块顶层 import 了 ui_map）。不比对的话，表会在
        # 第一次导入时按错误的根建好并一直空着，之后谁都想不到去 reload。
        self._loaded_assets_root: Path | None = None
        self.init_ui()

    def init_ui(self) -> None:
        assets_root = get_assets_dir()
        csv_path = assets_root / "config" / "ui_map.csv"
        if not csv_path.is_file():
            # 没有资产不等于用错：框架层单独安装就是没有这张表。按空表启动，
            # T("文字") 照常可用（它只走 ui_str，不查表），按 key 的目标会在取表时报错。
            logger.info("未找到 UI map 配置（%s），按空表启动；按 key 的目标需要游戏层资产", csv_path)
            self._ui.clear()
            self._loaded_assets_root = assets_root
            return
        logger.info("Loading UI map config: %s", csv_path)
        start_time = time.time()

        rows = _read_ui_map_rows(csv_path)
        entries: dict[str, UiEntry] = {}

        for index, row in enumerate(rows, start=1):
            key = row["key"].strip()
            if not key:
                raise ValueError(f"UI map row {index} has empty key")
            left, top, width, height = _parse_box(row, index, key)
            img_name = row.get("img", "").strip()
            img_path = str((assets_root / "pic" / img_name).resolve()) if img_name else None
            text_val = row.get("text", "").strip() or None
            entries[key] = UiEntry(key, Box(left, top, width, height), img_path, text_val)

        # 原地替换内容，不重新绑定 self._ui：模块级 ``ui`` 与 ``AutoScriptor.ui``
        # 都持有同一个 dict 对象，原地刷新才能让它们一起看到新表。
        self._ui.clear()
        self._ui.update(entries)
        self._loaded_assets_root = assets_root
        elapsed_time = time.time() - start_time
        logger.info("UI map initialized: %s entries in %.2fs", len(entries), elapsed_time)

    def get_ui(self):
        if self._loaded_assets_root != get_assets_dir():
            logger.info("资产根已变更，重新加载 UI map")
            self.init_ui()
        return self._ui


def _read_ui_map_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"key", "text", "left", "top", "width", "height", "img"}
        fields = set(reader.fieldnames or [])
        missing = sorted(required - fields)
        if missing:
            raise ValueError(f"UI map config missing columns: {', '.join(missing)}")
        return list(reader)


def _parse_box(row: dict[str, str], index: int, key: str) -> tuple[int, int, int, int]:
    try:
        return (
            int(row["left"]),
            int(row["top"]),
            int(row["width"]),
            int(row["height"]),
        )
    except ValueError as exc:
        raise ValueError(f"Invalid UI map box at row {index} ({key})") from exc


ui_manager = UIMapManager()
ui = ui_manager.get_ui()


def reload_ui_map():
    global ui
    ui_manager.init_ui()
    ui = ui_manager.get_ui()
    return ui
