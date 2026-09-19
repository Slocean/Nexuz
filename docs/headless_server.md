# 无头服务器版（Nexuz Server）

版本：v2（2026-09-19，v1 的"Linux 二期"并入一期；Web 界面改为复用现有前端）
目标版本：0.22.0（一期）

## 背景与定位

Nexuz 目前是 Windows 桌面应用（pywebview 宿主 + Python 后端）。约 73 个积木里，
真正需要"真机桌面"的只有约 17 个（鼠标键盘、屏幕、窗口、系统外设）；文件处理、
图片批处理、OCR、LLM 桥接、浏览器（CDP/DrissionPage）、HTTP 等能力本质是纯软件，
不依赖屏幕与输入设备。

**目标**：同一代码库产出一种无头服务器形态——

- 不启动 pywebview 窗口，常驻后台运行（**部署目标：WSL Ubuntu / Linux 服务**，
  Windows 同样可用）；后端引擎的桌面库依赖已全部懒加载化，Linux 上无需安装
  任何桌面依赖（`requirements-server.txt`）；
- 只暴露与真机无关的能力（A/B 档积木），真机积木给明确拒绝而非崩溃；
- 远程 agent（zcode / Claude Code 等）经 MCP 直接调用；
- **Web 界面复用现有前端**：服务器托管 `frontend/dist` 构建产物，前端
  bridge.js 在无 pywebview 环境下走 `POST /api/<method>`（白名单）桥接，
  浏览器打开 `http://服务器:端口/` 即是完整管理界面；
- 定时任务（schedule_trigger / FlowScheduler）常驻自然生效，通知可外发。

**非目标（一期不做）**：

- 真机反向代理（三期，见文末路线）；
- 流程编辑器的桌面交互组件在服务器上可用（选点/取色/录制等按钮会得到
  明确的 ok:false，编辑与保存、运行、定时管理全部可用）。

**核心原则**：不分叉项目、不复制引擎。桌面版与服务器版共享同一套
interpreter / registry / scheduler / execution_policy，只换"宿主"。

## 现状地基（已具备的部分）

设计建立在对现有代码的核实之上，以下四块是直接复用的地基：

| 地基 | 位置 | 现状 |
| --- | --- | --- |
| MCP HTTP 桥 | `backend/core/mcp_bridge.py` | 已是带 Bearer token 的 `POST /rpc` + `/health`，`nexuz_mcp.py` 只是 stdio 转发壳；并发槽位、请求体上限、看门狗超时齐备 |
| 流程解释器 | `backend/core/interpreter.py` | 顶层零 UI 依赖；UI 耦合只有构造时的 `emit` 回调 |
| 定时调度 | `backend/core/scheduler.py` | APScheduler + `jobs.json` 磁盘持久化 + `failures.jsonl` 失败记录；通知回调已解耦（`set_emit`），漏触发有 pending 补偿 |
| 执行策略闸 | `backend/core/execution_policy.py` | safe/standard/legacy 三档 + `MCP_FLOOR_DENY` 下限 + `__policy_floor__` 随流程字典传播（含 call_subflow 嵌套与定时重注入） |

`Api.run_flow` 的运行链（校验 → 参数校验 → interpreter）中 UI 相关的只有
`self._emit` 与 `hide_window`，因此服务器侧的门面可以做得很薄。

## 能力分档

给积木 SCHEMA 增加一个 `requires` 标记，三档口径如下。

### A 档：无头全可用（44 个，`requires` 缺省）

| 组 | 积木 |
| --- | --- |
| 控制类（12） | assign、call_subflow、if_condition、if_logic、if_text_contains、loop_foreach、loop_forever、loop_n、loop_while、switch、try_catch、schedule_trigger |
| 文件与系统（12） | disk_info、env_var、file_io、file_manage、http_request、llm_convert、llm_forward、process_list、process_kill、sys_path、timestamp、zip_archive |
| 图片处理（9） | ai_object_cut、image_generate、image_rename、image_scale、sprite_part_cut、sprite_sheet_cut、transparent_cut、style_audit、ocr_recognize（RapidOCR/onnxruntime 跨平台，作用于图片文件） |
| 浏览器（11） | browser_navigate / click / fill / eval / extract / screenshot / snapshot / tabs / resize / wait / close（CDP 引擎 + headless Chromium/Edge） |

### B 档：部分可用 / 降级（10 个，`requires: "partial"`）

| 积木 | 服务器口径 |
| --- | --- |
| delay | 纯延时，可用 |
| wait_until | 非"屏幕条件"可用，屏幕条件拒绝 |
| monitor_start / check / wait / list / stop | 进程（psutil）与文件条件可用，屏幕条件拒绝 |
| system_info | 基本可用（部分字段无意义时返回空） |
| open_path | 仅保留 shell 语义（可启动程序，本来就在 elevated 闸内） |
| clipboard | Windows 会话内可用；Session 0 服务模式下拒绝 |

### C 档：真机绑定（17 个，`requires: "desktop"`，无头明确拒绝）

- 鼠标键盘（6）：click、drag、key_press、mouse_hover、mouse_scroll、type_text
- 屏幕（5）：screenshot、color_detect、find_image、locate_text、if_color_match
- 窗口（3）：window_activate、window_close、window_wait
- 外设（3）：notify、volume_action、power_action

### 策略类（不属于 requires，单独说明）

`python_script`、`run_command` 保持现有口径：外部 AI 链（MCP run_block /
run_flow / 定时重注入）一律硬拒（`MCP_FLOOR_DENY`），服务器版不放松。
MCP 层工具 `capture_screen`、`locate_text_on_screen` 在无头模式返回明确错误
"服务器形态无屏幕"，且从 `list_blocks` 目录中隐藏（同 CRITICAL_TYPES 现口径）。

## 总体架构

```
桌面形态（现状）                      服务器形态（新增）
┌─────────────────────┐             ┌─────────────────────┐
│ backend/main.py     │             │ backend/server.py   │
│   pywebview 窗口    │             │   （无 GUI 入口）    │
│   Api（全量门面）    │             │   ServerApi（薄门面）│
└────────┬────────────┘             └────────┬────────────┘
         │  同一套引擎层，两边共享              │
┌────────┴──────────────────────────────────┴────────────┐
│ interpreter（执行） · registry（积木注册/requires 校验） │
│ scheduler（定时） · execution_policy（闸门）             │
│ mcp_bridge（HTTP+token） · flow_pack / flow_trust       │
│ blocks/（A/B/C 三档积木） · browser/（CDP+Drission 双引擎）│
└─────────────────────────────────────────────────────────┘
```

### ServerApi 门面（新增 `backend/server.py` 内）

只实现 `mcp_bridge.dispatch()` 实际触达的方法：
`list_flows`、`run_flow`、`stop_flow`、`pause_flow`、`resume_flow`、
`capture_desktop`（→ 无头报错），外加 interpreter 状态查询。
运行链复用 `Api.run_flow` 的非 UI 部分——把"校验 + 参数校验 + 解释器启动"
抽成共用函数（放 `backend/core/flow_runner.py`），`Api` 与 `ServerApi` 都调它，
不复制逻辑。**不 import `backend.api`**（其顶层 `import webview` 在无 GUI 的
Linux 上会炸，一期 Windows 虽无此问题也不引入该依赖）。

emit 回调接入"通知汇"（见下文），替代桌面版的 UI 事件队列。

### requires 校验点（一处生效，全链覆盖）

- `registry.py` 注册时记录 `requires`；`interpreter` 逐节点执行前、
  `run_block_once`（MCP run_block）入口各查一次，无头模式下 C 档拒绝、
  B 档按参数判定；
- 报错口径统一：`"积木 {type} 需要真机桌面，服务器形态不可用"`（对 agent
  给出可读原因，避免反复重试）；
- `tool_catalog.list_blocks` 增加运行环境过滤：无头模式默认不返回 C 档
  （同现有 CRITICAL_TYPES 不进目录的口径），B 档返回并附带限制说明。

### 运行模式与数据目录

- 新增 `backend/core/host_mode.py`：`is_headless()`（由 `backend/server.py`
  入口置位），供 registry / tool_catalog / mcp_bridge 查询；桌面版零感知。
- `paths.py` 增加 `NEXUZ_DATA_DIR` 环境变量覆盖，优先级：
  **env > config.json `data_dir` > `%LOCALAPPDATA%\Nexuz`**（env 最高，因为
  服务器场景 config 本身可能就落在不想用的默认位置）。流程库即
  `data_dir/flows`，部署流程 = 往目录里放 `.flow.json`（git pull / scp 同步）。

### 通知汇（定时任务的外发）

新增 `backend/core/notify_sink.py`，替代桌面版 UI 事件队列：

- 默认 sink：写 `log_hub` 日志（headless 下必开）；
- 可选 sink：webhook POST（config.json `[server] webhook_url`），事件至少含
  `schedule_fired`、`schedule_finished`（带 ok/error/耗时）、`flow_failed`；
  失败重试 1 次，超时 10s，绝不阻塞调度线程（异步发送）；
- `scheduler.set_emit` 在服务器入口指向 notify_sink，桌面版路径不变。

## 远程 agent 接入

### 一期：stdio 壳远程转发（改动最小）

`nexuz_mcp.py` 增加 `NEXUZ_HTTP_URL` + `NEXUZ_TOKEN` 环境变量：设置后跳过
port.json 发现与唤醒逻辑，直接转发到远端 `/rpc`。客户端配置：

```
claude mcp add nexuz --env NEXUZ_HTTP_URL=https://nx.example.com
                      --env NEXUZ_TOKEN=*** -- python nexuz_mcp.py
```

壳内工具描述按需微调：远端模式下 `capture_screen` / `locate_text_on_screen`
提示不可用（服务端本就会明确报错，双保险）。

### 二期（可选）：服务端原生 streamable HTTP MCP

在 mcp_bridge 增加 `/mcp` 端点（协议 2025-03-26+ streamable HTTP），客户端
`--transport http` 直连，省掉 stdio 壳进程。现有 shell 已兼容多协议版本，
工具清单与 dispatch 完全复用。

## 安全模型

| 项 | 桌面版现状 | 服务器版 |
| --- | --- | --- |
| 鉴权 | Bearer token，token 经本机 port.json 传递（本机信任边界） | token 启动时生成并持久化到数据目录 `server/token`（常驻进程重启不变，除非轮换）；`--token-file` 可注入外部 secret |
| 监听 | `127.0.0.1` 固定 | 默认 `127.0.0.1`；`--host 0.0.0.0` 必须显式指定，日志告警提示建议走反代 |
| 传输 | 明文本地 | 公网必须 HTTPS（nginx/caddy 反代终止 TLS），文档给反代配置样例 |
| 策略闸 | MCP_FLOOR_DENY + policy floor 传播 | 原样保留，服务器版不放松；C 档拒绝叠加在其上 |
| 隔离 | 用户桌面进程 | 建议专用 Windows 账号 + VM/容器；数据目录最小权限 |
| 滥用面 | — | 现有并发槽位（503）、请求体上限、看门狗超时直接复用；审计日志（`mcp_run_block` / `mcp_run_flow` 事件）保留 |

## 分期路线

### 一期（0.22.0）：Linux（WSL Ubuntu）/ Windows 无头服务器 + Web 界面

范围：`backend/server.py` 入口 + ServerApi 门面 + `flow_runner.py` 抽取 +
requires 标记与校验 + `host_mode.py` + `NEXUZ_DATA_DIR` + notify_sink +
`nexuz_mcp.py` 远程转发（`NEXUZ_HTTP_URL`）+ **Linux 导入消毒**（`ctypes.wintypes`
三处守卫、DPAPI 结构体跨平台化、`mss/pyautogui` 懒加载）+ **前端复用**
（bridge.js HTTP 传输层 + `/api/<method>` 白名单 + `frontend/dist` 静态托管）+
MCP 新工具 `list_schedules` / `recent_runs`。

验收标准：

1. `python backend/server.py` 在 WSL Ubuntu（无桌面依赖）常驻，`/health` 可探活；
2. 浏览器打开 `http://服务器:端口/` 得到完整 Web 界面（流程库/编辑/定时/运行），
   输入 token 后可对服务器流程做增删改查与运行；
3. 远程 agent 经 stdio 壳完成一次"部署流程 → run_flow → 定时注册"闭环，
   全程无屏幕参与（浏览器积木走 headless Chromium）；
4. C 档积木在 run_block 与 run_flow 两条路径都被明确拒绝，报错含"需要真机"；
5. 定时任务跨重启恢复（jobs.json 已支持），失败事件进 failures.jsonl 并触发 webhook；
6. 桌面版回归零变化：现有后端测试全过（真机积木测试标记 skip-if-headless，
   桌面环境下照常跑）。

### 部署（WSL Ubuntu / Linux）

```bash
# 1. 依赖（无需任何桌面库）
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-server.txt

# 2. 前端构建产物（在开发机上 npm run build 后随代码同步，或在服务器上构建）
cd frontend && npm ci && npm run build && cd ..

# 3. 数据目录与 token
sudo mkdir -p /var/lib/nexuz /etc/nexuz
echo "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" | sudo tee /etc/nexuz/token

# 4. 常驻（systemd 单元见 deploy/nexuz-server.service）
sudo cp deploy/nexuz-server.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now nexuz-server

# 5. 验证
curl http://127.0.0.1:9800/health
# 浏览器打开 http://127.0.0.1:9800/ → 输入 /etc/nexuz/token 里的 token
```

Windows 上直接 `python backend/server.py` 即可，无需 service 配置
（NSSM/任务计划注册开机自启可选）。

## 打包分流（桌面 / 服务器产物互不混入）

| | 桌面版 | 服务器版 |
| --- | --- | --- |
| 前端构建 | `npm run build` → `frontend/dist` | `npm run build:server` → `frontend/dist-server` |
| 烘焙目标标记 | `__NEXUZ_TARGET__ = "desktop"` | `__NEXUZ_TARGET__ = "server"` |
| 前端积木配置 | 桌面运行时 `get_block_registry` 返回全部积木 | 服务端按 `requires` 过滤（A/B 档 ~57 个），面板即服务器配置 |
| 服务器桥接代码 | **编译期 tree-shake 掉**（产物中无 `/api`、无 token 逻辑） | 包含完整 `/api` 桥 |
| Python 侧 | PyInstaller 打包，`--exclude-module backend.server backend.core.notify_sink` + 产物 xref 扫描验证（`package.py verify_no_server_modules`） | 源码/venv 直接跑 `backend/server.py`，依赖 `requirements-server.txt`（零桌面库） |
| 托管产物 | — | `_dist_dir()` 优先 `dist-server`，回退 `dist` |

守门措施（双层）：

1. `backend/test_packaging_split.py` — AST 静态检查：除 `server.py` 自身，
   任何 backend 源文件不得 import `backend.server` / `backend.core.notify_sink`；
2. `package.py` — PyInstaller `--exclude-module` 显式排除 + 构建后扫描
   xref 引用表，发现混入直接报错终止打包。

### 三期：服务器编排 + 真机反向代理

服务器不只"没有真机能力"，而是**指挥多台真机**：真机上的 Nexuz 以出站连接
注册到服务器（复用现有 token HTTP 桥反向使用），服务器新增积木
`remote_dispatch`（把 C 档积木路由到指定真机执行并回传结果）。策略闸与审计
随任务下发传播。此项单独立项设计，一期只保证架构不为它关死门。

## 测试策略

- 复用现有 554 例：A/B 档积木、interpreter、scheduler、execution_policy、
  llm_bridge、mcp_bridge 测试在无头模式下原样跑（它们本就不依赖显示器）；
- 新增：`test_server_entry.py`（ServerApi 门面 / /health / 鉴权）、
  `test_requires_gate.py`（C 档拒绝口径、B 档参数级判定、目录过滤）、
  `test_notify_sink.py`（webhook 事件与失败重试）、
  `test_paths_env.py`（NEXUZ_DATA_DIR 优先级）；
- mcp_bridge 现有测试加无头模式参数化（capture_screen 报错、目录裁剪断言）。

## 文件布局

新增：

- `backend/server.py` — 无头入口（argparse：--host/--port/--data-dir/--token-file/--webhook-url）+ ServerApi 门面（前端桥接方法子集 + 事件队列）
- `backend/core/flow_runner.py` — 从 Api.run_flow 抽出的共用运行链
- `backend/core/host_mode.py` — 运行模式标记（is_headless / requires 分档判定）
- `backend/core/notify_sink.py` — 日志 + webhook 通知汇
- `requirements-server.txt` — 服务器依赖（零桌面库）
- `deploy/nexuz-server.service` — systemd 单元（WSL Ubuntu / Linux）

修改：

- `frontend/src/bridge.js` — HTTP 传输层：无 pywebview 时走同源
  `POST /api/<method>`（token 经 localStorage，401 引导输入；纯客户端方法
  保留本地实现；后端不可达回落浏览器 mock）
- `backend/core/mcp_bridge.py` — `SERVER_API_METHODS` 白名单端点 +
  `frontend/dist` 静态托管（无头 only，桌面 404 不变）+ token 持久化 /
  --host 配置 / 无头下工具报错与目录裁剪 + `list_schedules` / `recent_runs` 工具
- `backend/paths.py` — NEXUZ_DATA_DIR 环境变量优先级
- `backend/core/registry.py` — requires 记录与环境过滤
- `backend/core/interpreter.py` / `backend/core/ai/run_block.py` — requires 校验点
- `nexuz_mcp.py` — NEXUZ_HTTP_URL / NEXUZ_TOKEN 远程转发
- 17 个 C 档 + 10 个 B 档积木的 SCHEMA — `requires` 标记
- Linux 导入消毒：`core/window_coords.py` / `core/dpi.py` /
  `core/browser/cdp_backend.py` / `core/ai/api_key_crypto.py` 的 wintypes
  守卫；`blocks/_helpers.py` 与 type_text/key_press/mouse_scroll 的
  mss/pyautogui 懒加载
- `backend/core/scheduler.py` — emit 默认接 notify_sink（桌面版 set_emit 覆盖，行为不变）

## 开放问题

1. **多 agent 并发**：单解释器 + `_run_lock` 串行已够一期；是否需要任务排队
   队列与优先级，视真实使用再定。
2. **多 token / 只读 token**：一期单 token；若要区分"可执行"与"只读监控"
   角色，在鉴权层加 scope，不动 dispatch。
3. **流程库版本管理**：目录即库 + git 同步一期够用；是否做服务端流程版本
   快照/回滚，待定时任务规模上来再议。
4. **浏览器会话生命周期**：headless Chromium 常驻还是按需拉起，跟随现有
   session 策略，一期不改，实测内存占用后再定。
