from __future__ import annotations

import importlib.util
import sys
import threading
import time
import types
import unittest
import tempfile
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
    control_pkg = types.ModuleType("AutoScriptor.control")
    mumu_pkg = types.ModuleType("AutoScriptor.control.MumuAdaptor")
    api_pkg = types.ModuleType("AutoScriptor.control.MumuAdaptor.api")
    adb_pkg = types.ModuleType("AutoScriptor.control.MumuAdaptor.api.adb")
    direct = types.ModuleType("AutoScriptor.control.MumuAdaptor.api.adb.direct")
    direct.adb_device_ready = lambda: False
    facade = SimpleNamespace(adb_device_ready=lambda: False)
    device_facade = types.ModuleType("AutoScriptor.control.MumuAdaptor.device_facade")
    device_facade.get_device_facade = lambda vm_index=None: facade
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
        "AutoScriptor.control": control_pkg,
        "AutoScriptor.control.MumuAdaptor": mumu_pkg,
        "AutoScriptor.control.MumuAdaptor.api": api_pkg,
        "AutoScriptor.control.MumuAdaptor.api.adb": adb_pkg,
        "AutoScriptor.control.MumuAdaptor.api.adb.direct": direct,
        "AutoScriptor.control.MumuAdaptor.device_facade": device_facade,
        "AutoScriptor.utils.cancel": cancel,
        "AutoScriptor.utils.logger": logger,
    }):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    module.test_facade = facade
    return module


def import_mumu_app_for_test():
    autoscriptor = types.ModuleType("AutoScriptor")
    utils_pkg = types.ModuleType("AutoScriptor.utils")
    control_pkg = types.ModuleType("AutoScriptor.control")
    mumu_pkg = types.ModuleType("AutoScriptor.control.MumuAdaptor")
    api_pkg = types.ModuleType("AutoScriptor.control.MumuAdaptor.api")
    adb_pkg = types.ModuleType("AutoScriptor.control.MumuAdaptor.api.adb")
    direct = types.ModuleType("AutoScriptor.control.MumuAdaptor.api.adb.direct")
    direct.run_adb = lambda args, timeout=10: SimpleNamespace(returncode=1, stdout="", stderr="")
    facade = SimpleNamespace(
        adb_force_stop_app=lambda package: False,
        adb_launch_app=lambda package: False,
        adb_app_state=lambda package: "stopped",
        adb_list_packages=lambda: [],
        adb_app_exists=lambda package: False,
    )
    device_facade = types.ModuleType("AutoScriptor.control.MumuAdaptor.device_facade")
    device_facade.get_device_facade = lambda: facade
    app_config = types.ModuleType("AutoScriptor.utils.app_config")
    app_config.cfg = {"emulator": {"adb_path": "adb", "adb_addr": "addr"}}
    logger = types.ModuleType("AutoScriptor.utils.logger")
    logger.logger = logger_stub()
    module_name = "mumu_app_under_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "AutoScriptor/control/MumuAdaptor/api/core/app.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "AutoScriptor": autoscriptor,
        "AutoScriptor.utils": utils_pkg,
        "AutoScriptor.control": control_pkg,
        "AutoScriptor.control.MumuAdaptor": mumu_pkg,
        "AutoScriptor.control.MumuAdaptor.api": api_pkg,
        "AutoScriptor.control.MumuAdaptor.api.adb": adb_pkg,
        "AutoScriptor.control.MumuAdaptor.api.adb.direct": direct,
        "AutoScriptor.control.MumuAdaptor.device_facade": device_facade,
        "AutoScriptor.utils.app_config": app_config,
        "AutoScriptor.utils.logger": logger,
    }):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    module.test_facade = facade
    return module


def import_mumu_adb_for_test():
    autoscriptor = types.ModuleType("AutoScriptor")
    utils_pkg = types.ModuleType("AutoScriptor.utils")
    control_pkg = types.ModuleType("AutoScriptor.control")
    mumu_pkg = types.ModuleType("AutoScriptor.control.MumuAdaptor")
    api_pkg = types.ModuleType("AutoScriptor.control.MumuAdaptor.api")
    adb_pkg = types.ModuleType("AutoScriptor.control.MumuAdaptor.api.adb")
    direct = types.ModuleType("AutoScriptor.control.MumuAdaptor.api.adb.direct")
    direct.adb_device_ready = lambda: False
    direct.configured_adb_host_port = lambda: None
    direct.run_adb = lambda args, timeout=10: SimpleNamespace(returncode=1, stdout="", stderr="")
    app_config = types.ModuleType("AutoScriptor.utils.app_config")
    app_config.cfg = {"emulator": {"adb_path": "adb", "adb_addr": "127.0.0.1:16416"}}
    module_name = "mumu_adb_under_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "AutoScriptor/control/MumuAdaptor/api/adb/Adb.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "AutoScriptor": autoscriptor,
        "AutoScriptor.utils": utils_pkg,
        "AutoScriptor.control": control_pkg,
        "AutoScriptor.control.MumuAdaptor": mumu_pkg,
        "AutoScriptor.control.MumuAdaptor.api": api_pkg,
        "AutoScriptor.control.MumuAdaptor.api.adb": adb_pkg,
        "AutoScriptor.control.MumuAdaptor.api.adb.direct": direct,
        "AutoScriptor.utils.app_config": app_config,
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


def import_device_facade_for_test():
    autoscriptor = types.ModuleType("AutoScriptor")
    autoscriptor.__path__ = [str(ROOT / "AutoScriptor")]
    utils_pkg = types.ModuleType("AutoScriptor.utils")
    utils_pkg.__path__ = [str(ROOT / "AutoScriptor" / "utils")]
    perf = types.ModuleType("AutoScriptor.utils.perf")

    class DummySafeSubprocess:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    perf.mumu_safe_subprocess = lambda: DummySafeSubprocess()

    module_name = "device_facade_under_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "AutoScriptor/control/MumuAdaptor/device_facade.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "AutoScriptor": autoscriptor,
        "AutoScriptor.utils": utils_pkg,
        "AutoScriptor.utils.perf": perf,
    }):
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

    def test_is_running_falls_back_to_adb_when_manager_crashes(self):
        module = import_power_for_test()

        class FakeUtils:
            def get_vm_id(self):
                return "1"

            def set_operate(self, operate):
                self.operate = operate

            def run_command(self, args):
                return 3221226505, ""

        def fake_run_adb(args, timeout=10):
            if args == ["get-state"]:
                return SimpleNamespace(returncode=0, stdout="device\n", stderr="")
            if args == ["shell", "getprop", "sys.boot_completed"]:
                return SimpleNamespace(returncode=0, stdout="1\n", stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="bad")

        def ready():
            return (
                fake_run_adb(["get-state"]).stdout.strip() == "device"
                and fake_run_adb(["shell", "getprop", "sys.boot_completed"]).stdout.strip() == "1"
            )

        module.test_facade.adb_device_ready = ready

        self.assertTrue(module.Power(FakeUtils()).is_running())


class TestMuMuAppLifecycle(unittest.TestCase):
    def test_get_installed_falls_back_to_adb_when_manager_crashes(self):
        module = import_mumu_app_for_test()

        class FakeUtils:
            def set_operate(self, operate):
                self.operate = operate

            def run_command(self, args):
                return 3221226505, ""

        module.test_facade.adb_list_packages = lambda: [
            {"package": "org.yjmobile.zmxy", "app_name": "", "version": ""},
            {"package": "x", "app_name": "", "version": ""},
        ]

        installed = module.App(FakeUtils()).get_installed()

        self.assertEqual(installed[0]["package"], "org.yjmobile.zmxy")

    def test_app_state_falls_back_to_adb_when_manager_crashes(self):
        module = import_mumu_app_for_test()

        class FakeUtils:
            def set_operate(self, operate):
                self.operate = operate

            def run_command(self, args):
                return 3221226505, ""

        module.test_facade.adb_app_state = lambda package: "running"

        self.assertEqual(module.App(FakeUtils()).state("org.yjmobile.zmxy"), "running")


class TestMuMuAdbLifecycle(unittest.TestCase):
    def test_click_prefers_direct_adb_without_manager_command(self):
        module = import_mumu_adb_for_test()
        calls = []
        manager_calls = []

        class FakeUtils:
            def set_operate(self, operate):
                self.operate = operate

            def run_command(self, args, repeat=1):
                manager_calls.append((args, repeat))
                return 0, ""

        def fake_run_adb(args, timeout=10):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(module, "run_adb", side_effect=fake_run_adb):
            self.assertTrue(module.Adb(FakeUtils()).click(2000, 0))

        self.assertEqual(calls, [["shell", "input", "tap", "2000", "0"]])
        self.assertEqual(manager_calls, [])

    def test_click_falls_back_to_manager_when_direct_adb_fails(self):
        module = import_mumu_adb_for_test()
        manager_calls = []

        class FakeUtils:
            def set_operate(self, operate):
                self.operate = operate

            def run_command(self, args, repeat=1):
                manager_calls.append((args, repeat))
                return 0, ""

        with patch.object(module, "run_adb", return_value=SimpleNamespace(returncode=1, stdout="", stderr="offline")):
            self.assertTrue(module.Adb(FakeUtils()).click(2000, 0))

        self.assertEqual(
            manager_calls,
            [(['-c', 'shell', 'input', 'tap', '2000', '0'], 1)],
        )

    def test_connect_info_falls_back_to_configured_adb_when_manager_crashes(self):
        module = import_mumu_adb_for_test()

        class FakeUtils:
            def set_operate(self, operate):
                self.operate = operate

            def run_command(self, args):
                return 3221226505, ""

        with patch.object(module, "adb_device_ready", return_value=True), \
                patch.object(module, "configured_adb_host_port", return_value=("127.0.0.1", "16416")):
            self.assertEqual(module.Adb(FakeUtils()).get_connect_info(), ("127.0.0.1", "16416"))


class TestDeviceFacadeDiagnostics(unittest.TestCase):
    def _facade(self, module, adb_path: str, emu_path: str):
        return module.DeviceFacade(
            emulator={
                "adb_path": adb_path,
                "emu_path": emu_path,
                "adb_addr": "127.0.0.1:16416",
                "index": 1,
                "mumu_folder": "C:/Program Files/Netease/MuMu",
            },
            app={"app_to_start": "org.yjmobile.zmxy"},
        )

    def test_default_diagnostics_skips_screenshot_probe(self):
        module = import_device_facade_for_test()
        with tempfile.TemporaryDirectory() as tmp:
            adb_path = str(Path(tmp) / "adb.exe")
            emu_path = str(Path(tmp) / "MuMuManager.exe")
            Path(adb_path).write_text("", encoding="utf-8")
            Path(emu_path).write_text("", encoding="utf-8")
            facade = self._facade(module, adb_path, emu_path)

            def fake_run(cmd, **kwargs):
                if cmd == [adb_path, "version"]:
                    return SimpleNamespace(returncode=0, stdout="Android Debug Bridge version 1.0.41\n", stderr="")
                if cmd[-1:] == ["version"]:
                    return SimpleNamespace(returncode=1, stdout="", stderr="manager failed")
                if cmd[-1:] == ["get-state"]:
                    return SimpleNamespace(returncode=0, stdout="device\n", stderr="")
                if cmd[-2:] == ["getprop", "sys.boot_completed"]:
                    return SimpleNamespace(returncode=0, stdout="1\n", stderr="")
                if cmd[-2:] == ["pm", "path"] or "pm" in cmd:
                    return SimpleNamespace(returncode=0, stdout="package:/data/app/pkg/base.apk\n", stderr="")
                if cmd[-2:] == ["pidof", "org.yjmobile.zmxy"]:
                    return SimpleNamespace(returncode=0, stdout="123\n", stderr="")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.object(module.subprocess, "run", side_effect=fake_run), \
                    patch.dict(sys.modules, {
                        "AutoScriptor.recognition.ocr_rec": SimpleNamespace(
                            ocr_manager=SimpleNamespace(is_ready=lambda: True),
                            ocr_config={"use_gpu": False},
                        ),
                        "AutoScriptor.utils.ui_map": SimpleNamespace(
                            ui_manager=SimpleNamespace(_ui={"x": object()}),
                        ),
                    }):
                diagnostics = facade.diagnostics(include_screenshot=False)

        self.assertEqual(diagnostics["checks"]["manager"]["status"], "warn")
        self.assertEqual(diagnostics["checks"]["nemu_ipc"]["status"], "skipped")
        self.assertEqual(diagnostics["overall"]["status"], "ok")

    def test_screenshot_probe_uses_nemu_ipc_only_when_requested(self):
        module = import_device_facade_for_test()
        facade = module.DeviceFacade(
            emulator={"adb_path": "adb", "emu_path": "mumu", "adb_addr": "127.0.0.1:16416", "index": 1},
            app={"app_to_start": "org.yjmobile.zmxy"},
        )
        calls = []
        nemu_module = types.ModuleType("AutoScriptor.control.NemuIpc.device.method.nemu_ipc")

        class FakeNemuIpc:
            def __init__(self, serial):
                calls.append(("init", serial))

            def screenshot_nemu_ipc(self):
                calls.append(("screenshot",))
                return SimpleNamespace(shape=(720, 1280, 3))

            def nemu_ipc_release(self):
                calls.append(("release",))

        nemu_module.NemuIpc = FakeNemuIpc
        with patch.dict(sys.modules, {
            "AutoScriptor.control.NemuIpc.device.method.nemu_ipc": nemu_module,
        }):
            skipped = facade._nemu_ipc_check(False)
            checked = facade._nemu_ipc_check(True)

        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(calls, [("init", "127.0.0.1:16416"), ("screenshot",), ("release",)])
        self.assertEqual(checked["status"], "ok")
        self.assertEqual(checked["shape"], (720, 1280))


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
