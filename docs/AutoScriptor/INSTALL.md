# AutoScriptor 源码安装与运行

当前 `src` 分支只维护源码运行。架构总图见 [architecture.md](architecture.md)。

```text
scripts\install.bat    安装/修复依赖
scripts\run.bat        启动 WebUI 或 Electron
scripts\update.bat     快进更新当前 Git 分支
```

## 环境

- Windows 10/11 x64
- winget / App Installer
- PowerShell
- MuMu 或 MuMu12

安装脚本会按需准备 Git、Node.js LTS、uv、Python 3.10.15 `.venv`、Python 依赖和 `webapp\node_modules`。

## 获取源码

```powershell
git clone https://github.com/kksp993/AutoScriptor.git
cd AutoScriptor
git branch --show-current
```

## 安装依赖

```powershell
.\scripts\install.bat
```

脚本流程：

1. 设置当前用户执行策略：

   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
   ```

2. 按需安装工具链：

   ```powershell
   winget install Git.Git -e --accept-source-agreements --accept-package-agreements
   winget install OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
   winget install astral-sh.uv -e --accept-source-agreements --accept-package-agreements
   ```

3. 刷新当前进程 PATH，并重新检测：

   ```powershell
   git --version
   node -v
   npm -v
   uv --version
   ```

4. 准备 Python：

   ```powershell
   uv python install 3.10.15
   uv venv --python 3.10.15 .venv
   uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
   ```

   `requirements.txt` 只包含公共依赖和 `paddleocr==3.7.0`。安装脚本随后卸载
   互斥的 `paddlepaddle` / `paddlepaddle-gpu`，再按所选设备安装：

   - `requirements-cpu.txt`：`paddlepaddle==3.2.0`；
   - `requirements-gpu.txt`：`paddlepaddle-gpu==3.2.2`，使用官方 CUDA 12.9 源。

   默认 `PaddleVariant=auto`：存在 `data/config.json` 时读取
   `ocr.use_gpu`，缺少配置文件时选择 CPU。

5. 准备 Electron：

   ```powershell
   cd webapp
   npm install
   cd ..
   ```

只修复某一类依赖：

```powershell
.\scripts\install.bat tools
.\scripts\install.bat python
.\scripts\install.bat python cpu
.\scripts\install.bat python gpu
.\scripts\install.bat electron
```

`npm start` 依赖 `webapp\node_modules`。如果直接进入 `webapp` 启动，必须先运行 `.\scripts\install.bat electron` 或在 `webapp` 手动执行 `npm install`。

## 运行

源码 Electron：

```powershell
.\scripts\run.bat electron
```

根目录快捷入口：

```powershell
.\start.bat
.\local_start.bat
```

源码 WebUI：

```powershell
.\scripts\run.bat webui
.\webui.bat
```

访问：

```text
http://127.0.0.1:5000
```

直接运行后端：

```powershell
.\.venv\Scripts\python.exe -X utf8 services\webui\gui.py
```

运行脚本不会安装依赖。缺 `.venv` 时运行 `.\scripts\install.bat python`，缺 `webapp\node_modules` 时运行 `.\scripts\install.bat electron`。

## OCR 与 Paddle 运行时

配置示例：

```json
{
  "ocr": {
    "use_gpu": true,
    "model": "PP-OCRv6_small",
    "digit_model": "PP-OCRv6_tiny"
  }
}
```

- `use_gpu=false` 对应 CPU Paddle；`use_gpu=true` 对应 GPU Paddle。
- CPU/GPU Paddle 提供同一个 `paddle` 包，不能在同一 `.venv` 中共存。
- 设置 `use_gpu=true` 后运行 `.\scripts\install.bat python gpu`；切回 CPU 时运行
  `.\scripts\install.bat python cpu`。不显式指定时，`python` 会按当前配置自动选择。
- 普通 OCR、线程局部 OCR 和数字 OCR 共用进程启动时的设备/模型快照。运行中保存
  `ocr.use_gpu` 或模型不会热切换；安装匹配的 Paddle 变体后必须重启 AutoScriptor。
- GPU 已配置但当前 Paddle 不含 CUDA，或没有可用 CUDA 设备时，OCR 初始化会明确失败，
  不会静默回退到 CPU。

## 配置与数据

```text
data/config.json          全局配置
data/config.template.json 配置模板
data/accounts/            账号、角色、任务配置和状态
data/custom_task/         用户自定义任务
data/battle_character/    用户职业脚本
logs/                     日志、截图、错误归档、礼包码缓存
```

首次缺少配置：

```powershell
Copy-Item "data\config.template.json" "data\config.json"
```

常见模拟器字段：

```json
{
  "emulator": {
    "index": 0,
    "adb_addr": "127.0.0.1:16384",
    "emu_path": "C:/Program Files/Netease/MuMu/nx_main/MuMuManager.exe",
    "adb_path": "C:/Program Files/Netease/MuMu/nx_main/adb.exe"
  }
}
```

## 更新

```powershell
.\scripts\update.bat
```

更新脚本固定检查远端 `main`，并只在当前检出分支可快进到 `origin/main` 时执行更新：

```powershell
git fetch origin main
git rev-list --left-right --count HEAD...origin/main
git pull --ff-only origin main
```

如果本地比 `origin/main` 领先，脚本会显示远端没有可拉取提交并输出领先提交数；如果本地和 `origin/main` 分叉，脚本会失败并要求手动处理。它不会安装依赖、stash/reset 本地改动、启动应用或切换到其他更新通道。依赖变化后再运行：

```powershell
.\scripts\install.bat
```

更新要求当前目录是 Git 工作区、当前检出状态不是 detached HEAD、工作区没有本地改动。Git stderr、timeout 或启动失败会直接显示为失败原因。

WebUI 的 `/api/update/status`、`/api/update/check`、`/api/update/run` 使用同一条源码 Git 更新通道；`check` 只做单次 `fetch origin main` 和提交比较，`run` 要求 runtime idle 且只做 fast-forward pull。WebUI 状态会区分 `up_to_date`、`ahead`、`available`、`updated`、`restarting` 和 `failed`；`ahead` 表示本地领先远端但未执行拉取，不等同于刚完成更新。WebUI 更新不会安装 Python/npm 依赖。

## MuMu 检查

1. 启动 MuMu 或 MuMu12。
2. 将分辨率设为横屏 `1280x720`；这是模板、`Box` 和点击坐标使用的绝对像素合同。
3. 确认游戏能正常进入。
4. 打开 WebUI 启动诊断。
5. 按 Manager、ADB、App、NemuIpc、OCR、UI Map 分层排查。

运行时截图尺寸不符会输出带实际尺寸和期望尺寸的中文 warning，同一异常尺寸会节流提示。任务仍会继续，截图也不会被自动缩放；此时识别和点击可能偏移，应在 MuMu 设置中恢复 `1280x720` 横屏，而不是修改任务坐标适配错误分辨率。

MuMu TCP ADB 地址不会因为 `adb start-server` 自动出现在 `adb devices`。设备诊断应连接 `data/config.json -> emulator.adb_addr` 后再判断。

## 排错

Python 版本不对：

```powershell
.\.venv\Scripts\python.exe --version
```

需要重建时删除 `.venv`，再运行：

```powershell
.\scripts\install.bat python
```

npm 无法识别：关闭旧终端，重新打开 PowerShell 后检查：

```powershell
node -v
npm -v
```

Electron 找不到可执行文件：

```powershell
.\scripts\install.bat electron
```

OCR 配置为 GPU 但提示 Paddle 不含 CUDA：

```powershell
.\scripts\install.bat python gpu
```

检查当前 Paddle 和 GPU：

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import paddle; print(paddle.__version__); print(paddle.device.is_compiled_with_cuda()); print(paddle.device.cuda.device_count())"
```

也可读取 `GET /api/ocr-status`，核对 `configured_use_gpu`、`runtime_use_gpu`、
`engine_device` 和 `restart_required`。GPU Paddle 已安装但 `gpu_count=0` 时先检查
NVIDIA 驱动和设备可见性。`AUTOSCRIPTOR_ELECTRON_RENDER_MODE` 只控制 Electron/Chromium
渲染，与 OCR 使用 CPU 还是 GPU 无关。

Electron 打开后系统明显卡顿：

```powershell
$env:AUTOSCRIPTOR_ELECTRON_RENDER_MODE = "software"
.\scripts\run.bat electron
```

`software` 是默认值，会关闭 Electron 硬件加速并避开常见 Windows GPU/Chromium 卡顿路径。对比排查时可临时改成 `d3d11` 或 `default`；浏览器直接访问 `http://127.0.0.1:5000` 不受该变量影响。

端口 `5000` 被占用：

```powershell
Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue
```

WebUI 启动但模拟器不可用：先修正 `data/config.json` 中的 MuMu 和 ADB 路径，再通过 WebUI 启动诊断看具体层级。

## 验收

- `scripts\install.bat` 能校验 Git、Node.js LTS、uv、Python `.venv` 和 Electron 依赖。
- `scripts\run.bat electron` 或 `start.bat` 能打开 Electron。
- `scripts\run.bat webui` 或 `webui.bat` 能启动 WebUI。
- `http://127.0.0.1:5000` 可访问。
- 日志页通过原生 WebSocket `/ws/logs` 显示日志。
- 任务树能加载、保存、刷新。
