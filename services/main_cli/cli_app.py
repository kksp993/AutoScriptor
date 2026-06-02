"""
CLIApp: CLI 应用主循环
======================
管理 UI 状态（ui_tasks, navigation_path），协调 MenuRenderer 和 ActionHandler。
不包含具体动作实现。
"""

import copy
import os
import questionary
from typing import Dict, Any, List
from AutoScriptor.utils.logger import logger

from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.logger import setup_task_aware_logging

from services.core.task_tree import TaskTree
from services.core.task_manager import TaskManager
from services.core.scheduler import Scheduler
from services.main_cli.menu_renderer import MenuRenderer
from services.main_cli.actions import ActionHandler


class CLIApp:
    """CLI 导航应用。"""

    def __init__(self, scheduler: Scheduler, task_manager: TaskManager):
        self._scheduler = scheduler
        self._task_manager = task_manager
        self._menu = MenuRenderer(scheduler)
        self._actions = ActionHandler(scheduler, task_manager)
        self._ui_tasks: Dict[str, Any] = {}
        self._nav: List[str] = []

        # 动作分发表：action_value → handler(has_unsaved) → should_exit
        self._dispatch_table = {
            "--exit--":    self._on_exit,
            "--edit--":    lambda _: self._on_edit(),
            "--save--":    lambda _: self._on_save(),
            "--execute--": lambda _: self._on_execute(),
            "--Account--": lambda _: self._on_account(),
            "--label--":   lambda _: self._on_label(),
            "--search--":  lambda _: self._on_search(),
            "--reload--":  lambda _: self._on_reload(),
            "--home--":    lambda _: self._on_home(),
            "--back--":    lambda _: self._on_back(),
        }

    def run(self):
        """主循环。"""
        setup_task_aware_logging()
        try:
            self._ui_tasks = copy.deepcopy(cfg["tasks"])
        except Exception as e:
            logger.error(f"加载任务配置失败: {e}")
            return

        while True:
            self._sync_if_needed()
            os.system('cls' if os.name == 'nt' else 'clear')

            current = TaskTree.get_node(self._ui_tasks, self._nav)

            # 叶子任务带参数 → 直接进入参数编辑
            if TaskTree.is_leaf(current) and current.get('params'):
                self._actions.do_param_edit(current, "/".join(self._nav))
                if self._nav:
                    self._nav.pop()
                continue

            self._print_header()
            has_unsaved = self._ui_tasks != cfg["tasks"]
            choices = self._menu.build_full_menu(current, self._nav, has_unsaved, cfg._config)

            action = questionary.select(
                "请选择:", choices=choices, use_search_filter=True, use_jk_keys=False
            ).ask() or "--exit--"

            if self._dispatch(action, has_unsaved):
                break

        logger.info("程序已退出。")

    # ── 分发 ──

    def _dispatch(self, action: str, has_unsaved: bool) -> bool:
        """分发动作。返回 True 表示退出主循环。"""
        handler = self._dispatch_table.get(action)
        if handler:
            return handler(has_unsaved)
        # 未匹配 → 选择了任务/目录
        self._on_navigate(action)
        return False

    # ── 各动作处理 ──

    def _on_exit(self, has_unsaved: bool) -> bool:
        if has_unsaved and not questionary.confirm("有未保存的修改，确定退出吗?", default=False).ask():
            return False
        return True

    def _on_edit(self):
        self._actions.do_edit(TaskTree.get_node(self._ui_tasks, self._nav), self._nav)
        return False

    def _on_save(self):
        self._actions.do_save(self._ui_tasks)
        return False

    def _on_execute(self):
        self._actions.do_execute(self._ui_tasks)
        return False

    def _on_account(self):
        self._actions.do_account()
        return False

    def _on_label(self):
        self._actions.do_label()
        return False

    def _on_search(self):
        result = self._actions.do_search(self._ui_tasks, self._nav)
        if result is not None:
            self._nav[:] = result
        return False

    def _on_reload(self):
        self._ui_tasks = self._actions.do_reload()
        return False

    def _on_home(self):
        self._nav.clear()
        return False

    def _on_back(self):
        if self._nav:
            self._nav.pop()
        return False

    def _on_navigate(self, action: str):
        current = TaskTree.get_node(self._ui_tasks, self._nav)
        selected = current.get(action)
        if selected and isinstance(selected, dict):
            if not TaskTree.is_leaf(selected) or selected.get('params'):
                self._nav.append(action)

    # ── 内部 ──

    def _sync_if_needed(self):
        if self._scheduler.consume_tasks_updated():
            self._ui_tasks = copy.deepcopy(cfg["tasks"])
            logger.info("🔄 后台任务已完成，UI 已同步")

    def _print_header(self):
        has_unsaved = self._ui_tasks != cfg["tasks"]
        path_display = " -> ".join(self._nav) or "主菜单"
        marker = " *" if has_unsaved else ""
        print("【AutoScriptor】 Author: Kksp993 | Repo: https://github.com/kksp993/AutoScriptor")
        logger.info(f" 当前位置: {path_display}{marker}\n")
