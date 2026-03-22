"""
ActionHandler: 菜单动作处理器
==============================
每个菜单操作对应一个方法，从 CLIApp 中解耦出交互逻辑。
"""

import copy
import importlib
import questionary
from questionary import Choice
from typing import Dict, Any, List, Optional
from AutoScriptor.utils.logger import logger
from pypinyin import lazy_pinyin

from AutoScriptor.utils.constant import cfg
from AutoScriptor.utils.task_registry import task_registry
from AutoScriptor.crypto.update_config import set_config, verify_config
from AutoScriptor import edit_img

from services.core.task_tree import TaskTree


class ActionHandler:
    """处理 CLI 菜单中每一个用户动作。"""

    def __init__(self, scheduler, task_manager):
        self._scheduler = scheduler
        self._task_manager = task_manager

    # ── 公共动作 ──

    def do_param_edit(self, node: Dict[str, Any], task_path: str = ""):
        """叶子任务参数编辑。"""
        meta = task_registry.get_param_meta(task_path) if task_path else {}
        for param, val in node['params'].items():
            new_val = self._edit_single_param(param, val, meta)
            if new_val is not None:
                node['params'][param] = new_val
        questionary.press_any_key_to_continue().ask()

    def do_edit(self, current_node: Dict[str, Any], nav_path: List[str]):
        """批量勾选/取消任务或目录。"""
        edit_choices = [
            Choice(title=k, value=k,
                   checked=(v['on'] if TaskTree.is_leaf(v) else TaskTree.is_branch_active(v)))
            for k, v in current_node.items() if isinstance(v, dict)
        ]
        if not edit_choices:
            return

        old_on = {k: v['on'] for k, v in current_node.items()
                  if isinstance(v, dict) and TaskTree.is_leaf(v)}

        selected = questionary.checkbox("勾选要开启的任务/目录:", choices=edit_choices).ask()
        if selected is None:
            return

        # 批量更新
        for key, value in current_node.items():
            if not isinstance(value, dict):
                continue
            on = key in selected
            if TaskTree.is_leaf(value):
                value['on'] = on
            else:
                TaskTree.set_branch_status(value, on)

        # 新启用的任务询问是否已完成
        for key, value in current_node.items():
            if isinstance(value, dict) and TaskTree.is_leaf(value):
                if not old_on.get(key, False) and value['on']:
                    self._confirm_task_completion(nav_path + [key], value)

    def do_save(self, ui_tasks: Dict[str, Any]):
        """保存配置。"""
        cfg["tasks"] = copy.deepcopy(ui_tasks)
        cfg.save_config()
        logger.info("\n✅ 配置已保存！")
        questionary.press_any_key_to_continue().ask()

    def do_execute(self, ui_tasks: Dict[str, Any]) -> bool:
        """激活调度器。"""
        if not cfg._config.get("game", {}).get("character_name", ""):
            logger.warning("⚠️ 请先验证账号（主菜单 → 👤 账号管理）")
            questionary.press_any_key_to_continue().ask()
            return False
        cfg["tasks"] = copy.deepcopy(ui_tasks)
        cfg.save_config()
        self._scheduler.activate()
        self._scheduler.wake()
        return True

    def do_account(self):
        """账号管理。"""
        action = questionary.select(
            "请选择操作:",
            choices=["更新账号信息【U】", "验证账号配置【V】", "返回上一级【B】"],
            use_search_filter=True, use_jk_keys=False,
        ).ask()
        dispatch = {
            "更新账号信息【U】": self._account_update,
            "验证账号配置【V】": self._account_verify,
        }
        handler = dispatch.get(action)
        if handler:
            handler()

    def do_label(self):
        edit_img()

    def do_search(self, ui_tasks: Dict[str, Any], nav_path: List[str]) -> Optional[List[str]]:
        """搜索任务。返回新导航路径或 None。"""
        path = self._search_tasks(ui_tasks)
        if not path:
            return None
        node = TaskTree.get_node(ui_tasks, path)
        if node.get("params"):
            return path
        # 切换开关
        node["on"] = not node.get("on", False)
        if node["on"]:
            self._confirm_task_completion(path, node)
        logger.info(f"已{'开启' if node['on'] else '关闭'}任务: {' -> '.join(path)}")
        questionary.press_any_key_to_continue().ask()
        return path[:-1]

    def do_reload(self) -> Dict[str, Any]:
        """重新加载任务配置。"""
        self._task_manager.reload_tasks()
        self._scheduler.wake()
        logger.info("任务已重新加载！")
        return copy.deepcopy(cfg["tasks"])

    # ── 内部：账号管理 ──

    def _account_update(self):
        if cfg._config.get("encryption", {}).get("encrypted_data", ""):
            if not questionary.confirm("更新会覆盖当前设置，是否继续？", default=False).ask():
                logger.info("已取消更新。")
                return
        set_config()
        cfg.save_config()
        logger.info("账号信息已更新并保存！")
        questionary.press_any_key_to_continue().ask()

    def _account_verify(self):
        data = verify_config()
        if data:
            for key in ("account", "password", "character_name"):
                cfg["game"][key] = data.get(key)
            logger.info("账号验证成功，配置已同步！")
        else:
            logger.info("账号验证失败。")
        questionary.press_any_key_to_continue().ask()

    # ── 内部：任务完成确认 ──

    def _confirm_task_completion(self, path: List[str], ui_node: Dict[str, Any]):
        """日常/每周任务启用时，询问是否已执行过。"""
        category = path[0] if path else ""
        if "每日任务" not in category and "每周任务" not in category:
            return
        period = "今天" if "每日任务" in category else "本周"
        if questionary.confirm(f"任务「{path[-1]}」{period}是否已执行过?", default=False).ask():
            self._task_manager._update_next_exec_time("/".join(path))
            refreshed = TaskTree.get_node(cfg["tasks"], path)
            ui_node['next_exec_time'] = refreshed.get('next_exec_time', 0)
        else:
            for node in (TaskTree.get_node(cfg["tasks"], path), ui_node):
                node['next_exec_time'] = 0
            logger.info("    - 下次执行时间重置为0")
            cfg.save_config()

    # ── 内部：参数编辑 ──

    def _edit_single_param(self, param: str, val, meta: dict):
        """编辑单个参数。返回新值或 None。"""
        # 枚举参数（有 meta 标注）
        if param in meta:
            raw = meta[param]
            path = (raw.get("enum") or raw.get("path")) if isinstance(raw, dict) else raw
            mod_name, cls_name = path.rsplit('.', 1)
            enum_cls = getattr(importlib.import_module(mod_name), cls_name)
            return self._edit_enum_param(param, val, enum_cls)
        # 布尔
        if isinstance(val, bool):
            return questionary.confirm(f'设置 "{param}" (当前: {val}):', default=val).ask()
        # 列表
        if isinstance(val, list):
            answer = questionary.text(
                f'设置列表 "{param}" (当前: {val}), 逗号分隔:',
                default=", ".join(map(str, val))
            ).ask()
            return [s.strip() for s in answer.split(',') if s.strip()] if answer else None
        # 其他标量
        answer = questionary.text(f'设置 "{param}" (当前: {val}):', default=str(val)).ask()
        if answer is None:
            return None
        try:
            return type(val)(answer)
        except (ValueError, TypeError):
            return answer

    @staticmethod
    def _edit_enum_param(param: str, val, enum_cls):
        """编辑枚举类型参数。"""
        if isinstance(val, list):
            current = [enum_cls[v].value for v in val if v in enum_cls.__members__]
            choices = [Choice(title=e.value, value=e.name, checked=(e.name in val)) for e in enum_cls]
            return questionary.checkbox(f'设置多选 "{param}" (当前: {current}):', choices=choices).ask()
        choices = [Choice(title=e.value, value=e.name) for e in enum_cls]
        current = enum_cls[val].value if val in enum_cls.__members__ else val
        return questionary.select(f'设置 "{param}" (当前: {current}):', choices=choices, default=val).ask()

    # ── 内部：搜索 ──

    def _search_tasks(self, ui_tasks: Dict[str, Any]) -> Optional[List[str]]:
        """拼音搜索任务，返回选中路径。"""
        leaves = TaskTree.collect_all_leaves(ui_tasks)
        items = []
        for path, _ in leaves:
            display = " -> ".join(path)
            syllables = lazy_pinyin(display)
            full = "".join(syllables)
            initials = "".join(s[0] for s in syllables if s)
            items.append((path, display, full, initials))

        query = questionary.text("请输入拼音搜索:").ask()
        if not query:
            return None
        q = query.lower()
        matches = [(p, d) for p, d, full, init in items if q in full.lower() or q in init.lower()]
        if not matches:
            logger.info("未找到匹配任务")
            questionary.press_any_key_to_continue().ask()
            return None
        return questionary.select(
            "请选择任务:", choices=[Choice(title=d, value=p) for p, d in matches], use_search_filter=False
        ).ask()
