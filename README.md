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

## 开发启动

需要两个终端：

**终端 1 — 前端 Vite**

```bash
cd frontend
npm run dev
```

**终端 2 — 桌面窗口（连接 Vite）**

```bash
python backend/main.py --dev
```

默认加载 `http://127.0.0.1:5173`。也可设置 `NEXUZ_DEV_URL`。

仅预览 UI（无真实点击/截图）时，可只跑 `npm run dev`，Bridge 会走浏览器 mock。

## 生产/打包前构建

```bash
cd frontend
npm run build
```

然后：

```bash
python backend/main.py
```

会加载 `frontend/dist/index.html`。

## 界面

- **默认前端**：`frontend/canvasflow/`（CanvasFlow UI）+ Nexuz 后端 Bridge  
- **视图切换**：顶栏「画布 / JSON」双向同步（校验后应用到画布；画布变更可同步回代码）  
- **运行控制**：运行 / 暂停 / 继续 / 停止 / **单步**  
- **积木面板**：支持搜索过滤  
- **逻辑/功能**：store / bridge / 执行引擎（录制、保存/打开、Schema 参数表单）  
- **未接入的设计稿控件**（如 Flow AI Helper、原 AI 积木卡片）保留不动  

主题偏好保存在 `localStorage`（`nexuz.themeName` / `nexuz.themeMode`）。


| 类别 | Block |
|------|--------|
| 动作 | click / drag / key_press / type_text / delay |
| 识别 | color_detect / if_color_match |
| 控制 | if_condition / switch / loop_n / loop_while / loop_forever |
| 平台 | 画布↔JSON 双向同步、参数表单、运行/暂停/停止/单步、日志、保存加载、录制 |

## 使用提示

1. 从左侧积木拖到画布，或双击添加
2. 连线：普通节点用 `next`；条件节点有「是/否」；循环节点右侧为 `body`，循环体跑完会自动回到循环节点
3. 右键节点可设为入口；右侧可「点击选取」坐标/区域
4. 切换到 JSON 视图可直接编辑，校验通过后自动同步画布
5. 录制：点「录制」后在屏幕操作，再点「停止录制」追加节点

## 示例流程

见 [`examples/demo_color_loop.flow.json`](examples/demo_color_loop.flow.json)，可在客户端「打开」后运行（会执行 delay / 取色 / 循环，几乎无副作用）。

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
