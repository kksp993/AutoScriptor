import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.custom_task.bagin_core import StaticBaginEnv, solve


def _run(counts, *, rewards=None, remaining=None, merge_value=10):
    env = StaticBaginEnv(counts, rewards or {}, remaining)
    trajectory = solve(
        list(counts),
        execute=env,
        merge_remaining=remaining,
        id_style="int",
        merge_value=merge_value,
        max_step_seconds=0.8,
    )
    return trajectory, env


def _count_ops(trajectory, op):
    return sum(1 for item in trajectory if item["op"] == op)


def test_bagin_single_user_respects_merge_quota():
    trajectory, env = _run({"a": [5, 5, 5]}, remaining=[3])

    assert _count_ops(trajectory, "merge") == 3
    assert env.merge_count == {"a": 3}


def test_bagin_two_user_swap_completes_both_badges():
    trajectory, env = _run({"a": [2, 0, 1], "b": [0, 2, 1]})

    assert _count_ops(trajectory, "exchange") == 1
    assert _count_ops(trajectory, "merge") == 2
    assert env.merge_count == {"a": 1, "b": 1}


def test_bagin_three_color_cycle_is_not_pruned_by_local_balance():
    trajectory, env = _run({"a": [3, 0, 0], "b": [0, 3, 0], "c": [0, 0, 3]})

    assert _count_ops(trajectory, "merge") == 3
    assert env.merge_count == {"a": 1, "b": 1, "c": 1}


def test_bagin_zero_remaining_user_can_still_be_exchange_source():
    trajectory, env = _run(
        {"a": [3, 0, 0], "b": [0, 3, 0], "c": [0, 0, 3]},
        remaining=[1, 0, 1],
    )

    assert _count_ops(trajectory, "merge") == 2
    assert env.merge_count == {"a": 1, "b": 0, "c": 1}


def test_bagin_replans_after_merge_rewards():
    trajectory, env = _run(
        {"a": [3, 0, 0], "b": [0, 3, 0], "c": [0, 0, 3]},
        rewards={"a": [0, 1, 2], "b": [1, 2, 0], "c": [2, 0, 1]},
    )

    assert _count_ops(trajectory, "merge") == 9
    assert env.merge_count == {"a": 3, "b": 3, "c": 3}
