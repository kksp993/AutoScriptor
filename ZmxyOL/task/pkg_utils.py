import importlib
import pathlib

from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.task_registry import task_registry
from ZmxyOL.task.translations import normalize_cfg_key, translate_path_part


PACKAGE_NAME = __name__.rsplit(".", 1)[0]
PACKAGE_PATH = pathlib.Path(__file__).parent


def get_min_order(node, path_prefix=""):
    """Return the smallest registration order found below a task tree node."""
    if isinstance(node, dict):
        if "on" in node:
            return task_registry.get_order(path_prefix)
        orders = []
        for key, value in node.items():
            if isinstance(value, dict):
                child_path = f"{path_prefix}/{key}" if path_prefix else key
                orders.append(get_min_order(value, child_path))
        return min(orders) if orders else float("inf")
    return float("inf")


def sort_tasks(node, path_prefix=""):
    """Sort task config trees by runtime registration order."""
    for key, child in list(node.items()):
        if isinstance(child, dict) and "on" not in child:
            child_path = f"{path_prefix}/{key}" if path_prefix else key
            sort_tasks(child, child_path)
    sorted_items = sorted(
        node.items(),
        key=lambda item: get_min_order(
            item[1],
            f"{path_prefix}/{item[0]}" if path_prefix else item[0],
        ),
    )
    node.clear()
    node.update(sorted_items)


def get_custom_order_key(path: pathlib.Path):
    """Build a nested sort key from existing _order.txt files."""
    try:
        relative_parts = path.relative_to(PACKAGE_PATH).parts
    except ValueError:
        return (float("inf"), str(path))

    order_key_list = []
    current_lookup_dir = PACKAGE_PATH

    for i, part_name in enumerate(relative_parts):
        order_file = current_lookup_dir / "_order.txt"
        order_index = float("inf")
        is_last_part = i == len(relative_parts) - 1
        name_to_check = path.stem if is_last_part and path.is_file() else part_name

        if order_file.is_file():
            with open(order_file, "r", encoding="utf-8") as f:
                order_list = [line.strip() for line in f.readlines()]
            if name_to_check in order_list:
                order_index = order_list.index(name_to_check)

        order_key_list.append((order_index, name_to_check))
        current_lookup_dir = current_lookup_dir / part_name

    return tuple(order_key_list)


def gather_py_files():
    """Collect all Python task source files under PACKAGE_PATH."""
    return list(PACKAGE_PATH.rglob("*.py"))


def sort_py_files(py_files):
    """Sort Python files using the custom order key."""
    py_files.sort(key=get_custom_order_key)
    return py_files


def import_modules(py_files):
    """Import task modules derived from source file paths."""
    for py_file in py_files:
        if py_file.name == "__init__.py":
            continue
        relative_path = py_file.relative_to(PACKAGE_PATH)
        module_path_parts = list(relative_path.with_suffix("").parts)
        relative_module_path = ".".join(module_path_parts)
        absolute_module_path = f"{PACKAGE_NAME}.{relative_module_path}"
        importlib.import_module(absolute_module_path)


def migrate_remove_daily_login_task(tasks: dict) -> None:
    """Remove stale daily/login task config left by older task trees."""
    daily_key = translate_path_part("daily_task")
    login_key = translate_path_part("login")

    daily = tasks.get(daily_key)
    if isinstance(daily, dict):
        daily.pop(login_key, None)

    chars = cfg._account_data.get("characters", {})
    dirty = False
    for srv_chars in chars.values():
        for char_data in srv_chars.values():
            if not isinstance(char_data, dict):
                continue
            char_daily = (char_data.get("tasks") or {}).get(daily_key)
            if isinstance(char_daily, dict) and login_key in char_daily:
                char_daily.pop(login_key)
                dirty = True
    if dirty:
        cfg._save_account_file()


def migrate_hgwj_daily_task_leaf_to_wanjiefuben(tasks: dict) -> None:
    """Move the old hgwj daily-task leaf to the newer wanjiefuben leaf."""
    daily_key = translate_path_part("daily_task")
    hgwj_key = translate_path_part("hgwj")
    wanjie_key = translate_path_part("wanjiefuben")

    root = tasks.get(daily_key)
    if not isinstance(root, dict):
        return
    hgwj = root.get(hgwj_key)
    if not isinstance(hgwj, dict):
        return
    old = hgwj.pop(daily_key, None)
    if not isinstance(old, dict):
        return
    if "on" not in old and "next_exec_time" not in old:
        hgwj[daily_key] = old
        return
    if wanjie_key in hgwj and isinstance(hgwj[wanjie_key], dict):
        hgwj[wanjie_key] = {**hgwj[wanjie_key], **old}
    else:
        hgwj[wanjie_key] = old


def normalize_cfg_tasks_to_cn():
    """Normalize task config keys to the project's current Chinese task keys."""

    def is_leaf(node: dict) -> bool:
        return isinstance(node, dict) and ("next_exec_time" in node or "on" in node)

    def deep_merge(dst: dict, src: dict) -> dict:
        for key, value in src.items():
            if key not in dst:
                dst[key] = value
                continue
            if isinstance(dst[key], dict) and isinstance(value, dict):
                if is_leaf(dst[key]) or is_leaf(value):
                    dst[key] = {**value, **dst[key]}
                else:
                    deep_merge(dst[key], value)
            else:
                dst[key] = value
        return dst

    normalized: dict = {}
    original = cfg._config.get("tasks", {}) or {}
    for key, value in original.items():
        cn_key = normalize_cfg_key(key)
        if isinstance(value, dict):
            tmp_normalized = {}
            for sub_key, sub_value in value.items():
                tmp_normalized[normalize_cfg_key(sub_key)] = sub_value
            deep_merge(normalized.setdefault(cn_key, {}), tmp_normalized)
        else:
            normalized[cn_key] = value

    cfg._config["tasks"] = normalized
