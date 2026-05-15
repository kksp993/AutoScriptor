from __future__ import annotations

import importlib.util
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Cancelled(Exception):
    pass


def logger_stub():
    return SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )


def import_power_for_test():
    autoscriptor = types.ModuleType("AutoScriptor")
    utils_pkg = types.ModuleType("AutoScriptor.utils")
    cancel = types.ModuleType("AutoScriptor.utils.cancel")
    cancel.TaskCancelled = Cancelled
    cancel.check_cancel_raise = lambda: None
    cancel.sleep_with_cancel = lambda seconds, cancel_check=None, chunk=0.05: (
        cancel_check() if cancel_check else None
    )
    logger = types.ModuleType("AutoScriptor.utils.logger")
    logger.logger = logger_stub()
    module_name = "mumu_power_under_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "AutoScriptor/control/MumuAdaptor/api/core/power.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "AutoScriptor": autoscriptor,
        "AutoScriptor.utils": utils_pkg,
        "AutoScriptor.utils.cancel": cancel,
        "AutoScriptor.utils.logger": logger,
    }):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


def import_cancel_for_test():
    module_name = "cancel_under_test"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "AutoScriptor/utils/cancel.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def import_api_for_test():
    module_name = "core_api_lifecycle_under_test"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "AutoScriptor/core/api.py")
    module = importlib.util.module_from_spec(spec)

    modules: dict[str, types.ModuleType] = {}

    def mod(name: str) -> types.ModuleType:
        m = types.ModuleType(name)
        modules[name] = m
        return m

    autoscriptor = mod("AutoScriptor")
    autoscriptor.__path__ = [str(ROOT / "AutoScriptor")]
    cv2_stub = mod("cv2")
    utils_pkg = mod("AutoScriptor.utils")
    utils_pkg.__path__ = [str(ROOT / "AutoScriptor" / "utils")]
    control = mod("AutoScriptor.control")
    mumu_adaptor = mod("AutoScriptor.control.MumuAdaptor")
    constant = mod("AutoScriptor.control.MumuAdaptor.constant")
    constant.AndroidKey = SimpleNamespace()
    control_mod = mod("AutoScriptor.core.control")
    targets = mod("AutoScriptor.core.targets")
    locate_dispatch = mod("AutoScriptor.core.locate_dispatch")
    ocr_rec = mod("AutoScriptor.recognition.ocr_rec")
    rec = mod("AutoScriptor.recognition.rec")
    box = mod("AutoScriptor.utils.box")
    logger = mod("AutoScriptor.utils.logger")
    app_config = mod("AutoScriptor.utils.app_config")
    app_resolve = mod("AutoScriptor.utils.app_package_resolve")
    mumu_mod = mod("AutoScriptor.control.MumuAdaptor.mumu")
    edit_img = mod("AutoScriptor.utils.edit_img")
    cancel = mod("AutoScriptor.utils.cancel")
    tracer = mod("AutoScriptor.utils.tracer")
    perf = mod("AutoScriptor.utils.perf")

    class Target:
        pass

    class Box:
        pass

    class FakeMixControl:
        def __init__(self, mumu, serial=None):
            self.mumu = mumu
            self.serial = serial
            self.window = SimpleNamespace(hidden=lambda: None)

        def click(self, x, y):
            return None

    class FakePower:
        def __init__(self):
            self.running = False
            self.started = False

        def is_running(self):
            return self.running

        def start(self, package=None, max_retries=2, cancel_check=None):
            if cancel_check:
                cancel_check()
            self.started = True
            self.running = True
            return True

    class FakeApp:
        def __init__(self):
            self.launched = []

        def launch(self, package):
            self.launched.append(package)
            return True

    class FakeMumu:
        selected: FakeMumu | None = None

        def __init__(self):
            self.power = FakePower()
            self.app = FakeApp()
            FakeMumu.selected = self

        def select(self, index):
            self.index = index
            return self

    targets.Target = Target
    targets.B = lambda *args, **kwargs: ("B", args, kwargs)
    targets.ImageTarget = type("ImageTarget", (Target,), {})
    targets.TextTarget = type("TextTarget", (Target,), {})
    targets.BoxTarget = type("BoxTarget", (Target,), {"box": None})
    targets.VLMTarget = type("VLMTarget", (Target,), {})
    control_mod.MixControl = FakeMixControl
    locate_dispatch.has_handler = lambda typ: False
    locate_dispatch.dispatch_locate = lambda target, frame: None
    ocr_rec.ocr_for_box = lambda *args, **kwargs: None
    rec.get_box_color = lambda *args, **kwargs: None
    box.Box = Box
    box.b2p = lambda *args, **kwargs: (0, 0)
    logger.logger = logger_stub()
    logger.setup_task_aware_logging = lambda: None
    logger.setup_logfile = lambda *args, **kwargs: None
    tracer.save_debug_screenshot = lambda *args, **kwargs: None
    app_config.cfg = {
        "emulator": {"emu_path": "mumu.exe", "index": 2, "adb_addr": "addr"},
        "app": {
            "app_to_start": "pkg",
            "auto_start": False,
            "run_in_background": False,
        },
    }
    app_resolve.resolve_app_to_start = lambda mumu, cancel_check=None: "resolved.pkg"
    mumu_mod.Mumu = FakeMumu
    edit_img.launch_editor = lambda *args, **kwargs: None
    cancel.check_cancel_raise = lambda: None
    cancel.cancellable_sleep = lambda seconds, chunk=0.05: None

    def join_with_cancel(thread, timeout, cancel_check=None, chunk=0.1):
        if cancel_check:
            cancel_check()
        thread.join(min(timeout, chunk))
        if cancel_check:
            cancel_check()

    cancel.join_with_cancel = join_with_cancel
    cancel.sleep_with_cancel = lambda seconds, cancel_check=None, chunk=0.05: (
        cancel_check() if cancel_check else None
    )
    perf.unboost = lambda: None
    cv2_stub.__version__ = "test"

    with patch.dict(sys.modules, modules):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    module.FakeMumu = FakeMumu
    module.stub_modules = modules
    return module


class TestMuMuPowerLifecycle(unittest.TestCase):
    def test_start_cancellation_is_not_swallowed_by_retry_loop(self):
        module = import_power_for_test()

        class FakeUtils:
            def get_vm_id(self):
                return "3"

            def set_operate(self, operate):
                self.operate = operate

            def run_command(self, args):
                return 1, "not ready"

        def cancel():
            raise Cancelled()

        with self.assertRaises(Cancelled):
            module.Power(FakeUtils()).start(cancel_check=cancel)


class TestEnsureAppRunningLifecycle(unittest.TestCase):
    def test_execution_start_ignores_legacy_auto_start_false(self):
        module = import_api_for_test()

        with patch.dict(sys.modules, module.stub_modules):
            mixctrl, mumu = module.ensure_app_running(
                2,
                "127.0.0.1:16448",
                "pkg",
                start_emulator=True,
                launch_app=True,
                cancel_check=lambda: None,
            )

        self.assertIs(mumu, module.FakeMumu.selected)
        self.assertTrue(mumu.power.started)
        self.assertEqual(mumu.app.launched, ["resolved.pkg"])
        self.assertEqual(mixctrl.serial, "127.0.0.1:16448")

    def test_join_with_cancel_interrupts_blocked_click_probe(self):
        module = import_cancel_for_test()
        stop = threading.Event()
        thread = threading.Thread(target=lambda: stop.wait(1), daemon=True)
        thread.start()

        def cancel():
            raise Cancelled()

        started = time.monotonic()
        with self.assertRaises(Cancelled):
            module.join_with_cancel(thread, 5, cancel)
        self.assertLess(time.monotonic() - started, 0.5)
        stop.set()


if __name__ == "__main__":
    unittest.main()
