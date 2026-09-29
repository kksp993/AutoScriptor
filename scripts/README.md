# scripts 目录约定

本目录只放当前源码主线需要的脚本。一次性实验和本机探针不要长期留在这里。

## 入口

每个入口都是一对 `.bat` + `.ps1`：`.bat` 负责用 `-ExecutionPolicy Bypass` 起 PowerShell，
`.ps1` 承担实际逻辑。根目录的 `start.bat`、`webui.bat` 只是对应目标的快捷方式。

| 脚本 | 作用 |
| --- | --- |
| `install.bat` / `install.ps1` | 安装依赖。默认 `all`，也支持 `tools`、`python`、`electron`、`qq`；`-WithQQ` 明确选装本机机器人；`python` 后可跟 `cpu`/`gpu` 指定 Paddle 变体 |
| `run.bat` / `run.ps1` | 运行源码。目标为 `webui`（默认）、`electron` 或本机 QQ 机器人 `qq` |
| `update.bat` / `update.ps1` | `fetch origin main`，只在当前检出分支可快进时执行 `pull --ff-only` |

根目录快捷入口：

| 文件 | 等价于 |
| --- | --- |
| `start.bat` | `scripts\run.bat electron` |
| `webui.bat` | `scripts\run.bat webui` |

## 维护工具

| 脚本 | 作用 |
| --- | --- |
| `collect_zmxy_redeem_2026.py` | 4399 官方公告礼包码增量采集器，写入 `logs/zmxy_redeem_codes.json`；WebUI 资讯页兑换码弹窗会调用它 |
| `audit_ui_assets.py` | 只读审计 `ui_map.csv`、模板引用与孤立图片，报告写入 `logs/` |
| `run_recognition_baselines.py` | 固定帧识别基准；样本要求严格 1280×720 |
| `benchmark_ocr_models.py` | 在相同截图或 ROI 上比较 PaddleOCR 模型档位 |
| `check_undefined_names.py` | 静态扫描未定义名字，作为 `py_compile` 之外的补充检查 |

## 独立部署

- `qq-robot-standalone/`：另一台 Windows 电脑专用的独立 QQ 机器人安装/启动脚本。整个文件夹可单独复制，
  不依赖本仓库或 Python/npm；按指定 LAN/VPN IP 配置消息接口和来源防火墙，管理页仍只监听回环。
  见 [独立部署步骤](qq-robot-standalone/README.md)。

## 边界

- 安装脚本负责依赖，不启动应用。
- `install.bat qq` 安装校验后的官方 NapCat 独立包，生成本机 HTTP 配置；`run.bat qq` 单独启动，
  首次登录需人工扫码。在 WebUI 的 QQ 通知页点击“使用本机配置”完成地址和令牌交接。
  详细边界见 [QQ 通知](../docs/AutoScriptor/operations/qq-notifications.md)。
- 运行脚本负责启动，不安装依赖。
- 更新脚本负责 Git 快进，不 stash/reset、不安装依赖、不启动应用。
- 发布器、安装器、CLI 菜单、Nuitka、Canvas、Socket.IO、打包验收脚本不属于当前主线。
