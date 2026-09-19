# 平台部署指南（容器化 PaaS：zip 上传 + docker build + Caddy/端口映射）

对应平台说明（后端项目 = 源码 + Dockerfile；前端项目 = 静态产物）。Nexuz 服务器
是**后端项目**——单条流水线即可，Web 界面由 server.py 自己托管（`/` 出前端、
`/api` 桥接、`/rpc` MCP、`/health` 探活全部同源），不需要单独的前端流水线。

## 流水线配置

| 平台配置项 | 填什么 |
| --- | --- |
| 流水线标识 | `nexuz`（正式）/ `nexuz-test`（测试，平台自动加 -test 域名） |
| 项目类型 | 后端项目（容器化服务） |
| 上传包 | 仓库源码打 zip（**已含 Dockerfile**；.dockerignore 会把 node_modules 等排除在构建上下文外） |
| 对外端口 | 留空——server.py 自动读平台注入的 `PORT` 环境变量（本地兜底 8080） |
| 自动建库 | **不勾**（Nexuz 是文件存储：流程库/定时任务/config 都在数据目录，不需要 PostgreSQL） |
| 自动密钥 | 变量名填 `NEXUZ_TOKEN`——平台生成的强随机值就是**主密钥**，每次部署复用 |

部署完成后平台会探测 `/health`（秒级就绪，30 秒窗口足够）。

## 首次使用（三步）

1. 打开 `http://<流水线域名>/` → 输入主密钥（= 平台"自动密钥"里的 NEXUZ_TOKEN 值）
2. 设置 → **API 密钥** → 生成密钥：勾选能力（积木目录/执行积木/运行流程/流程库/
   定时任务/运行记录），可选填积木白名单（如 `smtp_send,http_request`，留空不限）
3. 把明文 key（`nxz_…`，仅显示一次）交给调用方——程序走 `/api`，agent 走 MCP

## 程序调用（带 API Key 的 HTTP）

```bash
KEY=nxz_xxxxxxxx        # Web 界面签发的分权密钥
BASE=http://<流水线域名>

# 单积木直调（同步返回结果；受密钥的 scope 与积木白名单约束）
curl -X POST $BASE/api/run_block -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"args":[{"type":"smtp_send","params":{ ... }}]}'

# 跑整条流程（异步启动，轮询 is_running / drain_ui_events 拿进度）
curl -X POST $BASE/api/run_flow -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"args":[{ "flow_id":"r1", "name":"日报", "nodes":{...}, "entry":"n0" }]}'
```

401 = 没带/带错凭证；403 = 凭证有效但越权（错误信息注明缺哪个能力或哪个积木
不在白名单）。`apikey_*` 管理方法只有主密钥能调。

## Agent 接入（MCP）

MCP 走 `/rpc`，客户端直连本流水线域名：

```
claude mcp add nexuz --env NEXUZ_HTTP_URL=http://<流水线域名> --env NEXUZ_TOKEN=nxz_... -- python nexuz_mcp.py
```

建议给 agent 发**限定能力的 API Key**（而不是主密钥）：agent 只能列目录、查
schema、调白名单内积木、跑流程；签发密钥等管理操作它碰不到。

## 双流水线方案（可选）

若想把静态站拆出去：`npm run build:server` 后把 `frontend/dist-server` 内容打
zip 传到**前端项目**流水线，"API 上游"填后端流水线 id（浏览器侧 `/api/*` 同源
反代，免跨域）。注意 MCP 的 `/rpc` 不在 `/api/*` 反代规则里——agent 仍直连
后端流水线域名。**不推荐**，多一条流水线多一份维护。

## 数据持久性（重要）

容器文件系统随部署重建；`NEXUZ_DATA_DIR=/data`（Dockerfile 已设）放全部状态：

- 平台支持挂持久卷 → 挂到 `/data`，流程库/定时任务/配置全保留；
- 平台不支持 → 每次部署后需要重新放置 `flows/*.flow.json`（流程文件建议自己在
  git 里维护）并重新注册定时任务。config.json（含 API Key 记录）同样在 /data。

## 与桌面包的关系

打包分流互不影响：桌面包（`python package.py`）不含 server 模块与 API Key 功能；
服务器镜像不含桌面依赖。Web 界面的「API 密钥」设置节只在 server 构建里存在
（`__NEXUZ_TARGET__` 烘焙分流），桌面设置页看不到它。
