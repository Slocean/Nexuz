# Nexuz P0 → P1 整改计划

更新日期：2026-07-19

执行原则：P0 未关闭前不增加新的高权限积木；每项必须同时满足代码、自动化验证和失败回退三类验收。

## 阶段一：止血（已实施，待真实签名包验收）

- [x] P0-U1 删除前端可传入任意更新 URL 的接口参数。
- [x] P0-U2 仅允许固定 `Slocean/Nexuz` GitHub Release 与 GitHub 资源重定向域名。
- [x] P0-U3 Release 强制 Authenticode 签名，生成并发布 `Nexuz.exe.sha256`。
- [x] P0-U4 下载及应用前重复校验 SHA-256、Authenticode 和内置发布证书 SHA-256 信任锚。
- [x] P0-T1 Python 脚本、自定义积木明确标记为“仅可信代码”，删除“安全沙箱”承诺。
- [x] P0-T2 外部流程先解析、不落库；展示静态能力清单并要求显式确认后再提交。
- [x] P1-N1 修复启动通知 `x;` 回归，未读通知自动弹出并持久化已读 ID。
- [x] P1-A1 生产构建隐藏不可用的 Flow AI；仅 Vite 开发预览保留入口。
- [x] P1-C1 新增 PR/main CI：Python 编译、现有测试、更新安全回归、前端 lint/build。
- [x] P1-R1 Release 复用同一 CI 门禁；缺少签名秘密时直接失败。

真实发布验收：

1. 配置 `WINDOWS_CERTIFICATE` 与 `WINDOWS_CERTIFICATE_PASSWORD`，从新版本 tag 触发 Release。
2. 确认 Release 同时包含 `Nexuz.exe` 和 `Nexuz.exe.sha256`。
3. 用上一版受信任构建检查更新，确认下载、校验、替换和重启成功。
4. 分别篡改 exe、sha256 清单、下载 URL 和签名证书，确认四种情况均在替换前失败。

## 阶段二：关闭剩余 P0（预计 1–2 周）

### P0-S1 Python 脚本隔离

依赖：无。主要文件：`backend/blocks/python_script.py`、`backend/blocks/_script_sandbox.py`、新建 worker/IPC 模块。

执行：

1. [x] 将脚本执行迁入独立 worker，不再在主进程 `exec`。
2. [x] 使用 Job Object 限制内存、子进程数量和进程树，并设置最长运行时间。
3. [~] Windows worker 已降为 Low integrity，并通过审计策略默认阻断网络、子进程和文件写入；读取范围与原生扩展绕过仍需 AppContainer/独立低权限账户收口。
4. [x] IPC 仅传递 JSON 可序列化输入/输出；停止、超时或异常时终止整个进程树。
5. [x] 保留“可信代码”提示，不把进程隔离或语言级过滤宣传为安全沙箱。

当前验收：现有脚本用例通过；dunder/subclasses 逃逸仅发生在 worker；死循环与停止请求会杀死 worker；常规网络、子进程和文件写入被拒绝。未授权文件读取与原生扩展绕过仍待 AppContainer/独立低权限账户完成。

### P0-P1 用户积木隔离

依赖：先完成 P0-S1 的 worker/IPC 基础。

执行：

1. [x] 注册表刷新只静态解析字面量 `SCHEMA`，不执行模块顶层代码。
2. [x] 首次启用用户积木时展示文件名与 SHA-256 并记录授权；内容变化自动失效。
3. [x] 模块顶层代码与 handler 统一运行在一次性插件 worker，停止/超时后终止进程树。
4. [x] 内置积木与用户积木使用不同信任元数据，继续禁止覆盖内置 type。

当前验收：仅扫描目录不会执行 Python；未授权或哈希变化的积木不会注册；插件崩溃或死循环不影响 UI/解释器且无常驻进程。

## 阶段三：P1 工程门禁与发布（预计 1 周）

按以下顺序执行：

1. **P1-TYPE**：建立根 TypeScript 配置，修正 alias/types/include，先让 `tsc --noEmit` 可运行，再按模块消除真实错误并接入 CI。
2. **P1-TEST**：把现有脚本迁到 pytest；为 updater、Bridge、store、interpreter 和启动通知补契约测试；增加保存/导入/运行 Playwright 冒烟路径。
3. **P1-LOCK**：使用 uv 或 pip-tools 生成带哈希 Python 锁文件；统一 npm 单一锁文件；CI 和打包只从锁文件安装。
4. **P1-TAG**：修改 `trigger_release.py`，禁止删除或覆盖远端 tag；已发布版本只能递增。

验收命令：

- `python -m pytest`
- `npm run lint`
- `npm run typecheck`
- `npm run build`
- PR CI 与 tag Release 使用同一锁文件和同一质量门禁

## 阶段四：P1 权限、反馈与停止语义（预计 1–2 周）

1. **P1-BRIDGE**：按 flow、window、update、frida、filesystem 领域拆分最小 Bridge wrapper；生产模式不暴露开发 API；清库、更新、命令和 Frida 使用短期 capability token 与原生确认。
2. **P1-TRUST**：导入前静态生成能力清单；增加受限模式、授权目录、系统积木策略和审计日志。
3. **P1-ERROR**：统一 toast/dialog；保存、导入、导出和运行失败必须可见；校验失败自动选中首个问题节点并聚焦字段。
4. **P1-STOP**：维护子进程、Frida 会话和 worker registry；所有阻塞能力实现取消；停止后等待资源回收，超时则终止进程树。

验收：XSS/调试注入无法直接调用未授权高危 API；第三方流程默认受限；关键失败不再只写日志；停止后不存在继续运行的旧命令、RPC 或 worker。

## 阶段五：P1 可维护性收口（预计 1–2 周）

1. 按领域拆分 `backend/api.py`，保留兼容门面并为每个子 API 建契约测试。
2. 拆分 Bridge 客户端和 store slices，减少跨域状态订阅。
3. 将 Inspector 参数编辑器按输入类型拆成独立组件。
4. 恢复 Flow AI 前必须改走 Python Bridge、配置后端服务并接入正式 `addNodeFromSchema`；否则继续保持隐藏。

完成定义：核心单文件职责清晰、改动可由领域测试覆盖，且 P0/P1 全部在 CI 中有可重复的验收证据。
