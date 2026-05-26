# scripts 目录约定

这个目录只放项目日常入口和自动化流水线会直接调用的脚本，避免把一次性调试脚本长期留在这里。

## 根目录保留

- `launcher*.bat` / `launcher.ps1`: 用户和开发者启动入口。
- `bootstrap-python310.ps1` / `npm-postinstall.js`: 安装和启动器依赖准备。
- `build_release.py` / `verify_packaging_prereqs.py`: 发行构建与构建前自检。
- `collect_zmxy_redeem_2026.py`: WebUI 资讯页使用的 4399 官方兑换码采集器。
- `release_autoscriptor_locks.ps1`: 解除运行中进程/文件锁的维护工具，由仓库根目录 `release_locks.bat` 调用。

## 子目录

- `release/`: 发布辅助脚本，例如增量包、二进制补丁、manifest 签名。

## 不应放在这里

- 临时 Playwright 探针、网页调试、截图实验脚本。需要保留时应转成测试或放入专门文档示例。
- `__pycache__`、截图、日志、临时输出文件。
- 仅用于人工排查的一次性脚本。问题解决后应删除，或沉淀为可重复运行的测试。
