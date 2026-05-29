# AutoScriptor 文档索引

本目录按功能域组织。维护时优先更新对应功能域文档，并用 `rg` 检查旧路径和过期描述。

## 快速入口

| 功能域 | 文档 |
|--------|------|
| API 参考 | [reference/API.md](reference/API.md) |
| 运行生命周期 | [runtime/lifecycle.md](runtime/lifecycle.md) |
| 后台监控 | [runtime/background.md](runtime/background.md) |
| 调度与任务生命周期 | [schedule/scheduler.md](schedule/scheduler.md) |
| 性能与调度辅助 | [schedule/README.md](schedule/README.md)、[schedule/perf.md](schedule/perf.md) |
| 任务编写 | [tasks/script-authoring.md](tasks/script-authoring.md) |
| 任务安全与战斗 flow | [tasks/script-authoring-safety.md](tasks/script-authoring-safety.md)、[tasks/battle-flows.md](tasks/battle-flows.md) |
| WebUI 契约 | [webui/api-contract.md](webui/api-contract.md) |
| WebUI 验收轨迹 | [webui/user-trajectories.md](webui/user-trajectories.md) |
| 发行构建 | [release/build-and-run.md](release/build-and-run.md) |
| Nuitka 打包细节 | [release/nuitka-reference.md](release/nuitka-reference.md) |
| VM 验收 | [release/vm-acceptance.md](release/vm-acceptance.md) |
| 日志归档 | [operations/log-archiver.md](operations/log-archiver.md) |
| 历史重构记录 | [refactor/README.md](refactor/README.md) |
| 第三方资料 | [3rdparties/MumuAdaptor_README.md](3rdparties/MumuAdaptor_README.md) |

## 维护规则

- 行为、生命周期、API、状态语义、打包流程发生变化时，先按本索引审计全部相关功能域，再同步更新对应文档；不要只改一处入口说明。
- 移动或合并文档后必须更新 README、agent 规则、测试和脚本中的路径。
- 文档应作为跳表和当前事实基线；历史记录放入 `refactor/`，但历史文档中若出现已失效路径、模块名或危险规则，也要加当前注释或修正。
