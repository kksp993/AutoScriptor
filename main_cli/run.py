import copy
from datetime import datetime,  timedelta
import traceback
import questionary
import os
from questionary import Separator
from typing import Dict, Any, List
from AutoScriptor import *
from AutoScriptor.crypto.update_config import set_config, verify_config
from ZmxyOL import *
from ZmxyOL.nav.envs.decorators import LOC_ENV
task_menu = cfg["tasks"]
ui_tasks = copy.deepcopy(cfg["tasks"])

def is_leaf_node(node: Dict[str, Any]) -> bool:
    """判断一个节点是否为叶子节点（即一个具体的任务）。"""
    return 'fn' in node and 'on' in node

def get_node_by_path(data: Dict[str, Any], path: List[str]) -> Dict[str, Any]:
    """根据路径列表从数据源中获取当前节点。"""
    node = data
    for key in path:
        node = node[key]
    return node

def is_branch_active(branch_node: Dict[str, Any]) -> bool:
    """
    递归检查一个分支节点（目录）下是否有任何一个叶子节点（任务）是开启的。
    如果任何一个子任务的 'on' 为 True，则该分支被视为已选中。
    """
    for key, value in branch_node.items():
        if is_leaf_node(value):
            if value['on']:
                return True
        # 如果子节点还是一个分支，则递归深入
        elif isinstance(value, dict):
            if is_branch_active(value):
                return True
    return False

def set_branch_status_recursively(branch_node: Dict[str, Any], status: bool):
    """递归地将一个分支节点下所有叶子节点的 'on' 状态设置为指定值。"""
    for key, value in branch_node.items():
        if is_leaf_node(value):
            value['on'] = status
        elif isinstance(value, dict):
            set_branch_status_recursively(value, status)
            


def is_ui_task_node(node: Dict[str, Any]) -> bool:
    """
    判断一个节点是否为UI副本中的任务节点（叶子节点）。
    因为它没有'fn'键，所以我们只检查'on'键。
    """
    return isinstance(node, dict) and 'on' in node


def find_and_execute_tasks(
    master_branch: Dict[str, Any], 
    ui_branch: Dict[str, Any], 
    current_path: List[str]
) -> int:
    """
    ✨ (修正版) 递归查找并执行任务。
    该版本通过在循环开始时就获取主配置节点，使逻辑更健壮，避免了因在位修改导致的状态不同步问题。
    """
    executed_count = 0
    now = datetime.now()

    for key, ui_node in list(ui_branch.items()):
        path_list = current_path + [key]
        path_str = " -> ".join(path_list)
        master_node = master_branch.get(key)
        # Case A: UI中是目录，Master中也应该是目录
        if isinstance(ui_node, dict) and not is_ui_task_node(ui_node):
            if isinstance(master_node, dict):
                executed_count += find_and_execute_tasks(master_node, ui_node, path_list)
            else:
                logger.warning(f"⚠️ 跳过目录: {path_str} - 主配置与UI状态不同步 (UI为目录，主配置中不存在或不是目录)。")
                continue

        # Case B: UI中是任务，Master中也应该是任务
        elif is_ui_task_node(ui_node):
            # 决策 1: UI 必须是开启状态
            if not ui_node.get('on', False):
                continue

            # 决策 2: 冷却时间必须从主配置（真实状态）中读取
            if now.timestamp() < master_node.get('next_exec_time', 0):
                continue

            logger.info(f"▶️  正在执行: {path_str}")
            try:
                master_node['fn']()
                update_task_post_execution(master_node, ui_node, path_list)
                executed_count += 1
                logger.info(f"▶️  执行完毕: {path_str}")
                ensure_in(LOC_ENV)
                logger.info(f"▶️  等待3秒")
                sleep(3)
            except Exception as e:
                logger.error(f"❌ 执行失败: {path_str}，错误: {e}")
                traceback.print_exc()
        
    return executed_count

def update_task_post_execution(
    master_task_node: Dict[str, Any], 
    ui_task_node: Dict[str, Any], 
    task_path: List[str]
):
    """
    在任务成功执行后，根据类别，同时更新主配置节点和UI副本节点。
    早上5点之后视为第二天。
    """
    now = datetime.now()
    category = task_path[0] if task_path else "一般任务"

    if "日常任务" in category:
        # 如果当前时间在早上5点之后，则从明天开始计算；否则从今天开始计算
        if now.hour >= 5:
            next_date = (now + timedelta(days=1)).date()
        else:
            next_date = now.date()
        
        next_exec_dt = datetime.combine(next_date, datetime.min.time().replace(hour=5, minute=0, second=0, microsecond=0))
        
        new_timestamp = next_exec_dt.timestamp()
        
        master_task_node['next_exec_time'] = new_timestamp
        ui_task_node['next_exec_time'] = new_timestamp
        logger.info(f"    - 状态更新: 日常任务, 下次执行时间设置为 {next_exec_dt.strftime('%Y-%m-%d %H:%M')}")

    elif "每周任务" in category:
        # 如果当前时间在早上5点之后，则从下周一开始计算；否则从本周一开始计算
        if now.hour >= 5:
            days_until_monday = (7 - now.weekday()) % 7 or 7
            next_monday = (now + timedelta(days=days_until_monday)).date()
        else:
            days_until_monday = (7 - now.weekday()) % 7
            next_monday = (now + timedelta(days=days_until_monday)).date()

        next_exec_dt = datetime.combine(next_monday, datetime.min.time().replace(hour=5, minute=0, second=0, microsecond=0))

        new_timestamp = next_exec_dt.timestamp()

        master_task_node['next_exec_time'] = new_timestamp
        ui_task_node['next_exec_time'] = new_timestamp
        logger.info(f"    - 状态更新: 每周任务, 下次执行时间设置为 {next_exec_dt.strftime('%Y-%m-%d %H:%M')}")

    elif "活动任务" in category:
        logger.info(f"    - 状态更新: 活动任务, 状态保持不变。")
        pass

    else:  # "一般任务"
        master_task_node['on'] = False
        ui_task_node['on'] = False
        logger.info(f"    - 状态更新: 一般任务, 状态已设置为关闭 (on=False)。")
    cfg.save_config()


def run_cli_navigation():
    """运行CLI导航的主函数，实现了UI状态与主配置的正确分离。"""
    try:
        ui_tasks = copy.deepcopy(cfg["tasks"])
    except Exception as e:
        logger.error(f"加载任务配置失败，请检查config.json。错误: {e}")
        return

    navigation_path = []
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        
        current_node = get_node_by_path(ui_tasks, navigation_path)
        
        has_unsaved_changes = (ui_tasks != cfg["tasks"])
        unsaved_marker = " *" if has_unsaved_changes else ""
        path_display = " -> ".join(navigation_path) if navigation_path else "主菜单"
        logger.info(f"当前位置: {path_display}{unsaved_marker}\n")

        choices = []
        for key, value in current_node.items():
            if is_leaf_node(value):
                display_text = f"[{'✔' if value['on'] else ' '}] {key} (任务)"
            else:
                display_text = f"[{'✔' if is_branch_active(value) else ' '}] {key}/"
            choices.append(questionary.Choice(title=display_text, value=key))
        choices.append(Separator())
        if navigation_path:
            choices.append(questionary.Choice(title="◀ 返回上一级【Q】", value="--back--"))
            choices.append(questionary.Choice(title="🏠 返回开始【H】", value="--home--"))
            choices.append(questionary.Choice(title="🔧 修改配置【E】", value="--edit--"))
            choices.append(questionary.Choice(title=f"💾 保存配置{unsaved_marker}【S】", value="--save--"))
            choices.append(questionary.Choice(title="🚀 开始执行【R】", value="--execute--"))
        else:
            choices.append(questionary.Choice(title="🚪 退出程序【Q】", value="--exit--"))
            choices.append(questionary.Choice(title="👤 账号管理【A】", value="--Account--")) 
            choices.append(questionary.Choice(title="🏷 标注目标【L】", value="--label--"))
            choices.append(questionary.Choice(title="🚀 开始执行【R】", value="--execute--"))

        action = questionary.select("请选择:", choices=choices, use_search_filter=True, use_jk_keys=False).ask()
        if action is None: action = "--exit--"

        if action == "--exit--":
            if has_unsaved_changes and not questionary.confirm("有未保存的修改，确定退出吗?", default=False).ask():
                continue
            break

        elif action == "--edit--":
            edit_choices = [questionary.Choice(title=k, value=k, checked=(v['on'] if is_leaf_node(v) else is_branch_active(v))) for k, v in current_node.items()]
            if not edit_choices: continue
            selected = questionary.checkbox("勾选要开启的任务/目录:", choices=edit_choices).ask()
            for key, value in current_node.items():
                status = key in selected
                if is_leaf_node(value): value['on'] = status
                else: set_branch_status_recursively(value, status)

        elif action == "--save--":
            cfg["tasks"] = copy.deepcopy(ui_tasks)
            cfg.save_config()
            logger.info("\n✅ 配置已保存！")
            questionary.press_any_key_to_continue().ask()

        elif action == "--execute--":
            master_node_to_execute = get_node_by_path(cfg["tasks"], navigation_path)
            ui_node_counterpart = get_node_by_path(ui_tasks, navigation_path)
            
            total_executed = find_and_execute_tasks(master_node_to_execute, ui_node_counterpart, navigation_path)

            if total_executed > 0:
                cfg.save_config()
                logger.info(f"\n✅ 执行完毕，{total_executed}个任务的状态变更已自动保存！")
            else:
                logger.info("\n🔵 没有需要执行的任务。")
            questionary.press_any_key_to_continue().ask()

        elif action == "--Account--":
            res = questionary.select(
                "请选择操作:", 
                choices=["更新账号信息【U】","验证账号配置【V】","返回上一级【B】"],
                use_search_filter=True, 
                use_jk_keys=False,
            ).ask()
            if res == "更新账号信息【U】":
                set_config()
            elif res == "验证账号配置【V】":
                verify_config()
            elif res == "返回上一级【B】":
                continue
        elif action == "--label--":
            edit_img()
        elif action == "--home--":
            navigation_path.clear()

        elif action == "--back--":
            if navigation_path: navigation_path.pop()
        
        else:
            selected_node = current_node.get(action)
            if selected_node and not is_leaf_node(selected_node):
                navigation_path.append(action)

    logger.info("程序已退出。")


if __name__ == "__main__":
    try:
        run_cli_navigation()
    except KeyboardInterrupt:
        traceback.print_exc()
        logger.info("\n程序已退出")
    finally:
        bg.stop()