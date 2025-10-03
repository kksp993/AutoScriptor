import pathlib
import importlib
import os  # 用于文件和目录操作

from ZmxyOL.task.task_register import register_task, translate_path_part
from AutoScriptor.utils.constant import cfg  # 引入全局配置实例

# 递归获取最小注册顺序，用于分支排序
def get_min_order(node):
    if isinstance(node, dict):
        if 'order' in node:
            return node['order']
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

PACKAGE_NAME = __name__
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


def update_order_files(py_files):
    print("\n=== 开始更新 _order.txt 文件 ===")
    keys=[get_custom_order_key(py_file) for py_file in py_files]
    order_dict={}
    def update_order_dict(order_dict,key):
        for i in range(len(key)-1):
            key_path="/".join([key[j][1] for j in range(i)])
            if key_path not in order_dict:
                order_dict[key_path]=[key[i+1][1]]
            elif key[i+1][1] not in order_dict[key_path]:
                order_dict[key_path].append(key[i+1][1])
        return order_dict
    for key in keys:
        order_dict=update_order_dict(order_dict,key)
    # 为每个目录写入或更新 _order.txt 文件
    for key_path, names in order_dict.items():
        # 构造目标目录路径
        parts = key_path.split("/") if key_path else []
        dir_path = PACKAGE_PATH.joinpath(*parts)
        os.makedirs(dir_path, exist_ok=True)
        order_file = dir_path / '_order.txt'
        with open(order_file, 'w', encoding='utf-8') as f:
            for name in names:
                f.write(f"{name}\n")
        print(f"已更新: {order_file}")
    return order_dict


def print_k(area, i=0):
    for k in area:
        print('----' * i, k, sep='')
        if isinstance(area[k], dict):
            print_k(area[k], i+1)

def main():
    from AutoScriptor.core.background import bg
    # 收集并排序 Python 模块
    all_py_files = gather_py_files()
    sorted_files = sort_py_files(all_py_files)
    import_modules(sorted_files)
    sort_tasks(cfg['tasks'])
    # 打印任务配置树
    print_k(cfg['tasks'])
    
main()



