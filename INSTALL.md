# AutoScriptor 安装教程

本文从一台空白 Windows 机器开始，分成两条安装路线：

- **安装包安装**：面向普通用户。只需要运行发行版安装包，不需要 Python、Node.js、Git 或源码仓库。
- **源码安装**：面向开发者、维护者或需要改代码的人。需要 Git、Python 3.10、Node.js，并从仓库启动。

两条路线不要混用。普通使用优先选择安装包安装；只有要调试、开发、打包或直接改源码时才走源码安装。

## 一、安装包安装

### 1. 适用场景

安装包安装适合最终用户：

- 新电脑第一次安装。
- 没有 Python/Node/Git 环境。
- 只想运行造笔，不需要改源码。
- 后续通过完整安装包或小版本更新包升级。

发行版安装包会自带后端引擎、依赖库、默认数据和桌面壳。用户机器上不需要提前安装 Python 或 Node.js。

### 2. 系统准备

推荐环境：

- Windows 10/11 x64。
- 至少 6 GB 可用磁盘空间。安装包约 500 MB，解压后的 backend 较大，安装阶段还需要临时空间。
- MuMu 或 MuMu12 模拟器。
- 推荐安装目录放在用户有写权限的位置，例如 `D:\AutoScriptor` 或 `C:\Users\<用户名>\Documents\AutoScriptor`。

不建议：

- 装到 `C:\Program Files`。该目录常需要管理员权限，更新和写配置容易失败。
- 装到 OneDrive、网盘同步目录、公司受控目录。
- 把安装包放在网络共享盘上直接运行。建议先复制到本机磁盘。

### 3. 安装 MuMu

1. 安装 MuMu 或 MuMu12。
2. 启动一次模拟器，确认游戏能正常进入。
3. 建议模拟器分辨率设置为平板 `1280x720`。
4. 给模拟器分配合适的 CPU 和内存，避免 OCR 和截图阶段卡顿。

安装向导会尝试自动探测 MuMu、ADB 和 MuMuManager 路径。如果探测失败，可以在向导中手动选择，或安装完成后在应用设置/启动诊断中继续调整。

### 4. 获取安装包并校验

从可信来源获取发行版安装包，例如：

```text
AutoScriptor_Zao_Install_1.0.0.exe
```

如果发布者同时提供 SHA256，建议校验：

```powershell
Get-FileHash -Algorithm SHA256 .\AutoScriptor_Zao_Install_1.0.0.exe
```

校验值应与发布说明中的 SHA256 一致。若不一致，不要继续安装。

### 5. 运行安装向导

1. 双击 `AutoScriptor_Zao_Install_1.0.0.exe`。
2. 如果 Windows SmartScreen 提示未知发布者，确认来源可信后选择继续运行。
3. 选择安装目录。
   - 新安装：选择一个空目录或新建目录。
   - 修复安装：可以选择已有造笔安装目录。
4. 在安装前确认页执行预检。
   - 预检会读取 `backend.zip`、检查目标目录、磁盘空间和随包数据。
   - 预检不会复制文件、不会写注册表、不会修改 MuMu 配置。
5. 开始安装。
   - 安装器会解压 backend 到临时目录。
   - 校验 `autoscriptor-engine.exe` 后再切换到正式 `backend` 目录。
   - 合并 `data`，保留用户账号、配置、自定义任务和角色数据。
   - 写入 `造笔.exe`、卸载脚本和 Windows 应用卸载注册表。

首次安装可能需要数分钟。Windows Defender 或其他安全软件实时扫描时会明显变慢，这是正常现象。

### 6. 配置 MuMu/ADB

安装完成后会进入路径验证页：

- MuMu 安装目录。
- MuMuManager 路径。
- ADB 路径。
- ADB 设备连接。

如果路径检测全部通过，直接完成安装。若 MuMuManager `version` 检测失败但 ADB 可用，安装器会显示警告而不是强制阻断，因为实际运行时 ADB 往往已经足够完成基础操作。

如果暂时没有配置好 MuMu，也可以先完成安装，后续在 WebUI 的启动诊断里继续排查。

### 7. 首次启动验证

安装完成后，安装目录里会有：

```text
造笔.exe
backend\
data\
Uninstall.ps1
卸载造笔.bat
彻底卸载造笔.bat
```

双击 `造笔.exe` 启动。正常情况下会打开桌面窗口，并启动本地 WebUI：

```text
http://127.0.0.1:5000
```

进入应用后建议先打开启动诊断，依次确认：

- MuMuManager。
- ADB。
- App。
- NemuIpc。
- OCR。
- UI Map。

设备诊断默认不把游戏 App 缺失视为安装失败；这条链路只证明 MuMu/ADB/NemuIpc 等设备层可用。只有已经安装游戏并准备验证任务执行时，才需要把 App 层也作为阻断项。

维护者在 MuMu 可运行的验收机上可以额外执行发行态验收脚本，确认安装后的 `backend\autoscriptor-engine.exe` 能完成导包、启动/关闭 MuMu、截图和 WebUI API 诊断：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\release\mumu_device_acceptance.ps1 `
  -InstallRoot D:\AutoScriptor `
  -ExercisePowerCycle `
  -ExerciseScreenshot
```

### 8. 用户数据保存位置

安装包模式下，重要用户数据在安装目录的 `data` 下：

```text
data\config.json
data\accounts\
data\custom_task\
data\battle_character\
```

默认卸载会保留 `data`，这样重装或修复安装后账号、配置和自定义内容不会丢。彻底卸载才会删除整个安装目录。

建议在重装、换电脑或大版本升级前备份 `data` 目录。

### 9. 更新策略

#### 小版本更新

同一版本线的小版本，例如 `1.1.0 -> 1.1.5`，优先使用小版本更新包：

```text
AutoScriptor_Update_1.1.5.zip
```

在 WebUI 的更新页面选择或拖入该 `.zip`。应用会先做 dry run，校验版本线、文件 SHA256、写入路径和用户数据保护范围。预检通过后才会停止 backend、备份旧文件、替换少量文件并重启。

小版本更新包应当是累计包，允许从同一 `x.y.0` 版本线内跳版本更新，例如 `1.1.0 -> 1.1.5` 或 `1.1.2 -> 1.1.5`。

#### 大版本更新

跨版本线，例如 `1.0.x -> 1.1.0`，使用完整安装包。大版本可能包含依赖库、backend 目录结构、Electron 壳或安装器逻辑变化，不应只替换少量文件。

### 10. 卸载

有三种入口：

- Windows“设置 -> 应用 -> 已安装的应用”中卸载造笔。
- 运行安装目录下的 `卸载造笔.bat`。
- 运行安装目录下的 `彻底卸载造笔.bat`。

默认卸载保留 `data`。彻底卸载会删除整个安装目录，包括账号、配置、自定义任务和角色数据。

卸载前建议先退出造笔窗口和托盘。卸载脚本会尝试结束安装目录下的 `造笔.exe`、临时 portable 进程和 `autoscriptor-engine.exe`，避免文件被占用。

### 11. 常见问题

#### 安装很慢

常见原因是解压大体积 backend 和安全软件扫描。等待数分钟是正常的。若长期无进展：

- 确认磁盘空间充足。
- 将安装目录和安装包所在目录加入安全软件信任区后重试。
- 避免安装到网盘同步目录。

#### 提示权限不足

换到普通用户可写目录，例如：

```text
D:\AutoScriptor
C:\Users\<用户名>\Documents\AutoScriptor
```

不要优先选择 `C:\Program Files`。

#### WebUI 无法访问

检查：

- 是否已经启动 `造笔.exe`。
- 端口 `5000` 是否被其他程序占用。
- Windows 防火墙或安全软件是否拦截本地进程。
- 安装目录下 `backend\autoscriptor-engine.exe` 是否存在。

也可以关闭造笔后重新启动。异常退出后如果仍有残留进程，可在任务管理器中结束 `造笔.exe` 和 `autoscriptor-engine.exe` 后再试。

#### MuMu 连接失败

检查：

- MuMu 是否已启动。
- ADB 路径是否正确。
- `data\config.json` 中的 `adb_addr` 是否匹配当前模拟器实例。
- WebUI 启动诊断中是哪一层失败。

## 二、源码安装

### 1. 适用场景

源码安装适合：

- 开发或修改 AutoScriptor。
- 调试 WebUI、任务脚本、安装器或打包逻辑。
- 需要运行测试或构建发行包。

源码安装和发行包安装是两套环境。源码安装需要本机工具链，发行包安装不需要。

### 2. 安装基础工具

在空白 Windows 上准备：

- Git for Windows。
- Python 3.10.x x64。
- Node.js LTS。
- MuMu 或 MuMu12。

可用 `winget` 安装 Git 和 Node.js：

```powershell
winget install Git.Git -e --accept-source-agreements --accept-package-agreements
winget install OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
```

安装完成后关闭旧终端，重新打开 PowerShell，验证：

```powershell
git --version
node -v
npm -v
python --version
```

Python 需要是 `3.10.x`。如果系统里没有 Python 3.10，项目的 `scripts\launcher.ps1` 可以在首次运行时把 Python 3.10.11 安装到仓库内的 `.python310`，但开发机仍建议显式安装 Python 3.10。

### 3. 获取源码

选择一个普通用户可写目录，例如 `D:\Projects`：

```powershell
cd D:\Projects
git clone <仓库地址> AutoScriptor
cd AutoScriptor
```

如果是已经下载好的源码压缩包，也可以解压后进入目录。

### 4. 安装 Python 依赖

最稳的方式是先让项目安装器只准备 Python 环境：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1 install-only
```

它会：

- 检查或安装 Python 3.10。
- 创建 `.venv`。
- 按 `requirements.txt` 安装依赖。
- 尝试探测 MuMu/ADB 并写入配置。

如果依赖环境损坏，需要强制重装：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1 install-only --fresh-install
```

### 5. 启动源码版 WebUI

只启动 WebUI 后端：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1 webui
```

然后访问：

```text
http://127.0.0.1:5000
```

### 6. 启动源码版 Electron 桌面端

如果要运行和发行包接近的桌面窗口：

```powershell
cd webapp
npm install
npm start
```

`npm start` 会启动 Electron，并由 Electron 启动 Python backend。第一次运行前建议先执行过 `scripts\launcher.ps1 install-only`，确保 `.venv` 和 Python 依赖已经存在。

根目录也提供了便捷脚本：

```powershell
.\local_start.bat
```

如果要使用带 Git 更新逻辑的启动脚本：

```powershell
.\start.bat
```

`start.bat` 会尝试拉取指定分支并更新依赖，不适合有未提交本地改动时随手运行。

### 7. 源码版配置位置

源码版主要配置在仓库目录下：

```text
config.json
data\
logs\
```

首次配置可从模板生成：

```powershell
Copy-Item "config template.json" "config.json"
```

安装器通常会尝试自动写入 MuMu/ADB 路径。若自动探测不准，可以手动修改 `config.json`，或在 WebUI 设置页调整。

### 8. 源码版更新

源码版可以使用 Git 更新：

```powershell
git fetch
git pull --ff-only
powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1 install-only
```

如果依赖变化较大，重新安装依赖：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launcher.ps1 install-only --fresh-install
```

发行包用户不要使用源码更新通道。发行包没有 `.git`，应使用完整安装包或小版本更新包。

### 9. 构建发行包

维护者构建发行包使用 `.venv-nuitka`：

```powershell
.\.venv-nuitka\Scripts\python.exe -X utf8 scripts\build_release.py
```

默认产物在：

```text
dist_electron\AutoScriptor_Zao_Install_1.0.0.exe
```

构建脚本会执行 Nuitka 编译、收集数据、打包 `backend.zip`、Electron 打包和 pack 校验。更详细的构建说明见：

```text
docs\AutoScriptor\release-build-and-run.md
```

### 10. 源码版常见问题

#### npm 识别失败

关闭旧终端，重新打开 PowerShell。仍失败时确认：

```text
C:\Program Files\nodejs
```

是否在系统 `Path` 中。

#### Python 版本不对

项目依赖按 Python 3.10 设计。如果 `python --version` 不是 3.10，可使用：

```powershell
py -3.10 --version
```

或让 `scripts\launcher.ps1` 自动安装本地 `.python310`。

#### pip 安装慢或失败

可以换网络环境，或稍后重试。安全软件扫描 `.venv` 也可能显著拖慢安装。

#### 端口 5000 被占用

关闭旧的 WebUI/Electron 进程。必要时在任务管理器中结束 Python、Electron、`autoscriptor-engine.exe` 或相关 `node.exe` 进程后再启动。

## 三、安装前后检查清单

安装包安装：

- 已安装并能启动 MuMu。
- 安装目录可写，磁盘空间充足。
- 安装前预检通过。
- 安装后 `造笔.exe` 能启动。
- WebUI 能访问 `http://127.0.0.1:5000`。
- 启动诊断中 ADB/App/OCR/UI Map 状态符合预期。

源码安装：

- `git --version` 正常。
- `python` 或 `py -3.10` 可用。
- `node -v` 和 `npm -v` 正常。
- `scripts\launcher.ps1 install-only` 成功。
- `scripts\launcher.ps1 webui` 或 `npm start` 能启动。
