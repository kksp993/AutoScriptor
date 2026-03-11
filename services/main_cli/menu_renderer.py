"""
MenuRenderer: 菜单构建器
========================
根据 TaskTree 数据构建 questionary 选择项列表。
不处理用户交互，只生成 Choice 列表。
"""

from questionary import Choice, Separator
from datetime import datetime as _dt
from typing import Dict, Any, List

from services.core.task_tree import TaskTree


class MenuRenderer:
    """根据任务树状态构建 questionary 菜单选项。"""

    def __init__(self, scheduler):
        self._scheduler = scheduler

    def build_full_menu(self, current_node: Dict[str, Any], nav_path: List[str],
                        has_unsaved: bool, cfg_config: dict) -> list:
        """构建完整菜单：任务列表 + 分隔符 + 导航选项。"""
        now_ts = _dt.now().timestamp()
        tasks = [Choice(title=display, value=key)
                 for key, display in TaskTree.build_aligned_items(current_node, now_ts)]
        nav = self._build_sub_nav(has_unsaved) if nav_path else self._build_root_nav(cfg_config)
        return tasks + [Separator()] + nav

    def _build_sub_nav(self, has_unsaved: bool) -> List[Choice]:
        """子目录导航选项。"""
        mark = " *" if has_unsaved else ""
        return [
            Choice(title="◀ 返回上一级【Q】", value="--back--"),
            Choice(title="🏠 返回开始【H】", value="--home--"),
            Choice(title="🔧 修改配置【E】", value="--edit--"),
            Choice(title="🔍 搜索任务【F】", value="--search--"),
            Choice(title=f"💾 保存配置{mark}【S】", value="--save--"),
            Choice(title="🚀 开始执行【R】", value="--execute--"),
        ]

    def _build_root_nav(self, cfg_config: dict) -> List[Choice]:
        """主菜单导航选项。"""
        sched = self._scheduler
        icon = {"pending": "🟢", "running": "🟡", "error": "🔴"}.get(sched.state.value, "⚪")
        label = sched.state_label
        if sched.state.value == "running":
            next_ts = sched.get_next_execution_timestamp()
            if next_ts:
                label += f" (下次执行: {_dt.fromtimestamp(next_ts).strftime('%Y-%m-%d %H:%M')})"

        auth = "✅已验证" if cfg_config.get("game", {}).get("character_name") else "❌未验证"
        return [
            Choice(title="🚪 退出程序【Q】", value="--exit--"),
            Choice(title=f"👤 账号管理【A】{auth}", value="--Account--"),
            Choice(title="🏷 标注目标【L】", value="--label--"),
            Choice(title="🔍 搜索任务【F】", value="--search--"),
            Choice(title=f"🚀 开始执行【R】 {icon}{label}", value="--execute--"),
            Choice(title="🔄 重新加载【T】", value="--reload--"),
        ]
