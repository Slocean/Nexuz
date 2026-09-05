# Nexuz

Windows 桌面自动化平台（MVP）：可视化拖拽与 JSON 同源编排，积木化 Block 能力可插拔。

## 技术栈

- 桌面容器：pywebview（WebView2）
- 前端：React + Vite + CanvasFlow + Monaco + Zustand + shadcn/ui
- 后端：Python（pyautogui / pynput / mss / Pillow）

## 环境要求

- Windows 10/11
- Python 3.10+
- Node.js 18+
- WebView2 Runtime（Win10/11 一般已自带）

## 安装

```bash
# 后端依赖
python -m pip install --require-hashes -r requirements-dev.txt

# 前端依赖
cd frontend
npm ci
```

## 开发启动（一键）

在项目根目录执行其一即可（自动拉起 Vite + 桌面窗口）：

```bash
python dev.py
```

或双击 / 运行：

```bash
start.bat
```

关闭桌面窗口后会自动停掉 Vite。仅预览 UI（无真实点击/截图）时可只跑：

```bash
cd frontend
npm run dev
```

也可设置 `NEXUZ_DEV_URL`（默认 `http://127.0.0.1:2342`）。

## 生产/打包前构建

仅构建前端静态资源：

```bash
cd frontend
npm run build
```

然后可用 `python backend/main.py` 加载 `frontend/dist/index.html`。

## 一键打包（Windows exe）

在项目根目录：

```bash
python package.py
```

或：

```bash
package.bat
```

默认产出单文件：`dist/Nexuz.exe`（可直接分发）。

可选参数：

```bash
python package.py --skip-frontend   # 已有 frontend/dist 时跳过 npm build
python package.py --onedir          # 目录模式（exe + _internal，启动更快）
python package.py --version 0.1.1   # 写入版本号再打包（CI 用）
```

首次打包会自动安装 `pyinstaller`。产物含前端 `dist`、schemas、Frida 脚本与 OCR 运行时依赖。

## GitHub 自动打包与 Release

**不需要自备公钥/私钥。** Action 使用仓库内置的 `GITHUB_TOKEN` 创建 Release 并上传 `Nexuz.exe`（HTTPS）。若以后要 Windows 代码签名或更新包验签，再单独配置证书即可，当前热更新不依赖。

发版前改好 [`app_update.json`](app_update.json) 并 `git push` 到 `main`，然后本地执行：

```bash
release.bat
# 或
python trigger_release.py
```

会打 `v版本号` 的 tag 并推送，GitHub Action 自动打包上传 Release。**不需要安装 gh，也不需要代码签名证书。**

Release 正文只写入 [`app_update.json`](app_update.json) 里**当前发版版本**那一条的 `title` / `body`，不会再用 GitHub 自动 Changelog 链接，也不会把历史版本全塞进去。

进度：https://github.com/Slocean/Nexuz/actions  
成品：https://github.com/Slocean/Nexuz/releases

### 客户端热更新与通知

- 通道文件：[`app_update.json`](app_update.json)（累计 `history`）
- **检查更新**：顶栏 ↑，或「设置 → 关于与更新」
- **热更新**：下载 Release 中的 `Nexuz.exe`，校验固定仓库域名与 `Nexuz.exe.sha256` 后替换并重启（仅打包后的 exe；**不要求** Authenticode / 代码签名证书）
- **通知**（喇叭 / 启动弹窗）：读取 `history[].notice`；当前条为空则沿用上一条非空通知；点「我知道了」后同内容不再弹，直到出现新通知
- **版本更新记录**：仅在「设置 → 更新公告」查看（`title` / `body`）

发版时在 `history` **最前面**追加一条（不要删旧记录）：

```json
{
  "history": [
    {
      "version": "0.1.4",
      "title": "0.1.4 标题",
      "body": "版本更新说明（设置页展示）",
      "notice": "给用户的通知说明（喇叭/启动弹窗；可留空沿用上一条）"
    },
    {
      "version": "0.1.3",
      "title": "……",
      "body": "……",
      "notice": ""
    }
  ]
}
```

最新版本 = `history[0].version`。

## 界面

- **默认前端**：`frontend/canvasflow/`（CanvasFlow UI）+ Nexuz 后端 Bridge
- **视图切换**：顶栏「画布 / JSON」双向同步（校验后应用到画布；画布变更可同步回代码）
- **运行控制**：运行 / 暂停 / 继续 / 停止 / **单步** / **断点**（调试模式 + 变量监视）
- **积木面板**：支持搜索过滤
- **逻辑/功能**：store / bridge / 执行引擎（录制、保存/打开、Schema 参数表单）
- **导入导出**：`.flow.json` 或含模板图的 `.flow.zip`
- **未接入的设计稿控件**（如 Flow AI Helper、原 AI 积木卡片）保留不动

主题偏好保存在 `localStorage`（`nexuz.themeName` / `nexuz.themeMode`）。

| 类别 | Block                                                                                                                                |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------ |
| 动作 | click / **mouse_hover** / drag / key_press / type_text / delay / **wait_until**                                                      |
| 识别 | color_detect / if_color_match / ocr_recognize / **locate_text** / if_text_contains / find_image / **screenshot**                     |
| 浏览器 | **browser_navigate** / **browser_extract** / **browser_click** / **browser_fill** / **browser_screenshot** / **browser_wait** / **browser_eval** / **browser_close** |
| 控制 | if*condition / switch / loop*\* / **try_catch** / **schedule_trigger** / **monitor_start** / **monitor_wait** / **monitor_check** / **monitor_stop** / **monitor_list** / **call_subflow** / **assign** |
| 系统 | http_request / clipboard / file_io / run_command / notify / python_script / **window_wait** / **window_activate** / **window_close** / **system_info** / **sys_path** / **env_var** / **process_list** / **process_kill** / **open_path** / **disk_info** / **zip_archive** / **power_action** / **volume_action** / **timestamp** / **file_manage** |
| 平台 | 画布↔JSON（可自动同步）、变量面板、参数表单、运行控制、分类日志（运行/系统/操作/诊断）、保存加载、录制、定时任务落盘                 |

## 使用提示

1. 从左侧积木拖到画布，或双击添加
2. 连线：普通节点用 `next`；条件节点有「是/否」；循环节点右侧为 `body`，循环体跑完会自动回到循环节点；画布会显示循环体范围框
3. 右键节点可设为入口；右侧可「点击选取」坐标/区域；窗口积木用「选取窗口」
4. 切换到 JSON 视图可直接编辑，校验通过后自动同步画布
5. 录制：点「录制」后在屏幕操作，再点「停止录制」追加节点；设置「目标窗口相对」后，窗口挪了回放仍能点对
6. **数据绑定以右侧面板为主**：画布只显示少量主数据口（如 `x/y/found`）；`boxes/matches` 等复杂字段在输出区复制引用。顶栏「数据连线」默认关闭，需要时再开
7. **OCR 找字点击**：填「匹配文字」→ 输出 `found/x/y`；点击 X/Y 绑 `{{ocr.x}}` / `{{ocr.y}}`
8. **一次识别多字**：在「匹配多字」每行填一个目标 → 输出 `matches`；点击可用 `{{ocr.matches.0.x}}`。或 OCR 一次后用多个 **文字定位**（`locate_text`）绑 `{{ocr.boxes}}`，不重复截屏
9. **多点/序列**：点击、按键、取色支持「多点/序列」模式——一次配置多个目标、顺序与间隔，不必拖一串相同节点
10. 需要自定义变量名时用 **赋值变量**（`assign`）
11. **调试**：开调试 → 节点左侧设断点 → 运行；暂停时右上角可「继续」，并有可折叠的变量监视
12. **分享流程**：导出 `.flow.zip` 可带上找图模板；导入时自动解压并改写路径
13. **插件模式**：标题栏窗口图标可开启——浮在无边框全屏游戏之上、半透明可调；默认 `X+F6` 开关插件模式、`X+F7` 开关点击穿透（均可在设置 → 快捷键中改键）。独占全屏点到本窗口时仍可能退出全屏
14. **日志分类**：右侧默认只看「运行」；点芯片可切换系统/操作/诊断。行可展开入参出参摘要；设置里「记录诊断日志」默认关闭。导出可区分「当前显示 / 完整运行日志 / 应用日志（系统+操作）」
15. **浏览器积木（爬虫/自动化）**：「浏览器」分类的 browser_* 积木驱动本机 Edge/Chrome（默认无头、独立隔离 profile，不含你的登录态）；首次使用自动拉起浏览器，流程结束自动关闭（设置 → 浏览器引擎 可改引擎/keep-alive/浏览器路径）。选择器用 CSS 语法
16. **系统积木**：系统信息 / 系统路径 / 环境变量 / 进程列表 / 结束进程 / 打开路径网址 / 磁盘空间 / 压缩解压 / 电源操作 / 音量控制 / 时间戳。结束进程按名称为精确匹配且硬拒绝系统关键进程；电源操作、结束进程、压缩解压、打开路径属高权限积木，流程安全模式（safe）下会被拦截，需 standard/legacy 放行
17. **文件整理**（`file_manage`）：移动 / 复制 / 重命名 / 新建文件夹 / 列出目录内容，来源可多个（一行一个），目标已存在默认报错、显式开启才覆盖；不含删除类操作。素材等比缩放（`image_scale`）默认缩放模式为「统一到目标尺寸」（裁透明边 + 脚底居中立绘标准），按比例缩放可手动切回

## 外部 AI 接入（MCP）

Nexuz 内置 MCP 桥，可把积木能力（截图 / OCR / 点击 / 按键 / 执行流程等）开放给本机 AI 编码代理（Claude Code、zcode 等）。执行全部发生在正在运行的 Nexuz 应用内；应用未运行时，壳进程会自动拉起。

```text
Claude Code / zcode
   │ stdio (JSON-RPC)
nexuz_mcp.py（壳，纯标准库；应用不在线时自动唤醒）
   │ HTTP 127.0.0.1 + 随机 token
Nexuz 应用内 mcp_bridge（积木白名单 + 安全闸 + 审计）
```

接入（源码模式）：

```bash
claude mcp add nexuz -- python E:\Project\Nexuz\nexuz_mcp.py
```

打包版（exe）需额外用 `NEXUZ_EXE` 告诉壳去哪唤醒应用（壳本身仍需本机 Python 运行）：

```bash
claude mcp add nexuz --env NEXUZ_EXE=C:\path\to\Nexuz.exe -- python E:\Project\Nexuz\nexuz_mcp.py
```

设置 →「MCP / 外部 AI」卡片可开关服务、查看运行状态、一键复制接入命令。

给接入的 AI 代理装上随仓库发布的技能可以让它直接按正确姿势调用（调用顺序、执行边界、坐标纪律等）：打包版已内置技能与壳进程脚本——「接入教程」弹窗里可**一键安装技能**到 zcode / Claude Code，接入命令会自动释放壳文件；也可把 [.agents/skills/nexuz-mcp/](.agents/skills/nexuz-mcp/SKILL.md) 整个目录拷到你自己的 `~/.agents/skills/nexuz-mcp/`（Claude Code 为 `~/.claude/skills/`）。Release 资产附带 `nexuz_mcp.py` 与 `nexuz-mcp-skill.zip`（内含 `nexuz-mcp/SKILL.md`，解压到 skills 目录即完成安装）。

### 工具一览

| 工具 | 用途 |
| ---- | ---- |
| `get_status` | 版本、是否正在执行流程、应用内 AI 开关状态（不约束外部 AI） |
| `list_blocks` | 按分类列出可执行积木（编排 / 执行前先调用了解平台能力） |
| `get_block_schema` | 单个积木的完整 inputs / outputs，据此填写 `run_block` 的 params |
| `run_block` | 实时执行单个积木并返回结果（受下方「执行边界」约束） |
| `run_flow` / `list_flows` / `flow_control` | 执行流程库中的流程 / 列出流程 / 急停·暂停·继续 |
| `capture_screen` / `locate_text_on_screen` | 截取屏幕 + OCR 找字定位，返回真实坐标（配合 `shot_ref` 复用截图） |
| `reset_session` | 清空跨调用的 `{{变量}}` 上下文 |

### run_block 执行边界

外部 AI 的授权由所接入的 AI 客户端负责（工具审批），**不需要**在 Nexuz 里开任何开关；设置 → Nexuz AI 的「允许 AI 实时执行积木 / 允许高危积木」只约束应用内 AI。`run_block` 的硬边界：

- **全部可执行**：除下方拒绝清单外的所有积木——桌面动作（`click` `key_press` `type_text` 等）、文件 / 网络（`file_io` `file_manage` `http_request` 等）、图片处理（`image_generate` `image_rename` `image_scale` `transparent_cut` `sprite_sheet_cut` `sprite_part_cut`）、浏览器（`browser_*`）、系统（`env_var` `open_path` `process_kill` 等）、只读观察类（`screenshot` `ocr_recognize` `find_image` 等）
- **始终拒绝**（无开关可绕）：`python_script`、`run_command`（危险命令类）、`power_action`（关机/重启）、控制流（`if_*` / `loop_*` / `switch` / `try_catch`）、用户自定义插件

其他约束：等待类参数会被钳制（`delay` / `wait_until` / `monitor_wait` 等单次 ≤ 60s，单次 handler 执行 ≤ 90s），防止外部 AI 挂死应用。长时间监听用「监控与唤醒」组合：`monitor_start` 注册条件（进程/窗口/文件/屏幕），`monitor_wait` 长轮询（事件一出现调用即返回，等效被唤醒）或 `monitor_check` 配客户端定时任务周期唤醒。

### run_flow 执行边界

`run_flow`（内联 JSON 或流程库文件）不需要开关，但外部 AI 触发的执行会套用一道**策略下限**：流程内含 `python_script` / `run_command` / `power_action` / 自定义积木时整体拒绝——静态预扫描即时报错，运行期再由随流程传播的 `__policy_floor__` 标记逐节点强制，覆盖 `call_subflow` 嵌套加载的子流程；外部 AI 注册的定时任务在**每次触发**时重新套用下限（杜绝注册后改写流程文件的绕行）。流程自身声明的执行策略仍然生效（safe 模式拦截 elevated 积木等），但只能加严、不能削弱下限。其余正常积木全部放行。

### 推荐 agent 调用顺序

1. `get_status` 确认服务在线；被拒时按错误提示处理（危险命令类拒绝不可解除，agent 不应尝试绕过）
2. `list_blocks` → `get_block_schema` 查清积木与参数，再发起 `run_block`
3. 涉及屏幕坐标：先 `capture_screen` + `locate_text_on_screen` 获取真实坐标，**禁止臆造坐标**
4. `run_block` 的输出按 `{{ai_run_N.输出名}}`（N 为本次会话内的调用序号）进入上下文，后续调用可绑定引用；`reset_session` 可清空

**安全模型**：

- 服务仅监听 `127.0.0.1`，token 每次应用启动随机生成，只经 `%LOCALAPPDATA%\Nexuz\mcp\port.json` 分发
- 外部 AI 无法执行危险命令类：`run_block` 白名单硬拒；`run_flow` 靠策略下限逐节点强制（含子流程递归、定时任务再触发、注册后改写文件等绕行路径均已封堵）
- `run_flow` 走完整执行链（参数校验 + 执行策略预扫描 + 解释器逐节点闸），流程自身的 safe/standard 策略不受影响
- 每次执行写入审计日志（`data_dir/ai/audit/`，按日分文件；`mcp_run_flow` 含积木类型清单与策略档）；设置页可随时整体关闭服务

**当前限制**：MCP 触发的流程与手动运行互斥（同一时刻仅一条流程）；壳进程需要本机 Python（壳独立打包 exe 留待后续版本）；应用多开时后启动的实例接管端口文件。

## 示例流程

- [`examples/demo_color_loop.flow.json`](examples/demo_color_loop.flow.json)：delay / 取色 / 循环（几乎无副作用）
- [`examples/demo_ocr_click.flow.json`](examples/demo_ocr_click.flow.json)：OCR 匹配文字 → 赋值变量 → 点击坐标
- [`examples/demo_ocr_multi.flow.json`](examples/demo_ocr_multi.flow.json)：一次 OCR 多字 + `matches.i.x` + `locate_text` 复用 boxes

## 目录

```
Nexuz/
├── frontend/          # React UI
├── backend/
│   ├── blocks/        # Block Schema + Handler
│   ├── core/          # 注册表 / 引擎 / 变量 / 录制 / DPI
│   ├── api.py         # JS-Bridge
│   └── main.py
├── schemas/
├── examples/
└── requirements.txt
```

## 新增 Block

在 `backend/blocks/` 新增 `.py`，导出 `SCHEMA` 与 `handler`，重启程序后自动出现在积木面板（前端按 Schema 生成表单）。
