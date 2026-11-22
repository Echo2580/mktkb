# T302 交付说明

> 任务：T302 只读运营接口和权限（P3 运营数据中心后端）。
> 工作目录：`D:\GPT项目\市场部AI知识库`；Windows + PowerShell 7 + 仓库根 `.venv`。
> 全程 Mock / 受控样本，无真实模型、OCR、Ragas 或任何付费调用；未写 `var\`；未做 git 写操作。

## 1. 变更清单

### 新增（仅限允许目录）

| 路径 | 用途 |
| --- | --- |
| `backend\src\mktkb\operations\__init__.py` | 新包入口，导出 `router` |
| `backend\src\mktkb\operations\queries.py` | 共享查询层：Asia/Shanghai 窗口、已完成请求、引用/冲突归属、库存计数、游标分页 |
| `backend\src\mktkb\operations\schemas.py` | 6 个端点的显式白名单响应模型（Pydantic） |
| `backend\src\mktkb\operations\routes.py` | 6 个 GET 端点与管理依赖 |
| `backend\tests\operations\__init__.py` | 测试包标记 |
| `backend\tests\operations\conftest.py` | Trace 开/关隔离应用、`trace_admin` / `trace_employee` / `trace_db` fixture |
| `backend\tests\operations\helpers.py` | 受控样本构造（资料/版本/来源单元/导入任务/问答/引用/冲突） |
| `backend\tests\operations\test_permissions.py` | S1/S2/S3/S5/S6/S7、只读探针 |
| `backend\tests\operations\test_windows.py` | C1/C4/C5/C7、午夜边界、90 天上限 |
| `backend\tests\operations\test_overview.py` | 指标、六类分布、中断单列、待处理项、统计=下钻 |
| `backend\tests\operations\test_requests.py` | C2/C3/C6、文档/版本过滤、失效引用、列表不出口问题 |
| `backend\tests\operations\test_documents.py` | 资料过滤/分页/详情、失败原因脱敏、租约字段不外泄 |
| `backend\tests\operations\test_trace_states.py` | T-a~T-d、纯重放、空分母、Span 白名单 |
| `backend\tests\operations\test_evaluation_runs.py` | E-a~E-e、排序、非法 JSON |
| `backend\tests\operations\test_reconciliation.py` | §5.3 T301 样本重建与逐项对账 |
| `docs\reports\OBS-EVAL\P3\T302-evidence\*` | 本任务全部命令日志、OpenAPI 产物、对账表与本说明 |

### 修改（仅 2 个允许文件）

1. `backend\src\mktkb\main.py` —— 2 行注册，diff 原文：

```diff
@@ -21,6 +21,7 @@ from .ingestion.routes import router as ingestion_router
 from .observability import TraceMode, start_trace
 from .observability.routes import router as observability_router
 from .observability.store import TraceRepository
+from .operations.routes import router as operations_router
 from .providers import build_gateway, build_ocr_gateway
 from .qa import QaEngine, QaNotReady, resolve_rag_config
 from .sources.routes import router as sources_router
@@ -186,6 +187,7 @@ def create_app(
     api.include_router(conversations_router)
     api.include_router(sources_router)
     api.include_router(observability_router)
+    api.include_router(operations_router)
 
     @api.get("/healthz", tags=["health"], summary="最小健康检查")
     def healthz() -> dict[str, str]:
```

2. `frontend\src\api\schema.d.ts` —— 仅由 `openapi-typescript` 对本次 OpenAPI 产物生成，未手改。
   生成命令见 §2 第 4 条；diff 统计 `1645 insertions / 130 deletions`（删除行来自与 T08 旧快照的结构差异与排序变化，非手改）。`client.ts` 等前端源码未动。

### 明确未动

- T301 全部交付物（`git diff` 为空，见 `t301-untouched-end.txt`）。
- T08 历史 OpenAPI 证据、`package.json`、`backend\pyproject.toml`、P2 业务代码。
- 开工前在途改动（`.claude\handoffs\_index.md`、`docs\reports\OBS-EVAL\P2\T207-QUALITY-REPAIR\manager.md`）与未跟踪 P2 证据、`backend\requirements-ragas-eval.lock` 均原样保留。

## 2. 验证证据

| 命令 | 工作目录 | 退出码 | 通过/失败/跳过 | 证据文件 |
| --- | --- | --- | --- | --- |
| 0. `git status --short` 开工/收工快照 | 仓库根 | 0 | — | `git-status-start.txt`、`git-status-end.txt` |
| 1. `..\.venv\Scripts\python.exe -B -m pytest tests/operations -v` | `backend\` | 0 | 69 通过 / 0 失败 / 0 跳过 | `pytest-operations.txt`、`pytest-operations-exit.txt` |
| 2. `..\.venv\Scripts\python.exe -B -m pytest tests/observability tests/integration/test_auth.py -v` | `backend\` | 0 | 386 通过 / 0 失败 / 0 跳过 | `pytest-regression.txt`、`pytest-regression-exit.txt` |
| 3. `..\.venv\Scripts\python.exe -B tools/export_openapi.py --output docs\reports\OBS-EVAL\P3\T302-evidence\api\openapi.json` | 仓库根 | 0 | 28 paths / 32 operations；6/6 条 operations 路径仅 GET；sha256 `67ae8521…3258c` | `openapi-export.txt`、`api\openapi.json` |
| 4. `npx.cmd openapi-typescript ..\docs\reports\OBS-EVAL\P3\T302-evidence\api\openapi.json -o src\api\schema.d.ts` | `frontend\` | 0 | 生成成功（7.13.0） | `api-types-gen.txt`、`api-types-gen-exit.txt` |
| 5. `npm.cmd run build`（含 `tsc --noEmit`） | `frontend\` | 0 | 构建成功：40 modules，`dist/assets/index-CbApAQdQ.js` 367.29 kB | `frontend-build.txt`、`frontend-build-exit.txt` |

补充：

- 命令 3 使用仓库既有 `tools/export_openapi.py`：它用 `Settings(_env_file=None, ...)` 显式隔离 `.env`、`initialize=False`、库指向临时文件，避免 §6 示例命令因缺少密码字段失败，也未读真实 `.env`。
- 命令 4 按 §6 说明直接指定新 OpenAPI 路径，未改 `package.json` 的旧 `api:types` 脚本。
- 生效命令均在改动完成后执行；`pytest-operations.txt` 内为 69 条用例明细。

## 3. T301 对账结果

详见 `T302-reconciliation.md`，逐项一致：

| 口径 | 预期 | 实际 | 一致 |
| --- | --- | --- | --- |
| 已完成问答量 | 13 | 13 | ✅ |
| 六类分布 | 8/1/1/1/1/1 | 8/1/1/1/1/1 | ✅ |
| 未提交中断单列 | 2 | 2（不入六类） | ✅ |
| 非冲突持久引用行 | 13 | 13（统计可见；库内原始 14 含 S10 已删除会话 1 行） | ✅ |
| 文档维/版本维去重对 | 6 / 6 | 6 / 6 | ✅ |
| 待审核版本 | 1 | 1 | ✅ |
| 失败导入 | 1，`PARSE_INCOMPLETE` | 1，`PARSE_INCOMPLETE` | ✅ |
| Trace 覆盖率 | 10/13，`partial`；纯重放 1 不计、关闭 1、未记录 2 | 10/13，`partial` | ✅ |
| 午夜归属 | S17 → 2026-11-20；S18 → 2026-11-21 | 一致 | ✅ |
| 已删除会话 | S10 双侧排除 | overview/列表排除，详情 404 | ✅ |
| D5 冲突 | S05 持久 2 行，最终引用不含；过滤命中且 `conflict_flag=true` | 一致 | ✅ |
| 统计=下钻 | 逐项相等 | 一致 | ✅ |

预期值未改：对账测试中 `EXPECTED` 常量即 T301-recomputation 冻结值。

## 4. 接口契约登记

1. **窗口时区实现**：优先 `zoneinfo.ZoneInfo("Asia/Shanghai")`；本机 Windows 缺 IANA 时区库时回退固定 UTC+8（中国 1991 年后无夏令时，结果等价），对外 `timezone` 恒为 `Asia/Shanghai`。窗口始终左闭右开，`until` 含当天，自定义 >90 天或 `since>until` → 422 `INVALID_WINDOW`。
2. **`since/until` 与 preset 同时出现**：以自定义窗口为准；只给其一 → 422。
3. **`metrics.basis`**：按 §3.1 用 `basis: "current"` 标注 `review_required_versions` 与 `active_documents`，两指标均为当前库存、不随窗口回溯。
4. **`trace_coverage` 分母 0**：返回 `covered=0, total=0, status="not_recorded"`，`note="窗口内无已完成请求（空样本）"`；不输出任何百分比。status 严格限定 `recorded|partial|not_recorded|disabled|unavailable`，未新增枚举值。
5. **`requests` 列表**：增加 `conversation_id_hash`（SHA-256 前 16 位）；不返回 `conversation_id` 原文与问题原文。`page_size` 默认 20、上限 100；`page_size` 越界 → 422 `INVALID_PAGE_SIZE`；`kind` 非法 → 422 `INVALID_KIND`；游标非法 → 422 `INVALID_CURSOR`。
6. **冲突口径（D5）**：`requests` 详情中 `kind='conflict'` 的 `citations` 为空数组，两方来源统一由 `conflicts` 块给出（含 `document_id`/`version_id`/值/状态）；`citation_count` 恒为 0。冲突消息仍可有持久引用行，但不入最终引用。
7. **详情引用去重**：按 `(document_id, version_id)` 去重；同一组合多行时 `source_id` 取首条持久行。仅 `active` 带 `locator`，且 `locator` 去掉 `cells` 行快照；`superseded`/`deleted` 只给文档名、版本号、状态、发布时间。
8. **Trace attempt 扩展字段**：除 `trace_id/attempt/replayed/path/outcome/spans` 外，增加 `previous_trace_id`、`status`、`error_code`（均来自 Trace 记录白名单字段）。单请求 status 取 `recorded|not_recorded|disabled|unavailable`（不出现 `partial`）；只有重放记录 → `not_recorded`，attempt 仍标 `replayed=true`。
9. **`requests/{id}` 覆盖范围**：除已完成请求外，未完成/失败请求也可读取（存在且会话未删除即 200，结果字段按实际记录给空）；非法 UUID、未知、已删除会话 → 404 `REQUEST_NOT_FOUND`。
10. **`documents` 列表**：`current_version` = 有生效版本时取生效版本，无生效版本（如待审核/失败）取最新版本；`latest_import` 取最新版本的导入任务；`version_state` / `processing_state` 也按“最新版本及其导入任务”过滤。`deleted=True` 资料不出现在列表。
11. **`documents/{id}`**：已删除资料返回 404 `DOCUMENT_NOT_FOUND`；`drilldown.requests_filter` 含 `document_id`，存在生效版本时附 `version_id`；失败 `message` 含路径、反斜杠、堆栈、`sqlite`/`storage` 字样时只回 `error_code`（保守脱敏）。
12. **中断计数时间基**：按 `started_at` 落窗（未完成请求无 `finished_at`），仍排除已删除会话，且不入六类分布。
13. **`evaluation-runs`**：`eval/runs` 不存在 → 200 + `runs: []` + `status: "empty"`（不 404）；缺 manifest 或空目录 → `skipped += 1`；manifest/summary/gate 非法 → 该条目 `degraded_reason`（取首个原因），其余条目照常返回；holdout 仅用目录存在性判断是否含 `cases.jsonl`，不读取其内容。
14. **详情/列表并发**：本任务未加数据库索引（按派单留给 T306 实测查询计划后再定）；窗口聚合在 Python 内按共享查询结果计算，保证统计与下钻同源。
15. **`latest_import` 扩展字段**：在 §3.4 要求的 `state/stage/error_code/attempts` 外，补充 `retryable`、`finished_at`（均来自 `ImportJob` 白名单字段），便于运营判断是否可重试。
16. **`documents/{id}` imports 扩展字段**：在 `state/stage/error_code/attempts/retryable/finished_at` 外补充 `version_id`、`created_at`，用于把导入摘要对应到版本；仍不含 `lease_*`、`processing_report` 原文、`stored_path`。
17. **`pending` 扩展字段**：问答项除 `type/request_id/kind/finished_at/drilldown` 外补充 `error_code`；导入项补充 `finished_at`。均来自结果消息/导入任务的稳定字段，失败原因缺失时为 `null`，不推测。
18. **评测批次条目结构**：`runs[]` 每项为 `run_id + holdout_detected + details_withheld + manifest/summary/gate（复用 observability 白名单模型）+ degraded_reason`；单批次详情不在本任务新增端点。

## 5. 已知限制

- **Mock 范围**：模型全部为 `EvidenceEchoGateway` 替身；OCR 关闭；Ragas/评测不调用。S08/S09 为替身缝注入故障；S16/S19/S17/S18 为受控直写样本（已在测试与对账表标注）；S13/S14 使用真实离线解析 worker。
- **未覆盖**：E-f（对真实 `var\eval\runs` 的只读清点）为可选项，未执行，避免依赖本机运行数据；前端页面、图表、导航均未做（T303/T304 范围）。
- **性能**：窗口内请求全量加载后在内存聚合；大数据量下的分页/聚合性能未测，索引待 T306。
- **脱敏启发式**：`message` 中出现 `/`、`\`、`traceback`、`sqlite`、`storage` 即整条丢弃，可能误伤含斜杠的正常文案；宁少勿泄。
- **类型生成差异**：`schema.d.ts` 由当前 live OpenAPI 重生成，与 T08 旧快照存在结构/排序差异（含 T301 observability 端点），非本任务手改；`client.ts` 兼容性由 `tsc` 与 build 验证。
- **覆盖率语义**：查询应用与产生请求的应用可能不同（如 S15 在关闭 Trace 的应用产生）；开启 Trace 的查询应用对无 Trace 行只能给 `not_recorded`，不推断历史开关状态。

## 6. 上报事项

无。未发现任务书、T301 冻结口径与实际代码的冲突；D5 按裁决执行（查询侧排除，不修提交链路）。唯一实现适配是 §6 示例导出命令缺少必填密码会失败，改用仓库既有隔离导出脚本，已记录于 §2。

## 7. 边界自查

- **git 快照对比**：开工快照 `git-status-start.txt` 与收工 `git-status-end.txt` 对比，新增仅 `backend\src\mktkb\operations\`、`backend\tests\operations\`、`docs\reports\OBS-EVAL\P3\T302-evidence\`；修改仅 `backend\src\mktkb\main.py`、`frontend\src\api\schema.d.ts`；其余在途改动与未跟踪 P2 证据原样保留（`git-status-end-scope.txt`、`diff-stat-end.txt`）。
- **`var\` 未写**：`git status --short -- backend/var` 为空（`var-status-end.txt`）；测试库全部在 `tmp_path`。
- **T301 未改**：对 T301 交付物的 `git diff` 为空（`t301-untouched-end.txt`）。
- **无付费/外部调用**：全程 Mock 与离线解析，无模型/OCR/Ragas 网络请求；OpenAPI 导出 `initialize=False` 不建库不写盘。
- **git 只读**：仅使用 `status` / `diff` / `rev-parse`，未 add/commit/checkout/reset/stash/clean。
- **只读性**：`test_all_six_gets_are_read_only` 断言 6 个 GET 前后业务库与 Trace 库字节级不变。
