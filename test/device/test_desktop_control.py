"""主机（Windows 桌面）键鼠控制：坐标适配、输入注入、窗口筛选。

这些用例全部离线：不真的移动鼠标、不真的截屏、不拉起 OCR 引擎。钉住的是
「点击适配」的三条硬约束：

* 坐标合同——截图数组下标与鼠标坐标同为「物理像素、虚拟桌面左上角为原点」；
* ROI 适配——``T("文字")`` 自带的模拟器默认 1280x720 区域必须换成本次截图尺寸，
  否则比 1280x720 大的屏幕上，右/下方的控件永远找不到；
* 注入成败——``SendInput`` 被更高权限窗口拦下时必须报错，不能把没生效的点击
  当成成功。
"""

import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from AutoScriptor.control.DesktopControl import _win32
from AutoScriptor.control.DesktopControl import inputs as host_input
from AutoScriptor.control.DesktopControl import windows as host_windows
from AutoScriptor.control.DesktopControl.control import (
    DesktopControl,
    _adapt_preferred_box,
    _clip_box_to_frame,
    _target_parts,
)
from AutoScriptor.core.box import Box


class FakeFunction:
    """模拟 ctypes 函数：允许声明 argtypes/restype，并按名字记录调用与返回值。"""

    def __init__(self, name: str, calls: list[str], result):
        self.name = name
        self.calls = calls
        self.result = result
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(self.name)
        return self.result


class FakeUser32:
    """只实现被测路径用到的 user32 入口，并记录调用。"""

    def __init__(self, *, context_ok: bool = False, legacy_ok: bool = False):
        self.calls: list[str] = []
        # 真实 user32 两个入口都存在（SetProcessDPIAware 是 Win2000+ 的老 API），
        # 所以假对象也总是提供，只用返回值控制走哪条分支。
        self.SetProcessDpiAwarenessContext = FakeFunction(
            "SetProcessDpiAwarenessContext", self.calls, context_ok
        )
        self.SetProcessDPIAware = FakeFunction("SetProcessDPIAware", self.calls, legacy_ok)


class FakeShcore:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def SetProcessDpiAwareness(self, value):
        self.calls.append(value)
        return self.result


class TestDpiAwareness(unittest.TestCase):
    """DPI 感知决定坐标解释方式，必须按版本从新到旧挑第一个能用的。"""

    def _ensure(self, user32, shcore=None):
        with patch.object(_win32, "_dpi_awareness_mode", None), \
                patch.object(_win32, "_USER32", user32), \
                patch.object(_win32, "_SHCORE", shcore), \
                patch.object(_win32, "IS_WINDOWS", True):
            return _win32.ensure_dpi_awareness()

    def test_prefers_per_monitor_v2(self):
        user32 = FakeUser32(context_ok=True)
        shcore = FakeShcore(0)

        mode = self._ensure(user32, shcore)

        self.assertEqual(mode, "per-monitor-v2")
        self.assertEqual(shcore.calls, [], "新接口成功就不该再调旧接口")
        self.assertNotIn("SetProcessDPIAware", user32.calls)

    def test_falls_back_to_per_monitor(self):
        shcore = FakeShcore(0)
        mode = self._ensure(FakeUser32(context_ok=False), shcore)
        self.assertEqual(mode, "per-monitor")
        self.assertEqual(shcore.calls, [2])

    def test_falls_back_to_system_aware(self):
        user32 = FakeUser32(context_ok=False, legacy_ok=True)
        mode = self._ensure(user32, None)
        self.assertEqual(mode, "system")
        self.assertIn("SetProcessDPIAware", user32.calls)

    def test_reports_unchanged_when_already_set_by_someone_else(self):
        """宿主已经设过 DPI 感知时沿用现状，不能报错也不能假装自己设成功。"""
        mode = self._ensure(FakeUser32(context_ok=False), FakeShcore(-2147024891))
        self.assertEqual(mode, "unchanged")


class TestClickAdaptation(unittest.TestCase):
    """点击适配：区域裁剪与默认 ROI 重映射。"""

    def test_default_emulator_roi_is_replaced_by_real_frame_size(self):
        preferred = Box(0, 0, 1280, 720)

        adapted = _adapt_preferred_box(preferred, (2560, 1440))

        self.assertEqual(adapted, Box(0, 0, 2560, 1440))

    def test_explicit_roi_is_kept_and_clipped(self):
        adapted = _adapt_preferred_box(Box(2400, 1300, 400, 400), (2560, 1440))

        self.assertEqual(adapted, Box(2400, 1300, 160, 140))

    def test_roi_fully_outside_the_frame_fails_loudly(self):
        with self.assertRaises(ValueError):
            _clip_box_to_frame(Box(3000, 100, 50, 50), (2560, 1440))
        with self.assertRaises(ValueError):
            _clip_box_to_frame(Box(10, 10, 0, 0), (2560, 1440))

    def test_text_target_uses_full_screen_roi(self):
        """T("文字") 的默认区域是模拟器帧，定位时必须换成主机屏幕。"""
        # 直接用 TextTarget：``T()`` 会连带导入 ui_map（要读 assets/config/ui_map.csv），
        # 离线单测没有那份资产，但目标的默认区域完全一样。
        from AutoScriptor.core.targets import TextTarget, ui_str

        source, preferred, color = _target_parts(TextTarget(ui_str("终止执行")), (2560, 1440))

        self.assertEqual(source, "终止执行")
        self.assertEqual(preferred, Box(0, 0, 2560, 1440))
        self.assertIsNone(color)

    def test_unknown_target_type_fails_loudly(self):
        with self.assertRaises(TypeError):
            _target_parts(object(), (2560, 1440))


class TestLocateOnHostScreen(unittest.TestCase):
    def _desktop(self):
        desktop = DesktopControl.__new__(DesktopControl)
        desktop.default_confidence = 0.8
        desktop.dpi_awareness = "per-monitor-v2"
        return desktop

    def test_locate_passes_full_frame_roi_and_returns_box(self):
        desktop = self._desktop()
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        hit = Box(100, 200, 80, 30)
        captured = {}

        def fake_locate(haystack, targets, confidence, pf_boxes, colors):
            captured.update(
                frame_shape=haystack.shape,
                targets=list(targets),
                confidence=confidence,
                pf_boxes=list(pf_boxes),
            )
            return [[hit]]

        with patch("AutoScriptor.recognition.locate.locate_on_screen", fake_locate):
            found = desktop.locate("终止执行", screenshot=frame)

        self.assertEqual(found, hit)
        self.assertEqual(captured["targets"], ["终止执行"])
        self.assertEqual(captured["pf_boxes"], [Box(0, 0, 2560, 1440)])
        self.assertEqual(captured["confidence"], 0.8)

    def test_locate_returns_none_when_nothing_matches(self):
        desktop = self._desktop()
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)

        with patch("AutoScriptor.recognition.locate.locate_on_screen", lambda *a, **kw: [None]):
            self.assertIsNone(desktop.locate("不存在", screenshot=frame))

    def test_click_text_clicks_the_box_centre(self):
        desktop = self._desktop()
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        hit = Box(1000, 400, 120, 40)
        clicked = []

        with patch.object(desktop, "screenshot", lambda box=None: frame), \
                patch("AutoScriptor.recognition.locate.locate_on_screen", lambda *a, **kw: [[hit]]), \
                patch.object(host_input, "send_inputs") as send_inputs, \
                patch.object(host_input, "move_cursor") as move_cursor, \
                patch.object(host_input, "cursor_position", lambda: (1060, 420)):
            found = desktop.click_text("终止执行", timeout=0.1)

        self.assertEqual(found, hit)
        move_cursor.assert_called_once_with(1060, 420)      # (1000+120/2, 400+40/2)
        self.assertEqual(send_inputs.call_count, 2)         # 按下 + 抬起

    def test_click_text_returns_none_after_timeout(self):
        desktop = self._desktop()
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)

        with patch.object(desktop, "screenshot", lambda box=None: frame), \
                patch("AutoScriptor.recognition.locate.locate_on_screen", lambda *a, **kw: [None]), \
                patch.object(host_input, "send_inputs") as send_inputs:
            found = desktop.click_text("不存在", timeout=0.05, interval=0.01)

        self.assertIsNone(found)
        send_inputs.assert_not_called()


class TestInputInjection(unittest.TestCase):
    """输入注入：内容与成败判断。"""

    def test_send_inputs_reports_blocked_injection(self):
        fake_user32 = MagicMock()
        fake_user32.SendInput.return_value = 0

        with patch.object(_win32, "_USER32", fake_user32), patch.object(_win32, "IS_WINDOWS", True):
            with self.assertRaises(_win32.InputInjectionBlocked) as caught:
                _win32.send_inputs([_win32.mouse_event_input(_win32.MOUSEEVENTF_LEFTDOWN)])

        self.assertIn("管理员", str(caught.exception))

    def test_type_text_uses_unicode_code_units(self):
        sent = []
        with patch.object(host_input, "send_inputs", side_effect=lambda items: sent.extend(items)):
            typed = host_input.type_text("中a", interval_s=0)

        self.assertEqual(typed, 2)
        # 每个字符一对 down/up；中文走 KEYEVENTF_UNICODE，扫描码就是 UTF-16 码元。
        self.assertEqual(len(sent), 4)
        self.assertEqual(sent[0].ki.wScan, ord("中"))
        self.assertEqual(sent[0].ki.dwFlags, _win32.KEYEVENTF_UNICODE)
        self.assertEqual(sent[1].ki.dwFlags, _win32.KEYEVENTF_UNICODE | _win32.KEYEVENTF_KEYUP)
        self.assertEqual(sent[2].ki.wScan, ord("a"))

    def test_hotkey_presses_modifiers_first_and_releases_them_last(self):
        sent = []
        with patch.object(host_input, "send_inputs", side_effect=lambda items: sent.extend(items)):
            host_input.hotkey("ctrl", "l", gap_s=0)

        sequence = [(item.ki.wVk, bool(item.ki.dwFlags & _win32.KEYEVENTF_KEYUP)) for item in sent]
        self.assertEqual(
            sequence,
            [
                (_win32.VK_NAMES["ctrl"], False),
                (_win32.resolve_vk("l"), False),
                (_win32.resolve_vk("l"), True),
                (_win32.VK_NAMES["ctrl"], True),
            ],
        )

    def test_resolve_vk_accepts_names_and_single_characters(self):
        self.assertEqual(_win32.resolve_vk("enter"), 0x0D)
        self.assertEqual(_win32.resolve_vk("F5"), _win32.VK_NAMES["f5"])
        self.assertEqual(_win32.resolve_vk("a"), ord("A"))
        self.assertEqual(_win32.resolve_vk(0x41), 0x41)
        with self.assertRaises(ValueError):
            _win32.resolve_vk("不是键名")

    def test_drag_releases_button_even_when_moving_fails(self):
        released = []
        with patch.object(host_input, "move_to", side_effect=[None, OSError("boom")]), \
                patch.object(host_input, "mouse_down", lambda button="left": released.append("down")), \
                patch.object(host_input, "mouse_up", lambda button="left": released.append("up")), \
                patch.object(host_input, "time", MagicMock()):
            with self.assertRaises(OSError):
                host_input.drag((0, 0), (100, 100), duration_s=0)

        self.assertEqual(released, ["down", "up"])

    def test_click_rejects_half_a_coordinate(self):
        with self.assertRaises(ValueError):
            host_input.click(10, None)


class TestWindowFiltering(unittest.TestCase):
    """窗口筛选：按标题/进程名匹配，并过滤掉看不见的窗口。"""

    @contextlib.contextmanager
    def _stub_win32(self, entries):
        """entries: [(handle, title, class, process, visible, cloaked, minimized)]"""
        table = {handle: entry for handle, *entry in entries}

        def rect(handle):
            return (10, 20, 800, 600)

        with patch.object(_win32, "enum_top_level_windows", lambda: list(table)), \
                patch.object(_win32, "window_title", lambda h: table[h][0]), \
                patch.object(_win32, "window_class_name", lambda h: table[h][1]), \
                patch.object(_win32, "window_process_id", lambda h: h), \
                patch.object(_win32, "process_name", lambda pid: table[pid][2]), \
                patch.object(_win32, "is_window_visible", lambda h: table[h][3]), \
                patch.object(_win32, "is_window_cloaked", lambda h: table[h][4]), \
                patch.object(_win32, "is_iconic", lambda h: table[h][5]), \
                patch.object(_win32, "window_rect", rect):
            yield

    def test_cloaked_and_invisible_windows_are_skipped(self):
        entries = [
            (1, "Edge", "Chrome_WidgetWin_1", "msedge.exe", True, False, False),
            (2, "Edge 隐藏", "Chrome_WidgetWin_1", "msedge.exe", True, True, False),
            (3, "不可见", "Chrome_WidgetWin_1", "msedge.exe", False, False, False),
            (4, "", "Chrome_WidgetWin_1", "msedge.exe", True, False, False),
        ]
        with self._stub_win32(entries):
            found = host_windows.list_windows()

        self.assertEqual([info.handle for info in found], [1])

    def test_find_by_process_name_and_title_substring(self):
        entries = [
            (1, "AutoScriptor - Edge", "Chrome_WidgetWin_1", "msedge.exe", True, False, False),
            (2, "普通记事本", "Notepad", "notepad.exe", True, False, False),
        ]
        with self._stub_win32(entries):
            by_process = host_windows.find_windows(process_name="MSEDGE.EXE")
            by_title = host_windows.find_windows(title_contains="autoscriptor")
            none_match = host_windows.find_windows(process_name="msedge.exe", title_contains="记事本")

        self.assertEqual([info.handle for info in by_process], [1])
        self.assertEqual([info.handle for info in by_title], [1])
        self.assertEqual(none_match, [])


class TestScreenCapture(unittest.TestCase):
    def test_capture_converts_to_bgr_and_passes_screen_bbox(self):
        from PIL import Image

        from AutoScriptor.control.DesktopControl import screen as host_screen

        grabbed = {}

        def fake_grab(bbox=None, all_screens=False):
            grabbed["bbox"] = bbox
            grabbed["all_screens"] = all_screens
            return Image.new("RGB", (4, 3), (10, 20, 30))

        with patch.object(host_screen, "ensure_dpi_awareness", lambda: "per-monitor-v2"), \
                patch("PIL.ImageGrab.grab", fake_grab):
            frame = host_screen.capture(Box(-100, -50, 4, 3))

        self.assertEqual(grabbed["bbox"], (-100, -50, -96, -47))
        self.assertTrue(grabbed["all_screens"], "多显示器必须整块抓，否则副屏坐标全错")
        self.assertEqual(frame.shape, (3, 4, 3))
        # RGB(10,20,30) -> BGR(30,20,10)
        self.assertEqual(tuple(frame[0, 0]), (30, 20, 10))

    def test_capture_rejects_empty_region(self):
        from AutoScriptor.control.DesktopControl import screen as host_screen

        with patch.object(host_screen, "ensure_dpi_awareness", lambda: "per-monitor-v2"):
            with self.assertRaises(ValueError):
                host_screen.capture(Box(0, 0, 0, 10))


class TestImportStaysLazy(unittest.TestCase):
    """导入主机控制不能顺带拉起 OCR 引擎（项目一贯的惰性导入约束）。"""

    def test_importing_package_does_not_import_paddle(self):
        import subprocess
        import sys

        project_root = Path(__file__).resolve().parents[2]
        probe = (
            "import sys; sys.path.insert(0, r'%s');"
            "import AutoScriptor.control.DesktopControl as pkg;"
            "assert pkg.DesktopControl is not None;"
            "print('paddleocr' in sys.modules or 'paddle' in sys.modules)"
        ) % project_root
        with tempfile.TemporaryDirectory() as tmp:
            # 子进程必须指向临时数据目录：测试进程的写保护不跨进程，否则子进程会
            # 去读真实 data/（项目规则里的硬要求）。
            environment = {
                **os.environ,
                "AUTOSCRIPTOR_DATA_DIR": tmp,
                "PYTHONIOENCODING": "utf-8",
            }
            result = subprocess.run(
                [str(project_root / ".venv" / "Scripts" / "python.exe"), "-X", "utf8", "-c", probe],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                env=environment,
                cwd=str(project_root),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "False")


if __name__ == "__main__":
    unittest.main()
