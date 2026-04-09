# Windows 测试虚拟机：选型、CLI 与 MCP 集成调研

本文档说明**如何落地**一台可用于「干净安装 / 首次运行」测试的 Windows 虚拟机：先做**技术选型**，再按**命令行可自动化**优先；并单独说明 **MCP**、**与本仓库当前能力**的衔接。  
（背景与风险见同目录 [README.md](./README.md)。）

---

## 1. 选型结论（怎么选）

| 方案 | 典型成本 | 自动化成熟度 | MCP / 生态 | 适合你的场景 |
|------|-----------|--------------|------------|----------------|
| **本机 Hyper-V + PowerShell** | 低（硬件与许可已有） | **高**（`Hyper-V` 模块全系 cmdlet） | 无官方「Hyper-V MCP」；可用 **终端 + 脚本**；Agent 照样能执行 PowerShell | **首选**：不花钱、反复快照；与物理 Win10/11 用户环境最接近 |
| **Azure VM + Azure CLI / Bicep** | 按量计费 | **高**（`az vm`、`az group delete` 一条龙） | **有官方 [Azure MCP Server](https://learn.microsoft.com/azure/developer/azure-mcp-server/overview)**，面向 Azure 资源 | **首选补充**：偶尔要「绝对干净」或本机磁盘/性能不够时 |
| **Vagrant + Hyper-V 插件** | 低 | **中高**（`vagrant up/halt/destroy`） | 无专用 MCP；CLI 清晰 | 团队熟悉 HashiCorp、想 **Vagrantfile 版本化** 时 |
| **Packer（Hyper-V ISO）** | 一次性学习成本 | **高**（镜像即代码） | 无专用 MCP | 需要**标准化黄金镜像**、反复克隆时 |
| **VMware / VirtualBox** | 视许可 | **中**（`vmrun`、`VBoxManage`） | 无通用 MCP | 宿主是 Home 版装不了 Hyper-V 等 |

**推荐组合（务实）**：

1. **日常**：在 **Windows Pro/Enterprise** 上开 **Hyper-V**，用 **检查点** 做「干净机」循环。  
2. **偶尔 / CI 式回归**：同一 Azure 订阅里用 **`az` + 资源组**，测完 **`az group delete`** 连 VM 带盘一起删，避免闲置扣费。  
3. **与 AI 协作**：若希望 **对话里直接操作云资源**，在编辑器里接入 **Azure MCP Server**（见 §5）；本机 Hyper-V 仍以 **PowerShell 脚本** 为主。

---

## 2. 本机 Hyper-V：前置条件

- **系统**：Windows **Pro / Enterprise / Education**（家庭版默认无 Hyper-V 角色，需改用 VMware/VirtualBox 或其它宿主，以微软当期文档为准）。  
- **BIOS/UEFI**：开启 **Intel VT-x / AMD-V**。  
- **资源**：建议为测试 VM 预留 **≥8 GB 内存（客户机）**、**≥60 GB 磁盘**；宿主总内存建议 **≥16 GB**。  
- **启用角色**（管理员 PowerShell，示例）：

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
```

重启后可用：`Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V` 确认已启用。

---

## 3. Hyper-V 操作路径（GUI → CLI）

### 3.1 最快上手：Quick Create

- 打开 **Hyper-V 管理器** → **快速创建**，选 **Windows 11 dev environment** 或官方/本地 ISO。  
- 适合第一次建机；**重复「干净环境」**仍建议配合 **检查点**（见 §3.3）。

### 3.2 命令行核心：PowerShell `Hyper-V` 模块

以下 cmdlet 在 **Windows 10/11/Server** 的 Hyper-V 场景通用（具体参数以 `Get-Help` 与 [Microsoft Learn](https://learn.microsoft.com/powershell/module/hyper-v/) 为准）。

| 目的 | 示例（需按名称、路径替换） |
|------|-----------------------------|
| 列出虚拟机 | `Get-VM` |
| 启动 / 关闭 | `Start-VM -Name 'TestVM'`；`Stop-VM -Name 'TestVM'` |
| 创建检查点 | `Checkpoint-VM -VMName 'TestVM' -SnapshotName 'before-install'` |
| 列出检查点 | `Get-VMSnapshot -VMName 'TestVM'` |
| 应用检查点（回滚） | `Restore-VMSnapshot -Name 'before-install' -VMName 'TestVM' -Confirm:$false` |
| 删除检查点 | `Remove-VMSnapshot -VMName 'TestVM' -Name 'before-install'` |
| 嵌套虚拟化（内层要跑模拟器等） | `Set-VMProcessor -VMName 'TestVM' -ExposeVirtualizationExtensions $true`（需先关机） |

**工作流建议**：安装发行包**之前**打检查点 `before-install`；测完卸载或**直接恢复快照**，再测下一构建。

### 3.3 Windows 11 客户机注意

- 使用 **第二代虚拟机**、启用 **TPM**、**安全启动** 等以满足安装要求，见 [Tech Community：在 Hyper-V 中运行 Windows 11](https://techcommunity.microsoft.com/t5/itops-talk-blog/how-to-run-a-windows-11-vm-on-hyper-v/ba-p/3713944) 等实践说明。  
- 检查点类型：**生产检查点**（默认）更利于一致性；若你遇到应用安装与快照交互问题，再查 [Microsoft Learn：使用检查点](https://learn.microsoft.com/virtualization/hyper-v-on-windows/user-guide/checkpoints)。

---

## 4. Azure VM：CLI 与基础设施即代码

### 4.1 为什么单独写一节

- **不占用本机磁盘**、**每次都是新 VM**，适合「发版前做一次全干净回归」。  
- **Azure CLI** 是**一等公民**，脚本、CI、Agent 执行都稳定；与 **Azure MCP**（§5）同一条 Azure 身份体系。

### 4.2 前置

- 安装 [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli-windows)（Windows 可用 `winget` 或 MSI）。  
- 登录：`az login`（若有多订阅：`az account set --subscription <id>`）。

### 4.3 最小流程（示例）

以下仅为**结构示意**；镜像名、SKU、区域、管理员密码策略请以 [快速入门：使用 Azure CLI 创建 Windows VM](https://learn.microsoft.com/azure/virtual-machines/windows/quick-create-cli) 与 `az vm create --help` 为准。

```powershell
az group create --name rg-autoscriptor-test --location eastasia
az vm create `
  --resource-group rg-autoscriptor-test `
  --name vm-clean-install `
  --image Win2022Datacenter `
  --admin-username azureuser `
  --admin-password '<符合复杂度要求的密码>' `
  --public-ip-sku Standard
```

- 获取 RDP 地址：`az vm show -d -g rg-autoscriptor-test -n vm-clean-install --query publicIps -o tsv`（字段名以当前 CLI 输出为准）。  
- **测完即删**（避免持续计费）：

```powershell
az group delete --name rg-autoscriptor-test --yes --no-wait
```

### 4.4 进阶自动化

- **Bicep / ARM 模板**：把 VM、网卡、磁盘固定进模板，便于复现与 code review。  
- **Azure Developer CLI (`azd`)**：偏应用部署模板，若你将来把「测试环境」也产品化，可再评估。

---

## 5. MCP：Azure MCP Server（优先）

### 5.1 是什么

- [Azure MCP Server](https://learn.microsoft.com/azure/developer/azure-mcp-server/overview) 在 **Model Context Protocol** 下，让 AI 开发工具通过 **自然语言或统一工具接口** 管理 Azure 资源（与 Azure CLI、`azd` 等能力对齐）。  
- **入门**：[Get started with the Azure MCP Server](https://learn.microsoft.com/azure/developer/azure-mcp-server/get-started)。  
- **源码与包管理**：[`microsoft/mcp` 仓库中的 Azure.Mcp.Server](https://github.com/microsoft/mcp/tree/main/servers/Azure.Mcp.Server)。

### 5.2 与本仓库当前状态

- 本仓库 **Cursor MCP 配置**（`mcps/`）下**仅见**浏览器类工具，**未默认启用 Azure MCP**。  
- 若你希望在 Cursor 里「对话 + 创建/删除测试 VM」：  
  1. 按微软文档安装或连接 **Azure MCP Server**（含 Docker、包管理器等方式）。  
  2. 在 Cursor 的 MCP 设置中**添加该服务器**，并完成 **Entra ID / Azure 登录**（以文档为准）。  
  3. **仍建议**保留 **`az` 脚本** 作为「一键回归」与无 GUI 时的后备。

### 5.3 边界说明

- **Azure MCP** 面向 **Azure 资源**；**本机 Hyper-V** 没有微软官方同名 MCP，**自动化 = PowerShell + 可选脚本**。  
- 不要把 MCP 当作「无需订阅」的免费云；Azure 侧按资源计费。

---

## 6. 其它 CLI 方案（可选）

### 6.1 Vagrant + Hyper-V

- 文档：[Hyper-V Provider](https://developer.hashicorp.com/vagrant/docs/providers/hyperv)。  
- 价值：`Vagrantfile` 可版本控制，`vagrant up` / `destroy` 统一团队行为。  
- 前提：宿主已启用 Hyper-V；Linux 虚拟机 box 较多，**Windows 客户机 box** 需选可信镜像或自建。

### 6.2 HashiCorp Packer

- 使用 **hyperv-iso** 等构建器生成「黄金镜像」，再导入 Hyper-V；适合**长期固定环境基线**，学习成本高于「Quick Create + 检查点」。

### 6.3 VMware / VirtualBox

- **VMware**：`vmrun` 等（视产品）。  
- **VirtualBox**：`VBoxManage`。  
- 适合 **Hyper-V 无法安装** 的宿主；**与本项目 MuMu + Hyper-V 共存**问题已在 README 中讨论，勿与「物理机」结论混用。

---

## 7. Cursor Skills（当前仓库无现成 VM Skill）

- 公开 **Skills** 列表中**没有**「一键建 Hyper-V」的官方 Skill；**推荐做法**是自建 **Agent Skill**（`.cursor/skills` 或团队规范路径），内容可包含：  
  - 固定 VM 名称、检查点命名规则；  
  - 一段可复制的 `Checkpoint-VM` / `Restore-VMSnapshot` 脚本；  
  - Azure 资源组命名与 `az group delete` 清理清单。  
- 编写方式可参考 Cursor 的 **Create Skill** 流程（项目内若有 `create-skill` 技能说明）。

---

## 8. 建议落地顺序（你个人可以照做）

1. 确认宿主为 **Pro** 且已启用 **Hyper-V**（§2）。  
2. **Quick Create** 或 ISO 装一台 **Win10/11 客户机**，开机完成 OOBE，打 **干净检查点** `baseline-clean`。  
3. 每次发发行候选前：  
   - **恢复** `baseline-clean` → 安装当日构建 → 记录问题；  
   - 或 **新建检查点** `after-install-xxx` 再测卸载。  
4. 若需要云端对照：同一流程用 **Azure CLI** 建 **Windows Server / Win 客户端镜像**（以当前区域可用镜像为准），RDP 进去测，**删资源组**。  
5. 若希望 **在 Cursor 里用自然语言管 Azure**：按 §5 配置 **Azure MCP**，并保留 `az` 脚本作备份。

---

## 9. 参考链接

| 主题 | 链接 |
|------|------|
| Azure MCP 概览 | https://learn.microsoft.com/azure/developer/azure-mcp-server/overview |
| Azure MCP 入门 | https://learn.microsoft.com/azure/developer/azure-mcp-server/get-started |
| Azure CLI Windows VM 快速创建 | https://learn.microsoft.com/azure/virtual-machines/windows/quick-create-cli |
| `az vm` 参考 | https://learn.microsoft.com/cli/azure/vm |
| Hyper-V Checkpoint-VM | https://learn.microsoft.com/powershell/module/hyper-v/checkpoint-vm |
| 嵌套虚拟化概念 | https://learn.microsoft.com/virtualization/hyper-v-on-windows/user-guide/nested-virtualization |
| Vagrant Hyper-V | https://developer.hashicorp.com/vagrant/docs/providers/hyperv |

---

*文档整理日期：2026 年；Azure/Hyper-V 界面与参数名以微软当期文档为准。*
