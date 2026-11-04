import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from AutoScriptor.control.MumuAdaptor.device_facade import DeviceFacade, MuMuStartupError
from AutoScriptor.control.MumuAdaptor.api.core.power import Power
from AutoScriptor.control.MumuAdaptor.utils import utils as MuMuCommandUtils
from AutoScriptor.utils.cancel import TaskCancelled


# Host-side info from instance 1 while its window displayed Android startup failure.
FAILED_PLAYER = {
    "index": "1",
    "error_code": 0,
    "is_android_started": False,
    "is_process_started": True,
    "player_state": "start_finished",
    "adb_host_ip": "127.0.0.1",
    "adb_port": 16416,
    "launch_err_msg": "VERR_NEM_MAP_PAGES_FAILED",
    "launch_err_code": -2147467259,
}


class TestMuMuStartupFailure(unittest.TestCase):
    def setUp(self):
        self.facade = DeviceFacade(
            emulator={"index": 1, "adb_addr": "127.0.0.1:16416", "emu_path": "MuMuManager.exe"},
            app={},
        )
        self.power = Power(MuMuCommandUtils(device_facade=self.facade).set_vm_index("1"))

    def make_manager_result(self, **overrides):
        return SimpleNamespace(
            returncode=0, stdout=json.dumps({**FAILED_PLAYER, **overrides}), stderr="",
        )

    def test_endpoint_verification_reports_android_launch_error_despite_running_process(self):
        with patch.object(self.facade, "run_manager", return_value=self.make_manager_result()):
            with self.assertRaisesRegex(MuMuStartupError, "VERR_NEM_MAP_PAGES_FAILED") as raised:
                self.facade.verify_mumu_endpoint(allow_stopped=True)

        self.assertIn("-2147467259", str(raised.exception))
        self.assertIn("index=1", str(raised.exception))
        self.assertIn("16416", str(raised.exception))

    def test_readiness_catches_failure_before_adb_polling_or_sleep(self):
        with (
            patch.object(self.facade, "run_manager", return_value=self.make_manager_result()),
            patch.object(self.facade, "adb_device_ready", return_value=False) as adb_ready,
            patch("AutoScriptor.control.MumuAdaptor.api.core.power.time.monotonic", side_effect=[0, 0, 100]),
            patch("AutoScriptor.control.MumuAdaptor.api.core.power.sleep_with_cancel") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "VERR_NEM_MAP_PAGES_FAILED"):
                self.power.wait_until_android_ready(cancel_check=lambda: None)

        adb_ready.assert_not_called()
        sleep.assert_not_called()

    def test_failure_that_appears_while_booting_is_not_hidden_by_adb_timeout(self):
        with (
            patch.object(self.facade, "run_manager", side_effect=[
                self.make_manager_result(launch_err_code=0, launch_err_msg="", adb_port=None),
                self.make_manager_result(),
            ]),
            patch.object(self.facade, "adb_device_ready", return_value=False) as adb_ready,
            patch("AutoScriptor.control.MumuAdaptor.api.core.power.time.monotonic", side_effect=[0, 0, 2, 100]),
            patch("AutoScriptor.control.MumuAdaptor.api.core.power.sleep_with_cancel") as sleep,
        ):
            with self.assertRaises(MuMuStartupError):
                self.power.wait_until_android_ready(cancel_check=lambda: None)

        adb_ready.assert_called_once()
        sleep.assert_called_once()
        self.assertIn("VERR_NEM_MAP_PAGES_FAILED", self.power.last_readiness_error)

    def test_adb_timeout_without_host_failure_retains_adb_diagnostic(self):
        self.facade.last_adb_error = "device not found"
        with (
            patch.object(self.facade, "run_manager", return_value=self.make_manager_result(launch_err_code=0, launch_err_msg="")),
            patch.object(self.facade, "adb_device_ready", return_value=False),
            patch("AutoScriptor.control.MumuAdaptor.api.core.power.time.monotonic", side_effect=[0, 0, 100]),
            patch("AutoScriptor.control.MumuAdaptor.api.core.power.sleep_with_cancel"),
        ):
            self.assertFalse(self.power.wait_until_android_ready(cancel_check=lambda: None))
        self.assertEqual(self.power.last_readiness_error, "device not found")

    def test_explicit_launch_failure_does_not_repeat_launch_command(self):
        with (
            patch.object(self.power.utils, "run_command", return_value=(0, "accepted")) as command,
            patch.object(self.facade, "run_manager", return_value=self.make_manager_result()),
            patch.object(self.facade, "adb_device_ready", return_value=False),
            patch("AutoScriptor.control.MumuAdaptor.api.core.power.time.monotonic", side_effect=[0, 0, 100, 100, 100, 200, 200, 200, 300]),
            patch("AutoScriptor.control.MumuAdaptor.api.core.power.sleep_with_cancel"),
        ):
            with self.assertRaisesRegex(RuntimeError, "VERR_NEM_MAP_PAGES_FAILED"):
                self.power.start(cancel_check=lambda: None)

        command.assert_called_once_with(["launch"])

    def test_healthy_or_stopped_instance_does_not_reuse_old_launch_error(self):
        for overrides in (
            {"is_android_started": True},
            {"is_process_started": False, "is_android_started": False},
            {"launch_err_msg": "", "launch_err_code": 0},
        ):
            with self.subTest(overrides=overrides):
                with patch.object(self.facade, "run_manager", return_value=self.make_manager_result(**overrides)):
                    player = self.facade.verify_mumu_endpoint(allow_stopped=True)
                self.assertEqual(player["index"], "1")

    def test_wrong_instance_is_rejected_before_reading_its_launch_error(self):
        with patch.object(self.facade, "run_manager", return_value=self.make_manager_result(index="2")):
            with self.assertRaisesRegex(RuntimeError, "MuMu 实例核验失败") as raised:
                self.facade.verify_mumu_endpoint(allow_stopped=True)
        self.assertNotEqual(type(raised.exception).__name__, "MuMuStartupError")

    def test_cancel_before_host_probe_does_not_query_manager(self):
        cancel_check = Mock(side_effect=TaskCancelled("stop"))
        with patch.object(self.facade, "run_manager") as manager:
            with self.assertRaises(TaskCancelled):
                self.power.wait_until_android_ready(cancel_check=cancel_check)
        manager.assert_not_called()


if __name__ == "__main__":
    unittest.main()
