# Nexuz 无头服务器镜像（后端项目流水线用）
# 阶段 1：构建前端两份产物（dist 桌面 / dist-server 服务器）
# 阶段 2：Python 运行时，server.py 自己托管 dist-server + /api + /rpc

FROM node:22-alpine AS web
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build && npm run build:server

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    NEXUZ_DATA_DIR=/data

COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt

COPY backend ./backend
COPY schemas ./schemas
COPY app_update.json ./
COPY --from=web /build/dist-server ./frontend/dist-server

# 数据目录：平台若支持持久卷请挂载到 /data（流程库/定时任务/config 都在其中）
VOLUME /data

# 健康探测：GET /health（秒级就绪，平台 30 秒探测窗口足够）
# 端口：server.py 自动读 PORT 环境变量；主密钥：NEXUZ_TOKEN 环境变量（平台"自动密钥"注入）
CMD ["python", "backend/server.py", "--host", "0.0.0.0"]
