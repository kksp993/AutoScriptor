from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path
from typing import Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import AutoScriptor as autoscriptor_package
import AutoScriptor.core.api as core_api
from AutoScriptor import B, T, Box, click, count, init, locate, sleep, swipe, ui_F, ui_T, wait_for_appear
from AutoScriptor.core.targets import Target
from AutoScriptor.utils.logger import logger


FULL_PORTRAIT_BOX = Box(0, 0, 720, 1280)
BOTTOM_ACTION_BOX = Box(0, 900, 720, 380)

CONFIRM_TARGETS: tuple[Target, ...] = (
    T("确定", box=BOTTOM_ACTION_BOX),
    T("确认", box=BOTTOM_ACTION_BOX),
    T("提交", box=BOTTOM_ACTION_BOX),
)
WRONG_MESSAGE_TARGETS: tuple[Target, ...] = (
    T("请认真", box=FULL_PORTRAIT_BOX),
    T("返回", box=FULL_PORTRAIT_BOX),
)
RETRY_TARGETS: tuple[Target, ...] = (
    T("返回", box=FULL_PORTRAIT_BOX),
)
CONTINUE_TARGETS: tuple[Target, ...] = (
    T("继续", box=FULL_PORTRAIT_BOX),
)
RIGHT_MESSAGE_TARGETS: tuple[Target, ...] = (
    T("答对了", box=FULL_PORTRAIT_BOX),
)
TEST_SCREEN_TARGETS: tuple[Target, ...] = (
    T("测试", box=FULL_PORTRAIT_BOX),
    T("多选", box=FULL_PORTRAIT_BOX),
    T("单选", box=FULL_PORTRAIT_BOX),
    T("选项", box=FULL_PORTRAIT_BOX),
    *CONFIRM_TARGETS,
)
NEXT_LESSON_TARGETS: tuple[Target, ...] = (
    T("下一课", box=FULL_PORTRAIT_BOX),
    T("下一", box=BOTTOM_ACTION_BOX),
    T("开始学习", box=FULL_PORTRAIT_BOX),
    T("点击学习", box=FULL_PORTRAIT_BOX),
    T("开始", box=FULL_PORTRAIT_BOX),
    T("继续", box=FULL_PORTRAIT_BOX),
)
SLIDE_PROMPT_TARGET = T("滑动", box=FULL_PORTRAIT_BOX)

CHOICE_LABELS = ("A", "B", "C", "D")
CHOICE_ATTEMPTS: dict[int, tuple[tuple[str, ...], ...]] = {
    1: (("A",),),
    2: (("A",), ("B",), ("A", "B")),
    3: (("A",), ("B",), ("C",), ("A", "B", "C"), ("A", "B"), ("A", "C"), ("B", "C")),
    4: (
        ("A",),
        ("B",),
        ("C",),
        ("D",),
        ("A", "B", "C", "D"),
        ("A", "B", "C"),
        ("A", "B", "D"),
        ("A", "C", "D"),
        ("B", "C", "D"),
        ("A", "B"),
        ("A", "C"),
        ("A", "D"),
        ("B", "C"),
        ("B", "D"),
        ("C", "D"),
    ),
}


def initialize_autoscriptor_runtime(*, launch_app: bool, start_emulator: bool) -> None:
    """Initialize AutoScriptor without touching WebUI or Electron."""
    if launch_app and start_emulator:
        init()
        return

    selected_emulator_index, adb_address, app_to_start = core_api.ensure_all_environment_ready()
    mix_control, mumu_controller = core_api.ensure_app_running(
        selected_emulator_index,
        adb_address,
        app_to_start,
        start_emulator=start_emulator,
        launch_app=launch_app,
    )
    core_api.mixctrl = mix_control
    core_api.mumu = mumu_controller
    autoscriptor_package.mixctrl = mix_control
    autoscriptor_package.mumu = mumu_controller


def count_visible_choice_labels() -> int:
    """Return how many A/B/C/D option labels are currently visible."""
    choice_targets = [T(choice_label, box=FULL_PORTRAIT_BOX) for choice_label in CHOICE_LABELS]
    located_choices = locate(choice_targets, timeout=0, assure_stable=False)
    visible_counts = count(located_choices)
    visible_choice_labels = [
        choice_label
        for choice_label, visible_count in zip(CHOICE_LABELS, visible_counts)
        if visible_count > 0
    ]
    logger.info("当前可见选项: %s (raw=%s)", visible_choice_labels, visible_counts)
    return len(visible_choice_labels)


def click_choice_labels(choice_labels: Iterable[str]) -> None:
    for choice_label in choice_labels:
        wait_for_appear(CONFIRM_TARGETS, timeout=5)
        click(T(choice_label, box=FULL_PORTRAIT_BOX), timeout=3)


def answer_current_question_by_trial() -> None:
    """Try answer combinations until the page no longer reports a wrong answer."""
    click(T("测试", box=FULL_PORTRAIT_BOX), if_exist=True, timeout=2)

    visible_choice_count = count_visible_choice_labels()
    choice_attempts = CHOICE_ATTEMPTS.get(visible_choice_count, ())
    if not choice_attempts:
        logger.warning("无法识别可尝试的选项数量: %s", visible_choice_count)
        click(CONTINUE_TARGETS, if_exist=True, timeout=3)
        return

    for choice_attempt in choice_attempts:
        logger.info("尝试答案组合: %s", ",".join(choice_attempt))
        click_choice_labels(choice_attempt)
        sleep(1)
        click(CONFIRM_TARGETS, timeout=5)
        sleep(1)
        if ui_T(WRONG_MESSAGE_TARGETS, timeout=0) and ui_F(RIGHT_MESSAGE_TARGETS, timeout=0):
            logger.info("答案组合 %s 被判错，返回重试", ",".join(choice_attempt))
            click(RETRY_TARGETS, timeout=5)
            sleep(2)
            continue
        logger.info("答案组合 %s 未被判错，继续下一步", ",".join(choice_attempt))
        break

    click(CONTINUE_TARGETS, if_exist=True, timeout=5)


def swipe_slide_prompt() -> bool:
    slide_handle = locate(SLIDE_PROMPT_TARGET, timeout=3)
    if not slide_handle:
        return False
    handle_center_x, handle_center_y = slide_handle.center()
    swipe(B(handle_center_x, handle_center_y), B(720, handle_center_y))
    return True


def perform_dead_end_recovery(recovery_count: int) -> None:
    """Probe the old learning screen when no clear next/test/slide target is visible."""
    logger.info("未找到明确入口，执行第 %s 次兜底探测", recovery_count)
    click(B(515, 1162))
    for column_index, row_index in itertools.product(range(5), range(9)):
        click(B(700 - column_index * 100, 300 + row_index * 100, 50, 50))
    click(T("返回", box=BOTTOM_ACTION_BOX), if_exist=True, timeout=2)

    if recovery_count % 5 == 0:
        swipe(B(250, 400), B(525, 400))
        sleep(1)
        swipe(B(525, 400), B(250, 400))
        sleep(1)
        swipe(B(300, 200), B(300, 1000))
        sleep(1)
        swipe(B(300, 1000), B(300, 200))
        sleep(1)


def run_course_mode_forever(*, idle_sleep_seconds: float) -> None:
    """Run the legacy safety-education course and quiz loop."""
    recovery_count = 0
    while True:
        if ui_T(TEST_SCREEN_TARGETS, timeout=0):
            logger.info("检测到测试页面")
            answer_current_question_by_trial()
            recovery_count = 0
            sleep(idle_sleep_seconds)
            continue

        if ui_T((SLIDE_PROMPT_TARGET,), timeout=0):
            logger.info("检测到滑动提示")
            if swipe_slide_prompt():
                recovery_count = 0
            sleep(idle_sleep_seconds)
            continue

        if click(NEXT_LESSON_TARGETS, timeout=5, if_exist=True):
            logger.info("点击学习/下一步入口")
            recovery_count = 0
            sleep(idle_sleep_seconds)
            continue

        recovery_count += 1
        perform_dead_end_recovery(recovery_count)
        sleep(idle_sleep_seconds)


def countdown(minutes: int, seconds: int) -> None:
    total_seconds = minutes * 60 + seconds
    for remaining_seconds in range(total_seconds, 0, -1):
        remaining_minutes, remaining_display_seconds = divmod(remaining_seconds, 60)
        print(f"倒计时 {remaining_minutes:02d}:{remaining_display_seconds:02d}", end="\r", flush=True)
        sleep(1)
    print("倒计时 00:00")
    logger.info("倒计时 00:00")


def click_lab_item(item_index: int) -> None:
    click(B(120, 345 + 75 * item_index))


def turn_lab_page() -> None:
    swipe(B(120, 645), B(120, 365))


def run_lab_mode(
    *,
    pages: int,
    items_per_page: int,
    study_minutes: int,
    study_seconds: int,
) -> None:
    """Run the legacy lab-security list loop."""
    for page_number in range(1, pages + 1):
        logger.info("开始实验室安全第 %s/%s 页", page_number, pages)
        for item_index in range(items_per_page):
            logger.info("点击第 %s 页第 %s 个条目", page_number, item_index + 1)
            click_lab_item(item_index)
            countdown(study_minutes, study_seconds)
        turn_lab_page()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="独立运行历史安全教育脚本，不启动 AutoScriptor WebUI/Electron。",
    )
    parser.add_argument(
        "--mode",
        choices=("course", "lab"),
        default="course",
        help="course=安全教育课程/答题循环；lab=实验室安全列表学习循环。默认 course。",
    )
    parser.add_argument(
        "--no-start-emulator",
        action="store_true",
        help="不自动启动模拟器；仅连接已运行实例。",
    )
    parser.add_argument(
        "--no-launch-app",
        action="store_true",
        help="不重新拉起游戏 App；适合你已手动停在安全教育页面时使用。",
    )
    parser.add_argument(
        "--idle-sleep-seconds",
        type=float,
        default=1.0,
        help="course 模式每轮动作后的等待秒数。默认 1。",
    )
    parser.add_argument(
        "--lab-pages",
        type=int,
        default=100,
        help="lab 模式最多翻页数量。默认 100。",
    )
    parser.add_argument(
        "--lab-items-per-page",
        type=int,
        default=5,
        help="lab 模式每页点击条目数量。默认 5。",
    )
    parser.add_argument(
        "--study-minutes",
        type=int,
        default=2,
        help="lab 模式每个条目的学习分钟数。默认 2。",
    )
    parser.add_argument(
        "--study-seconds",
        type=int,
        default=1,
        help="lab 模式每个条目的额外学习秒数。默认 1。",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    initialize_autoscriptor_runtime(
        launch_app=not args.no_launch_app,
        start_emulator=not args.no_start_emulator,
    )

    if args.mode == "lab":
        run_lab_mode(
            pages=args.lab_pages,
            items_per_page=args.lab_items_per_page,
            study_minutes=args.study_minutes,
            study_seconds=args.study_seconds,
        )
        return 0

    run_course_mode_forever(idle_sleep_seconds=args.idle_sleep_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
