# AutoScriptor 1.0.3 Source Portable 验收记录

日期：2026-06-15

## 结论

- 可分发产物：`dist_source_portable/AutoScriptor_Zao_Source_Portable_1.0.3.zip`
- 本地更新包：`dist_source_portable/AutoScriptor_Source_Update_1.0.3.zip`
- 该路线不使用 Nuitka/C++ 编译后端；包内使用 `runtime/python/python.exe` 启动 `backend/src/gui.py`。
- 目录 zip 内根目录包含 `造笔.exe`，用户解压后双击即可使用。
- electron-builder 单文件自解压 exe 未通过启动 smoke，已移到 `dist_source_portable/not_accepted/`，不要分发。

## 参考策略

- ComfyUI 风格：运行时、源码、用户数据分层。AutoScriptor 使用 `runtime/python/`、`backend/src/`、`data/` 三层。
- Genshin/StarRail unlocker 风格：启动器保持简单、配置跟随 portable 根/用户数据，不把安装流程藏进大编译产物。
- AutoScriptor 特殊点：文件数量多，不能把用户账号、文档、日志、source map 打进包；更新包只替换后端源码，配置只补默认缺失项。

## 失败记录与修复

1. `/api/accounts/add` 和 `/api/config` 曾在 packaged runtime 报 `RuntimeError: Task got bad yield`。
   - 根因：Starlette `@app.middleware("http")` / `BaseHTTPMiddleware` body replay 在当前打包运行时不稳。
   - 修复：`services/webui/server.py` 改为原生 ASGI middleware：`_AuthAndApiErrorMiddleware`、`_StaticCacheHeadersMiddleware`。
   - 回归：`test_http_middlewares_do_not_wrap_request_body_with_base_http_middleware`。

2. `/api/credential/revoke` 后仍显示凭据已解锁。
   - 根因：只撤销 cookie token，没有清掉内存中的明文账号密码。
   - 修复：`cfg.clear_decrypted_credentials()` 清理运行态明文，保留账号 JSON 内的加密数据。
   - 回归：`test_clear_decrypted_credentials_keeps_encrypted_account_data`。

3. source portable runtime smoke 首次失败：Paddle 导入时 `site.USER_SITE is None`。
   - 根因：嵌入式 Python 的 `python310._pth` 没有执行 `import site`。
   - 修复：`packaging/source_portable/build_source_portable.py` 复制 runtime 后强制写入 `import site`；Electron 启动后端时设置 `PYTHONNOUSERSITE=1`。

4. 更新包生成器首次把 `data/` 放进 `replace`。
   - 根因：会与更新器的用户数据保护冲突，可能覆盖 `data/config.json`、账号、脚本或日志。
   - 修复：source update 只替换 `backend/src/**`，`config template.json` 进入 `config_defaults`，只补缺失项。

5. PowerShell 验收脚本向 `/api/config` 发送含中文 JSON 时 500。
   - 根因：Windows PowerShell 字符串 body 不是按 UTF-8 bytes 发送。
   - 修复：验收脚本把 JSON 转为 `[System.Text.Encoding]::UTF8.GetBytes(...)` 并设置 `application/json; charset=utf-8`。

6. electron-builder 单文件 portable exe 未通过。
   - 结果：60 秒内无窗口，WebUI 未 ready。
   - 判断：600MB 级 payload 自解压不符合“快速出窗口”目标。
   - 处理：不作为分发产物；使用目录 zip portable。

## 产物

| 产物 | 大小 | SHA-256 |
| --- | ---: | --- |
| `AutoScriptor_Zao_Source_Portable_1.0.3.zip` | 625,239,992 bytes | `8002737DF2B72604BF7758585E1CD385141D8A2B1404CB6E050938862DDD92DF` |
| `AutoScriptor_Source_Update_1.0.3.zip` | 14,414,934 bytes | `98445CEB61FAC65A9C683B63743A828B802522A76BDD3C604AFBE199EA531E11` |
| zip 内启动器 `造笔.exe` | 222,752,768 bytes | 目录包内文件 |

## 内容扫描

- `win-unpacked`：未发现 `*.map`、`docs/`、`data/accounts/*.json`、`backend/src/data/accounts/*.json`。
- 完整 zip：21,002 个 entry，未发现 forbidden entries。
- 更新 zip：600 个 entry，未发现 forbidden entries。
- 更新 manifest：`replace=599`，`copy_if_missing=0`，`mkdir=0`，含 `config_defaults`，无受保护路径。

## 本地验收

报告：`dist_source_portable/standard_acceptance_logs/plain_standard_20260615_224737/report.json`

说明：该轮功能验收 `Ok=true`，但报告内有 Electron cache 文件占用导致的 userData 自动恢复警告；测试后已手动恢复 `%APPDATA%/autoscriptor`，并继续补强验收脚本的进程清理等待。该警告不影响下面的 API/启动功能结果。

| 项 | 结果 |
| --- | --- |
| Electron 首窗口 | 1,750 ms |
| WebUI ready | 4,116 ms |
| `/api/accounts/add` | 通过，新增两个账号 |
| 角色新增/账号切换 | 通过，账号 A 保留 2 个角色 |
| 安全密码解锁 | 通过 |
| `/api/credential/revoke` | 通过，撤销后 `unlocked=false` |
| `/api/config` 保存 | 通过，`max_retry/run_in_background/emulator` 持久化 |
| OCR | 通过，PaddleOCR ready |
| UI Map | 通过，加载 290 项 |
| MuMu/ADB 设备层 | 未通过：本轮配置仍是模板路径，设备未 ready |

## 更新包验收

- `npm run test:release-update`：通过。
- 使用最终实际 `AutoScriptor_Source_Update_1.0.3.zip` 对临时 `1.0.0` 安装树执行 dry-run + apply：通过，摘要为 `replace=1`、`add=598`、`requiresBackendStop=true`。
- 验证点：
  - `backend/src/gui.py` 被替换。
  - `.autoscriptor/release_version.json` 更新为 `1.0.3`。
  - `install.json.version` 更新为 `1.0.3`。
  - 用户数据 canary 未改变。
  - `config_defaults` 只补缺失项，不覆盖用户已有 `app.debug_mode`。

## 未完成

- Clean VM full acceptance 未跑完，不能标记为正式发布完成。
- MuMu 真机/VM 设备验收未通过；当前本机能找到 `C:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe`，但 source portable 的 MuMu 验收脚本还需要适配 `runtime/python + backend/src/gui.py`，现有脚本只支持 `backend/autoscriptor-engine.exe`。
- 单文件自解压 exe 不合格，不分发。
