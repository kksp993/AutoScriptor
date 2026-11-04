# AutoScriptor 源码安装与运行

当前 `src` 分支只维护源码运行。架构总图见 [architecture.md](architecture.md)。

**第一次用请先看 [从零开始](GETTING-STARTED.md)**：那是「装完怎么真正跑起来」的逐步教程。
本文是同一套脚本的参考手册，讲参数、边界和排错细节。

```text
scripts\install.bat    安装/修复依赖
scripts\run.bat        启动 WebUI 或 Electron
scripts\update.bat     快进更新当前 Git 分支
```

安装失败会给出步骤、原因和处理建议，完整输出留在 `logs\install_*.log`。
无参数运行 `install.bat` 会在结束时等待按键，双击也能看清结果。安装可以重复运行，
不会删除现有 `.venv` 或覆盖账号配置；损坏/版本不匹配的虚拟环境需按提示手工处理。

## 环境

- Windows 10（17763 或更高）/11 x64；不支持 ARM64 或 32 位系统
- 系统自带的 64 位 PowerShell 5.1 或更高版本
- 可访问软件源的网络，以及安装系统组件时的授权权限
- MuMu 和游戏需自行安装；不属于本脚本下载范围

安装脚本按需准备 winget、Git、Node.js LTS、uv、VC++ x64 运行库、Python 3.10.15
`.venv`、Python 依赖和 Electron。下载、权限或组织策略阻止安装时会停止并报错，不绕过策略。

## 获取源码

全新电脑尚无 Git 时，在仓库网页选择 **Code → Download ZIP**，完整解压到用户可写的本地目录，
再双击 `scripts\install.bat`。不要在压缩包内运行，或直接放进 Program Files。
ZIP 没有 `.git`，可以运行但不能使用 Git 自动更新；需要自动更新时，在 Git 装好后重新 clone：

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

1. 检查系统架构、源码是否完整、目录能否写入。BAT 选择 64 位 PowerShell，
   只对本次进程使用 `-ExecutionPolicy Bypass`，不永久修改用户执行策略。

2. 按需安装工具链。没有 winget 时，先通过 PSGallery 的微软官方
   `Microsoft.WinGet.Client` 模块和 `Repair-WinGetPackageManager` 为当前用户准备；
   NuGet provider 和模块也只安装在当前用户范围，不改变 PSGallery 信任设置。
   已有 winget 则跳过引导；所有软件包明确使用 `--source winget`：

   ```powershell
   winget install Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
   winget install OpenJS.NodeJS.LTS -e --source winget --accept-source-agreements --accept-package-agreements
   winget install astral-sh.uv -e --source winget --accept-source-agreements --accept-package-agreements
   winget install "Microsoft.VCRedist.2015+.x64" -e --source winget --accept-source-agreements --accept-package-agreements
   ```

   VC++ x64 运行库基线为 14.40，已有兼容版本则保留。单独安装 Python 也检查运行库，
   避免全新电脑在 `import paddle` / `import cv2` 时才发现缺 DLL。系统组件可能要求 UAC 授权或重启。

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

   公共依赖固定 `setuptools<81`，用于兼容当前 `adbutils 1.2.15` 仍经过的
   `pkg_resources -> packaging -> distutils.util` 导入链。Python 安装结束时会
   检查 setuptools 版本并实际导入该链；校验失败时安装不会伪装成功。已有环境若出现
   `ModuleNotFoundError: No module named 'distutils.util'`，重新运行
   `scripts\install.bat python` 恢复依赖合同。

   最后执行 `uv pip check`，校验所选 Paddle 的 CUDA 状态，并实际导入
   PaddleOCR、OpenCV、FastAPI、Uvicorn、multipart、密码学和图像依赖。
   表单解析与 WebUI 一样使用 `python_multipart`，不依赖旧版 `multipart` 兼容模块的包结构。
   这些校验不启动模拟器、不写账号配置；OCR 模型仍在首次使用时联网下载，不能据此声称离线可运行。

5. 准备 Electron：

   ```powershell
   cd frontend\electron
   npm install --include=dev --ignore-scripts=false
   cd ..\..
   ```

   显式包含 Electron 所在的 devDependencies 并执行安装脚本；临时清除
   `ELECTRON_SKIP_BINARY_DOWNLOAD`，结束后恢复。已有包但缺二进制时重新执行 Electron
   自带的 `install.js`。必须实际启动 Electron 二进制的 Node 模式、核对版本后才算成功，
   不以 `node_modules/electron/package.json` 存在为准。校验不会打开应用窗口。

只修复某一类依赖：

```powershell
.\scripts\install.bat tools
.\scripts\install.bat python
.\scripts\install.bat python cpu
.\scripts\install.bat python gpu
.\scripts\install.bat electron
.\scripts\install.bat qq
.\scripts\install.bat all -NonInteractive
```

`-NonInteractive` 跳过可选 QQ 提问（默认不新增 QQ 机器人），但不绕过系统 UAC。
显式 `-WithQQ` 或维护已安装的机器人时仍执行 QQ 安装步骤。

## 可选 QQ 机器人

**只在另一台电脑安装机器人**时，单独复制
[`scripts/qq-robot-standalone`](../../scripts/qq-robot-standalone/README.md) 到目标 Windows 电脑，
右键 `1-install.cmd` 管理员安装，双击 `2-start.cmd` 启动；不需要以下整套源码安装。
它配置 LAN/VPN 来源限制，生成地址和令牌供脚本电脑手工填写，保持与本机安装路径独立。

完整安装末尾会询问是否选装 QQ 机器人，默认不安装；明确选装可执行
`scripts\install.bat all -WithQQ`。已有环境只需：

```powershell
.\scripts\install.bat qq
.\scripts\run.bat qq
```

安装器下载并校验官方 NapCat Windows x64 独立包到 `.autoscriptor\qq-bot`，不改现有 QQ。
HTTP 地址和随机令牌自动生成，接口及登录页只监听本机。安装不直接修改运行中的全局配置；
启动后扫码登录，再在 WebUI“QQ 通知”页点击“使用本机配置”，填写接收 QQ/群号并测试。
机器人窗口需保持开启，不注册开机自启。第三方机器人有账号风控风险，建议使用专用小号。
更多安装、重装、配置交接与错误处理见 [QQ 通知](operations/qq-notifications.md)。

`npm start` 依赖 `frontend\electron\node_modules`。如果直接进入 `frontend\electron` 启动，必须先运行 `.\scripts\install.bat electron` 或在 `frontend\electron` 手动执行 `npm install`。

## 运行

源码 Electron：

```powershell
.\scripts\run.bat electron
```

根目录快捷入口：

```powershell
.\start.bat
```

`start.bat` 等价于 `scripts\run.bat electron`，`webui.bat` 等价于 `scripts\run.bat webui`。

源码 WebUI：

```powershell
.\scripts\run.bat webui
.\webui.bat
```

访问：

```text
http://127.0.0.1:5000
```

端口不是固定的：启动脚本会先挑一个空闲端口，把结果写进 `AUTOSCRIPTOR_PORT` 并打印出来，
后端照它监听。首选端口被占用时自动顺延并在窗口里说明，所以**认命令行打印的那个地址**，
不要认固定的 5000。

固定端口：

```powershell
.\scripts\run.bat webui -Port 8080     # 单次
$env:AUTOSCRIPTOR_PORT = '8080'        # 环境变量，长期有效
```

`AUTOSCRIPTOR_PORT` 写法非法时启动会直接说明哪里不对，不会静默退回 5000。
Electron 外壳和后端必须用同一个端口，所以桌面版不允许顺延：端口被占时会明确报错，
而不是两边各挑一个。

启动脚本还会识别「已经在运行」：端口上已经有 AutoScriptor 时会提示并直接打开浏览器，
不再重复启动第二个实例。

启动前的自检失败（缺 `.venv`、缺 Electron 依赖、端口被占满…）都会打印
「哪一步 / 为什么 / 你可以怎么做」，不会只丢一句异常。

直接运行后端：

```powershell
.\.venv\Scripts\python.exe -X utf8 backend\webui\gui.py
```

这样直接跑时端口同样取 `AUTOSCRIPTOR_PORT`（缺省 5000）；也可以显式指定：

```powershell
.\.venv\Scripts\python.exe -X utf8 backend\webui\gui.py --port 8080
```

运行脚本不会安装依赖。缺 `.venv` 时运行 `.\scripts\install.bat python`，缺 `frontend\electron\node_modules` 时运行 `.\scripts\install.bat electron`。

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
data/character/    用户职业脚本
logs/                     日志、截图、错误归档、礼包码缓存
```

首次启动**不需要**手动创建 `data\config.json`：缺少它时后端会直接读
`data/config.template.json` 里的默认值，一样能进界面。界面里改设置会按需生成
`data/config.json`。只有 `install.bat` 判断 CPU/GPU Paddle 变体时会读它，缺文件按 CPU 处理。

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

不同 MuMu 版本的目录不一样（MuMu 5.0/12 与 6.0 用 `nx_main`，更老的 12 用 `shell`），
上面的值只是示例。设置页的 **自动定位 MuMu** 会按版本自己推导，手填只在自动定位失败时用。

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

winget 引导失败：检查网络能否访问 PSGallery 和微软下载服务，或在 Microsoft Store
安装/修复“应用安装程序”后重试。受组织管理的电脑请联系管理员，不要放宽全局执行策略。

出现 DLL load failed：先运行 `scripts\install.bat python` 补齐 VC++ x64 运行库并执行
实际导入校验；安装器要求重启时先重启，不要自行从 DLL 下载网站拷贝文件。

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

Electron 的 npm 包和可执行文件来自不同下载地址。仅换 npm registry 不能修复二进制下载。
网络需要镜像时可以在当前 PowerShell 设置后重试（不写全局 npm 配置）：

```powershell
$env:ELECTRON_MIRROR = 'https://npmmirror.com/mirrors/electron/'
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

也可读取 `GET /api/device/diagnostics` 的 OCR 段，核对 `configured_use_gpu`、
`runtime_use_gpu`、`engine_device` 和 `restart_required`。GPU Paddle 已安装但 `gpu_count=0` 时先检查
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

正常情况下不需要处理：`run.bat` / `webui.bat` 会自动顺延并打印新地址。要看是谁占着：

```powershell
Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue |
    Select-Object OwningProcess,
        @{n='Process';e={ (Get-Process -Id $_.OwningProcess).ProcessName }}
```

想固定端口就用 `-Port` 或 `AUTOSCRIPTOR_PORT`（见「运行」）。

WebUI 启动但模拟器不可用：先修正 `data/config.json` 中的 MuMu 和 ADB 路径，再通过 WebUI 启动诊断看具体层级。

## 验收

- 在无 Git/Node/uv/Python/VC++ 的干净 Windows x64 环境运行完整安装；额外覆盖没有 winget 的情况。
- `scripts\install.bat` 能校验工具链、VC++、Python x64、依赖一致性和 Electron 实际可执行性。
- 重复安装保留账号/配置，`tools/python/electron/qq` 只报告对应目标完成。
- `scripts\install.bat` 失败时输出「哪一步 / 为什么 / 你可以怎么做」并把完整输出写进 `logs\install_*.log`。
- `scripts\run.bat electron` 或 `start.bat` 能打开 Electron。
- `scripts\run.bat webui` 或 `webui.bat` 能启动 WebUI。
- 启动成功时命令行打印真实地址，该地址可访问；`-Port` 与 `AUTOSCRIPTOR_PORT` 都能改变它。
- 首选端口被占用时自动顺延并说明；端口上已有 AutoScriptor 时提示「已经在运行」而不是重复启动。
- 日志页通过原生 WebSocket `/ws/logs` 显示日志。
- 任务树能加载、保存、刷新。

离线回归：`python -m unittest test.framework.test_source_installer`。这些测试用 PowerShell
执行真实函数、替换外部安装命令，不下载软件或改系统配置；**不能代替干净 VM 的在线安装验收**。
开发机导入成功同样不能证明新电脑的下载、UAC、首次模型初始化和桌面界面已通过验收。
