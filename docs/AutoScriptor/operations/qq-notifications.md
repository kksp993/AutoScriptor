# QQ 角色结果通知

## 配置入口

**如果机器人装在另一台电脑：**使用可单独复制的
[`scripts/qq-robot-standalone`](../../../scripts/qq-robot-standalone/README.md)，不运行原来的
`install.bat qq`，也不点击“使用本机配置”。它只在指定 LAN/VPN 网卡开放 HTTP 3000，
防火墙限制到脚本电脑单一来源 IP，管理页保留在机器人电脑本机 6099。
这里的两个 IP 不同于接收 QQ/群号；连接参数从机器人电脑 `runtime/connection.txt` 填回本机通知页。
公共网络不要直连 HTTP，应先建立可信 VPN。独立脚本不自动登录、不修改本机通知配置。

WebUI 侧栏 **QQ 通知** 是独立页面，不需要填写 YAML。

1. 在 `scripts\install.bat` 安装末尾选装 QQ 机器人，或执行 `scripts\install.bat qq`。
   执行 `scripts\run.bat qq` 启动后在本机登录页面扫码，保持该窗口开启。
   页面“使用本机配置”会自动保存地址和令牌；已有外部 OneBot 服务可跳过安装并手动填写。
2. 填写 HTTP 地址（默认 `http://127.0.0.1:3000`，以实际机器人配置为准）。
3. 选择 QQ 好友或 QQ 群，填写接收号码。
4. 机器人配置了 HTTP token 时填写访问令牌，否则留空。
5. 点击“发送测试消息”，确认 QQ 收到后开启“自动推送”并保存。

机器人必须能给目标好友发消息，或者已加入目标群。本项目提供可选安装，不代登录 QQ；
第三方机器人存在账号风控和协议兼容风险，建议使用专用小号。
建议机器人只监听本机；远程服务使用 HTTPS 和 token，WebUI 使用访问密码。

测试使用表单当前值，不保存配置，也不要求自动推送已开启。运行中允许测试；保存要求 runtime idle。
令牌不回显：输入框留空代表保留；“清除已保存令牌”后保存才清除。

## 本机安装与配置交接

- `install.bat all -WithQQ` 可在完整依赖安装时明确选装，避免交互询问；`install.bat qq` 只准备
  Python 虚拟环境和机器人，不重装 Paddle/Electron。普通 `all` 会询问，默认不选装。
- 下载固定的官方 `NapNeko/NapCatQQ` Windows Node 独立发行包（当前 `v4.18.9`），校验固定 SHA-256、
  解压路径及运行文件后才移入 `.autoscriptor/qq-bot`。独立包自带 Node 和 QQ 运行组件，不改现有 QQ。
- HTTP 默认端口 3000、登录页默认 6099；安装时被占用就各向后寻找空闲端口。两者仅绑定 `127.0.0.1`，
  使用分别生成的随机令牌；关闭 CORS 和附带 WebSocket。安装文件、令牌、登录缓存均不进入 Git。
- 重复安装保留端口、令牌和登录数据，不做隐式升级。已有目录不完整时明确报错，不覆盖或自动删除。
- 安装不直接改 `data/config.json`，避免与运行中的 cfg 冲突。页面“使用本机配置”通过现有 lifecycle
  全局保存事务完成连接配置交接，保留已保存的接收号码/自动推送开关；表单未保存草稿会被重新加载。
  不会凭空填写接收号码或开启自动推送。该按钮要求 runtime idle。
- `GET /api/notify/qq/local` 只返回 installed/version/login_url，不返回任何令牌，安装存在不等于已登录。
  `POST /api/notify/qq/local` 不接受外部地址或路径，只读取受管目录并保存通知连接参数。
- `run.bat qq` 用文件锁拒绝重复启动，启动前检查两个端口；端口被占用则失败，不杀其他进程。
  当前为独立前台机器人进程，不安装 Windows 服务、不注册开机自启，也不随游戏任务起停。
- 2026-09-09 实测首次启动失败：上游 v4.18.19 Node 包的 fork 分支传入 Electron 参数
  `--no-sandbox`，Node 以 code 9 退出。启动器使用上游支持的 `NAPCAT_DISABLE_MULTI_PROCESS=1`
  单进程入口，不改包内源码；机器人管理页的多进程重启功能不可用，需关闭后重新 `run.bat qq`。
  本机管理页仅能在运行机器打开；远程 WebUI 用户不能把自己的 127.0.0.1 当作服务器地址。
- 同次实测发现 v4.18.19 发行包的 QQ 9.9.32 `wrapper.node` 导入 `crypto.dll` / `ssl.dll`，
  但上游组包未收集这两个文件，原生加载以 module not found 失败。因此暂时固定未切换该 QQ
  运行时的 v4.18.9，不从其他 QQ 版本拼 DLL，不以“下载/解压成功”替代启动验收。
- Windows 验收曾在刚解压后原子目录改名遇到 `WinError 5`。仅对此错误做最多五次短暂等待重试，
  目标已存在或持续拒绝访问仍明确失败；不退化成直接覆写已有运行目录。
- 安装在提交运行目录前执行无登录的 `wrapper.node` 加载探针，拒绝缺 DLL 的包。
  初版探针加载后等待自然退出曾超时；QQ 原生句柄会阻止退出，故探针成功后显式 `process.exit(0)`，
  仍保留 30 秒超时且不创建 QQ 登录会话。

## 消息口径

```text
2:(示例角色)任务完成-成功:3,失败:0
昆仑山完成、领取奖励完成、宠物培养完成
服务器: 示例服务器
```

- 编号来自本轮开始时的有效 `dispatch_queue`；不在队列中的手动执行省略编号。
- 报告本次实际执行的任务，而不是角色所有已配置任务；最多列出六项，失败项另列。
- 无重试的角色在执行管线转向其他角色时发送；待重试角色延迟到最终结果，避免先报失败再报成功。
- 重试覆盖同一个 run id 的结果，不重复计数；管线结束汇报尚未发送的角色。
- 取消、启动/登录异常及无成功结果的未完成任务显示“已中断”，不声称全部完成。
- 没有任务执行时不推送。每次新的执行管线重新汇报，不设置跨天或跨进程的永久已发送标记。
- 任务列表直跑保持已有跳过登录策略，通知中的角色名来自配置，不额外核对游戏内角色。

**数据边界：**当前只有任务执行器的结果口径。没有可靠的战力、活跃数值采集和独立玉虚成功标记，
因此不输出这些指标；尤其不能用 `has_YuxuDian_ticket=False` 推断“玉虚完成”，也不能把“昆仑山任务完成”
改写成“玉虚完成”。若后续补充游戏指标，应先在游戏业务层产生可验证的观测值，再扩展报告快照，
不要在 QQ 通道里调用 OCR、导航或点击。

## 实现边界

| 模块 | 职责 |
| --- | --- |
| `services/core/character_reports.py` | 每管线角色结果聚合、重试合并、文本格式；使用 publish 回调 |
| `services/core/qq_notify.py` | 配置校验、OneBot HTTP 发送、后台 FIFO 和最近记录；不依赖 cfg/调度/游戏 |
| `services/core/scheduler.py` | 在执行边界记录 pending/success/failed，结束时收束报告 |
| `services/webui/lifecycle_service.py` | 全局配置持久化、令牌保留/清除、公开版本递增 |
| `services/webui/routes/notifications.py` | 独立配置、测试和记录 API |
| `services/webui/static/js/components/NotificationsPanel.js` | 页面自己的表单草稿；刷新记录不覆盖未保存编辑 |

配置位于 `data/config.json -> notify.qq`，字段为 `enabled/endpoint/target_type/target_id/access_token`。
保存只写全局文件，不改账号 JSON，不重载任务或设备；磁盘写入失败回滚本次内存修改，不递增版本。
公开配置与通知 GET 仅返回 `token_set`；无认证豁免的 QQ API 不复用 `/api/deploy` 写入。
旧部署读写忽略 QQ 子段，导入未包含令牌的公开配置保留本机令牌。
旧 `notify.enabled/config_yaml` 及 Windows 桌面汇总通知保留，两套远程通道独立开关。

发送参数和结果文本入队后不再读取 cfg，避免切角色或改配置造成串号。发送队列最多等待 100 条，
连接/读取超时分别为 3/5 秒；线程排空后退出。失败只记录，不影响任务结果或游戏重试。
HTTP 200 不是成功证明，必须有 OneBot `status=ok`、整数 `retcode=0` 和 `data.message_id`。
消息使用 text segment，不解析任务名中的 CQ 指令；不跟随重定向，不在错误中回传 token 或服务响应正文。

这是尽力发送而非可靠消息存储：超时不自动重发以免重复，最近 20 条记录只在内存中，
关闭 WebUI 进程可能丢弃未发送消息。界面显示“接口确认成功”不代表 QQ 用户已阅读。

## 离线回归

```powershell
.venv\Scripts\python.exe -X utf8 -m unittest test.test_qq_notifications test.test_scheduler_retry_rounds
node --check services/webui/static/js/components/NotificationsPanel.js
```

通知测试使用模拟 HTTP，不向真实 QQ 发消息，也不初始化模拟器。
