"""WebUI 监听端口：可配置、被占用能顺延、非法值能看懂。

这一组钉住三类真实事故：

1. 端口写死 5000，本机被别的软件占了用户就完全没办法；
2. 用 ``SO_REUSEADDR`` 探测「端口是否空闲」——Windows 上它允许绑定别的进程
   已经在监听的端口，探测一律返回空闲，顺延逻辑形同虚设，真机上表现为
   uvicorn 仍然去绑旧端口并报 WinError 10048；
3. PowerShell 5.1 在没有 BOM 时按 ANSI 解码 ``.ps1``，脚本里的中文会破坏
   引号配对、整个脚本语法错误。所以带中文的脚本必须有 BOM。
"""
from __future__ import annotations

import os
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.webui import port as port_module

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UTF8_BOM = b"\xef\xbb\xbf"


def find_free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class PortFromEnvironmentTest(unittest.TestCase):
    def test_absent_variable_uses_the_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(port_module.PORT_ENV, None)
            self.assertEqual(port_module.read_configured_port(), port_module.DEFAULT_PORT)

    def test_explicit_value_is_honored(self):
        with patch.dict(os.environ, {port_module.PORT_ENV: "8123"}):
            self.assertEqual(port_module.read_configured_port(), 8123)

    def test_non_numeric_value_fails_with_the_variable_name(self):
        with patch.dict(os.environ, {port_module.PORT_ENV: "not-a-port"}):
            with self.assertRaises(ValueError) as failure:
                port_module.read_configured_port()

        message = str(failure.exception)
        self.assertIn(port_module.PORT_ENV, message)
        self.assertIn("not-a-port", message)
        # 报错要给出路，不能只说「错了」。
        self.assertIn(str(port_module.DEFAULT_PORT), message)

    def test_out_of_range_value_is_rejected(self):
        for raw in ("0", "-1", "65536", "99999"):
            with self.subTest(raw=raw), patch.dict(os.environ, {port_module.PORT_ENV: raw}):
                with self.assertRaises(ValueError):
                    port_module.read_configured_port()


class PortAvailabilityTest(unittest.TestCase):
    def test_a_listening_port_is_not_free(self):
        """这是 SO_REUSEADDR 那次事故的回归测试。

        探测必须真的去独占绑定：设了 SO_REUSEADDR 时 Windows 会允许绑定
        别人正在监听的端口，于是「占用」被误判成「空闲」。
        """
        occupied = find_free_port()
        blocker = socket.socket()
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", occupied))
        blocker.listen(1)
        try:
            self.assertFalse(
                port_module.port_is_free(occupied),
                "占用中的端口必须报 False；报 True 说明探测用了 SO_REUSEADDR",
            )
        finally:
            blocker.close()

    def test_a_closed_port_is_free(self):
        self.assertTrue(port_module.port_is_free(find_free_port()))


class ListeningPortResolutionTest(unittest.TestCase):
    def test_free_preferred_port_is_used_as_is(self):
        preferred = find_free_port()

        port, notice = port_module.resolve_listening_port(preferred)

        self.assertEqual(port, preferred)
        self.assertEqual(notice, "")

    def test_occupied_port_shifts_and_says_so(self):
        occupied = find_free_port()
        blocker = socket.socket()
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", occupied))
        blocker.listen(1)
        try:
            port, notice = port_module.resolve_listening_port(occupied)
        finally:
            blocker.close()

        self.assertNotEqual(port, occupied)
        self.assertGreater(port, occupied)
        # 提示要说清「换了哪个端口」和「怎么固定」，否则用户只能干瞪眼。
        self.assertIn(str(occupied), notice)
        self.assertIn(str(port), notice)
        self.assertIn(port_module.PORT_ENV, notice)

    def test_fixed_port_callers_get_an_error_instead_of_a_silent_shift(self):
        """Electron 外壳必须固定端口，换端口会让它连不上后端。"""
        occupied = find_free_port()
        blocker = socket.socket()
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", occupied))
        blocker.listen(1)
        try:
            with self.assertRaises(RuntimeError) as failure:
                port_module.resolve_listening_port(occupied, allow_shift=False)
        finally:
            blocker.close()

        message = str(failure.exception)
        self.assertIn(str(occupied), message)
        self.assertIn(port_module.PORT_ENV, message)


class LauncherContractTest(unittest.TestCase):
    """启动脚本要跟端口契约对齐，且必须能被 PowerShell 5.1 正确解码。"""

    def read_script(self, relative: str) -> tuple[bytes, str]:
        raw = (PROJECT_ROOT / relative).read_bytes()
        return raw, raw.decode("utf-8-sig")

    def test_scripts_accepted_by_powershell_5_1_carry_a_bom(self):
        import subprocess

        powershell = shutil_which_ps()
        for relative in ("scripts/run.ps1", "scripts/install.ps1"):
            raw, text = self.read_script(relative)
            non_ascii = sum(1 for char in text if ord(char) > 127)
            with self.subTest(script=relative):
                self.assertGreater(non_ascii, 0, "这些脚本是中文提示，不该是纯 ASCII")
                self.assertEqual(
                    raw[:3],
                    UTF8_BOM,
                    f"{relative} 含非 ASCII 却没有 BOM，PowerShell 5.1 会解码成乱码并语法报错",
                )
            # 真让 5.1 解析一遍：BOM 只是前提，语法本身也要过。
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-Command",
                    (
                        "$errors=$null;"
                        f"$null=[System.Management.Automation.Language.Parser]::ParseFile("
                        f"(Resolve-Path '{PROJECT_ROOT / relative}').Path,[ref]$null,[ref]$errors);"
                        "if ($errors.Count) { $errors | ForEach-Object { $_.Message }; exit 1 }"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            with self.subTest(script=relative):
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_run_script_accepts_a_port_and_resolves_it(self):
        _raw, run = self.read_script("scripts/run.ps1")

        self.assertIn("[int]$Port = 0", run)
        self.assertIn("function Resolve-WebUiPort", run)
        self.assertIn("ExclusiveAddressUse", run, "端口探测必须独占绑定")
        self.assertIn("AUTOSCRIPTOR_PORT", run)
        # 「已经在运行」要认出来，否则用户只会看到「双击没反应」。
        self.assertIn("function Test-AutoScriptorOnPort", run)
        self.assertIn("已经在运行", run)
        # 启动成功时必须把真实地址印出来。
        self.assertIn("地址：http://127.0.0.1:", run)

    def test_root_shortcuts_forward_arguments(self):
        for name, target in (("webui.bat", "webui"), ("start.bat", "electron")):
            body = (PROJECT_ROOT / name).read_text(encoding="utf-8-sig")
            with self.subTest(shortcut=name):
                self.assertIn(f'call "%ROOT%scripts\\run.bat" {target} %*', body)

    def test_electron_shell_follows_the_same_port(self):
        main = (PROJECT_ROOT / "frontend/electron/main.js").read_text(encoding="utf-8")

        self.assertIn("const PORT_ENV = 'AUTOSCRIPTOR_PORT';", main)
        self.assertIn("const webuiPort = pickWebUiPort();", main)
        self.assertIn("[PORT_ENV]: String(webuiPort),", main)
        # 外壳和后端必须同端口，所以不能再出现写死的地址。
        self.assertNotIn("http://127.0.0.1:5000", main)


def shutil_which_ps() -> str:
    """PowerShell 可执行文件；测试环境没有就退回 powershell.exe。"""
    from shutil import which

    return which("powershell.exe") or which("powershell") or "powershell.exe"


if __name__ == "__main__":
    unittest.main()
