# 市场部 AI 知识库前端（T08）

React 19 + TypeScript 5.9 + Vite 8 前端，对接现有 FastAPI 后端（`/api/v1`）。本目录只包含前端与浏览器测试，不包含后端源码、模型或 OCR 凭据。

## 运行

```powershell
# 1) 在项目根目录启动后端（示例，需先准备测试账号/数据库；不要使用生产数据）
.\.venv\Scripts\python.exe -B -m uvicorn mktkb.main:create_app --factory --host 127.0.0.1 --port 8077

# 2) 安装并启动前端
npm.cmd --prefix frontend install
npm.cmd --prefix frontend run dev
# 打开 http://127.0.0.1:5173
```

Vite 将 `/api` 代理到 `http://127.0.0.1:8077`，浏览器侧保持同源，Cookie、Origin 与 CSRF 语义与生产反向代理一致。后端需要把前端来源加入 `MKTKB_TRUSTED_ORIGINS`（本地为 `http://127.0.0.1:5173`），本地 HTTP 需 `MKTKB_COOKIE_SECURE=false`。

生产部署时应由同一来源的静态服务器提供 `dist/`，并把 `/api` 反向代理到 FastAPI；`BrowserRouter` 需要回退到 `index.html`（例如 nginx `try_files $uri /index.html`）。

## 脚本

| 命令 | 说明 |
| --- | --- |
| `npm run dev` | Vite 开发服务器（127.0.0.1:5173） |
| `npm run typecheck` | TypeScript 严格检查（含 e2e） |
| `npm run build` | 类型检查 + 生产构建到 `dist/` |
| `npm run test:e2e` | Playwright 浏览器测试（自动启动受控后端与 Vite） |
| `npm run api:types` | 从 `../docs/evidence/T08/api/openapi.json` 生成 `src/api/schema.d.ts` |

OpenAPI 快照由项目根目录 `tools/export_openapi.py` 生成：

```powershell
.\.venv\Scripts\python.exe -B tools/export_openapi.py --output docs/evidence/T08/api/openapi.json
npm.cmd --prefix frontend run api:types
```

## 浏览器测试结构

- `e2e/global.setup.ts`：通过真实 HTTP 登录测试账号，上传 T01 冻结语料中的 D01/D02/D03/D05/D06，运行单次 worker 并发布，保存登录态到 `e2e/.auth/`。
- `e2e/support/stub_server.py`：真实 FastAPI + 真实 SQLite/解析，模型网关为“只回显本次证据字段/文本”的受控替身；OCR 固定模拟额度不足；另提供仅测试可见的 `/__t08__/control`（模型故障/延迟注入）。
- `e2e/support/worker_stub.py`：真实单次 worker 流程，仅注入“OCR 额度不足”替身。
- `e2e/01-auth`、`02-chat`、`03-documents`、`04-kinds-and-isolation`：功能链路（仅 `functional` 项目运行，串行）。
- `e2e/05-responsive`：390×844 与 375×844；`06-layout`：1440×900、1366×768、1440×720。
- 截图写入 `../docs/evidence/T08/screenshots/<project>/`。

> 测试数据目录 `frontend/.e2e-data/` 每次运行由测试后端重建，属于可丢弃数据；不要放入需要保留的资料。

## 已知接口缺口（前端未伪造）

1. 冲突结果的 `sources` 为空，冲突条目里的 `source_id` 不能通过 `/messages/{id}/sources/{source_id}` 读取（404）。界面显示两个取值，但无法打开冲突来源的文件名/定位。
2. `GET /conversations/{id}/messages` 不返回 `candidates`/`conflicts`，历史消息刷新后只能保留文本与来源；候选与冲突明细仅在本次回答结果中展示。
3. 文档详情/列表不返回任务编号；刷新或换标签页后无法从检查抽屉重试失败任务（本次会话上传记录保存在 `sessionStorage`）。
4. 员工没有公开的“知识库是否为空”接口；空库提示只在管理员端根据资料列表判断，员工端通过“无匹配资料”表达。
5. 来源原件对 Office 文件通常是下载而非页内预览；链接为受保护接口，失效/他人来源由服务端拒绝。

## 约束

- 不在浏览器保存/展示模型或 OCR 密钥；前端没有任何供应商配置。
- 不使用模拟按钮冒充业务结果：所有列表、状态、回答与来源均来自后端响应。
- 移动端只提供登录、问答、个人会话与来源查看；资料管理在移动端明确提示使用电脑。
