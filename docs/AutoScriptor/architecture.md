# 架构基线

Source entrypoints: [install](INSTALL.md). FastAPI serves static/; Electron shell only. No legacy menus/frozen fallbacks/distribution installers/script Canvas/Socket.IO.

依赖 backend → orchestrator → tasks → ZmxyOL → AutoScriptor；后端仅经编排单例。model/planning 纯查询，catalog 装配，scheduler 派发，task_manager 执行恢复，projection 保存投影，delivery 通知，facade 组合/闸门。

core/api.py owns runtime orchestration; core/utils.py groups validation/results/target/deadline helpers. Preserve api imports; inject clock/cancellation, never import api/config/control/OCR from utils.

AutoScriptor.utils.paths: data/config.json (global/template fallback), data/accounts/ (account/character tasks), flattened cfg; global task_ordering/runtime_state; year/month/day/weekday view-only. Scripts: data/custom_task/, data/character/; evidence/cache: logs/; docs never runtime data.

任务 id 稳定、path 显示；移动不迁移，重命名钉旧 id。id 平表投影成树，仅 retarget_ordering_overlay 换键；参数签名唯一 spec。重载保留跨边界身份、拒绝空注册表清理；动态导出不因静态未引用删除，控制器实时读 runtime_ctx。

JSON 同目录原子替换，失败不覆写、不无条件 fsync；全局保存不改账号，自写重建基线而脚本仍可观察。

DesktopControl 仅主机：先声明 DPI 感知，虚拟桌面物理像素可负；SendInput 权限阻挡抛错。T 默认区域适配实屏，多匹配须收窄；不替换设备控制。

细则见 [生命周期](runtime/lifecycle.md)、[catalog](../../orchestrator/catalog.py)、[wheel](operations/library-packages.md)。
