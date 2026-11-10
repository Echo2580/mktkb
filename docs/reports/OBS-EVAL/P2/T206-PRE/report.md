# P2-T206-PRE 开发报告：真实准入前绑定（trace 身份 / 证据 id / config_hash / 失败产物）

- 角色：P2-T206-PRE **开发助手**（全新上下文）。分支 `codex/p2-e2e` @ HEAD `a8f2a6b`（未 commit/push）。
- 边界：**零真实调用**（Mock 产品应用 + Mock provider + 隔离临时目录）；未读 `.env`/H1/H2、未联网、
  未跑全仓、未改 `fixtures/`/`gate.py`/`p2_ingestion.py`/`gate_v0_3.json`、未写共享账本/GO。
- 目标：补齐 T205 review §3 两条限制与 R2 的 ①②③⑤⑥，让 `trace_integrity` 在 Mock dry-run **真 PASS**，
  缺任一身份仍 fail-closed；保留"失败也写产物 / 稳定错误码 / run_id 必填 / probe 不写仓库"。

## 1. 改动清单（逐文件；全部 additive，不改业务 API）

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `observability/tracer.py` (+60) | `TRACE_IDENTITY_FIELDS`、`trace_identity()` 上下文管理器、`current_trace_identity()`；`TraceContext` 创建时快照身份，组装 `TraceRecord` 时先落身份再让 `annotate` 覆盖 | 不改 main.py/业务路由即可绑身份；未设置时行为完全不变 |
| `observability/__init__.py` (+12/-1) | 导出上述三个名字 | 供评测侧使用 |
| `evaluation/product_adapter.py` (+181) | `ProductTurn.evidence`；`bind_trace_identity()`/`trace_identity_bound`/`binding_components()`；最外层 HTTP middleware 放身份进 contextvar；`citation_evidence()` 只读解析产品库 | 身份绑定 + 每轮引用证据 id（unit_id/locator/文档/版本） |
| `evaluation/p2_scoring.py` (+230) | `P2_BINDING_VERSION`/`binding_config_hash()`、`citation_evidence_status()`；scorecard/decision 增 `config_hash`/`binding_config_hash`；判定增 `run_binding_missing`/`config_hash_unbound`/`config_hash_binding_mismatch` | 确定性 config_hash + 判定侧 run/config 级绑定 |
| `evaluation/p2_runner.py` (+305/-30) | `P2RunError`（稳定 `.code`）；`run_p2(run_id=, gate_config=)`；绑定状态/数据集 sha；产物写全部身份字段 + `binding` + `citation_evidence`；**校验失败也写 5 件套**后抛出；公开 run 落 `dataset.jsonl` | 绑定落盘 + R2-F-R2-1/2/3 + 让 gate 直接消费 run 产物 |
| 两个测试文件 (+207/+192) | 4+3 个新用例（见 §3） | 证明绑定/证据/失败产物/run_id/确定性 |
| `p2-runner-contract-v0_1.md`(+20)、新增 `p2-live-binding-v0_1.md`(152)、T203/T204/T205 report 各加 `## T206-PRE` | 契约与报告同步（T203 记录 §F6 旧值、verify-r1 过时断言、probe1 副作用已清；T205 记录两条限制已补）；不改历史证据 | 文档同步 |
| `T203/probe1_product_entry_netguard.py` (+17/-1) | 结果文件默认写系统临时目录，`--out` 显式指定；不再写仓库 | R2-F-R2-5 |

**为什么不动业务 API**：`SourceSummary` 已带 unit 级 `source_id`/`locator`/`version_number`/`status`，
证据身份可在评测侧用只读 SQL 解析（与 `messages_in_db` 同一观测面）→ **零响应字段变更**，无兼容风险。

## 2. 绑定字段与语义

- **trace 身份**（六字段，缺一整体不绑）：`run_id / dataset_version / manifest_sha256 /
  pipeline_version / index_revision / config_hash`；runner 在灌库后（index_revision 定型）算绑定并调
  `adapter.bind_trace_identity`；gate 侧对齐 manifest 的 `run_id / dataset_version /
  corpus_manifest_sha256 / pipeline_version / index_revision / config_hash`（`_TRACE_BINDING` 原表）。
- **引用证据**：每轮 `product.evidence[*] = {unit_id, unit_key, locator, document_id, version_id,
  version_number, state, active, in_run, verified, reason}`；`complete=True` 仅当所有作答轮都有证据且
  每条 `verified`（locator 非空 ∧ 当前有效版本 ∧ published ∧ number≥1 ∧ 本 run 文档）。
- **config_hash**：`sha256(canonical_json({binding_version, dataset_version, manifest_sha256,
  label_version, pipeline_version, index_revision, provider, gate_version, gate_config_hash}))`；
  provider 只含身份（不含调用计数）；缺组件 → `binding_input_missing`；两次独立 run 同 hash（实测）。
- **写入位置**：`run_manifest.json`（顶层身份字段 + `binding` + `trace_store`/`dataset_path`）、
  `summary.json`（`binding`/`citation_evidence`/`network.available`）、`gate.json`（`binding`/
  `citation_evidence`/`artifact_validation`/`failure`）、`P2GateDecision.binding_config_hash`。
- **失败也写产物**：产物校验失败（如 `provider_network_detail_mismatch`）→ 仍写
  `run_manifest/summary/run_result/gate`（+holdout 聚合），`status=aborted`、
  `failure.stage=artifact_validation`、`summary.providers=null`、`summary.network.available=false`，
  **然后抛出同一稳定码**。
- **稳定错误码**：`provider_network_detail_mismatch`（`P2RunError.code`，消息以码开头，旧正则仍匹配）、
  `run_id_missing`（传空/非 str，在建目录/发送前拒绝）、门禁侧 `run_binding_missing`、
  `config_hash_unbound`、`config_hash_binding_mismatch`、`binding_input_missing/invalid`。
- **probe 副作用**：T203 probe1 复跑只写 `<tmp>/mktkb-p2-t203-probe1/probe1_result.json`；实测
  25 断言 0 失败、`external_attempts=[]`、仓库无新增未跟踪文件。

## 3. 验证（本机亲跑；原始输出见证据 1）

| 套件 | 期望 | 实测 |
|---|---|---|
| T203 `test_p2_runner.py` + `test_p2_product_e2e.py` | 原 30 | **34 passed**（+4） |
| T201 `test_p2_authorization.py` | 原 70 | **70 passed** |
| T204 `test_p2_ocr_ingestion.py` + `test_p2_ocr_source_identity.py` | 原 18 | **18 passed** |
| T205 `test_p2_scoring.py` + `test_p2_gate.py` + `test_p2_public_controls.py` | 原 51 | **54 passed**（+3） |
| 门槛 `test_gate.py` + `test_gate_quality.py` | 原 109 | **109 passed** |
| observability（tracer 改动受影响面） | — | **352 passed** |

关键新用例：①真实 run 产物 → `build_gate_run`+`evaluate_p2_hard_gates(require_trace=True)` →
`trace_integrity == "pass"`，且每条 trace 六字段与 manifest 逐值一致、`citation_evidence_status.complete
is True`、config_hash 三处一致；②不给 gate 配置 → `binding.complete=False`、trace 六字段全 None；
③顶层出站比 detail 多 3 → 抛 `provider_network_detail_mismatch` 但 5 件套仍在、
`network.available=False`、`real_sends_allowed=False`；④`run_id` 为 `""/"   "/123` → `run_id_missing`
且 run 目录不建；⑤摘要同输入同 hash、8 组件逐个变化必变、缺/空组件 fail closed；⑥证据缺/未核实/
空 locator/非作答轮都不算 complete，H2 口径不带 case_id；⑦缺 run_id / 缺 manifest config_hash /
scorecard 异 config_hash 各自命中对应 unknown 码且不放行。

探针（独立于 pytest 上下文）：两次独立 run 的 `config_hash` **完全相同**（`58caf4a2…b01e`）、
`trace_integrity` 均 pass、失败路径与 run_id 拒绝路径如上；真实出站 0。

## 4. 限制 / 未做（如实）

1. **真实 live 链未跑**：只证明"绑定口径在 Mock 链上成立且可机读"；真实 `P2Gate` 预留/结算/账本/GO
   仍归 T206 正式 pilot（零真实调用是硬约束）。
2. **引用证据不覆盖"检索候选集"**：只证明引用指向本轮灌入的有效证据单元；"引用 ⊆ 检索 candidates"
   仍由产品自身 `_validate_answer` 与 gate 的 `citation_evidence`（提供 `retrieved` 时）负责。
3. **`business_date`** 取用例集合唯一值；多值/空写空串 → `build_gate_run` 拒绝（fail-closed，不猜）。
4. **`index_revision`** 取灌库后产品 revision；run 期间再次发布时由 RAG 埋点写的值优先，可能不等于
   manifest → `trace_integrity` 按设计 fail（不掩盖）。
5. T203 verify-r1 探针的过时断言 `deleted-at-close` **未回改**（历史证据），只在 T203 report 记录。
6. 未做：真实模型/OCR/embedding/rerank、T206 GO/账本、T207 产品修复、Ragas、全仓回归、浏览器链路。

## 5. 证据入口（4）

1. `evidence/01-pytest.txt`：六条命令 + exit code + 原始输出尾部（34/70/18/54/109/352）。
2. `evidence/02-binding-digest.json`：探针机读摘要（两次 run 同 config_hash、trace 身份逐条、evidence
   计数、`trace_integrity=pass`、失败产物字段、run_id 拒绝、出站 0）。
3. `evidence/03-scope-hashes.txt`：逐文件增删行/行数/sha256[:16]、禁改面零 diff、账本/预算 hash、
   GO 不存在、零真实调用。
4. `evidence/probe_t206_pre.py`：可复跑生成器（stdout；复用 T203 测试夹具，不复制实现、不写仓库）。
