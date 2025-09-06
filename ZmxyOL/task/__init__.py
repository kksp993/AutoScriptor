import pathlib
import importlib

from ZmxyOL.task.task_register import register_task
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


# 1. 先一次性获取所有文件路径，并转换为列表
all_py_files = list(PACKAGE_PATH.rglob("*.py"))

# 2. 对文件路径列表进行排序。
all_py_files.sort(key=get_custom_order_key)

# 3. 打印排序后的结果，方便调试
print("=== 排序后的文件列表 ===")
for i, py_file in enumerate(all_py_files):
    # 忽略 __init__.py 文件自身
    if py_file.name == "__init__.py":
        continue
    relative_path = py_file.relative_to(PACKAGE_PATH)
    # 为了方便调试，同时打印出生成的排序键
    key = get_custom_order_key(py_file)
    print(f"{i+1:2d}. {str(relative_path):<40} | Key: {key}")
print("\n=== 开始导入模块 ===")

# 4. 遍历这个排序好的列表来进行导入
for py_file in all_py_files:
    # 避免导入自己
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

# 此时，全局变量 menu 就已经是完全有序的了！
print("\n=== 模块导入完成 ===")

# 5. 将排序后的顺序写入对应目录的 _order.txt 文件
print("\n=== 开始更新 _order.txt 文件 ===")
for py_file in all_py_files:
    if py_file.name == "__init__.py":
        continue
    
    relative_path = py_file.relative_to(PACKAGE_PATH)
    file_dir = py_file.parent
    
    # 为每个目录生成 _order.txt
    current_dir = PACKAGE_PATH
    for part in relative_path.parent.parts:
        current_dir = current_dir / part
        order_file = current_dir / "_order.txt"
        
        # 获取当前目录下的所有文件和子目录（排除 __init__.py、_order.txt 和 __pycache__）
        dir_items = []
        for item in current_dir.iterdir():
            if item.name not in ["__init__.py", "_order.txt", "__pycache__"]:
                # 如果是文件，去掉 .py 后缀；如果是目录，保持原名
                item_name = item.stem if item.is_file() else item.name
                dir_items.append(item_name)
        
        # 根据排序后的文件列表，为当前目录生成正确的顺序
        ordered_items = []
        for sorted_file in all_py_files:
            if sorted_file.is_relative_to(current_dir) and sorted_file.name != "__init__.py":
                item_name = sorted_file.stem if sorted_file.is_file() else sorted_file.name
                if item_name in dir_items and item_name not in ordered_items:
                    ordered_items.append(item_name)
        
        # 将剩余未排序的项目添加到末尾
        for item in dir_items:
            if item not in ordered_items:
                ordered_items.append(item)
        
        # 写入 _order.txt 文件
        try:
            with open(order_file, 'w', encoding='utf-8') as f:
                for item in ordered_items:
                    f.write(f"{item}\n")
        except Exception as e:
            print(f"❌ 更新失败 {order_file}: {e}")

