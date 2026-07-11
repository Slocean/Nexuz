# CanvasFlow（独立 UI）

本目录从 `UI_Design/canvasflow` 复制而来，与主程序 UI（`frontend/src/`）**分属两个文件夹**，互不合并。

- 主程序：`frontend/src/`（Nexuz 自动化编排）
- 本 UI：`frontend/canvasflow/`（CanvasFlow 设计稿演示）

由 `frontend/src/Shell.jsx` 负责页面切换：主程序顶栏「CanvasFlow」进入本页，本页顶栏「主程序」返回。

独立运行本 demo（可选，需本目录依赖与 server）：

```bash
cd frontend/canvasflow
npm install
npm run dev
```

嵌入主 Vite 应用时，请使用仓库根下的 `frontend/` 启动：`npm run dev`。
