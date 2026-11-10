# T113 交接单：监控 API（只读聚合，P1 第 13 包）

> 基线：分支 `p1/fix-retrieval`（T100–T107/T101–T106/T108/T109/T110/T111 已收口；T112 待主人指定方案、暂缓）。当前 HEAD 见 `git log -1`。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 0. PM 口径（先读）
1. **只读**：全部端点 `GET`；无写路径；不得改业务库/索引库 schema、不得写 Trace/评测产物、不得改业务 API 字段结构。
2. **权限**：全部端点 `Depends(require_role("admin"))`（沿用 `auth/routes.py:63`）；未登录 401、employee 403 的完整矩阵属 T114，本包至少保证 admin 200 + 依赖正确挂载（T113 可测 admin 与 employee 403）。
3. **不返回原文**：Trace 内容模式为 `hash`（`trace_content_mode=hash`），响应只允许哈希/计数/长度/时长/成本/状态等；**不得返回问题原文、答案原文、上下文正文、SQL/库路径、凭据**。若字段含 `*_json` 属性，需按白名单裁剪或只给聚合。
4. **Holdout 明细不可达**：`runs/{run_id}` 只返回 manifest/summary/gate 聚合；若 manifest `holdout_details=true`（或 run 目录含逐题 cases），**不返回逐题/题干/答案**，只给聚合与 `holdout_detected` 标记；不得通过其他端点间接暴露。
5. **Trace 关闭降级**：`settings.trace_enabled=false` 时 `app.state.trace_repo is None` → 端点返回 200 + 空聚合/说明（`degraded_reason="trace_disabled"`），不得 500。
6. **路径安全**：`run_id`/`trace_id` 严格校验（如 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`）；禁止路径穿越；不存在 → 404。
7. 不改 `conversations/`/业务代码/API schema；零真实调用；不读 `.env`/Holdout；不 push/amend；无 skip/xfail/删断言/新依赖。

## 1. 目标（设计 §6）
实现只读监控 API：`/api/v1/observability/{traces/{trace_id}, requests/{request_id}/traces, metrics?window=24h, runs/{run_id}}`，admin 权限，只返回哈希/计数，不暴露 Holdout 明细，trace 关闭时空聚合并说明。

## 2. 交付物（只准写这些路径）
1. **新增** `backend/src/mktkb/observability/routes.py`：`router = APIRouter(prefix="/observability", tags=["observability"])`，4 端点 + 响应模型（Pydantic，仅哈希/计数/时长/成本/状态）；admin 依赖；trace 关闭降级；窗口解析（`Nh`/`Nm` 等，非法 422）；run/trace id 校验；runs 读取 `settings.data_dir/"eval"/"runs"/<run_id>` 的 manifest/summary/gate.json（只读，缺失 404）。
2. `backend/src/mktkb/main.py`：注册 router（`api.include_router(observability_router)`）。
3. `backend/tests/` 本包测试：admin 200 ×4；employee 403；trace 关闭降级 200；不存在 404；非法 window/run_id 422/400；聚合正确（造 trace 记录后 metrics 计数/P50/P95/tokens/cost/degraded 字段）；**无原文字段**（断言响应 JSON 不含 question/answer 文本字段，只有 hash/chars）；holdout run 仅聚合（manifest `holdout_details=true` 时无逐题）；OpenAPI 含 4 路径；只读（仅 GET 路由，无 POST/PUT/DELETE）。
4. 证据 `docs/reports/OBS-EVAL/P1/evidence/T113/`（≤4）、`report.md`（≤80 行五段）、1 个 commit。
**若指标聚合必须新增 read-only 查询**：允许在 `observability/store.py` 增加**只读聚合方法**（SELECT/只读，不改 schema/写入语义），report §4 单列理由；否则优先不加。
禁止：`conversations/`/业务路由/业务 API/schema/账本/GO/`.env`/Holdout、改动既有 API 字段、新依赖、真实调用、push/amend。

## 3. 验收标准（逐条）
1. **admin 200**：4 端点 admin 会话下 200 且结构字段齐全（traces: trace+spans 摘要；requests: 该 request 的全部 trace 摘要（attempt/replayed/previous_trace_id 关系）；metrics: 按 path/outcome 的 count、P50/P95 latency、tokens、cost、degraded 次数；runs: manifest/summary/gate 聚合）。
2. **只读**：路由仅 GET；请求不产生 DB/文件写入（测试前后 trace 库/业务库 mtime/hash 不变或断言无写调用）。
3. **不返回原文**：所有响应仅哈希/计数/长度/时长/成本/状态；断言无问题/答案原文、无 `*_text`/`question`/`answer` 正文字段；`*_json` 若返回需裁剪为聚合。
4. **Holdout 不可达**：holdout run 只返回聚合 + 标记；无逐题/题干/答案；其他端点也不能间接取到（trace 记录本身无原文）。
5. **OpenAPI 可导出**：`app.openapi()` 含 4 路径与 admin 安全声明；导出 JSON 证据（不落 docs/契约文件，T114 再更新文档）。
6. **降级/错误**：trace 关闭 200 + `degraded_reason`；trace/run 不存在 404；非法 window/run_id 4xx；无 500。
7. **回归/预算**：本包测试 + `backend/tests/observability` + `backend/tests` 全量 0 failed/0 error（内存<2GB 轮询；flake 处理）；b0/badcase/regression local+gate 不受影响（`case_diffs=0`、hard `[]`）；证据 ≤4、report ≤80、1 commit、只改允许路径、无 skip/xfail/删断言/真实调用。

## 4. 必跑
本包测试 / `backend/tests/observability` / 全量；b0+badcase local+gate 对 P0（`case_diffs=0`、hard `[]`）；regression 状态不变。命令口径：pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；`.\.venv\Scripts\python.exe -B -m pytest ... -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`；同一时间只跑一套 pytest。

## 5. 坑
- `create_app(initialize=False)` 用于 OpenAPI 检查：routes 不得在导入时写库/建目录。
- trace 关闭时 `app.state.trace_repo is None`：端点返回空聚合，不要构造仓储。
- metrics 窗口基于 `created_at`（ISO 字符串），解析失败记录为 degraded 而非 500。
- runs 路径用 `settings.data_dir`，不要用硬编码 `var/`；`run_id` 校验防穿越。
- 响应模型不要漏字段导致既有 OpenAPI 契约测试失败；新增路径不影响既有 API 断言。
