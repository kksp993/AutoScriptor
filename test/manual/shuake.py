"""按当前课程目录的前端完成标记选课、观看、续播，直到指定范围全部完成。

绿色标记才表示页面已确认完成，蓝色只表示选中。播放结束弹窗经正常点击刷新后，
重新检查绿色标记；不直接上报完成、不跳时间、不修改倍速，也不跨课程报名。
"""
import json
import logging
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from urllib.parse import parse_qs, urljoin, urlsplit

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


from test.manual.dom_parser import DomParser, MediaState, connect_android_dom

logger = logging.getLogger("AutoScriptor.shuake")


@dataclass(frozen=True)
class Lesson:
    index: int
    title: str
    href: str
    selected: bool
    completed: bool


def read_lessons(dom: DomParser) -> tuple[Lesson, ...]:
    """任务专用的一次 DOM 读取：目录顺序、链接身份、选中与绿色完成标记。"""
    rows = dom.element(".vlist").evaluate("""container =>
        Array.from(container.querySelectorAll('.vitem'), (element, index) => ({
            index, title: element.querySelector('.vt')?.textContent.trim(),
            href: element.closest('a')?.getAttribute('href'),
            selected: element.classList.contains('active'),
            completed: !!element.querySelector('.chapter-icon-green')
        }))
    """, timeout=10000)
    if not rows or any(not row.get("title") or not row.get("href") for row in rows):
        raise RuntimeError("课程目录为空或标题/链接缺失，不能判断完成")
    lessons = tuple(Lesson(**row) for row in rows)
    if sum(lesson.selected for lesson in lessons) != 1 or len({lesson.href for lesson in lessons}) != len(lessons):
        raise RuntimeError("目录选中项或课程链接不唯一，停止猜测")
    page_url = urlsplit(dom.page.url)
    course_id = parse_qs(page_url.query).get("v_id")
    for lesson in lessons:
        target_url = urlsplit(urljoin(dom.page.url, lesson.href))
        parameters = parse_qs(target_url.query)
        if (target_url.netloc != page_url.netloc or target_url.scheme != page_url.scheme
                or target_url.path != "/fzdx/play" or not course_id
                or parameters.get("v_id") != course_id or len(parameters.get("r_id", [])) != 1):
            raise RuntimeError("目录链接不属于当前课程播放页，停止自动选择")
    return lessons


def progress(dom: DomParser) -> tuple[float, float | None]:
    """返回已播秒、总长秒；元数据未就绪或直播的总长为 None，无需悬停。"""
    state = dom.read_media()
    return state.current_time, state.duration


class PlaybackMonitor:
    """连续 30 秒无进展则暂停后续播，最多两次；不跳进度、不刷新页面。"""

    def __init__(self, dom: DomParser):
        self.dom = dom
        self.previous: MediaState | None = None
        self.last_progress_at = monotonic()
        self.recovery_attempts = 0

    def check(self, state: MediaState | None = None) -> MediaState:
        state = self.dom.read_media() if state is None else state
        checked_at = monotonic()
        if state.error_code is not None:
            raise RuntimeError(f"播放器错误 code={state.error_code}，请检查网络或媒体文件")
        source_changed = self.previous is None or state.source != self.previous.source
        position_changed = self.previous is not None and state.current_time != self.previous.current_time
        if source_changed or position_changed or state.ended:
            self.last_progress_at, self.recovery_attempts = checked_at, 0
        elif checked_at - self.last_progress_at >= 30:
            if self.recovery_attempts >= 2:
                raise RuntimeError(
                    f"播放仍无进展：time={state.current_time}, paused={state.paused}, "
                    f"readyState={state.ready_state}, networkState={state.network_state}"
                )
            self.recovery_attempts += 1
            logger.warning("播放无进展，尝试暂停后续播（%s/2）", self.recovery_attempts)
            self.dom.pause_media()
            self.dom.play_media()
            self.last_progress_at = monotonic()
        self.previous = state
        return state


def handle_player_dialog(dom: DomParser, *, allow_continue: bool = True) -> str | None:
    """只处理已核实的完成、断点续播、周期继续弹窗；未知弹窗停下报错。"""
    completion = dom.element(".layui-layer-dialog:visible")
    if completion.count():
        if completion.locator(".layui-layer-content").inner_text().strip() != "当前视频播放完毕！":
            raise RuntimeError("遇到未识别的页面弹窗，请人工检查")
        logger.info("收到播放完毕提示，确认并等待页面刷新")
        with dom.page.expect_navigation(wait_until="domcontentloaded", timeout=10000):
            completion.locator(".layui-layer-btn0").click(timeout=5000)
        return "completed"

    # 该站播放器的弹窗没有 class：直接挂到 body 下，卡片含标题、正文、按钮行。
    continuation = dom.element("body > div:has(> div > div > button):visible")
    if continuation.count():
        if continuation.count() != 1:
            raise RuntimeError("播放器弹窗不唯一，停止自动确认")
        if not allow_continue:
            raise RuntimeError("等待完成标记时出现续播弹窗，请检查状态")
        message = continuation.locator(":scope > div > div").nth(1).inner_text(timeout=5000).strip()
        if message == "视频已暂停，点击按钮后继续学习！":
            button_text = "继续"
        elif re.fullmatch(r"该视频已播放至 \d+(?::\d{2}){1,2}", message):
            button_text = "继续播放"
        else:
            raise RuntimeError("遇到未识别的播放器弹窗，请人工检查")
        logger.info("播放器提示：%s；点击%s", message, button_text)
        continuation.get_by_role("button", name=button_text, exact=True).click(timeout=5000)
        continuation.wait_for(state="hidden", timeout=5000)
        return "continued"
    return None


def select_lesson(dom: DomParser, lesson: Lesson) -> None:
    """按唯一链接点击，自动滚入视野，等导航完成后验证选中的是目标课程。"""
    logger.info("选择第 %s 项：%s", lesson.index + 1, lesson.title)
    with dom.page.expect_navigation(wait_until="domcontentloaded", timeout=10000):
        dom.element(f".vlist a[href={json.dumps(lesson.href)}]").click(timeout=5000)
    selected = next(item for item in read_lessons(dom) if item.selected)
    if selected.href != lesson.href:
        raise RuntimeError("点击后选中项与目标不符，停止播放")


def wait_for_completion(dom: DomParser, lesson: Lesson, *, wait: Callable[[float], None]) -> None:
    """结束/上报提示之后只等前端确认，不重播；30 秒无绿色标记则失败。"""
    deadline = monotonic() + 30
    while True:
        current = next(item for item in read_lessons(dom) if item.selected)
        if current.href != lesson.href:
            raise RuntimeError("等待完成时当前课程改变，停止确认")
        if current.completed:
            logger.info("前端已确认完成：%s", current.title)
            return
        if monotonic() >= deadline:
            raise RuntimeError(f"{lesson.title}：视频结束后未出现前端完成标记，不切换下一项")
        if handle_player_dialog(dom, allow_continue=False) == "completed":
            continue
        wait(2)


def watch_lesson(dom: DomParser, lesson: Lesson, *, wait: Callable[[float], None]) -> None:
    """正常播放 -> 自动继续 -> 监测进度/卡顿 -> 等待前端确认完成。"""
    logger.info("观看第 %s 项：%s", lesson.index + 1, lesson.title)
    playback = PlaybackMonitor(dom)
    start_requested = False
    next_progress_log = monotonic()
    while True:
        current = next(item for item in read_lessons(dom) if item.selected)
        if current.href != lesson.href:
            raise RuntimeError("观看过程中选中项改变，停止自动播放")
        if current.completed:
            logger.info("前端已确认完成：%s", current.title)
            return
        dialog_action = handle_player_dialog(dom)
        if dialog_action == "completed":
            wait_for_completion(dom, lesson, wait=wait)
            return
        state = dom.read_media()
        if state.ended:
            wait_for_completion(dom, lesson, wait=wait)
            return
        playback.check(state)
        if not state.paused or dialog_action == "continued":
            start_requested = True
        elif not start_requested and state.ready_state >= 2:
            logger.info("开始播放：%s", lesson.title)
            dom.play_media()
            start_requested = True
        if monotonic() >= next_progress_log:
            logger.info("观看进度：%s，%.1f / %s 秒", lesson.title, state.current_time, state.duration)
            next_progress_log = monotonic() + 30
        wait(2)


def watch_course(dom: DomParser, start_index: int = 1, *, wait: Callable[[float], None]) -> None:
    """优先看完当前未完成项，再按目录补齐；start_index 是从 1 起算的范围下限。"""
    lessons = read_lessons(dom)
    if isinstance(start_index, bool) or not isinstance(start_index, int) or not 1 <= start_index <= len(lessons):
        raise ValueError(f"start_index 必须在 1..{len(lessons)} 内")
    directory_links = tuple(lesson.href for lesson in lessons)
    while True:
        lessons = read_lessons(dom)
        if tuple(lesson.href for lesson in lessons) != directory_links:
            raise RuntimeError("课程目录发生变化，请重新确认观看范围")
        pending = [lesson for lesson in lessons[start_index - 1:] if not lesson.completed]
        if not pending:
            logger.info("当前目录第 %s 至 %s 项的前端完成标记已全部确认", start_index, len(lessons))
            return
        current = next(lesson for lesson in lessons if lesson.selected)
        following = current if current in pending else pending[0]
        if following.href != current.href:
            if handle_player_dialog(dom) == "completed":
                wait_for_completion(dom, current, wait=wait)
                continue
            select_lesson(dom, following)
        watch_lesson(dom, following, wait=wait)


def task(start_index: int = 1):
    from AutoScriptor import cfg, init, sleep

    init(emulator_index=2)
    with connect_android_dom(adb_path=cfg["emulator"]["adb_path"], serial="127.0.0.1:16448", url_pattern="*/fzdx/play*") as dom:
        watch_course(dom, start_index, wait=sleep)


if __name__ == "__main__":
    task(1)
