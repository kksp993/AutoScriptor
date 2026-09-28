"""Local deployment safety checks; no downloads, QQ login or game runtime."""
import hashlib
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from services.core import qq_bot


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
        with patch.object(qq_bot, "lock_bot", return_value=nullcontext()), \
                patch.object(qq_bot.socket, "socket"), \
                patch.object(qq_bot.subprocess, "call", return_value=0) as launch:
            self.assertEqual(qq_bot.start_bot(self.root), 0)
        self.assertEqual(launch.call_args.kwargs["env"]["NAPCAT_DISABLE_MULTI_PROCESS"], "1")
        self.assertEqual(launch.call_args.kwargs["cwd"], self.root)
        self.assertNotIn("--no-sandbox", launch.call_args.args[0])

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


if __name__ == "__main__":
    unittest.main()
