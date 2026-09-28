# 独立 QQ 机器人：另一台电脑安装，这台电脑运行脚本

这套文件可单独复制使用，**不调用 AutoScriptor 原来的安装器**。
机器人电脑无需安装 AutoScriptor、Python、Git、npm、Electron 或模拟器，也无需预装普通 QQ。
使用 Windows 10/11 x64 自带的 Windows PowerShell 5.1 下载官方 NapCat 独立运行包。

```text
脚本电脑 A（已有 AutoScriptor） ──局域网/VPN──> 机器人电脑 B ──> QQ
```

## 1. 复制文件到机器人电脑 B

把整个 `qq-robot-standalone` 文件夹复制到 B，例如 `D:\QQRobot`：

```text
D:\QQRobot\
  1-install.cmd       首次安装（右键，以管理员身份运行）
  2-start.cmd         日常启动（双击，普通用户运行）
  robot.ps1           公共脚本，必须和上面两个文件放一起
  README.md           本说明
```

只复制脚本，不复制本机已有的机器人运行目录、令牌或 QQ 登录缓存。
不要放在 Program Files、只读目录、共享盘或同步网盘；安装后不要随意移动，防火墙规则包含程序路径。

## 2. 确认两台电脑的 IP

两台电脑需要在可互通的可信局域网，或已经加入同一个 VPN（如 Tailscale）。
若不在同一网络，先配置 VPN；这套脚本不会自动安装 VPN 或公网穿透。

在两台电脑分别运行 `ipconfig`，找到正在使用的网卡 IPv4；使用 VPN 时填写 VPN 地址。

示例（请替换，不能直接照抄）：

| 电脑 | 示例 IP | 用途 |
| --- | --- | --- |
| 机器人电脑 B | `192.168.1.20` | 消息接口监听地址 |
| 脚本电脑 A | `192.168.1.10` | 唯一允许访问消息接口的来源地址 |

支持 `10.*`、`172.16.*` 至 `172.31.*`、`192.168.*`、VPN 常用的 `100.64.*` 至 `100.127.*`。
不接受公网 IP、`0.0.0.0`、`127.0.0.1`、通配符或整段网段。
建议通过路由器 DHCP 地址保留或固定 VPN 地址，避免重启后 IP 改变。

## 3. 安装：只在机器人电脑 B 操作

右键 **`1-install.cmd` → 以管理员身份运行**。管理员权限仅用于写入受限防火墙规则。

按两个英文提示填写：

```text
ROBOT computer LAN/VPN IPv4 (this computer):       填 B 的 IP
SCRIPT computer LAN/VPN IPv4 (the other computer): 填 A 的 IP
```

也可在管理员 PowerShell 指定两个地址，无需交互输入：

```powershell
cd D:\QQRobot
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\robot.ps1 -Action install -BotAddress 192.168.1.20 -ClientAddress 192.168.1.10
```

安装会完成以下操作：

1. 下载固定的官方 NapCat `v4.18.9` Windows Node 独立包，约 110 MiB。
2. 校验 SHA-256、解压安全路径和 QQ 原生模块依赖；失败不会覆盖已有运行目录。
3. 安装到本文件夹下的 `runtime`，自动生成两个独立随机令牌。
4. 消息接口监听 **B 的指定 IP:3000**，管理页面仅监听 **127.0.0.1:6099**。
5. 创建仅匹配 **A 的 IP、B 的 IP、TCP 3000、该 node.exe** 的入站防火墙允许规则。
6. 将连接参数写入 **`runtime\connection.txt`**。

Windows 防火墙必须启用且默认入站为阻止。脚本不关闭防火墙、不开放管理端口、不做路由器端口映射。
此规则不会撤销机器上其他已有的宽泛放行规则；不要额外给 Node/3000 端口勾选“允许所有网络”。
若公司安全策略拒绝本地规则，需要管理员配置，不能通过关闭防火墙规避。

看到 `Setup complete` 仅表示安装和本地规则配置成功，**不代表 QQ 已登录或跨机连接已验收**。
重复安装保留令牌、地址与登录数据，只恢复本安装自己的防火墙规则。
如果防火墙步骤失败，修复原因后重新安装即可，不需要删除运行目录。

## 4. 启动、登录：仍然在机器人电脑 B

关闭安装管理员窗口，双击 **`2-start.cmd`**，保持窗口开启。

打开输出中的本机管理链接（也保存在 `runtime\connection.txt`）：

```text
http://127.0.0.1:6099/webui?token=管理令牌
```

选择“扫码登录”，用准备作为机器人的手机 QQ 扫码确认。
建议使用专用小号；第三方 QQ 自动化存在账号风控、协议失效和掉线风险。
机器人需要能向接收好友发送消息，或已经加入目标群。

首次 QQ 登录前 3000 端口可能尚未启动，这是正常的；先完成登录再测连接。
本套脚本不选择已有账号、不自动扫码、不替你填接收人、不发送任何测试消息。
没有注册 Windows 服务或开机自启；B 重启后需要再次启动，必要时重新登录。
使用上游单进程开关解决 Node 启动兼容问题，需重启时关闭窗口后再运行 `2-start.cmd`，不要依赖 NapCat 内置多进程重启按钮。

## 5. 配置 AutoScriptor：回到脚本电脑 A

打开 **QQ 通知** 页面，填写：

| 页面字段 | 填什么 |
| --- | --- |
| 机器人 HTTP 地址 | `http://192.168.1.20:3000`，替换成 B 的实际 IP |
| 访问令牌 | B 的 `runtime\connection.txt` 中 **Access token** 的值，不是管理令牌 |
| 接收类型 | QQ 好友或 QQ 群 |
| 接收号码 | 真正接收通知的 QQ 号或群号，不一定是机器人自己的 QQ 号 |

**不要点击“使用本机配置”**，那个按钮指向 A 自己的机器人，不适用于这次远程部署。
先保持自动推送关闭，点击“发送测试消息”；确认收到后再开启自动推送并保存。
测试使用当前草稿，不会自动保存。

只需把 HTTP 地址和 Access token 安全地带回 A。`connection.txt` 还含管理令牌，不要上传 Git、
发到群聊或公开截图。运行目录和生成文件已在随附 `.gitignore` 中排除。

## 连不上时

在 A 的 PowerShell 执行（替换 B 的 IP）：

```powershell
Test-NetConnection 192.168.1.20 -Port 3000
```

- TCP 不通：检查 B 的机器人是否启动并登录、两个 IP 是否填反、VPN/局域网是否互通、网络是否有客户端隔离。
- `401/403`：检查填的是消息接口的 Access token，不是管理令牌。
- OneBot 拒绝发送：检查机器人 QQ 登录、好友关系和群权限。
- `Cannot bind`：IP 不属于 B 的本机网卡，或 3000/6099 被占用；脚本不会结束其他程序抢端口。
- 原生依赖加载失败：可安装微软官方 VC++ x64 运行库后重试：
  <https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist>。
- 下载失败或 SHA-256 不匹配：检查到 GitHub 的访问，不要跳过校验或从陌生 DLL 网站补文件。
- 只在可信局域网或加密 VPN 中使用 HTTP；令牌不等于传输加密。不要直接暴露公网。

## 更换 IP、移动目录或卸载

不要只修改 `remote-setup.json`，NapCat 首次登录会生成账号专属 `onebot11_*.json`，单改清单不会同步它。
最简单且明确的迁移方式：关闭机器人，按下方步骤移除旧防火墙规则，将整个旧目录改名留作备份，
把这套纯脚本重新复制到新目录安装，使用新 IP、重新登录，再到 A 更新地址和新令牌。

在机器人电脑 B 的管理员 PowerShell，进入旧脚本目录后删除**本次安装自己的规则**：

```powershell
$settings = Get-Content -Raw -Encoding UTF8 .\runtime\remote-setup.json | ConvertFrom-Json
Remove-NetFirewallRule -Name $settings.firewall_rule
```

卸载时关闭机器人、移除上述规则，然后删除这个文件夹即可；会删除其令牌和登录配置。
不要删除普通 QQ 或 AutoScriptor 的数据目录。

## 维护说明

固定版本及 hash 与此前本机原生启动验证一致；不自动追随 latest。v4.18.19 官方独立包曾缺少
QQ 9.9.32 所需的 crypto.dll/ssl.dll，所以不能仅凭下载成功认定可用。
独立部署不引用项目模块，更新版本时应单独核对归档结构、原生探针、扫码登录与两台电脑实际通信。
