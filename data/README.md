# data 目录约定

这个目录是运行态可编辑数据根目录，开发环境和发行安装后的 `data/` 保持同一语义。

- `accounts/`: 本机账号、角色、任务状态文件。真实 `*.json` 含账号加密数据，不提交。
- `custom_task/`: 用户自定义任务脚本，会被任务系统动态加载。
- `battle_character/`: 运行态职业脚本唯一生效目录，放在 Nuitka 外；`AutoScriptor/battle_character/` 只保留兼容导入入口。
- `canvas_data/`: 画布保存数据，由 WebUI 运行时生成。

不要在仓库根目录新建 `accounts/`、`custom_task/` 或 `battle_character/`。
