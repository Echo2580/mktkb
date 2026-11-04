# P0「自动化评测与可观测性」任务拆解与派单计划（2026-11-04）

> 状态：**待主人审阅；未派发、未开工、未创建任何 P0 代码文件。**
> 方案依据：`docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md`（定稿）与 `docs/superpowers/plans/2026-11-04-mktkb-observability-evaluation-p0.md`（P0 计划）。
> 基线：`main` @ `366046d`，tag `v0.1-local-20261104`（GitHub `Echo2580/mktkb`）。
> 分支：P0 在 `p0/obs-eval` 分支逐包提交；T009 独立验收通过并经主人审核后再合并 `main`。
> 证据：入库 `docs/reports/OBS-EVAL/P0/`；运行产物 `var/eval/`、`var/observability/` 不入库。
> 全局铁律：不改业务行为/API Body/业务库与 `rag-index.sqlite3` schema；P0 零真实模型/OCR/embedding/rerank 调用、不读 `.env`；不新增生产依赖；不接 Ragas/Langfuse/OTel/Prometheus；不动 `docs/evidence/`、`var/`、账本、GO、冻结语料；测试命令一律带 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；每包收口提交一次 commit 并附证据路径。

## 1. 工作包总表

| 包 | plan 对应 | 目标 | 交付物（新增/修改） | 依赖 | 独立验收 |
|---|---|---|---|---|---|
| T001 | Task 1 | Trace 数据契约与版本绑定 | 新增 `observability/{__init__,contracts,versioning}.py`、`docs/evaluation/{trace_schema_v0_1,eval_data_v0_1}.md`、`tests/observability/{test_contracts,test_versioning}.py` | — | V1 |
| T002 | Task 2 | SQLite Trace 仓储 | 新增 `observability/store.py`、`tests/observability/test_store.py` | T001 | V1 |
| T003 | Task 3 | 最小侵入埋点 + 中间件 + `X-Trace-ID` | 新增 `observability/tracer.py`、`tests/observability/{conftest,test_tracer,test_middleware}.py`；修改 `config.py`、`main.py`、`qa/service.py`、`rag/{index,retrieval,answer}.py`、`conversations/service.py` | T002 | V2 |
| T004 | Task 4 前半 | 评测数据集 + gold 解析 + scorer | 新增 `evaluation/{__init__,dataset,gold,scorers}.py`、`tools/build_eval_dataset.py`、`fixtures/evaluation/{b0,badcase}.jsonl`、`tests/evaluation/{test_dataset,test_gold,test_scorers}.py` | T001 | V3 |
| T005 | Task 4 后半 | Replay/Local Runner 与运行清单 | 新增 `evaluation/{runner,corpus}.py`、`tests/evaluation/{conftest,test_runner}.py` | T004 | V3 |
| T006 | Task 5 | 双层发布门禁与退出码 | 新增 `evaluation/gate.py`、`docs/evaluation/gate_v0_1.json`、`tests/evaluation/test_gate.py` | T005 | V4 |
| T007 | Task 6 | Baseline / Diff / 报告 | 新增 `evaluation/{baseline,report}.py`、`tests/evaluation/{test_baseline,test_report}.py` | T006 | V4 |
| T008 | Task 7 | CLI 与 P0 七条验收 | 新增 `evaluation/cli.py`、`tools/rag_eval.py`、`tests/evaluation/{golden/chat_response.json,test_p0_acceptance.py}`、`docs/reports/OBS-EVAL/P0/p0-report.md` | T007 | V5 |
| T009 | Task 7 收口 | 独立验收与 P0 收口 | `docs/reports/OBS-EVAL/P0/{review.md,evidence/}` | T001–T008 | 人工门 |

## 2. 每包任务单

### T001 · Trace 数据契约与版本绑定
- 目标：定稿 `TRACE_SCHEMA_VERSION` / `CASE_SCHEMA_VERSION` / `GATE_SCHEMA_VERSION` 与枚举；实现 `required_spans`、`conditional_required_spans`、`pipeline_version`、`config_hash`、`hash_question`、`key_fingerprint` 与冻结 dataclass。
- 输入：设计文档 §6.3/§6.4/§6.5、§7.3；plan Task 1。
- 禁止：不写 SQLite、不接业务代码、不文档化任何真实业务样例原文。
- 验收标准（逐条可判定）：① 设计 §6.4 表全部组合断言通过；② `pipeline_version` 随 prompt/top_k 变化；③ `hash_question` 对 hmac 空 key 抛 `ValueError` 且返回值不含原文；④ `config_hash` 拒收 `key|secret|token|password` 键；⑤ 新增测试与既有测试全过。
- 验证：`python -B -m pytest backend/tests/observability -q`；`python -B -m pytest backend/tests -q`（全量基线不得出现新增失败）。

### T002 · SQLite Trace 仓储
- 目标：`TraceRepository`（write/write_best_effort/get/list_by_request/export_jsonl/purge/close），WAL + 幂等建表 + 参数化 SQL。
- 输入：设计 §6.2/§6.6；plan Task 2。
- 禁止：不引入 SQLAlchemy 依赖，不用业务库连接；不写 `var/` 之外的路径（测试用 tmp_path）。
- 验收标准：① 写读回环；② `write_best_effort` 在库不可写时不抛；③ 建表幂等；④ 多次尝试 `list_by_request` 全量返回；⑤ purge 按天数与保留条数生效。
- 验证：`pytest backend/tests/observability/test_store.py -q`；只读目录场景。

### T003 · 最小侵入埋点 + 中间件（最高风险包）
- 目标：`tracer.py`（contextvar `TraceContext`/`SpanHandle`/`start_trace`/`current_trace`）；QA POST 中间件生成 `X-Trace-ID` 并以 best-effort 落库；RAG 与 legacy 路径按实际执行打 Span 与 outcome。
- 输入：设计 §5、§6.1、§6.4、§6.6；plan Task 3。
- 允许改：仅 plan Task 3 列出的 8 个文件 + 新增 observability/tracer.py 与 3 个测试文件。禁止改：API 请求参数/响应 Body、业务 schema、其他生产文件。
- 验收标准：① `X-Trace-ID` 出现在 QA POST 响应头；② 用 trace_id 能查到 traces/spans 且必需 Span 按 path+outcome 完整（clarification 无 `answer` Span 不误判）；③ legacy 路径 `query_expansion` 仅触发时存在；④ Trace 写入失败不影响产品响应（monkeypatch 验证）；⑤ 固定问答响应除新增响应头外与 golden 一致；⑥ 既有 integration 测试全绿。
- 验证：`pytest backend/tests/observability backend/tests/integration/test_chat.py backend/tests/integration/test_answer_commit.py -q`。
- 风险对策：改动最多，开发助手必须在包内维护「改动行清单 + 行为不变 golden 证据」；独立验收逐文件核 diff。

### T004 · 评测数据集与 scorer
- 目标：`CaseSpec` 校验、`load_cases`、`dataset_version`、`resolve_gold`（稳定引用解析，0/多匹配 fail closed）、`score_case`、检索指标与拒答三指标；生成 `b0.jsonl`（40）/`badcase.jsonl`（13）。
- 输入：设计 §7；plan Task 4 前半；`fixtures/acceptance/questions.json`、`docs/evidence/LOCAL-R1-20261101/S1-DEV/questions.json`、`40题矩阵-题目与标准答案-20261104.md`。
- 禁止：`expected_sources` 不得写 chunk_id/unit_id；不得弱化断言或跳过样本；OCR 题必须标 `requires_ocr`。
- 验收标准：① 40/13 行数正确且校验通过；② 含 chunk_id 的 case 被拒；③ gold 0/多匹配抛 `GoldUnresolved`；④ 全角/空格归一化值命中；⑤ 拒答三指标分离；⑥ `requires_ocr` 在 Replay/Local 标记 skipped。
- 验证：`python -B tools/build_eval_dataset.py ...`（两次运行幂等）；`pytest backend/tests/evaluation/test_dataset.py test_gold.py test_scorers.py -q`。

### T005 · Replay / Local Runner
- 目标：`run_suite`（local 建隔离索引、mock provider、直接调 `RagIndex.ask`；replay 从上一轮 run 重评分）；输出 `run_manifest.json`/`cases.jsonl`/`summary.json`；版本字段全量绑定。
- 输入：设计 §7.3/§9；plan Task 4 后半。
- 禁止：local 不调用真实 provider（provider spy=0 / socket guard=0）；replay 不建索引。
- 验收标准：① b0 与 badcase 独立 run 各产出三件套；② manifest 含 dataset/corpus/index/pipeline/gate/mode/scope；③ replay 复评与 local 评分一致（确定性）；④ OCR case 不入评分分母；⑤ 每次 case 有 trace_id。
- 验证：`pytest backend/tests/evaluation/test_runner.py -q`；`python -B tools/rag_eval.py run --suite b0 --mode local ...`（T008 后联调）。

### T006 · 双层发布门禁
- 目标：硬门禁 8 项 + 质量门禁（stratum/总体、绝对阈值、max_regression_pp、min_sample）、退出码 0/1/2/3/4、 waiver 规则、`--calibrate` 提案。
- 输入：设计 §8；plan Task 5。
- 禁止：硬门禁不可豁免；不得为通过而改判分器/断言；跨版本 baseline 只能分析不可放行。
- 验收标准：① 敏感来源 → `security_leak` exit 1；② 期望值未命中 → `exact_value_contract`；③ 质量回退 exit 2；④ 样本不足 exit 3；⑤ 全拒答 run 不能只靠 refusal_recall 过关；⑥ trace 缺失 → exit 1。
- 验证：`pytest backend/tests/evaluation/test_gate.py -q`；注入 case 走 P0 流程（T008）。

### T007 · Baseline / Diff / 报告
- 目标：`baseline_id` 绑定版本；`approve_baseline` 需 approver/reason/通过门禁；`diff_runs`；`render_markdown/render_html`（单文件内联 CSS、无 JS）。
- 输入：设计 §8.3/§8.5；plan Task 6。
- 禁止：不提供 copy/rename baseline；跨版本默认拒绝。
- 验收标准：① 不同 pipeline_version 的 baseline_id 不同；② 无 compare-with 跨版本 raise；③ diff 列出 new/fixed failures；④ 报告硬门禁置顶；⑤ 审批缺 approver/reason 失败。
- 验证：`pytest backend/tests/evaluation/test_baseline.py test_report.py -q`。

### T008 · CLI 与 P0 集成验收
- 目标：`cli.py` 子命令（dataset build/validate、run、gate --calibrate、baseline approve/list、diff、export）与 `tools/rag_eval.py` 包装；P0 七条验收测试 + `p0-report.md`。
- 输入：设计 §11；plan Task 7；`本地交付说明-20261104.md` 的冻结行为。
- 禁止：不引入 `--allow-holdout-details`（P0 不存在）；不改业务行为。
- 验收标准：① 七条 P0 验收逐条有证据；② 全量 `pytest backend/tests` 全绿（含新增）；③ provider spy=0、socket guard=0、未读 `.env`；④ `report.html` 生成且不参与门禁；⑤ `gate --calibrate` 生成提案、审批后写入 `gate_v0_1.json`。
- 验证：plan Task 7 命令序列逐条执行并留输出到 `docs/reports/OBS-EVAL/P0/evidence/`。

### T009 · 独立验收与 P0 收口
- 职责：全新上下文验收者，按 T001–T008 验收标准逐条复跑（不引用开发报告作为证据），输出 `review.md`（PASS/FAIL/BLOCKED/NOT-RUN + 命令与文件:行）。
- 通过条件：七条 P0 验收全 PASS；全量 pytest 无新增失败；零真实调用证据；无业务行为变化（golden）。
- 收口：`docs/reports/OBS-EVAL/P0/{p0-report.md,review.md,anchors.json,evidence/}`；PM 汇总提交主人人工审核门（G5），主人决策后才合并 `main` 并解锁下一步修复。

## 3. 验收节奏

| 验收 | 触发 | 重点 |
|---|---|---|
| V1 | T001+T002 完成 | 契约/版本/仓储单测；全量基线无新增失败 |
| V2 | T003 完成 | 行为不变（golden + integration 全绿）；trace 完整性；写失败不影响响应 |
| V3 | T004+T005 完成 | 数据集 40/13；gold fail-closed；local 零真实调用；replay 确定性 |
| V4 | T006+T007 完成 | 退出码 0/1/2/3；baseline 审批；diff/html |
| V5 | T008 完成 | P0 七条验收全流程 + 全量 pytest |
| 人工门 | T009 完成 | 主人按 §11 七条验收 + p0-report 复核，四选一决策 |

## 4. 派单参数（待主人确认）

1. 执行方式：建议 **1 开发助手（顺序 T001→T008）+ 1 独立验收助手（V1–V5 分别证伪）**；PM 只派单/守门/记录，不写交付物。
2. 提交与 PR：每包一个 commit（`p0/T00x ...`）在 `p0/obs-eval` 分支；全部完成后开 1 个 PR 便于逐包 review。
3. 证据口径：验收证据进 `docs/reports/OBS-EVAL/P0/`（入库）；原始 run 产物 `var/eval/` 与 trace 库 `var/observability/` 不入库，只记路径与 sha256。
4. 是否接受当前包粒度（9 包，T003 与 T004/T005 工作量最大）；如需更细，可在开工前再拆。

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| T003 侵入业务代码导致行为变化 | golden 固定响应 + 既有 integration + 仅新增 `X-Trace-ID`，独立验收逐文件 diff |
| 必需 Span 过严误判 | 按 `path + outcome` 表 + 条件 Span；clarification/not_found 用例覆盖 |
| Trace 泄漏真实内容 | 默认 `hash`；真实问题 HMAC；`full` 仅合成语料；`config_hash` 拒收凭据键 |
| Replay 通过掩盖回归 | V5 同时要求 Local + 全量 pytest |
| gold 解析不稳定 | 只绑稳定 `doc_code + unit_key`；0/多匹配 fail closed |
| 证据遗漏 | 每包更新 `docs/reports/OBS-EVAL/P0/` 与 commit sha；PM 在 G6 核对路径可访问 |

## 6. 现在不做的事

不创建 `observability/`、`evaluation/` 代码；不改业务文件；不跑任何真实调用；不派发 teammate、不创建 T001 handoff 与四段提示词。等主人审过本文件 §1–§4 并确认派单参数后，才进入 G1 派单。
