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

WebUI 的 `/api/update/status`、`/api/update/check`、`/api/update/run` 使用同一条源码 Git 更新通道；`check` 只做单次 `fetch origin main` 和提交比较，`run` 只做 fast-forward pull。WebUI 状态会区分 `up_to_date`、`ahead`、`available`、`updated`、`restarting` 和 `failed`；`ahead` 表示本地领先远端但未执行拉取，不等同于刚完成更新。WebUI 更新不会安装 Python/npm 依赖。

## MuMu 检查

1. 启动 MuMu 或 MuMu12。
2. 建议分辨率设为横屏 `1280x720`。
3. 确认游戏能正常进入。
4. 打开 WebUI 启动诊断。
5. 按 Manager、ADB、App、NemuIpc、OCR、UI Map 分层排查。

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
