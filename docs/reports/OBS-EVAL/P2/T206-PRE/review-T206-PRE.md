# P2-T206-PRE 独立验收报告（review-T206-PRE）

- 角色：全新上下文的独立验收助手（非开发/非经理），证伪优先；只写本文件与 `evidence/verify-t206-pre/`。
- 现场：分支 `codex/p2-e2e` @ HEAD `a8f2a6b`；T206-PRE 未提交（13 tracked 改动 + 新增 binding 契约/T206-PRE 报告/证据）。
- 边界：全 Mock/离线；未读 `.env`/H1/H2、未联网、未跑全仓、未改源码/测试/契约/报告/历史证据、未 commit/push。
- **结论：PASS**（逐条 9/9 满足；2 条非阻断缺口 R-1/R-2 + 1 条文档精度 R-3；无硬违例）。

## 1. 逐条判定

| # | 验收项 | 判定 | 本机证据（复跑/探针） |
|---|---|---|---|
| 1 | trace 六字段绑定；gate 配置下 `trace_integrity` PASS；缺字段 fail-closed | **PASS** | 2 条 trace 六字段逐值等于 manifest；`evaluate_p2_hard_gates(require_trace=True)` → `trace_integrity=pass`；未绑 run 六字段全 None，原生 manifest 被 `build_gate_run` 拒（`run_manifest_incomplete`），补全清单+trace None → `version_binding` 六字段全 mismatch → fail；半套身份 `bind_trace_identity` 拒绝 |
| 2 | 引用证据 id；`citation_evidence_status.complete=True` 且逐条 verified；无证据 unknown；API additive | **PASS** | 4 条证据逐条回查产品库：unit_id==source_id、document/version/number 一致、published/active/locator 非空/in_run；missing/unverified/not_found 均 `complete=False`；H2 不带 case_id；无 `qa/`/`conversations/`/`main.py` 改动 |
| 3 | config_hash 确定性；两次同 hash；索引变更即变；绑定 manifest/scorecard/decision；缺失/不一致 fail-closed | **PASS（R-1）** | 两次独立 run 同 `58caf4a2…b01e`（自定义 run_id 不变）；8 组件逐个改均变、缺失/空均 `binding_input_missing`；manifest/summary/gate/decision 一致；manifest 缺 hash → `config_hash_unbound`，scorecard 异 hash → `config_hash_binding_mismatch`；**scorecard 不声明 hash 时不阻断（R-1）** |
| 4 | 失败也写四件产物；status/failure/network/providers 如实 | **PASS** | `provider_network_detail_mismatch` 抛出后 7 文件在盘（含四件）；status=aborted、stop_code 一致、failure.stage=artifact_validation、network.available=false+code、providers=null、real_sends_allowed=false；run_id 四件一致 |
| 5 | `P2RunError.code`；run_id 空/非 str 在建目录/start 前拒绝 | **PASS** | `.code`/消息以码开头/仍是 ValueError；`""`、`"   "`、`123` → `run_id_missing`，run_dir 未建、adapter 未 start；自定义 run_id 贯穿 manifest/trace/requests |
| 6 | probe1 不写仓库 | **PASS** | probe1 exit 0（25 断言/0 失败/`external_attempts=[]`）；结果落 `%TEMP%/mktkb-p2-t203-probe1`；仓库无 `probe1_result.json`，该目录仅探针脚本自身修改 |
| 7 | 文档同步（T203 §F6 旧值、verify-r1 过时断言、binding 契约） | **PASS（R-3）** | T203 report 保留旧值并追加说明；`probe_verify_r1.py:751` 旧断言存在且被说明；binding 契约与代码逐项一致（见 R-3 的精度注） |
| 8 | 范围/回归；observability 最小；104/18/54/109/352；账本/budget；出站 0 | **PASS** | 34+70=104、18、54、109、352 全 exit 0；禁改面零 diff；文件 hash 与 `03-scope-hashes` 全一致；ledger/budget hash 未变、GO 不存在；出站 0；未跑全仓 |
| 9 | 真实性；无 skip/xfail；真实调用 0 | **PASS** | 报告/证据关键值与本机复跑一致；无 skip/xfail；real_requests=0、billed=0、outbound=0；未发现美化/省略 |

## 2. 非阻断发现（建议 T206 pilot 前处理）

- **R-1｜scorecard 缺 `config_hash` 不 fail-closed**：`evaluate_p2_gate` 对 `card.config_hash is None` 直接 `continue`；
  实测 manifest 有 hash、scorecard 无 hash → 无 `config_hash_*` block（`02-gate-decision-check.json`）。
  契约 §3 只约定"声明的 hash 不一致 → mismatch"，未约定缺失；因此**不按硬违例阻断**。
  若按验收条款"缺失 fail-closed"字面执行，最小修复：当 manifest 有 hash 且 card 为 None hash 时补
  `config_hash_unbound`（或要求 scorecard 构造必须带 hash），并补一条用例。
- **R-2｜新证据未回填 hard gate 的 `retrieved`**：绑定 run 的 `trace_integrity=pass`，但同一 run 的
  `citation_required` 仍 fail（`citation_not_in_evidence`，`evidence_units=0`）——`build_gate_rows` 的 gate 行有
  citations 的 unit_ids，但 `retrieved` 候选集为空。属 T205 review §3 限制 2 的已知边界（契约 §2 已写明"需要 retrieved"），
  不是 T206-PRE 新增回归；但 T206 真实 pilot 若直接消费该行，仍会被 citation 硬门禁挡住，需先接线或显式记 unknown。
- **R-3｜契约 §8 首行精度**：写"未绑 trace 身份 → trace_integrity = version_binding 硬失败"；本机复现显示
  runner 原生未绑 manifest 会先被 `build_gate_run` 以 `run_manifest_incomplete` 拒绝（fail-closed 成立，
  只是不是 trace_integrity 这一层）。建议契约改成"先 `run_manifest_incomplete`；若清单补全而 trace 未绑，
  则 `version_binding` 失败"，避免读者误以为总能走到该 gate。

## 3. 未覆盖 / 限制

- H2 端到端未跑（无 case_id 仅由 `citation_evidence_status(include_case_ids=False)` 单测/探针覆盖）；
  真实 live 链、真实模型/OCR/embedding/rerank、Ragas、浏览器链路均未跑（零真实调用是硬约束）。
- `probe1 --out` 显式路径未单测；只验证默认临时目录与仓库零新增。
- 全仓回归未跑（按验收约束只跑定向套件）；未复核 `.claude/handoffs/_index.md` 的经理备注（非本包代码面）。
- 未验证"产品 live 重新发布导致 index_revision 与 manifest 不一致"的时序（报告 §4 已如实列为限制）。

## 4. 结论与放行意见

- **PASS**：T206-PRE 的绑定/证据/config_hash/失败产物/错误码/run_id/probe 清理均有可复现实测，回归数字与账本边界一致，未发现硬违例。
- 非阻断 R-1/R-2/R-3 建议在 T206 GO 前决定：R-1 若按字面 fail-closed 需 1 处小修；R-2 需在 pilot 前把
  citations/retrieved 接进 `build_gate_rows`（或明确该硬门禁记 unknown）；R-3 只改文档措辞。
- 证据入口（4）：`evidence/verify-t206-pre/{probe_verify_t206_pre.py,01-probe-output.json,02-gate-decision-check.json,03-regressions-and-scope.txt}`。
