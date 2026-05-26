# 递归获取最小注册顺序，用于分支排序
import importlib
import os
import pathlib
from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.paths import is_compiled
from AutoScriptor.utils.task_registry import task_registry
from ZmxyOL.task.translations import translate_path_part, normalize_cfg_key


def get_min_order(node, path_prefix=""):
    """从 TaskRegistry 获取节点的最小注册顺序。"""
    if isinstance(node, dict):
        if 'on' in node:
            return task_registry.get_order(path_prefix)
        orders = []
        for key, v in node.items():
            if isinstance(v, dict):
                child_path = f"{path_prefix}/{key}" if path_prefix else key
                orders.append(get_min_order(v, child_path))
        return min(orders) if orders else float('inf')
    return float('inf')


def sort_tasks(node, path_prefix=""):
    """递归对任务树按注册顺序排序。"""
    for key, child in list(node.items()):
        if isinstance(child, dict) and 'on' not in child:
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

# 您也可以从这里导出排序后的 menu，如果主程序需要的话
__all__ = ["register_task"]

# 目标根包应为 ZmxyOL.task，而非当前模块 ZmxyOL.task.pkg_utils
# 例如：__name__ == 'ZmxyOL.task.pkg_utils' -> 根包名取 'ZmxyOL.task'
PACKAGE_NAME = __name__.rsplit('.', 1)[0]
PACKAGE_PATH = pathlib.Path(__file__).parent

def get_custom_order_key(path: pathlib.Path):
    """
    一个支持层级排序的复杂排序键函数。
    它会从根目录开始，逐级向下解析 _order.txt 文件，
    为每个文件路径生成一个代表其层级顺序的元组。
    """
    # 获取相对于包根目录的路径部分
    # 例如: 对于 tasks/group_a/task_1.py, relative_parts 为 ('group_a', 'task_1.py')
    try:
        relative_parts = path.relative_to(PACKAGE_PATH).parts
    except ValueError:
        # 如果路径不在 PACKAGE_PATH 下，则返回一个默认的、靠后的排序键
        return (float('inf'), str(path))

    order_key_list = []
    current_lookup_dir = PACKAGE_PATH

    # 逐级向下遍历路径的每个部分
    for i, part_name in enumerate(relative_parts):
        order_file = current_lookup_dir / "_order.txt"
        order_index = float('inf')  # 默认顺序，排在最后

        # 确定要在 _order.txt 中查找的名字
        # 如果是路径的最后一部分且是文件，我们查找它的文件名（不带后缀）
        # 否则，我们查找目录名
        is_last_part = (i == len(relative_parts) - 1)
        name_to_check = path.stem if is_last_part and path.is_file() else part_name

        if order_file.is_file():
            try:
                with open(order_file, 'r', encoding='utf-8') as f:
                    order_list = [line.strip() for line in f.readlines()]
                if name_to_check in order_list:
                    order_index = order_list.index(name_to_check)
            except Exception:
                # 如果文件读取失败, 保持默认顺序
                pass
        
        order_key_list.append((order_index, name_to_check))

        current_lookup_dir = current_lookup_dir / part_name

    # 返回由元组组成的元组，作为最终的排序键
    # 例如：((0, 'group_a'), (1, 'task_1'))
    return tuple(order_key_list)



def gather_py_files():
    """Collect all Python files under PACKAGE_PATH.

    In compiled (Nuitka) mode, .py files don't exist on disk.
    Return an empty list -- import_modules() will use the manifest instead.
    """
    if is_compiled():
        return []
    return list(PACKAGE_PATH.rglob("*.py"))


def sort_py_files(py_files):
    """Sort Python files using the custom order key."""
    py_files.sort(key=get_custom_order_key)
    return py_files


def print_sorted_files(py_files):
    print("=== 排序后的文件列表 ===")
    for i, py_file in enumerate(py_files):
        if py_file.name == "__init__.py":
            continue
        relative_path = py_file.relative_to(PACKAGE_PATH)
        key = get_custom_order_key(py_file)
        print(f"{i+1:2d}. {str(relative_path):<40} | Key: {key}")


def import_modules(py_files):
    """Import task modules.

    In compiled mode (py_files is empty), use the explicit manifest list.
    In dev mode, derive module names from file paths as before.
    """
    if not py_files and is_compiled():
        from ZmxyOL.task._manifest import TASK_MODULES
        for module_name in TASK_MODULES:
            try:
                importlib.import_module(module_name)
            except Exception as e:
                print(f"Error importing {module_name}: {e}")
        return

    for py_file in py_files:
        if py_file.name == "__init__.py":
            continue
        relative_path = py_file.relative_to(PACKAGE_PATH)
        module_path_parts = list(relative_path.with_suffix("").parts)
        relative_module_path = ".".join(module_path_parts)
        absolute_module_path = f"{PACKAGE_NAME}.{relative_module_path}"
        try:
            importlib.import_module(absolute_module_path)
        except Exception as e:
            print(f"Error importing {absolute_module_path}: {e}")


def migrate_remove_daily_login_task(tasks: dict) -> None:
    """daily_task/login/ 目录已被移除（登录由 scheduler 自动处理）。
    清理当前角色 cfg['tasks']['每日任务'] 及账号文件中所有角色的残留 '登录' 分支。
    """
    daily = tasks.get("每日任务")
    if isinstance(daily, dict):
        daily.pop("登录", None)

    chars = cfg._account_data.get("characters", {})
    dirty = False
    for srv_chars in chars.values():
        for char_data in srv_chars.values():
            if not isinstance(char_data, dict):
                continue
            char_daily = (char_data.get("tasks") or {}).get("每日任务")
            if isinstance(char_daily, dict) and "登录" in char_daily:
                char_daily.pop("登录")
                dirty = True
    if dirty:
        cfg._save_account_file()


def migrate_hgwj_daily_task_leaf_to_wanjiefuben(tasks: dict) -> None:
    """旧版 hgwj/daily_task.py 在「荒古万界」下注册为中文键「每日任务」，与分类重名。
    现改为 wanjiefuben.py → 「万界副本」。将旧叶节点配置合并到新键下。
    """
    root = tasks.get("每日任务")
    if not isinstance(root, dict):
        return
    hgwj = root.get("荒古万界")
    if not isinstance(hgwj, dict):
        return
    old = hgwj.pop("每日任务", None)
    if not isinstance(old, dict):
        return
    if "on" not in old and "next_exec_time" not in old:
        hgwj["每日任务"] = old
        return
    new_key = "万界副本"
    if new_key in hgwj and isinstance(hgwj[new_key], dict):
        hgwj[new_key] = {**hgwj[new_key], **old}
    else:
        hgwj[new_key] = old


def normalize_cfg_tasks_to_cn():
    """将 cfg['tasks'] 的所有键统一为中文，并合并重复分支。
    - 兼容中文/英文（新旧）键，统一映射为中文键
    - 合并时优先保留已注册的运行期字段（fn、order、param_meta 等）
    - 就地替换 cfg._config['tasks'] 并保存
    """
    def is_leaf(node: dict) -> bool:
        return isinstance(node, dict) and ('next_exec_time' in node or 'on' in node)

    def deep_merge(dst: dict, src: dict) -> dict:
        for k, v in src.items():
            if k not in dst:
                dst[k] = v
                continue
            if isinstance(dst[k], dict) and isinstance(v, dict):
                if is_leaf(dst[k]) or is_leaf(v):
                    merged = {**v, **dst[k]}
                    dst[k] = merged
                else:
                    deep_merge(dst[k], v)
            else:
                dst[k] = v
        return dst

    original = cfg._config.get('tasks', {}) or {}
    normalized: dict = {}
    for key, value in original.items():
        cn_key = normalize_cfg_key(key)
        if isinstance(value, dict):
            # 递归规范化子树
            sub_cfg = {'__temp__': value}
            # 将一层展开并规范化
            tmp_normalized = {}
            for sub_k, sub_v in value.items():
                cn_sub_k = normalize_cfg_key(sub_k)
                tmp_normalized[cn_sub_k] = sub_v
            deep_merge(normalized.setdefault(cn_key, {}), tmp_normalized)
        else:
            normalized[cn_key] = value

    cfg._config['tasks'] = normalized
    try:
        cfg.save_config()
    except Exception:
        pass

def _read_order_lines(order_file: pathlib.Path):
    """读取已有 _order.txt；无文件或为空则返回 None。"""
    if not order_file.is_file():
        return None
    try:
        with open(order_file, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        return lines if lines else None
    except Exception:
        return None


def update_order_files(py_files):
    """基于实际文件系统维护各层级 _order.txt（不创建新目录）。
    - 若某目录下已有非空的 _order.txt，则保留其中的顺序，仅追加新子项、去掉已不存在的名。
    - 仅在尚无 _order.txt（或为空）时，按注册顺序生成；根目录首次生成时可用固定前缀顺序。
    - 编译模式下跳过（包目录不可写且无源文件）。
    """
    if is_compiled():
        return {}
    fixed_orders = {
        "": ["daily_task", "weekly_task", "event_task", "normal_task"],
    }

    def write_order_file(dir_parts_eng, child_names_eng):
        dir_path = PACKAGE_PATH.joinpath(*dir_parts_eng) if dir_parts_eng else PACKAGE_PATH
        if not dir_path.exists() or not dir_path.is_dir():
            return
        order_file = dir_path / '_order.txt'
        if "__pycache__" in dir_parts_eng: return

        existing = _read_order_lines(order_file)
        present = set(child_names_eng)
        if existing is not None:
            merged = [name for name in existing if name in present]
            seen = set(merged)
            for name in child_names_eng:
                if name not in seen:
                    merged.append(name)
                    seen.add(name)
            child_names_eng = merged
        else:
            key = "/".join(dir_parts_eng)
            override = fixed_orders.get(key)
            if override:
                ordered = [name for name in override if name in present]
                for name in child_names_eng:
                    if name not in ordered:
                        ordered.append(name)
                child_names_eng = ordered

        with open(order_file, 'w', encoding='utf-8') as f:
            for name in child_names_eng:
                f.write(f"{name}\n")

    def list_children(dir_parts_eng):
        dir_path = PACKAGE_PATH.joinpath(*dir_parts_eng) if dir_parts_eng else PACKAGE_PATH
        if not dir_path.exists() or not dir_path.is_dir():
            return []
        names = []
        for child in sorted(dir_path.iterdir()):
            if child.name.startswith('_'):
                continue
            if child.is_dir():
                names.append(child.name)
            elif child.suffix == '.py' and child.name not in {
                '__init__.py', 'translations.py', 'task_register.py', 'pkg_utils.py', 'template.py'
            }:
                names.append(child.stem)
        return names

    def order_key_for(dir_parts_eng, name_eng):
        try:
            node = cfg['tasks']
            path_parts = []
            if not dir_parts_eng:
                top_map_rev = {
                    'daily_task': '每日任务',
                    'weekly_task': '每周任务',
                    'event_task': '活动任务',
                    'normal_task': '一般任务',
                }
                cn_key = top_map_rev.get(name_eng, translate_path_part(name_eng))
                node = node.get(cn_key, {})
                return get_min_order(node, cn_key)
            for seg in dir_parts_eng:
                cn_seg = translate_path_part(seg)
                path_parts.append(cn_seg)
                node = node.get(cn_seg, {}) if isinstance(node, dict) else {}
            cn_name = translate_path_part(name_eng)
            path_parts.append(cn_name)
            child_node = node.get(cn_name, {}) if isinstance(node, dict) else {}
            return get_min_order(child_node, "/".join(path_parts))
        except Exception:
            return float('inf')

    def walk(dir_parts_eng):
        children = list_children(dir_parts_eng)
        children.sort(key=lambda name: order_key_for(dir_parts_eng, name))
        write_order_file(dir_parts_eng, children)
        # 递归子目录
        dir_path = PACKAGE_PATH.joinpath(*dir_parts_eng) if dir_parts_eng else PACKAGE_PATH
        for child in dir_path.iterdir():
            if child.is_dir():
                walk(dir_parts_eng + [child.name])

    try:
        walk([])
    except Exception as e:
        print(f"update_order_files error: {e}")
    return {}


def print_k(area, i=0):
    for k in area:
        print('----' * i, k, sep='')
        if isinstance(area[k], dict):
            print_k(area[k], i+1)
