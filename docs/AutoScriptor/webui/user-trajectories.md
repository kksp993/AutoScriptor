# WebUI 验收轨迹

这些轨迹用于回归测试和手工验收，覆盖 WebUI、配置生命周期和设备边界，不保证具体游戏业务脚本能打完。

## 首次打开

1. 启动 WebUI 或 Electron。
2. `/api/init-status` 从未完成变为完成。
3. 默认不启动 MuMu、不初始化 `mixctrl/mumu`。
4. 页面通过 `/api/refresh` 和 `/api/runtime/snapshot` 得到配置与状态。

## 任务编辑保存

1. 打开任务树。
2. 编辑一个关闭任务，打开开关并保存。
3. 弹窗关闭，任务仍为启用。
4. 刷新页面后状态仍为启用。
5. `next_exec_time=0` 时显示为待执行。
6. 保存后的账号 JSON 不包含 `fn/order/param_meta/param_keys/beta/custom/debug_mode/task_description/task_doc_flow/_due/progress/progress_display` 等运行时字段。

## 未注册任务隐藏

1. 在账号 JSON 中保留一个已经不存在的任务叶子。
2. 启动 WebUI 并刷新。
3. 该叶子不会显示在任务树或总览汇总中。
4. 保存任务后不会把未注册叶子重新写回。

## 进度与人工接管展示

1. 任务运行中写入 `progress=5/6`。
2. 未完成进度在黄色待执行/重试期间显示 `5/6`。
3. retry 耗尽后显示红色 `5/6` 和 `human_takeover_error`。
4. `next_exec_time` 到期后该任务重新显示为待执行，可自动再试。

## 跨角色调度队列

1. 在总览页添加多个角色到调度队列。
2. 调整顺序并刷新页面。
3. 顺序保持不变，重复和不存在角色被过滤。
4. 开始调度后只执行队列内角色，按队列顺序寻找到期任务。
5. 当前活动角色在队列末尾时，其他队列角色仍能被切换并执行。

## 停止执行

1. 开始调度或直接执行任务。
2. 在启动模拟器、等待登录、脚本 `sleep()` 或 retry 等待阶段点击停止。
3. WebUI 快速进入停止中。
4. 任务协作退出后回到待运行。
5. 后续任务链不再继续执行。

## Debug 任务直跑

1. 任务使用 `@register_task(debug_mode=True)`。
2. 从当前游戏画面直接运行。
3. 不强制回登录页重新登录。
4. 失败后不关闭/重启游戏。
5. 本轮只执行 debug 任务时不执行 `post_execution`。

## 设备诊断

1. 打开“启动诊断”页。
2. 默认刷新只检查 Manager、ADB、App、OCR、UI Map 状态，不触发 NemuIpc 截图。
3. 点击“截图探测”后才检查 NemuIpc。
4. MuMuManager `version` 失败但 ADB 可用时，Manager 显示 warning，整体按 ADB/App/NemuIpc 结果判断。

## Editor 离线与实时

1. 导入图片或已有截图后运行 OCR、颜色、模板定位。
2. 这些离线操作不启动模拟器。
3. 点击实时截图、遥控点击/滑动、真实执行代码时才申请设备会话。
4. 没有 credential unlock 时，真实设备动作被拒绝。

## 错误归档

1. 任务失败后在错误归档页出现新条目。
2. 详情页能看到摘要、日志段和截图。
3. Shift 多选可选中连续归档。
4. 批量删除只删除选中目录。
5. zip 导入写入新的 `import` 归档目录，不覆盖已有归档。

## 更新页

1. 源码部署显示 git updater 状态，可检查/执行源码更新。
2. 发行包中 git updater 不可用，不应诱导用户执行 git 更新。
3. 发行版内容更新走 `/api/content-update/*`，需 manifest、hash/签名、保护路径校验。
4. 本地小版本更新包由 Electron releaseUpdate 通道 dry-run 后再应用。

## 安装器

1. 首次运行 HTML 安装向导。
2. dry run 只读取 `backend.zip`、目标目录、磁盘和 data 计划，不写入安装目录。
3. 安装解压到临时 `.backend.new.*`，校验后事务切换。
4. 修复安装保留 `data/config.json`、账号、自定义任务和 `battle_character`。
5. MuMuManager `version` 失败但 ADB 可用时不阻断安装，显示 warning。
