# 递归获取最小注册顺序，用于分支排序
import importlib
import os
import pathlib
from AutoScriptor.utils.constant import cfg
from ZmxyOL.task.translations import translate_path_part, normalize_to_cn


def get_min_order(node):
    if isinstance(node, dict):
        if 'order' in node:
            v = node['order']
            # 兼容字符串/None，统一为数字
            try:
                return int(v)
            except Exception:
                return float('inf')
        orders = [get_min_order(v) for v in node.values() if isinstance(v, dict)]
        return min(orders) if orders else float('inf')
    return float('inf')

# 递归对任务树按注册顺序排序
def sort_tasks(node):
    for child in node.values():
        if isinstance(child, dict):
            sort_tasks(child)
    sorted_items = sorted(node.items(), key=lambda item: get_min_order(item[1]))
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
    """Collect all Python files under PACKAGE_PATH."""
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
    print("\n=== 开始导入模块 ===")
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
    print("\n=== 模块导入完成 ===")


def normalize_cfg_tasks_to_cn():
    """将 cfg['tasks'] 的所有键统一为中文，并合并重复分支。
    - 兼容中文/英文（新旧）键，统一映射为中文键
    - 合并时优先保留已注册的运行期字段（fn、order、param_meta 等）
    - 就地替换 cfg._config['tasks'] 并保存
    """
    def is_leaf(node: dict) -> bool:
        return isinstance(node, dict) and ('next_exec_time' in node or 'fn' in node)

    def deep_merge(dst: dict, src: dict) -> dict:
        for k, v in src.items():
            if k not in dst:
                dst[k] = v
                continue
            if isinstance(dst[k], dict) and isinstance(v, dict):
                # 叶子节点合并：保留 fn/order 等运行期字段
                if is_leaf(dst[k]) or is_leaf(v):
                    # 优先保留已有的 fn；若不存在则使用新的
                    fn_val = dst[k].get('fn') or v.get('fn')
                    merged = {**v, **dst[k]}
                    if fn_val:
                        merged['fn'] = fn_val
                    dst[k] = merged
                else:
                    deep_merge(dst[k], v)
            else:
                dst[k] = v
        return dst

    original = cfg._config.get('tasks', {}) or {}
    normalized: dict = {}
    for key, value in original.items():
        cn_key = normalize_to_cn(key)
        if isinstance(value, dict):
            # 递归规范化子树
            sub_cfg = {'__temp__': value}
            # 将一层展开并规范化
            tmp_normalized = {}
            for sub_k, sub_v in value.items():
                cn_sub_k = normalize_to_cn(sub_k)
                tmp_normalized[cn_sub_k] = sub_v
            deep_merge(normalized.setdefault(cn_key, {}), tmp_normalized)
        else:
            normalized[cn_key] = value

    cfg._config['tasks'] = normalized
    try:
        cfg.save_config()
    except Exception:
        pass

def update_order_files(py_files):
    """基于实际文件系统生成各层级 _order.txt（不创建新目录）。
    - 子项按已加载并排序后的 cfg['tasks'] 的注册顺序排序；若无记录则置后。
    - 根目录与 daily_task/hyper 可覆盖顺序，但仅包含已存在的子项。
    """
    print("\n=== 开始更新 _order.txt 文件（基于文件系统与已加载顺序） ===")

    fixed_orders = {
        "": ["daily_task", "weekly_task", "event_task", "normal_task"],
    }

    def write_order_file(dir_parts_eng, child_names_eng):
        dir_path = PACKAGE_PATH.joinpath(*dir_parts_eng) if dir_parts_eng else PACKAGE_PATH
        if not dir_path.exists() or not dir_path.is_dir():
            return
        order_file = dir_path / '_order.txt'
        if "__pycache__" in dir_parts_eng: return
        key = "/".join(dir_parts_eng)
        override = fixed_orders.get(key)
        if override:
            present = set(child_names_eng)
            ordered = [name for name in override if name in present]
            for name in child_names_eng:
                if name not in ordered:
                    ordered.append(name)
            child_names_eng = ordered

        with open(order_file, 'w', encoding='utf-8') as f:
            for name in child_names_eng:
                f.write(f"{name}\n")
        print(f"已更新: {order_file}")

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
            # 映射父路径与当前名称为中文以查询 cfg['tasks']
            node = cfg['tasks']
            if not dir_parts_eng:
                # 顶层目录英 -> 中
                top_map_rev = {
                    'daily_task': '每日任务',
                    'weekly_task': '每周任务',
                    'event_task': '活动任务',
                    'normal_task': '一般任务',
                }
                node = node.get(top_map_rev.get(name_eng, translate_path_part(name_eng)), {})
                return get_min_order(node)
            # 非顶层
            for seg in dir_parts_eng:
                node = node.get(translate_path_part(seg), {}) if isinstance(node, dict) else {}
            child_node = node.get(translate_path_part(name_eng), {}) if isinstance(node, dict) else {}
            return get_min_order(child_node)
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
