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
python -m pip install -r requirements.txt

# 前端依赖
cd frontend
npm install
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

也可设置 `NEXUZ_DEV_URL`（默认 `http://127.0.0.1:5173`）。

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

会打 `v版本号` 的 tag 并推送，GitHub Action 自动打包上传 Release。**不需要安装 gh。**

Release 正文只写入 [`app_update.json`](app_update.json) 里**当前发版版本**那一条的 `title` / `body`，不会再用 GitHub 自动 Changelog 链接，也不会把历史版本全塞进去。

进度：https://github.com/Slocean/Nexuz/actions  
成品：https://github.com/Slocean/Nexuz/releases

### Windows 代码签名

未签名 exe 容易被 Defender 删。配置方法见 [`docs/WINDOWS_SIGNING.md`](docs/WINDOWS_SIGNING.md)。  
在 GitHub Secrets 填入 `WINDOWS_CERTIFICATE` + `WINDOWS_CERTIFICATE_PASSWORD` 后，Release Action 会自动签名。

### 客户端热更新与通知

- 通道文件：[`app_update.json`](app_update.json)（累计 `history`）
- **检查更新**：顶栏 ↑，或「设置 → 关于与更新」
- **热更新**：下载 Release 中的 `Nexuz.exe` →「立即更新」替换并重启（仅打包后的 exe）
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


| 类别 | Block |
|------|--------|
| 动作 | click / **mouse_hover** / drag / key_press / type_text / delay / **wait_until** |
| 识别 | color_detect / if_color_match / ocr_recognize / **locate_text** / if_text_contains / find_image / **screenshot** |
| 控制 | if_condition / switch / loop_* / **schedule_trigger** / **call_subflow** / **assign** |
| 系统 | http_request / clipboard / file_io / run_command / notify / python_script / **window_wait** / **window_activate** / **window_close** |
| 平台 | 画布↔JSON（可自动同步）、变量面板、参数表单、运行控制、日志、保存加载、录制、定时任务落盘 |

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
13. **插件模式**：标题栏窗口图标可开启——浮在无边框全屏游戏之上、半透明可调；「点击穿透」后可操作下层游戏，按 `X+F9` 开关穿透。独占全屏点到本窗口时仍可能退出全屏

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
