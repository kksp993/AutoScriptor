"""模拟器系统弹窗的防护。

MuMu 在应用启动失败时会弹一个「App 启动失败 / App 启动超时」的**模态**框。模态的意思是
不点掉它，屏幕上所有点击都到不了游戏——任务的表现是「页面一直不变」，然后在几十秒后
超时，报错还指向各自的第一步。2026-10-02 有一轮 52 个任务因为这个框连续失败。

抓过的真实事故：登录状态机重跑同一个 handler 直到步数耗尽（`超过最大步数`），
`locate_region` 重试到 `无法找到当前位置`，两个报错都没提到底下压着一个弹窗。

测试分四层：

* 锚点契约——锚点必须是弹窗独有的字串，不能是随处可见的「确定」，否则会误点正常弹窗；
* 真实识别——在**按实机坐标合成**的帧上跑真 OCR，验证能认出弹窗、且点击落在按钮上；
* 单次 OCR——所有锚点共用搜索区，只允许 OCR 跑一遍（分开查实测慢一倍）；
* 接线——两条恢复路径（`try_close_via_x`、`PageRouter`）确实会去关它。

合成帧里各元素的坐标来自 2026-10-02 实机截图，**不是从被测公式推出来的**，
所以「点击是否命中」这一条不构成循环论证。
"""

import contextlib
import importlib
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import AutoScriptor.core.api as core_api
from AutoScriptor.core.box import Box
from AutoScriptor.core.control import locate_on_screen

nav_api = importlib.import_module("ZmxyOL.nav.api")
login_module = importlib.import_module("ZmxyOL.nav.envs.login")

# 实机截图（1280x720）的 OCR 输出，本测试的期望值来源：
#   y=291 x=497 w=140 h=25  App启动失败
#   y=341 x=468 w=300 h=29  App启动超时，请稍后再试。
#   y=405 x=624 w=32  h=19  确定
DIALOG_TITLE_TEXT = "App启动失败"
DIALOG_BODY_TEXT = "App启动超时，请稍后再试。"
REAL_BUTTON_BOX = Box(624, 405, 32, 19)
FRAME_SIZE = (1280, 720)

_CJK_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
)


def _load_cjk_font(size):
    from PIL import ImageFont

    for font_path in _CJK_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(font_path, size)
        except OSError:
            continue
    return None


def _render_dialog_frame():
    """按实机坐标画一张带弹窗的帧；环境里没有中文字体时返回 None。"""
    from PIL import Image, ImageDraw

    body_font = _load_cjk_font(26)
    button_font = _load_cjk_font(19)
    if body_font is None or button_font is None:
        return None

    image = Image.new("RGB", FRAME_SIZE, (18, 18, 24))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((450, 265, 830, 500), radius=14, fill=(250, 250, 252))
    draw.rounded_rectangle(
        (REAL_BUTTON_BOX.left, REAL_BUTTON_BOX.top,
         REAL_BUTTON_BOX.left + REAL_BUTTON_BOX.width,
         REAL_BUTTON_BOX.top + REAL_BUTTON_BOX.height),
        radius=4, fill=(0, 170, 120),
    )
    draw.text((497, 292), DIALOG_TITLE_TEXT, font=body_font, fill=(40, 40, 46))
    draw.text((468, 341), DIALOG_BODY_TEXT, font=body_font, fill=(90, 90, 100))
    draw.text((632, 404), "确定", font=button_font, fill=(255, 255, 255))
    return np.array(image)[:, :, ::-1].copy()   # PIL 是 RGB，识别要 BGR


def _render_empty_frame():
    return np.full((FRAME_SIZE[1], FRAME_SIZE[0], 3), 40, dtype=np.uint8)


class OcrOnlyEmulator:
    """只做识别、不连设备的 mixctrl 替身：OCR 真实跑在注入的帧上。"""

    def __init__(self, frame):
        self._frame = frame

    def screenshot(self):
        return self._frame

    def locate(self, tgt_triples, confidence=0.8, screenshot=None):
        sources, pf_boxes, colors = zip(*tgt_triples)
        return locate_on_screen(
            self._frame if screenshot is None else screenshot,
            sources, confidence, pf_boxes, colors,
        )


@contextlib.contextmanager
def emulator_showing(frame):
    with patch.object(core_api, "mixctrl", OcrOnlyEmulator(frame)):
        yield


@contextlib.contextmanager
def captured_click():
    """接住 dismiss_system_dialogs 发出的点击，拿到裸 Box 而不是包装过的目标。"""
    clicked_boxes = []
    with patch.object(nav_api, "click", lambda *a, **kw: None), \
            patch.object(nav_api, "B", lambda *args: clicked_boxes.append(args) or "stub"), \
            patch.object(nav_api, "sleep", lambda *a, **kw: None):
        yield clicked_boxes


class SystemDialogAnchorContractTest(unittest.TestCase):
    """锚点必须能唯一定位到弹窗，否则宁可不防护也不能误点。"""

    # 游戏里到处都是这些字，拿它们当锚点会去点正常的确认弹窗。
    FORBIDDEN_ANCHORS = frozenset({
        "确定", "确认", "取消", "关闭", "是", "否", "返回", "继续", "退出",
    })

    def test_anchors_exist_and_are_specific(self):
        self.assertTrue(nav_api._SYSTEM_DIALOG_ANCHORS, "没有锚点，防护就是空的")
        for anchor in nav_api._SYSTEM_DIALOG_ANCHORS:
            self.assertNotIn(
                anchor, self.FORBIDDEN_ANCHORS,
                f"锚点「{anchor}」在游戏里随处可见，会误点正常弹窗",
            )
            self.assertGreaterEqual(len(anchor), 4, f"锚点「{anchor}」太短，容易误匹配")

    def test_button_offset_points_below_the_anchor(self):
        self.assertGreater(nav_api._SYSTEM_DIALOG_BUTTON_GAP, 0, "按钮必须在锚点文字下方")
        button_width, button_height = nav_api._SYSTEM_DIALOG_BUTTON_SIZE
        self.assertGreaterEqual(button_width, REAL_BUTTON_BOX.width)
        self.assertGreaterEqual(button_height, REAL_BUTTON_BOX.height)


class SystemDialogRecognitionTest(unittest.TestCase):
    """在合成帧上跑真 OCR：认得出，且点得中。"""

    @classmethod
    def setUpClass(cls):
        cls.dialog_frame = _render_dialog_frame()
        if cls.dialog_frame is None:
            raise unittest.SkipTest("环境里没有中文字体，无法合成弹窗帧")

    def test_dialog_is_detected_and_button_is_clicked(self):
        with emulator_showing(self.dialog_frame), captured_click() as clicked_boxes:
            dismissed = nav_api.dismiss_system_dialogs()

        self.assertTrue(dismissed, "带弹窗的帧没有被识别出来")
        self.assertEqual(len(clicked_boxes), 1, f"应当只点一次，实际 {len(clicked_boxes)} 次")
        click_x, click_y, click_w, click_h = clicked_boxes[0]

        button_center_x = REAL_BUTTON_BOX.left + REAL_BUTTON_BOX.width / 2
        button_center_y = REAL_BUTTON_BOX.top + REAL_BUTTON_BOX.height / 2
        self.assertTrue(
            click_x <= button_center_x <= click_x + click_w,
            f"横向没盖住按钮：点击框 x={click_x}..{click_x + click_w}，按钮中心 x={button_center_x}",
        )
        self.assertTrue(
            click_y <= button_center_y <= click_y + click_h,
            f"纵向没盖住按钮：点击框 y={click_y}..{click_y + click_h}，按钮中心 y={button_center_y}",
        )

    def test_click_targets_dialog_centre_axis(self):
        """MuMu 的框居中弹出，按钮也在中轴线上——这条是上面那次的几何理由。"""
        with emulator_showing(self.dialog_frame), captured_click() as clicked_boxes:
            nav_api.dismiss_system_dialogs()

        click_x, _, click_w, _ = clicked_boxes[0]
        self.assertAlmostEqual(
            click_x + click_w / 2, FRAME_SIZE[0] / 2, delta=2,
            msg="点击框应当落在屏幕中轴线上",
        )

    def test_plain_screen_is_left_alone(self):
        """没有弹窗时不能乱点：宁可不防护，也不能往游戏里乱插手。"""
        with emulator_showing(_render_empty_frame()), captured_click() as clicked_boxes:
            dismissed = nav_api.dismiss_system_dialogs()

        self.assertFalse(dismissed)
        self.assertEqual(clicked_boxes, [], "屏幕上没有弹窗，却发出了点击")


class SystemDialogSingleOcrPassTest(unittest.TestCase):
    """所有锚点共用搜索区，只允许 OCR 跑一遍。"""

    @classmethod
    def setUpClass(cls):
        cls.dialog_frame = _render_dialog_frame()
        if cls.dialog_frame is None:
            raise unittest.SkipTest("环境里没有中文字体，无法合成弹窗帧")

    def test_anchors_cost_one_ocr_pass(self):
        ocr_rec = importlib.import_module("AutoScriptor.recognition.ocr_rec")
        real_ocr = ocr_rec.ocr
        passes = []

        def counting_ocr(*args, **kwargs):
            passes.append(1)
            return real_ocr(*args, **kwargs)

        with emulator_showing(self.dialog_frame), \
                patch.object(ocr_rec, "ocr", counting_ocr), \
                captured_click():
            nav_api.dismiss_system_dialogs()

        self.assertEqual(
            len(passes), 1,
            f"{len(nav_api._SYSTEM_DIALOG_ANCHORS)} 个锚点跑了 {len(passes)} 遍 OCR；"
            "锚点必须共用同一个搜索区才会合并成一遍",
        )


class SystemDialogRealFrameFalsePositiveTest(unittest.TestCase):
    """拿归档的真机截图验误报：认错就会往游戏里乱点，比不防护更糟。

    归档在 `logs/` 下（不进版本库），没有归档时跳过。

    `logs/` 会随真实运行一直堆积（2026-10-12 本机已有 10133 张），一次全读进内存
    约 28GB，会把测试进程压成 OOM、整个套件拿不到汇总。所以只取最近的一批，并且
    一张一张解码，样本仍然全部来自真机截图。
    """

    MAX_ARCHIVED_FRAMES = 24

    def _archived_frames(self):
        """逐张产出归档截图；用生成器避免把整批图像同时留在内存里。"""
        import cv2

        archive_root = Path(__file__).resolve().parents[1] / "logs"
        candidates = sorted(
            archive_root.glob("**/debug_screenshots/*.png"),
            key=lambda path: (path.stat().st_mtime, str(path)),
            reverse=True,
        )[: self.MAX_ARCHIVED_FRAMES]
        for path in candidates:
            image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
            if image is not None and image.shape[:2] == (FRAME_SIZE[1], FRAME_SIZE[0]):
                yield path, image

    def test_real_screens_are_not_mistaken_for_dialogs(self):
        misdetected = []
        checked = 0
        for path, image in self._archived_frames():
            checked += 1
            with emulator_showing(image), captured_click() as clicked_boxes:
                if nav_api.dismiss_system_dialogs():
                    misdetected.append(path.name)
            if clicked_boxes:
                misdetected.append(f"{path.name}（还发出了点击）")

        if checked == 0:
            raise unittest.SkipTest("logs/ 下没有归档的真机截图")

        self.assertEqual(
            misdetected, [],
            f"{checked} 张真机截图里有 {len(misdetected)} 张被误判成弹窗",
        )


class TryCloseViaXIntegrationTest(unittest.TestCase):
    """`try_close_via_x` 是 locate_region 的恢复路径，必须最先处理模态框。"""

    def test_dialog_is_checked_before_close_targets(self):
        order = []
        remaining = [True]                      # 第一次说「关掉了一个」，之后说「没有了」

        def fake_dismiss():
            order.append("dismiss")
            if remaining:
                remaining.pop()
                return True
            return False

        def fake_ui_idx(_targets):
            order.append("close_targets")
            return -1

        with patch.object(nav_api, "dismiss_system_dialogs", fake_dismiss), \
                patch.object(nav_api, "ui_idx", fake_ui_idx), \
                patch.object(nav_api, "ui_T", lambda *a, **kw: False), \
                patch.object(nav_api, "click", lambda *a, **kw: None), \
                patch.object(nav_api, "sleep", lambda *a, **kw: None):
            nav_api.try_close_via_x()

        first_dismiss = order.index("dismiss")
        first_targets = order.index("close_targets")
        self.assertLess(
            first_dismiss, first_targets,
            "模态框必须先处理：它挡着底下所有控件，先点别的都是白点",
        )
        self.assertEqual(order.count("dismiss"), 2, "关掉之后应当再确认一次")


class PageRouterStuckRecoveryTest(unittest.TestCase):
    """登录状态机反复停在同一页时，要去关可能压着的模态框。"""

    class TrackedCtx:
        """够 PageRouter 用的最小上下文。"""

        def __init__(self):
            self.prev_state = None
            self.handler_calls = 0

        def login_client(self):
            return login_module.LoginClient.H4399

    def _build_router(self):
        router = login_module.PageRouter()

        @router.page("卡住的页", login_module.T("已阅读并同意"),
                     clients=login_module.LoginClient.H4399)
        def _handler(ctx):
            ctx.handler_calls += 1

        return router

    def _run(self, ctx, max_steps, detect=None):
        """跑到 handler 调用次数够 max_steps 就收工，避免撞上「超过最大步数」。"""
        router = self._build_router()
        dismiss_calls = []
        with patch.object(login_module, "locate", lambda *a, **kw: [Box(1, 1, 2, 2)]), \
                patch.object(nav_api, "dismiss_system_dialogs",
                             lambda: dismiss_calls.append(1) or False):
            patches = [patch.object(router, "detect", detect)] if detect else []
            with contextlib.ExitStack() as stack:
                for active_patch in patches:
                    stack.enter_context(active_patch)
                router.run(
                    ctx, initial_timeout=0, step_timeout=0, max_steps=max_steps,
                    is_done=lambda c: c.handler_calls >= max_steps,
                )
        return ctx, dismiss_calls

    def test_repeated_state_triggers_dialog_check(self):
        ctx, dismiss_calls = self._run(self.TrackedCtx(), max_steps=6)
        self.assertEqual(ctx.handler_calls, 6, "handler 应当每轮都跑")
        # 页面从第 3 轮起连续重复，所以第 3、6 轮各查一次。
        self.assertEqual(
            len(dismiss_calls), 2,
            f"连续卡住却没有去关模态框（查了 {len(dismiss_calls)} 次）",
        )

    def test_single_pass_does_not_pay_for_a_check(self):
        """页面正常推进时不该付这次 OCR 的钱。"""
        states = iter([("A", None), ("B", None), ("C", None)])

        def fake_detect(_boxes, prev_state=None, pages=None):
            return (next(states), self._build_router()._pages[0][3])

        _, dismiss_calls = self._run(self.TrackedCtx(), max_steps=3, detect=fake_detect)
        self.assertEqual(dismiss_calls, [], "页面每轮都在变，不该去查弹窗")


if __name__ == "__main__":
    unittest.main()
