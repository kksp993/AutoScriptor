from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test.runtime.test_lifecycle_device_startup import (
    Cancelled, import_api_for_test, import_device_facade_for_test,
)


class TestInitEmulatorSelection(unittest.TestCase):
    def setUp(self):
        self.api = import_api_for_test()
        self.api.cfg["emulator"].update(
            index=1, adb_addr="127.0.0.1:16416", adb_path="adb.exe"
        )
        self.original_config = copy.deepcopy(self.api.cfg)
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.api.stub_modules["AutoScriptor.utils.paths"] = SimpleNamespace(
            get_logs_root=lambda: Path(temporary_directory.name)
        )
        module_patch = patch.dict(sys.modules, self.api.stub_modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)

    def tearDown(self):
        self.assertEqual(self.api.cfg, self.original_config)

    def test_explicit_zero_selects_zero_and_its_adb_port(self):
        self.assertEqual(
            self.api.ensure_all_environment_ready(0),
            (0, "127.0.0.1:16384", "pkg"),
        )

    def test_omitted_index_retains_configured_instance(self):
        self.assertEqual(
            self.api.ensure_all_environment_ready(),
            (1, "127.0.0.1:16416", "pkg"),
        )

    def test_other_explicit_index_updates_derived_adb_port(self):
        self.assertEqual(
            self.api.ensure_all_environment_ready(2),
            (2, "127.0.0.1:16448", "pkg"),
        )

    def test_custom_address_is_preserved_unless_explicitly_overridden(self):
        for address in ("192.168.1.50:5555", "localhost:16416", "127.0.0.1:5555"):
            with self.subTest(address=address):
                self.api.cfg["emulator"]["adb_addr"] = address
                self.assertEqual(self.api.ensure_all_environment_ready(0)[1], address)
        self.api.cfg["emulator"]["adb_addr"] = self.original_config["emulator"]["adb_addr"]

    def test_init_forwards_explicit_address_without_mutating_config(self):
        controls = SimpleNamespace()
        emulator = SimpleNamespace()
        with patch.object(self.api, "ensure_app_running", return_value=(controls, emulator)) as start:
            self.api.init(emulator_index=0, adb_addr="192.168.1.50:5555")
        self.assertEqual(start.call_args.args, (0, "192.168.1.50:5555", "pkg"))
        self.assertFalse(start.call_args.kwargs["launch_app"])

    def test_init_binds_manager_and_ipc_to_the_same_instance(self):
        self.api.init(emulator_index=0)
        self.assertEqual(self.api.mumu.index, 0)
        self.assertEqual(self.api.mumu.adb_addr, "127.0.0.1:16384")
        self.assertEqual(self.api.mixctrl.serial, self.api.mumu.adb_addr)

    def test_failed_initialization_leaves_configuration_untouched(self):
        with patch.object(self.api, "ensure_app_running", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                self.api.init(emulator_index=0)

    def test_mismatched_index_and_port_fail_before_creating_controls(self):
        with patch.object(self.api, "MixControl") as controls:
            with self.assertRaisesRegex(ValueError, "index=0.*16448"):
                self.api.ensure_app_running(0, "127.0.0.1:16448", "pkg", launch_app=False)
        controls.assert_not_called()

    def test_initialization_never_sends_a_test_click(self):
        with patch.object(self.api.MixControl, "click") as click:
            self.api.init(emulator_index=0)
        click.assert_not_called()

    def test_manager_verification_failure_blocks_start_and_controls(self):
        with (
            patch.object(self.api.FakeMumu, "verify_connection", side_effect=RuntimeError("wrong endpoint")),
            patch.object(self.api.FakePower, "start") as start,
            patch.object(self.api, "MixControl") as controls,
        ):
            with self.assertRaisesRegex(RuntimeError, "wrong endpoint"):
                self.api.init(emulator_index=0, launch_app=True)
        start.assert_not_called()
        controls.assert_not_called()
        self.assertEqual(self.api.FakeMumu.selected.app.launched, [])

    def test_readiness_failure_reports_instance_address_and_original_error(self):
        with patch.object(self.api.FakePower, "wait_until_android_ready", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "index=0.*16384.*offline"):
                self.api.init(emulator_index=0, launch_app=True)
        self.assertEqual(self.api.FakeMumu.selected.app.launched, [])

    def test_screenshot_failure_and_cancellation_release_ipc_without_publishing_session(self):
        for failure in (RuntimeError("capture failed"), Cancelled("cancelled")):
            with self.subTest(failure=failure):
                controls = Mock()
                controls.screenshot.side_effect = failure
                with patch.object(self.api, "MixControl", return_value=controls):
                    with self.assertRaises(type(failure)):
                        self.api.init(emulator_index=0, launch_app=True)
                controls.nemu_control.nemu_ipc.nemu_ipc_release.assert_called_once()
                controls.click.assert_not_called()
                self.assertEqual(self.api.FakeMumu.selected.app.launched, [])
                self.assertIsNone(self.api.mixctrl)


class TestMuMuConnectionVerification(unittest.TestCase):
    def setUp(self):
        module = import_device_facade_for_test()
        self.facade = module.DeviceFacade(
            emulator={"index": 2, "adb_addr": "127.0.0.1:16448", "emu_path": "MuMuManager.exe"},
            app={},
        )
        self.player = {
            "index": "2", "name": "test-instance", "is_process_started": True,
            "is_android_started": True, "adb_host_ip": "127.0.0.1", "adb_port": 16448,
        }

    def mock_manager(self, payload, returncode=0, stderr=""):
        result = subprocess.CompletedProcess([], returncode, json.dumps(payload), stderr)
        return patch.object(self.facade, "run_manager", return_value=result)

    def test_actual_manager_endpoint_and_localhost_alias_are_accepted(self):
        self.facade.emulator["adb_addr"] = "localhost:16448"
        with self.mock_manager(self.player) as manager:
            self.assertEqual(self.facade.verify_mumu_endpoint(), self.player)
        manager.assert_called_once_with([], operate="info", timeout=8)

    def test_conflicting_manager_port_and_host_are_not_silently_accepted(self):
        for changed_fields in ({"adb_port": 16416}, {"adb_host_ip": "192.168.1.50"}):
            with self.subTest(changed_fields=changed_fields):
                with self.mock_manager({**self.player, **changed_fields}):
                    with self.assertRaisesRegex(RuntimeError, "16448.*adb_addr="):
                        self.facade.verify_mumu_endpoint()
        self.assertEqual(self.facade.adb_addr, "127.0.0.1:16448")

    def test_missing_instance_or_port_does_not_count_as_verified(self):
        for payload in ({}, {"index": "1"}, {"index": "2", "is_process_started": True}):
            with self.subTest(payload=payload):
                with self.mock_manager(payload):
                    with self.assertRaises(RuntimeError):
                        self.facade.verify_mumu_endpoint()

    def test_stopped_instance_is_only_allowed_during_preflight(self):
        stopped = {"index": "2", "is_process_started": False, "is_android_started": False}
        with self.mock_manager(stopped):
            self.assertEqual(self.facade.verify_mumu_endpoint(allow_stopped=True), stopped)
            with self.assertRaises(RuntimeError):
                self.facade.verify_mumu_endpoint()

    def test_manager_failure_preserves_original_error(self):
        with self.mock_manager({}, returncode=7, stderr="manager failed"):
            with self.assertRaisesRegex(RuntimeError, "index=2.*16448.*exit=7.*manager failed"):
                self.facade.verify_mumu_endpoint()

    def test_invalid_or_remote_endpoints_fail_before_manager_query(self):
        addresses = ("", "http://127.0.0.1:16448", "127.0.0.1:70000", "127.0.0.1:0",
                     "127.0.0.1:5555", "127.0.0.1:16416", "192.168.1.50:16448")
        with patch.object(self.facade, "run_manager") as manager:
            for address in addresses:
                with self.subTest(address=address):
                    self.facade.emulator["adb_addr"] = address
                    with self.assertRaises(ValueError):
                        self.facade.verify_mumu_endpoint()
        manager.assert_not_called()

    def test_offline_adb_preserves_reconnect_failure_detail(self):
        offline = subprocess.CompletedProcess([], 1, "", "device offline")
        with (
            patch.object(self.facade, "run_adb", return_value=offline),
            patch.object(self.facade, "_adb_reconnect_serial", return_value="connection refused"),
        ):
            self.assertFalse(self.facade.adb_device_ready())
        self.assertIn("device offline", self.facade.last_adb_error)
        self.assertIn("connection refused", self.facade.last_adb_error)


class TestBoundEmulatorAdapters(unittest.TestCase):
    def test_manager_readiness_and_adb_actions_share_session_parameters(self):
        from AutoScriptor.control.MumuAdaptor import device_facade
        from AutoScriptor.control.MumuAdaptor.mumu import Mumu
        from AutoScriptor.utils import app_config

        config = {
            "emulator": {
                "index": 1,
                "adb_addr": "127.0.0.1:16416",
                "adb_path": "adb.exe",
                "emu_path": "MuMuManager.exe",
            },
            "app": {"app_to_start": "configured.pkg"},
        }
        original_config = copy.deepcopy(config)
        commands = []

        def run_command(command, **kwargs):
            commands.append(command)
            if command[0] == "MuMuManager.exe":
                return subprocess.CompletedProcess(command, 1, "", "manager unavailable")
            output = "device\n" if command[-1] == "get-state" else "1\n"
            return subprocess.CompletedProcess(command, 0, output, "")

        with (
            patch.object(app_config, "cfg", config),
            patch.object(Mumu, "_require_configured_path"),
            patch.object(device_facade.subprocess, "run", side_effect=run_command),
        ):
            emulator = Mumu(adb_addr="127.0.0.1:16384").select(0)
            self.assertTrue(emulator.power.wait_until_android_ready())
            self.assertTrue(emulator.adb.click(10, 20))
            self.assertTrue(emulator.adb.swipe(10, 20, 30, 40))
            self.assertTrue(emulator.adb.key_event(4))
            self.assertTrue(emulator.app.launch("requested.pkg"))
            self.assertTrue(emulator.app.close("requested.pkg"))
            self.assertTrue(emulator.app.exists("requested.pkg"))
            self.assertEqual(emulator.app.state("requested.pkg"), "running")
            self.assertEqual(config, original_config)

            config["emulator"]["index"] = 2
            config["emulator"]["adb_addr"] = "127.0.0.1:16448"
            self.assertTrue(emulator.adb.click(50, 60))

        self.assertTrue(commands)
        for command in commands:
            if command[0] == "adb.exe":
                self.assertEqual(command[1:3], ["-s", "127.0.0.1:16384"])
            else:
                self.assertEqual(command[command.index("-v") + 1], "0")


if __name__ == "__main__":
    unittest.main()
