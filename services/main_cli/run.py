import copy
from datetime import timedelta
import traceback
import questionary
import os
from questionary import Separator, Choice
import importlib
from typing import Dict, Any, List
from datetime import datetime as _datetime, datetime
from ZmxyOL import *
from AutoScriptor import *
from AutoScriptor.crypto.update_config import set_config, verify_config
from ZmxyOL.nav.envs.decorators import LOC_ENV
from ZmxyOL.nav.api import ensure_in
from logzero import logfile, logger
from pypinyin import lazy_pinyin
from services.core.task_manager import TaskManager

# 判断分支下是否存在未完成的任务
def branch_uncompleted(branch: dict, now_ts: float) -> bool:
    # 遍历分支中所有值，仅处理字典类型节点
    for v in branch.values():
        if not isinstance(v, dict):
            continue
        # 叶子任务节点
        if 'fn' in v and 'on' in v and v.get('on', False):
            # 判断是否已执行
            if now_ts >= v.get('next_exec_time', 0):
                return True
        # 目录节点，递归检查
        else:
            if branch_uncompleted(v, now_ts):
                return True
    return False

# 异常日志写入及全量日志文件切换
def dump_error_and_log(path_str: str, exc: Exception):
    ts = datetime.now().strftime('%y%m%d_%H%M%S')
    safe = path_str.replace(' -> ', '_')
    err_dir = os.path.join(os.getcwd(), 'logs', 'errors')
    log_dir = os.path.join(os.getcwd(), 'logs', 'log')
    os.makedirs(err_dir, exist_ok=True); os.makedirs(log_dir, exist_ok=True)
    err_file = os.path.join(err_dir, f"[{ts}][{safe}].log")
    log_file = os.path.join(log_dir, f"[{ts}][{safe}].log")
    with open(err_file, 'w', encoding='utf-8') as ef:
        ef.write(f"[{ts}] {path_str} 执行错误: {exc}\n")
        ef.write(traceback.format_exc())
    logfile(log_file, encoding='utf-8')

task_menu = cfg["tasks"]
ui_tasks = copy.deepcopy(cfg["tasks"])
task_manager = TaskManager()

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
    failed_count = 0
    total_count = len(ui_branch.keys())
    from datetime import datetime
    now = datetime.now()

    for key, ui_node in list(ui_branch.items()):
        path_list = current_path + [key]
        path_str = " -> ".join(path_list)
        master_node = master_branch.get(key)
        # Case A: UI中是目录，Master中也应该是目录
        if isinstance(ui_node, dict) and not is_ui_task_node(ui_node):
            if isinstance(master_node, dict):
                executed_count += find_and_execute_tasks(master_node, ui_node, path_list)[0]
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
            # 复用 TaskManager 的参数解析与执行后更新逻辑
            task_key = "/".join(path_list)
            prev_ts = master_node.get('next_exec_time', 0)
            prev_on = master_node.get('on', False)

            success_count, failed_count = task_manager.execute_tasks([task_key])

            # 执行后，同步 UI 节点，并判断是否视为成功
            refreshed_master = get_node_by_path(cfg["tasks"], path_list)
            new_ts = refreshed_master.get('next_exec_time', prev_ts)
            new_on = refreshed_master.get('on', prev_on)
            ui_node['next_exec_time'] = new_ts
            if 'on' in ui_node:
                ui_node['on'] = new_on

            executed_count += success_count
            failed_count += failed_count
            logger.info(f"▶️  [{executed_count}/{total_count}] 执行完毕: {path_str}，等待3秒")
            ensure_in(LOC_ENV)
            sleep(3)
                
    return executed_count, total_count

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
    if "每日任务" in category:
        # 如果当前时间在早上5点之后，则从明天开始计算；否则从今天开始计算
        if now.hour >= 5:
            next_date = (now + timedelta(days=1)).date()
        else:
            next_date = now.date()
        
        next_exec_dt = datetime.combine(next_date, datetime.min.time().replace(hour=5, minute=0, second=0, microsecond=0))
        
        new_timestamp = next_exec_dt.timestamp()
        
        master_task_node['next_exec_time'] = new_timestamp
        ui_task_node['next_exec_time'] = new_timestamp
        logger.info(f"    - 状态更新: 每日任务, 下次执行时间设置为 {next_exec_dt.strftime('%Y-%m-%d %H:%M')}")

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


def format_display(key: str, node: dict, now_ts: float) -> str:
    """返回任务或目录的显示文本，包括勾选和完成状态后缀"""
    if 'fn' in node and 'on' in node:
        if not node['on']:
            base = f"[ ] {key}"
            return base + (" [可编辑]" if node.get('params') else "")
        check = '✔'
        done = now_ts < node.get('next_exec_time', 0)
        suffix = " ✅已完成" if done else " ❌未完成"
        base = f"[{check}] {key}"
        if node.get('params'): base += " [可编辑]"
        return base + suffix
    # 目录节点
    check = '✔' if is_branch_active(node) else ' '
    suffix = ''
    if check == '✔':
        suffix = " ❌未完成" if branch_uncompleted(node, now_ts) else " ✅已完成"
    return f"[{check}] {key}/{suffix}"

def search_tasks(ui_tasks):
    """根据拼音搜索任务并返回选中的任务路径列表"""
    items = []
    def recurse(node, path):
        for k, v in node.items():
            # 只处理 dict 类型的节点
            if not isinstance(v, dict):
                continue
            new_path = path + [k]
            if is_leaf_node(v):
                items.append((new_path, v))
            else:
                recurse(v, new_path)
    recurse(ui_tasks, [])
    item_maps = []
    for path, node in items:
        display = " -> ".join(path)
        syllables = lazy_pinyin(display)
        full_py = "".join(syllables)
        initials = "".join(s[0] for s in syllables)
        item_maps.append((path, display, full_py, initials))
    search_str = questionary.text("请输入拼音搜索:").ask()
    if not search_str:
        return None
    search_str = search_str.lower()
    filtered = [
        (path, disp)
        for path, disp, full_py, initials in item_maps
        if search_str in full_py.lower() or search_str in initials.lower()
    ]
    if not filtered:
        logger.info("未找到匹配任务")
        questionary.press_any_key_to_continue().ask()
        return None
    choices = [Choice(title=disp, value=path) for path, disp in filtered]
    selected = questionary.select("请选择任务:", choices=choices, use_search_filter=False).ask()
    return selected


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
        from services.core.banner import _print_banner
        _print_banner(banner_only=True)
        current_node = get_node_by_path(ui_tasks, navigation_path)
        # 如果当前节点是叶子任务且有参数，进入参数编辑模式
        if is_leaf_node(current_node) and current_node.get('params'):
            # 参数编辑，支持枚举、多选枚举及列表类型
            param_meta = current_node.get('param_meta', {})
            for param, val in current_node['params'].items():
                if param in param_meta:
                    # 枚举参数处理
                    module_name, class_name = param_meta[param].rsplit('.', 1)
                    mod = importlib.import_module(module_name)
                    EnumClass = getattr(mod, class_name)

                    if isinstance(val, list):
                        # 多选枚举
                        current_values = [EnumClass[v].value for v in val if v in EnumClass.__members__]
                        choices = [
                            Choice(title=e.value, value=e.name, checked=(e.name in val))
                            for e in EnumClass
                        ]
                        selected = questionary.checkbox(
                            f"设置多选枚举参数 \"{param}\" (当前: {current_values}):",
                            choices=choices
                        ).ask()
                        if selected is not None:
                            current_node['params'][param] = selected
                    else:
                        # 单选枚举
                        choices = [Choice(title=e.value, value=e.name) for e in EnumClass]
                        current_value = EnumClass[val].value if val in EnumClass.__members__ else val
                        selected = questionary.select(
                            f"设置枚举参数 \"{param}\" (当前: {current_value}):",
                            choices=choices,
                            default=val
                        ).ask()
                        if selected is not None:
                            current_node['params'][param] = selected

                elif isinstance(val, bool):
                    # 布尔参数处理
                    answer = questionary.confirm(
                        f"设置布尔参数 \"{param}\" (当前: {val}):",
                        default=val
                    ).ask()
                    if answer is not None:
                        current_node['params'][param] = answer
                elif isinstance(val, list):
                    # 列表参数（非枚举）
                    default_val = ", ".join(map(str, val))
                    answer = questionary.text(
                        f"设置列表参数 \"{param}\" (当前: {val}), 请用逗号分隔:",
                        default=default_val
                    ).ask()
                    if answer is not None:
                        current_node['params'][param] = [item.strip() for item in answer.split(',') if item.strip()]
                else:
                    # 其他基本类型参数
                    answer = questionary.text(f"设置参数 \"{param}\" (当前: {val}):", default=str(val)).ask()
                    if answer is not None:
                        try:
                            current_node['params'][param] = type(val)(answer)
                        except Exception:
                            current_node['params'][param] = answer
            questionary.press_any_key_to_continue().ask()
            # 返回上一级菜单
            if navigation_path:
                navigation_path.pop()
            continue
        
        has_unsaved_changes = (ui_tasks != cfg["tasks"])
        unsaved_marker = " *" if has_unsaved_changes else ""
        path_display = " -> ".join(navigation_path) if navigation_path else "主菜单"
        logger.info(f"当前位置: {path_display}{unsaved_marker}\n")

        # 构建对齐的任务/目录列表
        now_ts = _datetime.now().timestamp()
        items = []
        for key, value in current_node.items():
            # 构建 base 文本和 suffix
            if 'fn' in value and 'on' in value:
                if not value['on']:
                    base = f"[ ] {key}"
                    if value.get('params'): base += " [可编辑]"
                    suffix = ''
                else:
                    base = f"[✔] {key}"
                    if value.get('params'): base += " [可编辑]"
                    done = now_ts < value.get('next_exec_time', 0)
                    suffix = " ✅已完成" if done else " ❌未完成"
            else:
                # 目录节点
                check = '✔' if is_branch_active(value) else ' '
                base = f"[{check}] {key}/"
                suffix = ''
                if check == '✔':
                    incomplete = branch_uncompleted(value, now_ts)
                    suffix = " ❌未完成" if incomplete else " ✅已完成"
            items.append((key, base, suffix))
        # 计算显示宽度，考虑中英文宽度差异
        def display_width(text: str) -> int:
            return sum(2 if ord(c) > 127 else 1 for c in text)
        max_base = max(display_width(base) for _, base, _ in items) if items else 0
        choices = []
        for key, base, suffix in items:
            pad = max_base - display_width(base)
            display_text = base + ' ' * pad + suffix
            choices.append(questionary.Choice(title=display_text, value=key))
        choices.append(Separator())
        if navigation_path:
            choices.append(questionary.Choice(title="◀ 返回上一级【Q】", value="--back--"))
            choices.append(questionary.Choice(title="🏠 返回开始【H】", value="--home--"))
            choices.append(questionary.Choice(title="🔧 修改配置【E】", value="--edit--"))
            choices.append(questionary.Choice(title="🔍 搜索任务【F】", value="--search--"))
            choices.append(questionary.Choice(title=f"💾 保存配置{unsaved_marker}【S】", value="--save--"))
            choices.append(questionary.Choice(title="🚀 开始执行【R】", value="--execute--"))
        else:
            choices.append(questionary.Choice(title="🚪 退出程序【Q】", value="--exit--"))
            auth_status = "✅已验证" if cfg["game"].get("character_name", None) else "❌未验证"
            choices.append(questionary.Choice(title=f"👤 账号管理【A】{auth_status}", value="--Account--"))
            choices.append(questionary.Choice(title="🏷 标注目标【L】", value="--label--"))
            choices.append(questionary.Choice(title="🔍 搜索任务【F】", value="--search--"))
            choices.append(questionary.Choice(title="🚀 开始执行【R】", value="--execute--"))
            choices.append(questionary.Choice(title="🔄 重新加载【T】", value="--reload--"))

        action = questionary.select("请选择:", choices=choices, use_search_filter=True, use_jk_keys=False).ask()
        if action is None: action = "--exit--"

        if action == "--exit--":
            if has_unsaved_changes and not questionary.confirm("有未保存的修改，确定退出吗?", default=False).ask():
                continue
            break

        elif action == "--edit--":
            edit_choices = [questionary.Choice(title=k, value=k, checked=(v['on'] if is_leaf_node(v) else is_branch_active(v))) for k, v in current_node.items()]
            if not edit_choices: continue
            # 记录旧状态
            old_status = { key: value['on'] for key, value in current_node.items() if is_leaf_node(value) }
            selected = questionary.checkbox("勾选要开启的任务/目录:", choices=edit_choices).ask()
            for key, value in current_node.items():
                status = key in selected
                if is_leaf_node(value): value['on'] = status
                else: set_branch_status_recursively(value, status)
            # 对新启用的日常/每周任务进行询问
            for key, value in current_node.items():
                if is_leaf_node(value) and not old_status.get(key, False) and value['on']:
                    category = navigation_path[0] if navigation_path else ""
                    if "日常任务" in category or "每周任务" in category:
                        prompt = f"任务「{key}」{'今天' if '日常任务' in category else '本周'}是否已执行过?"
                        if questionary.confirm(prompt, default=False).ask():
                            master_node = get_node_by_path(cfg["tasks"], navigation_path + [key])
                            update_task_post_execution(master_node, value, navigation_path + [key])
                        else:
                            # 用户选择未执行，则重置下次执行时间为0并保存配置
                            master_node = get_node_by_path(cfg["tasks"], navigation_path + [key])
                            master_node['next_exec_time'] = 0
                            value['next_exec_time'] = 0
                            logger.info(f"    - 状态更新: 任务未执行，下次执行时间重置为0。")
                            cfg.save_config()

        elif action == "--save--":
            cfg["tasks"] = copy.deepcopy(ui_tasks)
            cfg.save_config()
            logger.info("\n✅ 配置已保存！")
            questionary.press_any_key_to_continue().ask()

        elif action == "--execute--":
            while mixctrl.app.state(cfg["app"]["app_to_start"]) != "running":
                mixctrl.app.launch(cfg["app"]["app_to_start"])
                sleep(5)
            master_node_to_execute = get_node_by_path(cfg["tasks"], navigation_path)
            ui_node_counterpart = get_node_by_path(ui_tasks, navigation_path)
            # 全局执行异常处理
            try:
                total_executed, total_count = find_and_execute_tasks(master_node_to_execute, ui_node_counterpart, navigation_path)
                if total_executed > 0:
                    cfg.save_config()
                    logger.info(f"\n✅ 执行完毕，{total_executed}/{total_count}个任务的状态变更已自动保存！")
                else:
                    logger.info("\n🔵 没有需要执行的任务。")
            except KeyboardInterrupt:
                bg.clear(clear_signals=True)
                logger.info("🔴 任务执行已中断，返回菜单")
                questionary.press_any_key_to_continue().ask()
                continue

        elif action == "--Account--":
            res = questionary.select(
                "请选择操作:",
                choices=["更新账号信息【U】","验证账号配置【V】","返回上一级【B】"],
                use_search_filter=True,
                use_jk_keys=False,
            ).ask()
            if res == "更新账号信息【U】":
                set_config()
                cfg.save_config()
                logger.info("账号信息已更新并保存！")
                questionary.press_any_key_to_continue().ask()
            elif res == "验证账号配置【V】":
                data = verify_config()
                if data:
                    # 同步到 cfg
                    for key in ["account","password","character_name"]:
                        cfg["game"][key] = data.get(key)
                    # cfg.save_config()
                    logger.info("账号验证成功，配置已同步更新！")
                else:
                    logger.info("账号验证失败，配置未更新。")
                questionary.press_any_key_to_continue().ask()
            elif res == "返回上一级【B】":
                continue
        elif action == "--label--":
            edit_img()
        elif action == "--search--":
            selected_path = search_tasks(ui_tasks)
            if selected_path:
                master_node = get_node_by_path(cfg["tasks"], selected_path)
                ui_node = get_node_by_path(ui_tasks, selected_path)
                if ui_node.get("params"):
                    navigation_path.clear()
                    navigation_path.extend(selected_path)
                else:
                    # 记录旧状态并切换
                    old_status = ui_node.get("on", False)
                    ui_node["on"] = not old_status
                    new_status = ui_node["on"]
                    # 如果是日常或每周任务且刚启用，则询问是否已执行过
                    if new_status and ("日常任务" in selected_path[0] or "每周任务" in selected_path[0]):
                        prompt = f"任务「{selected_path[-1]}」{'今天' if '日常任务' in selected_path[0] else '本周'}是否已执行过?"
                        if questionary.confirm(prompt, default=False).ask():
                            master_node = get_node_by_path(cfg["tasks"], selected_path)
                            update_task_post_execution(master_node, ui_node, selected_path)
                        else:
                            # 用户选择未执行，则重置下次执行时间为0并保存配置
                            master = get_node_by_path(cfg["tasks"], selected_path)
                            master['next_exec_time'] = 0
                            ui_node['next_exec_time'] = 0
                            logger.info("    - 状态更新: 任务未执行，下次执行时间重置为0。")
                            cfg.save_config()
                    logger.info(f"已设置任务 {' -> '.join(selected_path)} {'开启' if ui_node['on'] else '关闭'}")
                    questionary.press_any_key_to_continue().ask()
                    navigation_path.clear()
                    navigation_path.extend(selected_path[:-1])
                continue
        elif action == "--reload--":
            task_manager.reload_tasks()
            logger.info("任务已重新加载！")
            questionary.press_any_key_to_continue().ask()
            continue

        elif action == "--home--":
            navigation_path.clear()

        elif action == "--back--":
            if navigation_path: navigation_path.pop()
        
        else:
            selected_node = current_node.get(action)
            if selected_node:
                # 目录或带参数的任务可进入以进行参数设置
                if not is_leaf_node(selected_node) or selected_node.get('params'):
                    navigation_path.append(action)

    logger.info("程序已退出。")


if __name__ == "__main__":
    try:
        run_cli_navigation()
    except KeyboardInterrupt:
        traceback.print_exc()
        logger.info("\n程序已退出")   