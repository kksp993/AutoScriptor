# 源码安装与运行

## 获取源码

Windows10 17763+/11 x64, PowerShell5.1+; no ARM64/32-bit. Supply MuMu/game. ZIP runs; updates require clone:

```powershell
git clone https://github.com/kksp993/AutoScriptor.git
cd AutoScriptor
.\scripts\install.bat
.\webui.bat
# 桌面版：.\start.bat
```

Installs missing winget/Git/Node LTS/uv/VC++ x64/Python3.10.15 `.venv`. Missing winget uses Microsoft CurrentUser bootstrap; process-only Bypass respects policy. Reruns preserve environment/accounts; failures: `logs/install_*.log`.

Path-returning helpers send installer stdout to Out-Host, never pipeline return values.

`install.bat tools|python|electron|qq` repairs components; `all -NonInteractive` skips QQ prompt; `-WithQQ` opts in.

emulator.index/adb_addr/emu_path/adb_path support discovery, preserving explicit addresses.

Common dependencies: requirements.txt. Paddle CPU/GPU mutually exclusive; ocr.use_gpu selects requirements-cpu.txt/requirements-gpu.txt. Switch with `install.bat python cpu|gpu`. OCR model/digit_model/device changes require restart; GPU failure never silently falls back. setuptools<81; validate pkg_resources/adbutils/uiautomator2 imports/dependencies. Editable installation registers [ascli](reference/ascli.md); existing environments can use scripts/ascli.bat without reinstalling.

Electron: `npm install --include=dev --ignore-scripts=false`, verify actual binary version. Startup never installs. Use printed port; WebUI may advance, desktop/backend share it; `-Port`/AUTOSCRIPTOR_PORT supported. Loading window precedes stages/logs. AUTOSCRIPTOR_ELECTRON_RENDER_MODE=software default; d3d11/default optional. Never change host power/priority.

scripts/update.bat/WebUI: source Git only, one `fetch origin main`, compare HEAD ahead/behind, current branch `pull --ff-only origin main`. Reject non-Git/detached/dirty/diverged; preserve stderr/timeout. Never stash/reset/install dependencies; changed dependencies need explicit install.

See [installer](../../scripts/install.ps1)/[tests](../../test/framework/test_source_installer.py); offline checks do not replace clean Windows VM acceptance.
