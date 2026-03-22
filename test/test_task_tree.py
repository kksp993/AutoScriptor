from AutoScriptor.utils.constant import cfg


def _is_leaf(node: object) -> bool:
    return isinstance(node, dict) and "on" in node


def _print_tree(node: dict, prefix: str = "") -> None:
    keys = [k for k, v in node.items() if isinstance(v, dict)]
    for i, k in enumerate(keys):
        v = node[k]
        last = i == len(keys) - 1
        branch = "└─ " if last else "├─ "
        print(prefix + branch + k)
        if not _is_leaf(v):
            _print_tree(v, prefix + ("   " if last else "│  "))


def test_print_tasks_tree() -> None:
    tasks = cfg["tasks"]
    assert isinstance(tasks, dict)
    print("tasks")
    _print_tree(tasks)


if __name__ == "__main__":
    test_print_tasks_tree()


