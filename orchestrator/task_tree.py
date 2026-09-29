"""
TaskTree: 任务树数据模型
========================
提供任务树的所有纯数据操作：遍历、状态查询、显示格式化、状态切换。
不依赖任何游戏逻辑（AutoScriptor / ZmxyOL），仅操作 dict 结构。
"""

from typing import Any, Callable, Dict, List, Optional, Tuple


class TaskTree:
    """任务树的纯数据操作集合。所有方法均为静态/类方法，不持有状态。"""

    # ── 节点判断 ──

    @staticmethod
    def is_leaf(node: Dict[str, Any]) -> bool:
        """判断一个节点是否为叶子节点（具体任务），含 'on' 键。

        fn / order / param_meta 已迁至 TaskRegistry，cfg 侧仅保留
        用户可序列化配置 (on, next_exec_time, params …)。
        """
        return isinstance(node, dict) and 'on' in node

    is_ui_leaf = is_leaf  # 统一后两者等价

    @staticmethod
    def is_branch(node: Dict[str, Any]) -> bool:
        """判断一个节点是否为目录节点（非叶子的 dict）。"""
        return isinstance(node, dict) and 'on' not in node

    # ── 路径操作 ──

    @staticmethod
    def get_node(data: Dict[str, Any], path: List[str]) -> Dict[str, Any]:
        """根据路径列表从数据源中获取节点。"""
        node = data
        for key in path:
            node = node[key]
        return node

    @staticmethod
    def prune_leaves_not_in_registry(
        branch: Dict[str, Any],
        path_prefix: str,
        has_task: Callable[[str], bool],
    ) -> None:
        """就地删除「叶节点路径在注册表中不存在」的项；若子目录变空则删除。"""
        for key, val in list(branch.items()):
            path = f"{path_prefix}/{key}" if path_prefix else key
            if TaskTree.is_leaf(val):
                if not has_task(path):
                    del branch[key]
            elif isinstance(val, dict):
                TaskTree.prune_leaves_not_in_registry(val, path, has_task)
                if not val:
                    del branch[key]

    # ── 状态查询 ──

    @staticmethod
    def is_branch_active(branch: Dict[str, Any]) -> bool:
        """递归检查分支下是否有任何叶子任务 on=True。"""
        for value in branch.values():
            if not isinstance(value, dict):
                continue
            if TaskTree.is_leaf(value):
                if value['on']:
                    return True
            elif TaskTree.is_branch_active(value):
                return True
        return False

    @staticmethod
    def branch_uncompleted(branch: Dict[str, Any], now_ts: float) -> bool:
        """检查分支下是否存在未完成的已开启任务（next_exec_time <= now）。"""
        for value in branch.values():
            if not isinstance(value, dict):
                continue
            if TaskTree.is_leaf(value) and value.get('on', False):
                if now_ts >= value.get('next_exec_time', 0):
                    return True
            elif TaskTree.branch_uncompleted(value, now_ts):
                return True
        return False

    # ── 状态修改 ──

    @staticmethod
    def set_branch_status(branch: Dict[str, Any], status: bool):
        """递归设置分支下所有叶子节点的 on 状态。"""
        for value in branch.values():
            if not isinstance(value, dict):
                continue
            if TaskTree.is_leaf(value):
                value['on'] = status
            else:
                TaskTree.set_branch_status(value, status)

    # ── 显示格式化 ──

    @staticmethod
    def display_width(text: str) -> int:
        """计算显示宽度，中文字符按2计算。"""
        return sum(2 if ord(c) > 127 else 1 for c in text)

    @staticmethod
    def format_leaf(key: str, node: Dict[str, Any], now_ts: float) -> Tuple[str, str]:
        """格式化叶子节点的 base 和 suffix 文本。
        
        Returns:
            (base, suffix) 元组
        """
        if not node.get('on', False):
            base = f"[ ] {key}"
            if node.get('params'):
                base += " [可编辑]"
            return base, ''
        
        base = f"[✔] {key}"
        if node.get('params'):
            base += " [可编辑]"
        done = now_ts < node.get('next_exec_time', 0)
        suffix = " ✅已完成" if done else " ❌未完成"
        return base, suffix

    @staticmethod
    def format_branch(key: str, node: Dict[str, Any], now_ts: float) -> Tuple[str, str]:
        """格式化目录节点的 base 和 suffix 文本。
        
        Returns:
            (base, suffix) 元组
        """
        active = TaskTree.is_branch_active(node)
        check = '✔' if active else ' '
        base = f"[{check}] {key}/"
        suffix = ''
        if active:
            incomplete = TaskTree.branch_uncompleted(node, now_ts)
            suffix = " ❌未完成" if incomplete else " ✅已完成"
        return base, suffix

    @staticmethod
    def format_node(key: str, node: Dict[str, Any], now_ts: float) -> Tuple[str, str]:
        """统一格式化节点（自动判断叶子/目录）。
        
        Returns:
            (base, suffix) 元组
        """
        if TaskTree.is_leaf(node):
            return TaskTree.format_leaf(key, node, now_ts)
        return TaskTree.format_branch(key, node, now_ts)

    @staticmethod
    def build_aligned_items(
        current_node: Dict[str, Any], 
        now_ts: float
    ) -> List[Tuple[str, str]]:
        """构建对齐的 (key, display_text) 列表，用于菜单显示。
        
        Returns:
            [(key, aligned_display_text), ...]
        """
        items = []
        for key, value in current_node.items():
            if not isinstance(value, dict):
                continue
            base, suffix = TaskTree.format_node(key, value, now_ts)
            items.append((key, base, suffix))

        if not items:
            return []

        max_base = max(TaskTree.display_width(base) for _, base, _ in items)
        result = []
        for key, base, suffix in items:
            pad = max_base - TaskTree.display_width(base)
            display_text = base + ' ' * pad + suffix
            result.append((key, display_text))
        return result

    # ── 搜索辅助 ──

    @staticmethod
    def collect_all_leaves(
        node: Dict[str, Any], 
        path: Optional[List[str]] = None
    ) -> List[Tuple[List[str], Dict[str, Any]]]:
        """递归收集所有叶子节点及其路径。
        
        Returns:
            [(path_list, node_dict), ...]
        """
        if path is None:
            path = []
        results = []
        for key, value in node.items():
            if not isinstance(value, dict):
                continue
            new_path = path + [key]
            if TaskTree.is_leaf(value):
                results.append((new_path, value))
            else:
                results.extend(TaskTree.collect_all_leaves(value, new_path))
        return results
