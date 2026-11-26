# FU-3 开发自测报告 · N/C/U 正式入口默认回源校验

日期：2026-11-21（Asia/Shanghai）｜分支 `codex/p2-e2e`｜基线 HEAD `93486b6590c6542f34dd70d20a19b792c659f416`
开发自测（非独立验收）。零真实模型 / OCR 调用，零新增费用；只读历史 run 与冻结清单。

## 1. 先核对：既有脚本 vs 正式门禁的实际覆盖

| 检查项（`verify_manifest.py` 口径） | 脚本 | 改前正式门禁 `cross_check_evidence_manifest` | 本次处置 |
|---|---|---|---|
| N/C/U 样本数 8/6/10、case_id 唯一 | 有 | 部分（冻结范围逐题比对，但不查重复 case_id） | **新增**逐题重复/空前缀校验 |
| `question_sha256` 与冻结题面内容一致 | 有 | **无** | **新增**（冻结题集 / 原 run dataset / 原 run 产品行三处内容比对） |
| 证据路径存在 + 摘要一致 | 有 | 仅 `SHA256SUMS` 整行重算；**不查逐题声明路径** | **新增**逐题路径解析 + 摘要，且按已批准根拒绝越界 |
| run 身份（plan_sha256/config_hash/pipeline/index） | 有 | 有（本项**复用，未重复实现**） | 保持原样 |
| trace 属于该 run、题面/run 身份一致 | 有 | **无**（套件硬门禁 `require_trace=False`） | **新增**（含 trace 库只读打开、manifest_sha256 比对） |
| 同 run 不同回合（同题面）trace 互换 | 有（间接） | **无** | **新增**：用该题在原 `cases.jsonl` 行里的 `trace_id` 绑定（决定性检测点） |
| 跨 run trace | 有 | **无** | **新增** |
| U 真实/本地类型混用 | 有 | **无**（L 档字段被忽略，不判混用） | **新增**（R 档带 L 字段 / L 档带 R 字段都阻断） |
| L 档受控测试映射与结果完整性 | 部分 | 只核 u-controls 状态 | **新增**（test_file 存在+摘要、historical/rerun 结果完整、u-controls 有该题且 pass） |
| 四档承接 / tally | 有 | 有（本项**复用**，未重复实现） | 保持原样 |

结论：已有有效逻辑直接复用（run 身份、四档、两行 tally、SHA256SUMS），只补"正常送检入口尚未默认执行"的
逐题回源；不改判据、不放宽阈值、不改 6 条原机械失败。

## 2. 实现

| 文件 | 改动 |
|---|---|
| `backend/src/mktkb/evaluation/p2_release_provenance.py` | **新建**（≈600 行）：`check_evidence_provenance()` / `provenance_rows()` / `approved_evidence_roots()`；固定问题码与 `verify_manifest.py` 同名 |
| `backend/src/mktkb/evaluation/p2_release_gate.py` | `evaluate_release_gate()` 在加载到 `evidence_manifest` 时**默认**调用 `_provenance_rows()`（异常折成阻断行，fail closed） |

已批准根 = 仓库根 + 每个字节绑定 run 的 `run_dir` + 其仓外 `data` 目录 + 该 run 的仓外根
（`<run根>\p2-run\dataset.jsonl`、`<run根>\data\...` 都在这三处内）。越界/绝对路径/`..` 逃逸一律
`EVIDENCE_PATH_OUT_OF_ROOT`；读不到 trace 库/冻结题集 → `SOURCE_UNAVAILABLE` 且阻断。

## 3. 正例（真实任务 3 清单，只读）

真实 v3 清单（`docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/manifest.json`，24 题 = N8/C6/U10）：

```
cd D:\GPT项目\市场部AI知识库
$env:P2_RELEASE_NCU_OUT="$env:TEMP\fixed-ncu2.json"
.\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\CROSS-SCENARIO-GATE\scripts\wire_real_ncu.py
→ {"ok": true, "decision": "blocked", "counts": {"pass": 38, "blocked": 1, ...},
   "reason_codes": ["release_version_mismatch"]}
```

`evidence_provenance` 行 = **pass**：

```json
{"cases_checked": 24, "files_checked": 156, "files_verified": 156,
 "traces_checked": 15, "u_real_cases": 1, "u_local_cases": 9,
 "problem_count": 0, "source_unavailable": []}
```

全门禁 `pass 38 / blocked 1 / observed 10`——唯一 blocked 是 `candidate.pipeline`（版本门，见下节），
`evidence_provenance` 与既有 26 条 pass 行、四档 tally、D-011 披露行逐值不变
（[`evidence/gate-fixed-tree.json`](evidence/gate-fixed-tree.json)）。干净候选 `93486b6` 同一脚本 = `pass 38 / blocked 0 / observed 9`、
`decision=pass`（[`evidence/gate-clean-93486b6.json`](evidence/gate-clean-93486b6.json)）。

保留项核对：N/C/U = 8/6/10；四档 `ADOPTED {N7,C2,U9}` + `ADOPTED_WITH_BINDING_PROOF {N1,C4,U1}` = **6 条原机械失败**
（`trace_integrity/version_binding`）原样保留；`gates.trace_integrity` 未被改成 pass；U02–U10 的 L 档
`historical/rerun/test_file/u-controls` 全部可核；原证据文件 0 处改写（`SHA256SUMS` 156/156 命中）。

## 4. 负例（21 passed）

```
.\.venv\Scripts\python.exe -m pytest backend\tests\evaluation\test_p2_fu3_provenance.py -q
→ 21 passed, exit 0
```

| 任务书要求 | 用例 | 命中码 |
|---|---|---|
| 合法十六进制但内容错配的题目摘要 | `test_question_digest_content_mismatch_is_blocked` / `test_question_digest_shape_is_blocked` / 真实清单篡改集成用例 | `QUESTION_HASH_MISMATCH` → 行阻断 + `release_digest_mismatch` |
| 缺失证据路径 | `test_missing_evidence_path_is_blocked` | `EVIDENCE_PATH_MISSING` |
| 越界证据路径（绝对路径 / `..` 逃逸） | `test_evidence_path_outside_approved_roots_is_blocked` / `test_relative_escape_path_is_blocked` | `EVIDENCE_PATH_OUT_OF_ROOT` |
| 摘要不符 / 未声明摘要 | `test_evidence_digest_mismatch_is_blocked` / `test_evidence_digest_missing_is_blocked` | `EVIDENCE_SHA_MISMATCH` / `EVIDENCE_SHA_MISSING` |
| 缺权威来源（清单非对象 / trace 库不可读） | `test_non_object_manifest_is_blocked` / `test_unreadable_trace_db_is_blocked_not_passed` / `test_required_authority_declaration_missing_is_blocked` | `SOURCE_UNAVAILABLE` / `EVIDENCE_NOT_DECLARED` |
| 同 run 不同回合（同题面）trace 互换 | `test_same_run_different_turn_trace_swap_is_blocked`（两条 trace 的 `question_hash/run_id/身份`全同，只靠原行 `trace_id` 分辨） | `TRACE_CASE_MISMATCH:trace_id_not_in_case_row` |
| 跨 run trace | `test_cross_run_trace_is_blocked` | `TRACE_CASE_MISMATCH:trace.run_id` / `TRACE_NOT_IN_RUN` |
| 重复 trace | `test_duplicate_trace_id_is_blocked` | `TRACE_DUPLICATE` |
| trace 身份错绑 | `test_trace_identity_mismatch_is_blocked` | `TRACE_IDENTITY_MISMATCH:trace.config_hash` |
| U 真实/本地类型混用 | `test_l_basis_with_run_evidence_is_blocked` / `test_r_basis_with_local_control_fields_is_blocked` | `U_TYPE_MIXED` |
| L 档受控映射/结果不完整 | `test_l_control_rerun_failure_is_blocked` / `test_l_control_not_in_local_controls_is_blocked` | `U_CONTROL_INCOMPLETE` |
| **正常送检默认执行**（真实清单篡改一个题面摘要后重跑正式门禁） | `test_gate_entry_runs_provenance_by_default` | `evidence_provenance` = blocked、`cause=provenance_failed`、`problems` 含 `QUESTION_HASH_MISMATCH` |
| 与既有脚本一致 | `test_reference_script_agrees_on_positive_and_digest_negative`（同一份合成清单分别跑 `verify_manifest.py` 与正式门禁） | 正例两边 ok；篡改后两边同判 |

阻断行原因码映射：摘要类 → `release_digest_mismatch`；缺失/越界/缺证 → `release_evidence_missing`；
trace/类型 → `release_identity_mismatch`；重复 → `release_duplicate_evidence`。**不产生 pending/observed 降级**。

## 5. 发现（需主人决定）

与 FU-1 同因：修复树改动了 `p2_runner.py` / `product_adapter.py` → 候选流水线摘要变化 → 正式门禁
`candidate.pipeline` 阻断（`release_version_mismatch`）。因此**修复树**上 `test_p2_release_gate_positive.py`
（7 条）与 `test_p2_release_gate_real_ncu.py`（4 条）、`test_p2_release_gate_negative.py`（1 条 pending 变 blocked）
失败，**全部**由该版本门引起（失败断言均为 `blocked != pass/pending`）；干净候选 `93486b6` 同套用例
15/15 + 27/27 通过。这是"新候选需重新冻结"的既有规则，不是 FU-3 判据放宽或实现缺陷。

## 6. 未覆盖 / NOT-RUN

- 真实 H2 受限逐题：`NOT-RUN`（本项范围外；受限真件按既有授权处理）。
- 历史 run 的完整复跑：`NOT-RUN`（缺历史输入时不重跑，只做回源对照）。
- 旧历史证据内含路径的清洗：按任务书**只登记、不改**（见 FU-4 报告）。
- 新候选重新冻结后的门禁复跑：`NOT-RUN`（等主人决定）。

## 7. 证据

| 文件 | 说明 |
|---|---|
| [`evidence/gate-clean-93486b6.json`](evidence/gate-clean-93486b6.json) | 干净候选跑正式门禁的完整结果（pass 38 / blocked 0 / observed 9） |
| [`evidence/gate-fixed-tree.json`](evidence/gate-fixed-tree.json) | 修复树同脚本结果（唯一 blocked = `candidate.pipeline`；`evidence_provenance` pass） |
| [`candidate-fingerprint.json`](../candidate-fingerprint.json) | 新增/改动文件指纹（`p2_release_provenance.py` = `c309f8994490…`） |
