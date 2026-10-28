"""Local deployment safety checks; no downloads, QQ login or game runtime."""
import hashlib
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from backend.core import qq_bot


class TestLocalBotInstall(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / "robot"

    def prepare_runtime(self):
        for filename in qq_bot.REQUIRED_FILES:
            path = self.root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        qq_bot.prepare_configuration(self.root, 3010, 6100)

    def test_configuration_uses_loopback_and_separate_random_tokens(self):
        self.prepare_runtime()
        configuration = qq_bot.read_document(self.root / "napcat/config/onebot11.json")
        server = configuration["network"]["httpServers"][0]
        webui = qq_bot.read_document(self.root / "napcat/config/webui.json")
        connection = qq_bot.local_notification_settings(self.root)
        self.assertEqual(server["host"], "127.0.0.1")
        self.assertEqual(webui["host"], "127.0.0.1")
        self.assertFalse(server["enableCors"])
        self.assertFalse(server["enableWebsocket"])
        self.assertTrue(server["enable"])
        self.assertEqual(connection["endpoint"], "http://127.0.0.1:3010")
        self.assertEqual(connection["access_token"], server["token"])
        self.assertNotEqual(server["token"], webui["token"])
        public_status = json.dumps(qq_bot.local_installation_status(self.root))
        self.assertNotIn(server["token"], public_status)
        self.assertNotIn(webui["token"], public_status)

    def test_reinstall_preserves_configuration_and_login_data(self):
        self.prepare_runtime()
        login_file = self.root / "login.data"
        login_file.write_bytes(b"session")
        original = (self.root / "autoscriptor.json").read_bytes()
        with patch.object(qq_bot, "urlopen") as download:
            qq_bot.install_bot(self.root)
        download.assert_not_called()
        self.assertEqual((self.root / "autoscriptor.json").read_bytes(), original)
        self.assertEqual(login_file.read_bytes(), b"session")

    def test_missing_and_partial_install_are_distinct(self):
        self.assertEqual(qq_bot.local_installation_status(self.root), {"installed": False})
        self.root.mkdir()
        with self.assertRaises(ValueError):
            qq_bot.install_bot(self.root)

    def test_bad_digest_prevents_installation(self):
        archive = self.directory / "download.zip"
        archive.write_bytes(b"untrusted download")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            qq_bot.verify_archive(archive)
        qq_bot.verify_archive(archive, hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_archive_paths_cannot_escape_staging(self):
        for filename in ("../escaped", "C:/escaped", "/escaped", "folder/../../escaped", "..\\escaped"):
            with self.subTest(filename=filename):
                archive = self.directory / "unsafe.zip"
                with zipfile.ZipFile(archive, "w") as package:
                    package.writestr(filename, "payload")
                with self.assertRaises(ValueError):
                    qq_bot.extract_archive(archive, self.root)
                self.assertFalse(self.root.exists())

    def test_invalid_token_is_not_returned_to_notifier(self):
        self.prepare_runtime()
        path = self.root / "autoscriptor.json"
        settings = qq_bot.read_document(path)
        settings["access_token"] = "bad\r\nheader"
        qq_bot.write_document(path, settings)
        with self.assertRaises(ValueError):
            qq_bot.local_notification_settings(self.root)

    def test_start_uses_upstream_single_process_mode(self):
        self.prepare_runtime()
        observed = {}
        process = Mock()
        process.pid = 4321

        def wait():
            # ``stop_bot`` reads this file while the bot runs, so capture it at
            # that moment: the file is removed once the process is gone.
            observed["recorded_pid"] = qq_bot._pid_file(self.root).read_text(encoding="ascii")
            return 0

        process.wait.side_effect = wait
        with patch.object(qq_bot, "lock_bot", return_value=nullcontext()), \
                patch.object(qq_bot.socket, "socket"), \
                patch.object(qq_bot.subprocess, "Popen", return_value=process) as launch:
            self.assertEqual(qq_bot.start_bot(self.root), 0)
        self.assertEqual(launch.call_args.kwargs["env"]["NAPCAT_DISABLE_MULTI_PROCESS"], "1")
        self.assertEqual(launch.call_args.kwargs["cwd"], self.root)
        self.assertNotIn("--no-sandbox", launch.call_args.args[0])
        # The console path must record its child, or "stop" cannot find it later.
        self.assertEqual(observed["recorded_pid"], "4321")
        # And it must clear the record once the child is gone, so the next caller
        # is not misled by a dead pid.
        self.assertFalse(qq_bot._pid_file(self.root).exists())

    def test_ensure_bot_running_uses_the_remembered_quick_login_account(self):
        with patch.object(qq_bot, "load_local_settings", return_value={"http_port": 3010}), \
                patch.object(qq_bot, "bot_is_running", return_value=False), \
                patch.object(qq_bot, "remembered_account", return_value="1480755330"), \
                patch.object(qq_bot, "launch_bot") as launch:
            self.assertTrue(qq_bot.ensure_bot_running(self.root))

        launch.assert_called_once_with(self.root, account="1480755330")

    def test_ensure_bot_running_is_noop_without_a_cached_account(self):
        with patch.object(qq_bot, "load_local_settings", return_value={"http_port": 3010}), \
                patch.object(qq_bot, "bot_is_running", return_value=False), \
                patch.object(qq_bot, "remembered_account", return_value=""), \
                patch.object(qq_bot, "cached_accounts", return_value=[]), \
                patch.object(qq_bot, "launch_bot") as launch:
            self.assertFalse(qq_bot.ensure_bot_running(self.root))

        launch.assert_not_called()

    def test_ensure_bot_running_does_not_start_a_second_process(self):
        with patch.object(qq_bot, "load_local_settings", return_value={"http_port": 3010}), \
                patch.object(qq_bot, "bot_is_running", return_value=True), \
                patch.object(qq_bot, "launch_bot") as launch:
            self.assertFalse(qq_bot.ensure_bot_running(self.root))

        launch.assert_not_called()

    def test_ensure_bot_running_is_noop_when_not_installed(self):
        with patch.object(qq_bot, "load_local_settings", return_value=None), \
                patch.object(qq_bot, "launch_bot") as launch:
            self.assertFalse(qq_bot.ensure_bot_running(self.root))

        launch.assert_not_called()

    def test_native_runtime_failure_is_not_accepted(self):
        with patch.object(qq_bot.subprocess, "run", return_value=Mock(
            returncode=1, stderr="wrapper.node: required DLL missing",
        )):
            with self.assertRaisesRegex(OSError, "required DLL missing"):
                qq_bot.validate_native_runtime(self.root)

    def test_publish_retries_only_transient_windows_denial(self):
        denied = PermissionError("scanner holds the directory")
        denied.winerror = 5
        staging = Mock()
        staging.rename.side_effect = [denied, None]
        with patch.object(qq_bot.time, "sleep") as wait:
            qq_bot.publish_runtime(staging, self.root)
        self.assertEqual(staging.rename.call_count, 2)
        wait.assert_called_once()
        self.root.mkdir()
        staging.rename.reset_mock(side_effect=True)
        staging.rename.side_effect = denied
        with patch.object(qq_bot.time, "sleep") as wait:
            with self.assertRaises(PermissionError):
                qq_bot.publish_runtime(staging, self.root)
        wait.assert_not_called()


class TestLocalBotProcess(unittest.TestCase):
    """找得到、停得掉、说得清 —— 这三件事一起坏过一次。

    真实事故：`stop_bot` 只认 pid 文件，而控制台启动路径根本不写它。于是 stop
    打印「not running」并返回成功，机器人仍在跑、端口仍被占，之后每次启动都报
    「端口 3000 被占用，机器人可能已在运行」——用户永远起不来，也没有任何提示
    告诉他真正发生了什么。
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / "robot"
        for filename in qq_bot.REQUIRED_FILES:
            path = self.root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        qq_bot.prepare_configuration(self.root, 3010, 6100)

    @unittest.skipUnless(os.name == "nt", "Windows process handle semantics")
    def test_exited_process_with_open_handle_does_not_block_autostart(self):
        """OpenProcess can succeed after exit while Popen retains its handle."""
        with subprocess.Popen([sys.executable, "-c", "pass"]) as process:
            process.wait(timeout=10)
            qq_bot._pid_file(self.root).write_text(str(process.pid), encoding="ascii")
            qq_bot.remember_account("123456789", self.root)

            with patch.object(qq_bot, "_listening_pid", return_value=None), \
                    patch.object(qq_bot, "launch_bot") as launch:
                self.assertTrue(qq_bot.ensure_bot_running(self.root))

            launch.assert_called_once_with(self.root, account="123456789")
            self.assertFalse(qq_bot._pid_file(self.root).exists())

    @unittest.skipUnless(os.name == "nt", "Windows process handle semantics")
    def test_live_process_without_listener_still_blocks_duplicate_start(self):
        process_id = os.getpid()
        qq_bot._pid_file(self.root).write_text(str(process_id), encoding="ascii")

        with patch.object(qq_bot, "_listening_pid", return_value=None), \
                patch.object(qq_bot, "launch_bot") as launch:
            self.assertEqual(qq_bot.running_bot_pid(self.root), process_id)
            self.assertFalse(qq_bot.ensure_bot_running(self.root))

        launch.assert_not_called()
        self.assertTrue(qq_bot._pid_file(self.root).exists())

    @unittest.skipUnless(os.name == "nt", "Windows process handle semantics")
    def test_failed_wait_closes_handle_without_discarding_pid(self):
        qq_bot._pid_file(self.root).write_text("4321", encoding="ascii")
        kernel32 = Mock()
        kernel32.OpenProcess.return_value = 1234
        kernel32.WaitForSingleObject.return_value = 0xFFFFFFFF

        with patch("ctypes.WinDLL", return_value=kernel32), \
                patch("ctypes.get_last_error", return_value=6):
            with self.assertRaises(OSError):
                qq_bot.running_bot_pid(self.root)

        kernel32.WaitForSingleObject.assert_called_once_with(1234, 0)
        kernel32.CloseHandle.assert_called_once_with(1234)
        self.assertTrue(qq_bot._pid_file(self.root).exists())

    def test_listening_pid_reads_the_pid_column_of_a_listener(self):
        output = "\n".join([
            "  TCP    127.0.0.1:3010         0.0.0.0:0              LISTENING       4242",
            # Same prefix, different port: must not match.
            "  TCP    127.0.0.1:30100        0.0.0.0:0              LISTENING       9999",
            # Our port, but not a listener.
            "  TCP    192.168.1.5:3010       10.0.0.1:51000         ESTABLISHED     1111",
            "garbage",
        ])
        with patch.object(qq_bot.subprocess, "run", return_value=Mock(returncode=0, stdout=output)):
            self.assertEqual(qq_bot._listening_pid(3010), 4242)

    def test_listening_pid_is_none_when_netstat_fails(self):
        with patch.object(qq_bot.subprocess, "run", side_effect=OSError("no netstat")):
            self.assertIsNone(qq_bot._listening_pid(3010))
        with patch.object(qq_bot.subprocess, "run", return_value=Mock(returncode=1, stdout="")):
            self.assertIsNone(qq_bot._listening_pid(3010))

    def test_stop_finds_a_bot_the_pid_file_never_recorded(self):
        """The port is the fact both start paths share; the pid file is not."""
        with patch.object(qq_bot, "_listening_pid", return_value=7777), \
                patch.object(qq_bot, "_is_our_node_process", return_value=True), \
                patch.object(qq_bot.subprocess, "run") as taskkill:
            self.assertTrue(qq_bot.stop_bot(self.root))
        taskkill.assert_called_once()
        self.assertEqual(list(taskkill.call_args.args[0][:3]), ["taskkill", "/PID", "7777"])

    def test_stop_leaves_another_program_holding_the_port_alone(self):
        """Only a node.exe may be terminated on our behalf."""
        with patch.object(qq_bot, "_listening_pid", return_value=7777), \
                patch.object(qq_bot, "_is_our_node_process", return_value=False), \
                patch.object(qq_bot.subprocess, "run") as taskkill:
            self.assertFalse(qq_bot.stop_bot(self.root))
        taskkill.assert_not_called()

    def test_stop_is_a_noop_when_nothing_is_running(self):
        with patch.object(qq_bot, "_listening_pid", return_value=None), \
                patch.object(qq_bot.subprocess, "run") as taskkill:
            self.assertFalse(qq_bot.stop_bot(self.root))
        taskkill.assert_not_called()

    def test_status_reports_whether_the_bot_is_running(self):
        with patch.object(qq_bot, "_listening_pid", return_value=None):
            self.assertFalse(qq_bot.local_installation_status(self.root)["running"])
        with patch.object(qq_bot, "_listening_pid", return_value=1234), \
                patch.object(qq_bot, "_is_our_node_process", return_value=True):
            self.assertTrue(qq_bot.local_installation_status(self.root)["running"])

    def test_status_still_hides_both_tokens(self):
        """``running`` is a new public field; the no-credential rule still holds."""
        with patch.object(qq_bot, "_listening_pid", return_value=1234), \
                patch.object(qq_bot, "_is_our_node_process", return_value=True):
            public = json.dumps(qq_bot.local_installation_status(self.root))
        server_token = qq_bot.read_document(self.root / "napcat/config/onebot11.json")
        webui_token = qq_bot.read_document(self.root / "napcat/config/webui.json")
        self.assertNotIn(server_token["network"]["httpServers"][0]["token"], public)
        self.assertNotIn(webui_token["token"], public)


if __name__ == "__main__":
    unittest.main()
