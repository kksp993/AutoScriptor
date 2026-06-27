import csv
import time
from pathlib import Path

from AutoScriptor.core.targets import UiEntry
from AutoScriptor.utils.box import Box
from AutoScriptor.utils.logger import logger
from AutoScriptor.utils.paths import get_assets_dir


class UIMapManager:
    def __init__(self):
        self._ui: dict[str, UiEntry] = {}
        self.init_ui()

    def init_ui(self) -> None:
        assets_root = get_assets_dir()
        csv_path = assets_root / "config" / "ui_map.csv"
        logger.info("Loading UI map config: %s", csv_path)
        start_time = time.time()

        rows = _read_ui_map_rows(csv_path)
        ui: dict[str, UiEntry] = {}

        for index, row in enumerate(rows, start=1):
            key = row["key"].strip()
            if not key:
                raise ValueError(f"UI map row {index} has empty key")
            left, top, width, height = _parse_box(row, index, key)
            img_name = row.get("img", "").strip()
            img_path = str((assets_root / "pic" / img_name).resolve()) if img_name else None
            text_val = row.get("text", "").strip() or None
            ui[key] = UiEntry(key, Box(left, top, width, height), img_path, text_val)

        self._ui = ui
        elapsed_time = time.time() - start_time
        logger.info("UI map initialized: %s entries in %.2fs", len(ui), elapsed_time)

    def get_ui(self):
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
