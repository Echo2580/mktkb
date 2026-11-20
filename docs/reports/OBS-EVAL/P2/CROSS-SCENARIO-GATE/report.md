# P2 正式跨场景门禁 · 阶段一报告

2026-11-20（Asia/Shanghai）。任务 4 阶段一交付：输入契约 + 门禁入口 + 合成验证（含"历史绑定适用性证明"增补）。
工作树 `D:/GPT项目/市场部AI知识库`，分支 `codex/p2-e2e`，接手锚点 `97b0066726e5b8d6f94cbc0b63a890084550c106`。**零真实请求**：本轮未发起任何网络/模型/OCR/检索调用；所有判定只读既有工件与合成夹具。未 commit / push / merge。

## 0. 结论

**PASS（最终装配：阶段一 + D-004/D-005/D-007 + 任务 3 v3 清单真实 N/C/U）**。

* 合成齐备证据 → 总门 `pass`；`test_p2_release_gate_*`（42 passed，T4-R3 后）+ `test_p2_gate.py`（27 passed）全绿。
* **真实 N/C/U（v3 清单）+ H2 聚合 → 总门 `pass`**：`38 pass / 0 blocked / 0 pending / 9 observed`，退出码 **0**（D-011 后；`release_allowed=false`）。
  **无剩余 pending**：H2 聚合已接线；`hard_gate_min_sample.unmet` 因主人 **D-011** 改为按 suite 计划题数覆盖（10>=10）而不再出现，run 级子集改由 `hard_gate_min_sample.run_level_subset` 固定披露（observed）。
* **四档原样承接**：`ADOPTED` N7/C2/U9、`ADOPTED_WITH_BINDING_PROOF` N1/C4/U1、`FAIL` 0、`UNKNOWN` 0；未把证明档折成无条件档，也未把 `trace_integrity=fail` 写成 pass。
* **两行 tally**：无条件可采 7/2/9（observed）；正式可采（含 D-005）**8/6/10 → pass**。
* **v3 `SHA256SUMS` 17/17 全命中**（mismatch 0 / missing 0）。
* `gate.py` 仅因 D-004 改动（`e04990db…`），B0 准入 `evidence_sha256=2226fa20…` 逐字节不变，`p2-admit` exit 0。
* 误删事故见 §12；本轮起禁通配符删除。

## 1. 输入契约定义

单一入口：`p2-release-gate`。清单契约 `p2-release-gate-inputs/v0.1`（严格键集合，多键/缺键一律 `release_inputs_invalid`）。

| 段 | 字段 | 来源 | 绑定方式 | 缺失/不符时的固定原因码 |
| --- | --- | --- | --- | --- |
| `schema_version` | 字面量 `p2-release-gate-inputs/v0.1` | 手写 | 精确匹配 | `release_version_mismatch` |
| `gate_config` | `path` + `sha256` | `docs/evaluation/gate_v0_3_approved.json` | 实算文件 SHA-256 必须等于 `b1094cc7…`，再走 `load_approved_b0_config`（摘要 `7fa6f47a…`、`status=approved`、`gate_version=mktkb.gate.v0.3`） | 未批准 → `release_gate_config_unapproved`；指向冻结模板 → `release_stale_config` |
| `candidate_pipeline` | `pipeline_source_sha256` + `pipeline_version` | `p2_b0.pipeline_source_sha256()`（产品/评测/后端 `.py` 折摘要） | 与实算比对；再要求等于 B0 准入证明里 `pipeline_version` 的 `+` 后缀 | `release_version_mismatch` |
| `document_codes` | `path` + `sha256` | 历史公开语料的"产品文档名 → doc_code"映射（N/C/U 共用） | 字节摘要；交付 `public`/`u` 时必填 | `release_evidence_missing` / `release_digest_mismatch` |
| `b0` | `baseline_root`+`baseline_id`+`run_id`+`baseline_sha256`+`admission_sha256`+`approval_sha256` | `var/eval/baselines/7981d4afc2d1/`（基线 `7981d4afc2d1`、run `p2-t209-b0-20261120-02`） | ① `baseline_root` 解析后必须等于 `var/eval/baselines`；② 三份文件摘要必须等于**钉死常量** `09cf747c…`/`07d2b1e3…`/`f760bf4f…`；③ 回执 `evidence_sha256 == payload_sha256(b0-admission.json)`；④ 登记工件集合 = 7 份 `B0_ARTIFACTS` | 未登记 → `release_baseline_unregistered`；摘要不符 → `release_digest_mismatch`；身份不符 → `release_identity_mismatch` |
| `public.selection` | `path` + `sha256`（内容：`authority{document,sha256,section}` + `assignments[suite,case_id,run_id]`） | 冻结选题范围（T207-PM-decisions-01 §11–12、§24） | 选择文件摘要 + 授权文档摘要双绑定；逐题唯一、覆盖必须精确等于 N01–N08 / C01–C06 | 缺题 → `release_evidence_missing`；重复 → `release_duplicate_evidence`；指向未登记 run → `release_identity_mismatch` |
| `public.runs[]` | `suite`+`run_id`+`run_dir`+`artifacts{4}`+`original{6}` | 历史三份公开 run（R1/R2/R4） | 4 份工件逐字节摘要绑定；`run_manifest` 的 `run_id/gate_config_hash/pipeline_version/index_revision/dataset_version` 必须逐字段等于声明；`original.gate_config_sha256` 实算 = 冻结模板 `3af301db…` 且其加载器摘要 = `d1097573…` | `release_identity_mismatch` / `release_digest_mismatch` / `release_version_mismatch` |
| `public.runs[].applicability` | `path` + `sha256`（可选：跨版本必需） | 门禁自身 `p2-release-applicability` 生成 | 加载时**逐字段重算**：原配置口径 + 目标配置 + 工件摘要 + 冻结范围 + 派生评分器身份 + 状态向量；声明值必须等于重算值 | `release_applicability_invalid` / `release_binding_proof_missing` |
| `public.runs[].rag_db` | `path` + `sha256`（可选） | run 的 `data/rag-index.sqlite3` | 二进制摘要绑定 | `release_evidence_missing` / `release_digest_mismatch` |
| `public.runs[].binding_proof` | `path` + `sha256`（有 `rag_db` 时必需） | 门禁自身 `p2-release-binding` 生成 | 重算：`rag_meta.revision`、逐轮 `product.revision`、两套身份、先例工件、双跑结果 | `release_binding_attestation_invalid` / `release_binding_proof_missing` |
| `u.real` | `suite`+`run_id`+`run_dir`+`case_ids`+`artifacts`+`original`(+`rag_db`,`binding_proof`) | R2 真实 smoke（U01） | 同 `public.runs`；`case_ids` 必须是 U01–U10 的非空子集且含 U01 | `release_identity_mismatch` / `release_duplicate_evidence` |
| `u.local_controls` | `path` + `sha256`（可选） | `docs/reports/…/T207/scoring/u-controls.json`（pytest junit 折叠） | 字节摘要；`basis` 必须为 `L`；逐 U 状态取自 `cases` | `release_identity_mismatch` / `release_not_executed` |
| `h2.composition_aggregate` | `path` + `sha256` | 任务 2 组合聚合视图（`p2-h2-composition-aggregate/v0.1`，卡本体在仓外） | 字节摘要 + 聚合内等式复核（30/30/29/1/0、36 回合、五层、四轴、`verified`） | `release_evidence_missing` / `release_version_mismatch` / `release_sample_below_min` |
| `h2.source_proof` | `path` + `sha256` | `h2-source-proof.full.json`（`p2-release-h2-source-proof/v0.1`；脱敏审计视图另存但不喂校验器） | 批绑定三摘要 = 组合；逐场景 run/plan/状态/摘要 = 组合；派生评分器身份 = 任务 1 源码实算；零调用；C25 口径计数 | `release_identity_mismatch` / `release_digest_mismatch` / `release_binding_attestation_invalid`（来源证明错配） |
| `h2.cards_index` | `path` + `sha256` | 任务 2 卡索引（`p2-h2-cards-index/v0.1`） | 4 卡固定顺序 + 逐卡 `card_file_sha256`（**仓内不可复算，来自保管方**）+ 校验结果；另与聚合的 `card_aggregate_sha256` 分列并断言不等 | 顺序/身份 → `release_identity_mismatch`；哈希混用 → `release_identity_mismatch`；未通过校验 → `release_hard_failure` |
| `pending` | `{public|u|h2: "PENDING-TASK2"|"PENDING-TASK3"}` | 手写 | 段与其待交付标记互斥（同时出现即拒） | `release_inputs_invalid`；缺段又没标记 → `release_evidence_missing` |

**固定原因码词表（17+3 条，`p2_release_model.REASON_CODES`）**
`release_evidence_missing`、`release_not_executed`、`release_required_unknown`、`release_hard_failure`、`release_version_mismatch`、`release_identity_mismatch`、`release_digest_mismatch`、`release_duplicate_evidence`、`release_cross_plan_merge`、`release_applicability_invalid`、`release_sample_below_min`、`release_quality_below_threshold`、`release_stale_config`、`release_pending_input`、`release_inputs_invalid`、`release_gate_config_unapproved`、`release_baseline_unregistered`、`release_binding_proof_missing`、`release_binding_attestation_invalid`、`citation_grounding_field_missing`。

**反自报约束**：清单里没有任何 `verified`/`approved`/`passed` 布尔被采信；所有摘要与状态向量都在加载时重算；H2 的 `verified`/`threshold_met` 由现有校验器按等式推导，调用方只能"报告"，不能"声明"。

## 2. 入口命令（可复算）

```powershell
# 1) 生成输入模板（B0 真实绑定 + 其余 PENDING）
.\.venv\Scripts\python.exe docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/build_template_inputs.py

# 2) 正式门禁：通过=0 / 阻断=3 / 待交付=4
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli p2-release-gate `
  --inputs docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/inputs.template.json `
  --out    docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/gate-result.phase1.json

# 3) 历史 run 的旧版本适用性证明（任务 3 接线用；不改原证据）
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli p2-release-applicability `
  --inputs <inputs.json> --out-dir <dir>

# 4) 历史绑定适用性证明（rag_meta.revision + 逐轮 product.revision + 双跑）
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli p2-release-binding `
  --inputs <inputs.json> --out-dir <dir>

# 5) 真实历史工件干跑（非正式清单；需要本机存在 D:\mktkb-p2-run\t207\R{1,2,4}\data）
.\.venv\Scripts\python.exe docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py `
  docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/gate-result.real-ncu.json
```

**预期输入**：`--inputs` 指向 `p2-release-gate-inputs/v0.1` 清单；相对路径按 `--project-root`（默认仓库根）解析。

**脱敏输出格式**（`p2-release-gate-result/v0.1`，stdout 与 `--out` 同体）：

```json
{"schema_version":"p2-release-gate-result/v0.1","inputs_sha256":"…","gate_config_hash":"…",
 "candidate_pipeline_version":"…","decision":"pass|blocked|pending",
 "release_allowed":false,"release_authority":"owner","owner_release_decision":"not_decided",
 "technical_gate":"…","counts":{"pass":n,"blocked":n,"pending":n,"observed":n},
 "reason_codes":["…"],"pending":{"h2":"PENDING-TASK2"},
 "rows":[{"row_id":"…","title":"…","decision":"…","reasons":["…"],"detail":{…},"evidence":["…"]}],
 "notes":["…"]}
```
输出**不含**题干、答案、标签、密钥、逐题明细与工作区外绝对路径；只出计数、摘要前缀、固定原因码与判定。`release_allowed` 恒为 `false`——技术门不是发布决定。

## 3. 门禁判定表

行判定取值：`pass`（达标）/ `blocked`（不达标或缺证）/ `pending`（等外部输入）/ `observed`（只展示、不参与总门）。

| 判定项 | 行 ID | 判定口径 | 固定原因码（不满足时） | 证据引用 |
| --- | --- | --- | --- | --- |
| 已批准配置 | `gate_config` | 文件摘要 = `b1094cc7…` 且加载器 `7fa6f47a…`、`approved` | `release_stale_config` / `release_gate_config_unapproved` | `docs/evaluation/gate_v0_3_approved.json` |
| 输入契约 | `inputs` | 严格键 + 全部摘要重算通过 | `release_inputs_invalid` / `release_digest_mismatch` | 清单自身 SHA-256 |
| 候选流水线 | `candidate.pipeline` | 候选摘要 = B0 绑定 `…+28aae43c…` | `release_version_mismatch` | B0 准入 `pipeline_version` |
| B0 准入留存 | `b0.admission` | `check_b0_admission(portable_proof=…)` 重算；回执/登记/准入三摘要闭合 | `release_digest_mismatch` / `release_identity_mismatch` | `var/eval/baselines/7981d4afc2d1/b0-admission.json` |
| B0 执行 | `b0.execution` | `executed == planned == 40` | `release_not_executed` | 准入 proof `b0` |
| B0 正确 | `b0.quality` | `passed ≥ 36`（实测 38） | `release_quality_below_threshold` | 同上 |
| B0 精确 | `b0.exact` | `exact_passed == exact_planned == 24` | `release_quality_below_threshold` | 同上 |
| B0 OCR | `b0.ocr` | `ocr_executed == 8`（通过 7） | `release_not_executed` | 同上 |
| B0 八项硬门 | `hard_gates.b0` | 8 项全为 `pass|not_applicable`；`min_sample=32`、`scored_count=40`、`exit=0` | `release_hard_failure` / `release_required_unknown` / `release_sample_below_min` | 准入 proof `hard_gate` |
| N 8/8 | `negative` | 逐题重算 `pass==8`、无 error/未执行 | `release_not_executed` / `release_quality_below_threshold` | `synthetic-*` / 历史 R1+R4（`selected_sha256`） |
| C 6/6 | `boundary` | 逐题重算 `pass==6` | 同上 | 同上 |
| N/C 硬门 | `negative.hard_gates`、`boundary.hard_gates` | 套件级 8 项；`min_sample` 按批准配置（badcase 8 / boundary 6）；`record_code_only_gold` 经 run 自身 rag 单元重建后计入 `source_hit_basis=record_reconstruction` | `release_required_unknown` / `release_hard_failure` / `release_sample_below_min` | 套件 `selected_sha256` + 重建 `unit_key` |
| 历史适用性 | `applicability.<run_id>` | 逐字段重算 = 声明；原配置口径 = 目标口径（实质投影相同） | `release_applicability_invalid` | 证明文件 SHA-256 |
| 历史绑定 | `binding.<run_id>` | 证明重算通过 + 原始机械失败非空 + 修正视图 0 失败 + 改写行数 ≥1 | `release_binding_proof_missing` / `release_binding_attestation_invalid` / `release_version_mismatch` | 见 §9 |
| U 10/10 | `u`、`u.local`、`u.coverage` | 逐题覆盖 U01–U10（R 优先、L 对照），全 pass | `release_evidence_missing` / `release_not_executed` / `release_quality_below_threshold` | `u-controls` SHA-256 + R2 run |
| U01 引用口径 | `u.citation` | `retrieved=[]` 而 `evidence≠[]` → **不改判据**，标待裁量 | `citation_grounding_field_missing`（pending，非 pass） | 见 §10 |
| U 硬门 | `u.hard_gates` | 覆盖按 suite 计划题数（D-011，10>=10）+ run 级子集门禁无失败 + 必需未知 0 → 才 pass；覆盖不成立才 pending | `release_sample_below_min` / `release_required_unknown` | 套件 proof |
| 硬门最小样本 | `hard_gate_min_sample.unmet` | 仅当 `suite_planned_cases < required_min_sample` 时出现（覆盖不成立），交主人裁量 | `hard_gate_min_sample_unmet` | 批准配置 `hard_gate_min_sample` |
| H2 组合 | `h2.composition` | `validate_hard_evidence_composition(total=30)` | `release_evidence_missing` / `release_version_mismatch` | 组合 SHA-256 |
| H2 来源证明 | `h2.source_proof` | 同批三摘要 + 逐卡摘要 + 派生评分器身份 + 零调用 + C25 计数 | `release_identity_mismatch` / `release_digest_mismatch` | 证明 SHA-256 |
| H2 逐卡 | `h2.card.<scenario>` | 四张 v0.2 卡逐卡 `validate_hard_evidence_scorecard` | `release_version_mismatch` / `release_evidence_missing` | 卡文件 SHA-256 |
| H2 覆盖 | `h2.coverage` | 30 题 36 回合、`not_started=0`、`status=complete` | `release_sample_below_min` | 组合 `turns_*` |
| H2 五层 | `h2.strata` | 10/5/5/5/5 精确相等 | `release_evidence_missing` | 组合 `by_stratum` |
| H2 质量 | `h2.quality` | `passed ≥ 24` | `release_quality_below_threshold` | 组合 `passed` |
| H2 硬失败 | `h2.hard_failures` | `hard_failures == 0` | `release_hard_failure` | 组合 `hard_failures_by_kind` |
| H2 必需轴 | `h2.required_axes` | 冻结标注 `required>0` 的轴：`unknown==0` 且 `violations==0` | `release_required_unknown` / `release_hard_failure` | 组合 `annotation.axis_counts` |
| H2 非必需轴 | `h2.non_required_axes` | `required==0` 的轴 unknown 单列展示（C25 原口径） | 不阻断（`observed`） | 同上 |
| H2 整卡 verified | `h2.card_verified` | 如实展示组合 `hard_evidence.verified`（非必需 unknown 会使其为 `false`） | 不单独阻断（`observed`） | 组合 `hard_evidence` |
| 八项硬门汇总 | `hard_gates` | 各来源逐门禁合并：任一 `fail` → 硬失败；适用范围内 `unknown` → 必需未知；`not_applicable` 覆盖单列 | `release_hard_failure` / `release_required_unknown` | 各来源 `gate_status` |
| **总门** | `decision` | 任一 `blocked` → blocked；否则任一 `pending` → pending；否则 pass | 汇总全部 | — |

## 4. 合成通过用例 + 负例

### 4.1 合成通过用例（`test_complete_synthetic_evidence_passes_gate`）

证据构成：**B0 = 已登记真实基线**（离线重算）+ **N/C/U/H2 全部合成**（本地构造的 run 目录、卡、组合、来源证明、选题清单）。
结果：`decision=pass`，`release_allowed=false`，全部关键行 pass（`observed=5`：三个合成 run 未声明 `rag_db`/无 trace 库 → `binding.*` 记 observed「绑定不适用」，另加 `h2.non_required_axes` 与 `h2.card_verified` 两个只展示行；不是新增通过项），`h2.non_required_axes`/`h2.card_verified` 为 `observed`。
命令与退出码：`pytest backend/tests/evaluation/test_p2_release_gate_*.py` → **0**（T4-R1 时 35；H2 接线后 38；D-011 后 41；T4-R3 后 **42**）。

### 4.2 负例（24 条，全部实际执行；返工 T4-R1 另加 5 条见本节末）

| # | 负例 | 接受码 | 实际阻断原因码 |
| --- | --- | --- | --- |
| 1 | 陈旧配置（指向冻结模板 `gate_v0_3.json`） | `release_stale_config` | `release_stale_config` |
| 2 | 同版本错摘要（`b0.admission_sha256` 换成 baseline 摘要） | `release_digest_mismatch` | `release_digest_mismatch` |
| 3 | 假 B0（自造登记处，非规范路径） | `release_baseline_unregistered` | `release_baseline_unregistered` |
| 4 | 假 B0（规范路径 + 自洽摘要，钉死常量拦截） | `release_digest_mismatch` | `release_digest_mismatch` |
| 5 | 候选流水线不符 | `release_version_mismatch` | `release_version_mismatch` |
| 6 | 跨计划合并（同一 run 目录塞两份计划的逐题行） | `release_cross_plan_merge` | `release_cross_plan_merge` |
| 7 | 覆盖缺失（选题范围删掉 N08） | `release_evidence_missing` | `release_evidence_missing` |
| 8 | 未执行（N05 无逐题行） | `release_not_executed` | `release_not_executed` |
| 9 | H2 v0.1 卡冒充 v0.2 | `release_version_mismatch` | `release_version_mismatch` |
| 10 | H2 必需轴未知（把 `stale_source` 标成必需，仍留 1 unknown） | `release_required_unknown` | `release_required_unknown` |
| 11 | H2 真硬失败（卡内 1 条 violation） | `release_hard_failure` | `release_hard_failure` |
| 12 | 回执/摘要错配（卡文件被改一字节，组合摘要未变） | `release_digest_mismatch` | `release_digest_mismatch` |
| 13 | H2 来源证明批绑定错配 | `release_identity_mismatch` | `release_identity_mismatch` |
| 14 | 伪造适用性（改 `derivation.statuses_sha256`） | `release_applicability_invalid` | `release_applicability_invalid` |
| 15 | U 重复（`case_ids=[U01,U01]`） | `release_duplicate_evidence` | `release_duplicate_evidence` |
| 16 | 绑定：伪造 `attested_index_revision` | `release_binding_attestation_invalid` | `release_binding_attestation_invalid` |
| 17 | 绑定：证明工件 hash 不符（rag 库摘要） | `release_binding_attestation_invalid` | `release_binding_attestation_invalid` |
| 18 | 绑定：A run 的证明套到 B run | `release_identity_mismatch` | `release_identity_mismatch` |
| 19 | 绑定：证明值 = 原值（无修正却称已修正） | `release_version_mismatch` | `release_version_mismatch` |
| 20 | 绑定：缺原始机械结果（只给修正后） | `release_evidence_missing` | `release_evidence_missing` |
| 21 | 绑定：整份证明缺失 | `release_binding_proof_missing` | `release_binding_proof_missing` |
| 22 | D-004：引用单元既不在 evidence 也不在 retrieved | `citation_not_in_evidence` | `fail`（`unit_ids` 原样列出） |
| 23 | D-004：引用无 `unit_ids`（非单位级） | `citation_not_unit_level` | `fail` |
| 24 | D-004 正例：retrieved 为空、同轮 evidence 含该单元 | 应 pass | `citation_required=pass` |

另：`U01 被强行标 pass` 由"U01 引用缺口 → 必为 pending"的结构保证——`test_u01_citation_gap_is_pending_master_decision_not_pass` 断言总门≠pass、`u.citation` 为 `pending` 且原因码 `citation_grounding_field_missing`。
命令与退出码：`pytest backend/tests/evaluation/test_p2_release_gate_negative.py` → **0**（**26 passed**；口径演变：T4-R1 后 22 → H2 接线 +1 = 23 → D-011 +3 = 26）；伪造适用性在 `test_p2_release_gate_positive.py`（10 passed）；第 22–24 条在 `test_p2_gate.py`（27 passed）。合计负例场景 24 条（含 1 条正例对照），全部实际执行。

**返工 T4-R1 新增 3 个用例函数（覆盖 5 个负例场景；32→35，详见 §返工 T4-R1）**：`test_zero_rewrite_claim_without_legal_zero_is_rejected`（伪造零改写 → `release_binding_attestation_invalid`）、`test_missing_binding_row_is_caught_by_completeness_invariant`（丢 binding 行 → `release_rows_incomplete`）、`test_u01_binding_proof_forgery_delete_and_cross_run_are_rejected`（伪造/删除/跨 run → `release_binding_attestation_invalid` / `release_binding_proof_missing` / `release_identity_mismatch`）。

## 5. PENDING 占位清单

| 占位 | 行 | 等什么 | 现在的状态 |
| --- | --- | --- | --- |
| `PENDING-TASK3` | `negative`、`boundary`、`hard_gates.negative`、`hard_gates.boundary`、`applicability` | 任务 3 的 N/C 正式清单（run 绑定、冻结选题、旧版本适用性证明） | `pending`（模板）；试接已能 pass（§6.4） |
| `PENDING-TASK3` | `u`、`u.local`、`hard_gates.update_delete` | 任务 3 的 U 证据（1 真实 smoke + 9 本地控制、U01 引用重建） | `pending`；试接 U 10/10 pass，U01 引用待裁量 |
| ~~`PENDING-TASK2`~~ | `h2.*` | 任务 2 聚合已落地并接线（2026-11-21）；H2 行全部为真实判定 | **已解除**（见 §H2 接线） |
| ~~`PENDING-MASTER-DECISION`~~ | `u.hard_gates`、`hard_gates` | 主人 **D-011** 已裁定：按 suite 计划题数计覆盖（10>=10），run 级子集由 `hard_gate_min_sample.run_level_subset` 披露 | **已解除**（见 §D-011） |
| — | `hard_gates` | 各来源行（含 unknowns）都无 fail/非披露 unknown 才汇总 pass | 模板 `pending`；真实接线后 **pass**（D-011；判据与来源行一致） |

## 6. 定向回归（本机实测）

| # | 命令 | 退出码 | 结果 |
| --- | --- | --- | --- |
| 1 | `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_p2_gate.py -q` | **0** | 27 passed（含 D-004 三条） |
| 2 | `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_p2_score_run.py -q` | **0** | 9 passed |
| 3 | `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_diff_release_gate.py -q` | **0** | 15 passed |
| 4 | `.\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_baseline_portability.py -q` | **4** | `NOT-RUN`：任务书给的这个路径不存在（`file or directory not found`）；实际文件在 `backend/tests/evaluation/test_baseline_portability.py` → 同样命令换该路径 **exit 0 / 21 passed** |
| 5 | `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_p2_holdout_scenarios.py -q` | **0** | 84 passed |
| 6 | `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_p2_release_gate_*.py -q` | **0** | 42 passed（T4-R3 后；PowerShell 不展开通配符，实际以展开后的四个文件传入） |

版本：Python **3.12.7**，pytest **9.1.1**。`gate.py` 与 `test_p2_gate.py` 本轮**仅因 D-004（主人授权）改动**：`gate.py` 改前 `10235099…` → 改后 `e04990db…`，`test_p2_gate.py` 新增 3 条 D-004 用例（详见 §13）；`trace_integrity` 的逐值相等语义未改。

### 6.4 真实历史工件试接（阶段二真实接线结果）

命令见 §2 第 5 条。结果：`decision=pass`，`pass=38 / observed=9 / pending=0 / blocked=0`，退出码 **0**（详见 §14 与 §D-011）。
通过的实质项：B0 全行、N 8/8、C 6/6、N/C 硬门、三份 run 的旧版本适用性、两两 run 的历史绑定（原始机械失败 27/2/2，修正视图 0 失败）、U 10/10。
H2 已接线（无 pending）；U 的 min-sample 按 D-011 以 suite 计划题数覆盖（10>=10），run 级子集 1 条以 `hard_gate_min_sample.run_level_subset` 固定披露；U01 引用按 D-004 记 observed。

## 7. 未覆盖项与已知限制

1. **H2 真实聚合未到位**：四张 v0.2 卡、组合、来源证明均缺（任务 2）。本阶段只验证了"结构合法 + 三视图分离 + 负例"，不对真实 H2 结论作任何断言。
2. **跨版本适用性依赖冻结模板的实质投影相同**：目前 `gate_v0_3.json`（`3af301…`）与 `gate_v0_3_approved.json`（`b1094cc7…`）在 `gate_version/schema_version/hard_gates/hard_gate_min_sample/suites/sensitive_patterns/metrics/p2_standards.{b0,negative,boundary,update_delete,holdout,denominators}` 逐键相同，差异仅授权元数据。一旦这些键被改，历史证明会立即失效（这是设计意图）。
3. **绑定修正的语义边界**：修正视图是"派生 trace 视图"（复制原库后把继承产品计数的 trace 改为实际 RAG 索引版本），**不写回原库**，且原始机械失败逐题保留。它证明的是"两层计数器口径"而不是"trace 内容正确"。
4. **U 的 8 门禁样本**：历史口径只有 1 条 U 真实 run 行，`update_delete` 的最小样本 10 只能由 9 条本地控制补足；本地控制不是 run 行，因此 U 的硬门证据在"真实 run 级"意义上是 1/10。合成通过用例改用 10 条 run 级 U 证据演示"可达通过"，历史证据不满足。
5. **八项硬门的覆盖**：`cross_entity`/`pagination_contract`/`stale_bypass` 在 B0/N/C/U 现有题集里全为 `not_applicable`（批准配置允许），汇总行把它们单列在 `not_applicable_gates`，T900 需据此判断覆盖是否足够。
6. **`accepted_wording` 不计分**：任务 3 已标注，本门禁沿用（不影响判定）。
7. **U 八门的 run 级样本限制**：D-011 已裁定按 suite 计划题数判覆盖（10>=10），但八项硬门禁实际只在 1 条 run 级样本上评估（其余 9 条本地控制不产生 cases 行）；该限制由 `hard_gate_min_sample.run_level_subset` 固定披露，见 §D-011。
8. **误删事故**：见 §12（3 个既有未跟踪根目录文件，不可恢复）。
9. `p2_release_inputs.py` 的 B0 三份登记摘要被钉死为常量；**重新登记基线需要改代码**（用"代码变更"换"假 B0 不可伪造"）。
10. **D-004 的边界**：只改 `citation_required` 的候选集合字段读取；`citation_missing`、`citation_not_unit_level`、`citation_not_in_evidence` 三个拒绝分支逐字未改，且 B0 准入摘要逐字节不变。

## 8. 任务 2/3 接线所需字段（可直接转给保管人）

**任务 2（H2，`h2` 段）**
1. `h2.composition.path` + `sha256`：四场景 v0.2 组合 JSON，必须能被 `validate_hard_evidence_composition(total=30, expected_strata={paraphrase:10,multi_turn:5,negative:5,stale_conflict:5,cross_doc_security:5})` 接受。
2. `h2.cards`：**恰好四张**，按 `base_b0, base_b0_plus_v01, pre_v05_without_v07, post_v05_without_v01` 顺序，每张给 `scenario_id/path/sha256`；每张卡 `payload_sha256` 必须等于组合 `runs[i].aggregate_sha256`。
3. `h2.source_proof.path` + `sha256`，内容（`p2-release-h2-source-proof/v0.1`）：
   - `batch_id`、`batch_authority{document,sha256,section}`（授权文档 + 摘要 + 条款）；
   - `batch_binding{manifest_sha256, full_cases_sha256, assignment_sha256}`（必须等于组合里的同名摘要）；
   - `scenarios[]`：`scenario_id/run_id/plan_sha256/status/case_count/turns_executed/config_hash/hard_evidence_sha256/derived_card_sha256/original_identities{gate_config_hash,pipeline_version,index_revision,dataset_version}/derived_scorer{tool,source_sha256}`；`case_count` 必须 12/8/5/5、`turns_executed` 必须 14/10/6/6；`derived_scorer.source_sha256` 必须等于 `p2_hard_evidence.py + p2_holdout_scenarios.py` 的实算摘要。
   - `zero_call{new_requests:0, new_outbound:0, replayed:false}`；`c25_non_required_unknown{case_id:"C25", axes:[…], count:n}`，`count` 必须等于组合里非必需轴的 unknown 总数。
4. 卡内不得出现题干/答案/标签（`FORBIDDEN_PUBLIC_KEYS`）。

**任务 3（N/C/U，`document_codes`/`public`/`u` 段）**
1. `document_codes{path,sha256}`：历史语料"产品文档名 → doc_code"映射。
2. `public.selection{path,sha256}`，内容 `p2-release-selection/v0.1`：`authority{document,sha256,section}` + `assignments[{suite,case_id,run_id}]`，覆盖必须精确等于 N01–N08、C01–C06，逐题唯一。
3. `public.runs[]`（R1/R2/R4 去重后 3 条；同一 run 服务 N 与 C 时声明两次、绑定须完全一致）：
   `suite/run_id/run_dir/artifacts{run_manifest.json,summary.json,dataset.jsonl,cases.jsonl}/original{gate_config_path,gate_config_sha256,gate_config_hash,pipeline_version,index_revision,dataset_version}/rag_db{path,sha256}/applicability{path,sha256}/binding_proof{path,sha256}`。
   `applicability` 与 `binding_proof` 由 `p2-release-applicability` / `p2-release-binding` 生成后回填（不要手改）。
4. `u.real{suite:"update_delete", run_id, run_dir, case_ids:["U01"], artifacts, original, rag_db, applicability, binding_proof}` + `u.local_controls{path,sha256}`（`basis` 必须 `L`）。
5. 若 U01 引用缺口要改判据：由主人出书面裁决（本门禁不会自动接受 `evidence` 充当引用依据）。

## 9. 历史绑定适用性证明（本轮新增）

> 主人 **D-005**：「接受『历史绑定适用性证明』作为正式 N/C/U 证据口径；要求全程披露原始机械 FAIL。」本节即按该口径实现与披露。

### 9.1 规则

`rule = "adopted-standard:gate_binding_value_is_actual_rag_index_revision"`。
即：**门禁绑定值取实际 RAG 索引版本**（`rag_meta.revision`）。历史 run 的 `manifest.index_revision` 写的是产品 revision，属绑定侧缺陷；`trace.index_revision` 由 `rag/retrieval.py` 用 `rag_meta.revision` 覆盖，未走 RAG 的轮次继承了产品计数——两层同名异义计数器在 `gate.py::_TRACE_BINDING` 被当成同一身份比较。**本节的绑定机制不改 `gate.py` 的 trace 语义**（D-004 只改 citation 的候选接地字段读取，见 §12）。

### 9.2 证明字段（`p2-release-binding-applicability/v0.1`）

`schema_version`、`run_id`、`plan_sha256`、`manifest_sha256`、`recorded_index_revision`、`attested_index_revision`、`rule`、
`attestation{rag_source{db_path,db_sha256,read_key="rag_meta.revision",read_value}, product_source{cases_sha256,per_turn[{case_id,turn,revision}],values_sha256}, precedent[{artifact,sha256,claim}]}`、
`gate_replay{original_binding_failures[], corrected_binding_failures[], rewritten_trace_rows, original_trace_db_sha256}`。

### 9.3 重算校验点（全部 fail closed）

1. `manifest_sha256` = 实算 run_manifest 摘要；`run_id`/`plan_sha256` = run 自身；
2. `recorded_index_revision` = `manifest.index_revision`；
3. `attested_index_revision` = 只读打开该 run 的 `rag-index.sqlite3` 读出的 `rag_meta.revision`（DB 摘要也要等于声明）；
4. 逐轮 `product.revision` = 从 `cases.jsonl` 回读的向量（逐值 + 向量摘要）；
5. `attested != recorded`（否则"无修正却称已修正"→ 拒）；
6. 原始机械结果非空、修正视图 0 失败、`rewritten_trace_rows ≥ 1`；
7. 证明整体与重算结果**逐字段相等**（伪造/过期一律拒）。

### 9.4 双跑结果（真实历史工件，本机实测）

| run | recorded | attested | 原始机械 `version_binding` 失败 | 修正视图失败 | 改写 trace 行 |
| --- | --- | --- | --- | --- | --- |
| `p2-t207-r1-20261111-01` | 11 | 12 | **27** | 0 | 25 |
| `p2-t207-r4-20261111-01` | 5 | 6 | **2** | 0 | 1 |
| `p2-t207-r2-20261111-01` | 3 | 4 | **2** | 0 | **0**（零改写：trace 全部已在 attested=4） |

6 条在范围内（N01/C01/C02/U01/C05/C06）逐条对照：原始视图 6 条全 FAIL（与任务 3 `trace-adjudication.json` 的 6 条一致，R1 全量 27/52），修正视图 6 条全 PASS。

**R2 的「改写 trace 行」是 0（不是 1，返工 T4-R1 更正）**：R2 的 trace 库共 2 行、`index_revision` 全为 `'4'`（= attested），`where index_revision='3'` 命中 0 行，修正视图与原库字节相同。零改写本身合法，但不能凭"声称"通过：证明里新增
`trace_rows_total` / `trace_rows_not_at_attested` / `post_update_not_at_attested` 三个可复算字段，契约是
`rewritten == not_at_attested` 且改写后 `not_at_attested == 0`；伪造"零改写"会在重算时暴露（见 §返工 T4-R1 缺陷 2）。**行内同时输出 `original_mechanical` 与 `corrected_view`，并标 `binding_correction_applied=true`、原值、修正值、证明 SHA-256**；不存在"只报修正后"的输出形态。

## 10. U01 引用口径（D-004 已解决，保留历史说明）

事实：U01 同轮 `product.retrieved=[]`，但 `product.evidence` 有 1 个单元；trace 引用 `chunk a202ff9b…` 的 `record_unit_id=072d28f2…` 与 evidence 单元一致（`unit_key=sheet:物品位置:row:8`）。

* **D-004 前**：门禁候选接地集合只取 `retrieved` → `citation_required=fail`（任务 3 **旧 v2** 清单因此把 U01 记 `FAIL`；该清单已作废）。
* **D-004 后**：候选集合 = `evidence ∪ retrieved` → `citation_required=pass`，判据仍要求"引用落在已接地单元"，因此不是放宽。
* 门禁输出把这一变化记成 `u.citation` **observed**（`mechanical_before` / `after_d004` 两行都在）。v3 清单里 U01 = `ADOPTED_WITH_BINDING_PROOF`（`trace_integrity` 机械 FAIL 保留，按 D-005 采信），**不再是 FAIL**。
* 仍未放行的部分与 U01 无关：`u.hard_gates` 因 run 级样本 1/10 待裁量（§15）。

## 11. 主人决定登记（原文引用）

> **D-004（2026-11-20，主人批准）**：「`citation_required` 的候选接地集合改为 `outcome.evidence ∪ outcome.retrieved`。性质：**字段接线缺陷修复**，不是放宽判据。判据仍是'引用必须落在已接地的证据单元内'。」
>
> **D-005（2026-11-20，主人接受）**：「接受『历史绑定适用性证明』作为正式 N/C/U 证据口径；要求全程披露原始机械 FAIL。」
>
> **D-007（2026-11-20，主人确认并登记）**：T209 attempt3 额外独立结果复核的免除范围＝「正式 B0 基线接收所需的额外独立结果复核」，**不覆盖** N/C/U/H2、跨场景门禁、P2 发布与 T900 总判定。

以上三条是本轮 `gate.py` 变更与证据口径的唯一授权来源；执行方未自行放宽任何判据。

## 12. 误删披露

* **误删文件**：`tmp_qc.txt`、`tmp_run_a.txt`、`tmp_run_b.txt`（仓库根）。
* **删除原因**：清理本轮自己产生的 `tmp_t4_*` 临时脚本时，用了 `Get-ChildItem -Filter "tmp_*" \| Remove-Item` 的通配符删除，把同前缀的既有文件一并删掉。
* **可恢复性**：`Remove-Item` 不经回收站；已在 `.claude/`、`docs/`、`var/`、`%TEMP%` 递归按文件名搜索，`C:\\$Recycle.Bin`、`D:\\$Recycle.Bin` 亦无同名条目 —— **不可恢复**。三个文件均不在 git 索引（`git ls-files` 无匹配）、不在任何证据目录、不是任务 1/3 的交付物。
* **影响评估**：不改变任何已登记的 run、基线、归档、账本或阈值；不改变本轮任何判定输入（门禁只读 `docs/`、`var/`、历史 run 目录）。对经理的"保留未提交改动"要求构成一次流程违规，已记录在案。
* **纪律**：本轮起**禁止任何通配符删除**。需要清理时逐文件确认，只删除本轮自己新建并在报告中列明的文件。本轮删除清单：`tmp_*` 共 74 个（均为本轮新建的探针/补丁脚本，逐一删除）；交付目录内删除 `scripts/probe_real_evidence.py`、`gate-result.historical-probe.json`（本轮新建、被 `wire_real_ncu.py` 取代）。

## 13. `gate.py` 变更（D-004）

| 项 | 值 |
| --- | --- |
| HEAD 版（`git show HEAD:…`） | `7e54fbf672cbc1c02bbe746c164038613d5861070796794f6a41aae1595b7fe7`（147624 B） |
| D-004 前工作树 | `102350994939fcd47b9c268cf732743a322b1b05bd282d563de06a354b1fec1b`（147965 B）——**未提交中间态，git 不可重建**（由改后文件精确反推移除新增块得到，字节数与接手时一致） |
| D-004 后（当前） | `e04990db52d72c06dcd4e87fea8f80644171fd5b686810bc0fa6aa3fa8c831b7`（148546 B） |
| 变更点 | `_gate_citation_required` 里候选接地集合由「`outcome.retrieved` 的 unit_ids」扩为「∪ `outcome.evidence[].unit_id`」；其余判据分支（`citation_missing` / `citation_not_unit_level` / `citation_not_in_evidence`）逐字未改 |
| 性质声明 | **这修改了已批准判据的字段读取，属主人 D-004 授权**；不是阈值放宽 |

**负例（`test_p2_gate.py` 新增 3 条，全部实跑）**

| 用例 | 场景 | 结果 |
| --- | --- | --- |
| `test_d004_evidence_field_grounds_citation_when_retrieved_empty` | retrieved=[]、同轮 evidence 含该单元 | `citation_required = pass` |
| `test_d004_citation_outside_evidence_and_retrieved_still_fails` | 引用单元既不在 evidence 也不在 retrieved | `fail` / `citation_not_in_evidence`，`unit_ids == [UNIT_ID]` |
| `test_d004_citation_without_unit_ids_still_fails` | 引用无 `unit_ids` | `fail` / `citation_not_unit_level` |

**B0 回归（T209 归档 run，离线）**

```powershell
.\.venv\Scripts\python.exe -m mktkb.evaluation.cli baseline p2-admit `
  --run var/eval/runs/p2-t209-b0-20261120-02/p2-run `
  --gate-config docs/evaluation/gate_v0_3_approved.json
```
退出码 **0**；`baseline_id=7981d4afc2d1`、`run_id=p2-t209-b0-20261120-02`、`real_calls=112`、`evidence_sha256=2226fa208aec7db84ab69e5f7a068e94322414d38b90c14399979b96fcea8b5d`（**与 D-004 前逐字节相同**）；`citation_required/exact_value_contract/trace_integrity` 均 `pass`，其余 5 项 `not_applicable`，`hard exit=0, unknown=0`；B0 tally 仍 40/40 执行、38/40 正确、精确 24/24、OCR 8/8 执行（7 通过）。

**R1/R2/R4 重跑八门禁（D-004 前后）**

| run | `citation_required`（D-004 前） | `citation_required`（D-004 后） | `version_binding` 机械失败（B 方案，未改） |
| --- | --- | --- | --- |
| R1 | pass | pass | 27 |
| R2 | **fail**（U01 `citation_not_in_evidence`） | **pass** | 2 |
| R4 | not_applicable | not_applicable | 2 |

U01 的变化正是 D-004 的效果：`product.retrieved=[]`、`product.evidence=[{unit_id: 072d28f2…}]`、引用 `unit_ids=[072d28f2…]` → 候选接地集合现在包含该单元。`trace_integrity` 仍按 D-005 的绑定适用性口径处理（原始机械 FAIL 保留 + 修正视图重放），未改成"逐值相等"以外的语义。

## 14. 任务 3 v3 清单重跑结果（最终）

命令（零真实请求，只读历史工件）：

```powershell
.\\.venv\\Scripts\\python.exe docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py
```
退出码 **0**（`pass`），产物 `gate-result.real-ncu.json`：`38 pass / 0 blocked / 0 pending / 9 observed`（D-011 后）。

**v3 绑定与 SHA 交叉核对**（旧 v2 已作废，不再引用）

| 工件 | 声明 SHA-256 | 实算 |
| --- | --- | --- |
| `manifest.json` | `0129cd2ba6abf625c61afaaf958ae2e30e675977ad3045eb381d568ab4ab3fab` | 命中 |
| `report.md` | `52c33b1475eec177c017f5855afb6529be4afc89137ae492330ea91f05ca5cd3` | 命中 |
| `SHA256SUMS` | `746fa6633186356c0795583d8dccb84bb0414c94d39d7a5cb4a65f8dbac55b01` | 命中 |
| `SHA256SUMS` 内 17 行 | — | **17/17 命中**（mismatch 0、missing 0） |

**四档（原样承接，未折叠）**

| 档位 | N | C | U | 含义 |
| --- | --- | --- | --- | --- |
| `ADOPTED` | 7 | 2 | 9 | 无条件可采（无任何机械 FAIL） |
| `ADOPTED_WITH_BINDING_PROOF` | 1 | 4 | 1 | 机械 FAIL 保留，按 **D-005** 凭绑定适用性证明采信 |
| `FAIL` | 0 | 0 | 0 | — |
| `UNKNOWN` | 0 | 0 | 0 | — |

**两行 tally（输出里都出）**

| 行 | 计数 | 判定 |
| --- | --- | --- |
| `tallies.unconditional` | N 7/8、C 2/6、U 9/10 | **observed**（分档展示，非门槛） |
| `tallies.formal` | N 8/8、C 6/6、U 10/10（= 无条件 + 证明档） | **pass**（正式可采，含 D-005） |

**U01**：v3 记 `ADOPTED_WITH_BINDING_PROOF`（`adopt_reason` 明示 `trace_integrity:version_binding` 机械 FAIL 保留、`citation_required` 已按 D-004 由 fail 转 pass）；门禁输出 `u.citation` = observed，`u`/`u.local`/`u.coverage` = pass 10/10。6 条证明档的 `gates.trace_integrity.status` 仍为 `fail`，`mechanical_gate_failures` 逐条留痕；交叉核对显式断言"若被改成 pass 即阻断"。

其余行：`evidence_manifest` pass（scope 15 题、15 条 run 级身份逐字段一致、tiers 与两行 tally 双向复算一致）；N 8/8、C 6/6、`negative/boundary.hard_gates` pass（C05/C06 的 `record_code_only_gold` 经 run 自身 rag 单元重建，`source_hit_basis=record_reconstruction`）；三份 run 的 `applicability`/`binding` 全 pass（原始机械 FAIL 27/2/2 保留，修正视图 0 失败）。

## 15. `hard_gate_min_sample.unmet`（固定行；D-011 后仅在覆盖不成立时出现）

**D-011 之后**：该行只在 `suite_planned_cases < required_min_sample` 时出现（覆盖成立时改由 `hard_gate_min_sample.run_level_subset` 披露 run 级子集）。当前 U 覆盖成立（10>=10），因此最终 JSON 中**没有**该行。以下为覆盖不成立时的固定形态：

```json
{"row_id": "hard_gate_min_sample.unmet",
 "decision": "pending",
 "reasons": ["hard_gate_min_sample_unmet"],
 "detail": {"marker": "PENDING-MASTER-DECISION",
   "evidence": {"suite": "update_delete", "evaluated": 1, "required": 10,
     "approved_config": "docs/evaluation/gate_v0_3_approved.json",
     "why": "U 的 run 级 evaluated_count 只有 1（U01）；其余 9 条是本地控制（L），不是 run 行，八项硬门禁只能在 run 级逐题上评估。",
     "handling": "不自行放宽、不把 1R+9L 冒充 10 条 run 证据；由主人裁量。"}}}
```

覆盖不成立时：`u.hard_gates` 行以 `release_sample_below_min` 呈现、`hard_gates` 汇总保持 pending（不写 pass、也不写 blocked 后停手）。**D-011 已裁定按 suite 计划题数覆盖**，上述三选项不再适用；U 的 run 级 1 条样本限制改由 `hard_gate_min_sample.run_level_subset.disclosed_limit` 固定披露。

## 16. 实现依赖与身份链

### 16.1 `case_rows` 依赖（D-004 的实现前提，属限制不属缺陷）

D-004 的 `citation_required` 修复依赖 `build_gate_rows(..., case_rows=...)` 把同轮 `product.evidence` 投影进 `outcome.evidence`。生产路径已全部传参：`p2_score_run.score_run:353`、`p2_b0.py:643`、`p2_release_public.py` 的 `_suite_hard_gates` / `_run_hard_gates_on_run`。

* **缺省行为更严**：不传 `case_rows` 时 `outcome.evidence` 为空，候选接地集合退化回 `retrieved`，会**更早判 fail**（fail-closed），**不会误放行**——属可接受方向。
* **约束**：后续任何调用 `build_gate_rows` 的新路径**不得省略** `case_rows`，否则会把已修复的 U01 类案例重新判 fail。已在 `build_gate_rows` 的 docstring 写明。

### 16.2 `gate.py` 身份链（三个值）

| 版本 | SHA-256 | 大小 | 说明 |
| --- | --- | --- | --- |
| `HEAD`（`codex/p2-e2e @ 97b00667`） | `7e54fbf672cbc1c02bbe746c164038613d5861070796794f6a41aae1595b7fe7` | 147624 B | git 可重建 |
| D-004 前工作树 | `102350994939fcd47b9c268cf732743a322b1b05bd282d563de06a354b1fec1b` | 147965 B | **未提交中间态，git 不可重建**；由改后文件移除新增块精确反推（字节数与接手时一致） |
| D-004 后（当前） | `e04990db52d72c06dcd4e87fea8f80644171fd5b686810bc0fa6aa3fa8c831b7` | 148546 B | 本轮交付态 |

## 冻结候选摘要清单

本包关键文件（SHA-256 + 字节数；T4-R3 后重新回读校验，drift 0）：

| 文件 | SHA-256 | 字节数 |
| --- | --- | --- |
| `backend/src/mktkb/evaluation/gate.py` | `e04990db52d72c06dcd4e87fea8f80644171fd5b686810bc0fa6aa3fa8c831b7` | 148546 |
| `backend/src/mktkb/evaluation/p2_scoring.py` | `6e197bc3b0b3bd275bacb2af5f7f2a24acffe8927061ffa1e1d3bb9078234344` | 100309 |
| `backend/src/mktkb/evaluation/p2_score_run.py` | `6a5edd87b8f73fb999a816096a25a005fcada63fc2e32c09147928182b45cb47` | 43024 |
| `backend/src/mktkb/evaluation/p2_b0.py` | `1f00d882d1e1de97a7977b3444fa7e32d0a10b5cf2ca764574694d9305c9f34e` | 35898 |
| `backend/src/mktkb/evaluation/cli.py` | `f2ca03ab8e84b1454d3f3173eb137aa5afae6e9952fed125415725ec956f82dc` | 74595 |
| `backend/src/mktkb/evaluation/p2_release_model.py` | `3aab5f06148cd58759b6675c62f8597eecf7953e8725b21040e86cb2502e3fdc` | 14173 |
| `backend/src/mktkb/evaluation/p2_release_inputs.py` | `4ec060a7adab179bc18686ab4fc3e3d46600e28000e390b73bdbd44023530743` | 38318 |
| `backend/src/mktkb/evaluation/p2_release_public.py` | `706dc3ad690f566acbcaec6f34033b420db4cb2a4ab4d9f56e94238d6cc44840` | 64664 |
| `backend/src/mktkb/evaluation/p2_release_h2.py` | `4a00a31366e8b2f95a4fe9358963478499b306561c030971c14c03bf53bb0474` | 22358 |
| `backend/src/mktkb/evaluation/p2_release_h2_aggregate.py` | `92a5e41a64bbb096b9190b9e5124eccc108e9b461bb1dd7b3cf6bc15ec46f4b0` | 30825 |
| `backend/src/mktkb/evaluation/p2_release_binding.py` | `a2481fffd2297aaa6b321c16d9c1b4c8f9f751d4e3a303567e4976019b3a819f` | 27008 |
| `backend/src/mktkb/evaluation/p2_release_gate.py` | `552d6ff7cfe467bafeaea4b564d55c29a0a7d7dba44c727109154d5f3ee2e330` | 26904 |
| `backend/tests/evaluation/test_p2_gate.py` | `712fb0c3ca213c7057b6519f15d7a4095ac35d0add89f2dd3409b37481965d03` | 39691 |
| `backend/tests/evaluation/test_p2_release_gate_fixtures.py` | `1d47f467e4f8ac6c160fab866e8460f200593b33a4233c7718d125eaeb1d7ce5` | 37520 |
| `backend/tests/evaluation/test_p2_release_gate_positive.py` | `3bbad536e63586f6b05ed2ecd404a188901713df98b73355853e7087c45c9ceb` | 8064 |
| `backend/tests/evaluation/test_p2_release_gate_negative.py` | `14ab76d9f52e8c972ad326b476b00e4d1ecf2420e6c7d16814987a8ec976d99c` | 21997 |
| `backend/tests/evaluation/test_p2_release_gate_real_ncu.py` | `8901b9aedf5fcf9987ec1f2d43044a103370b8aceb87d6ea1136dc09988c54d7` | 11510 |
| `docs/evaluation/gate_v0_3_approved.json` | `b1094cc726230be2ec22ec811d34a948ea4a2fe03aab2c0fcc4f20c99764d961` | 5785 |
| `.../H2-REBUILT-CARDS/h2-source-proof.full.json` | `f6465fcb206821f26d51c5f93918aefe229908120cd4708917424e9ebb61d555` | 5167 |
| `.../H2-REBUILT-CARDS/h2-composition-aggregate.json` | `096de42fd573c107f97fa247cc8157ed191bdce2b32a2e26eb6d3b9c680e1c94` | 4102 |
| `.../H2-REBUILT-CARDS/cards-index.json` | `f20661d23822b6ad2f11d70feb21b818dc8f08843da80c2ccd0e3e5a57e1e487` | 1301 |
| `.../H2-REBUILT-CARDS/h2-source-proof.json` | `359c9554ab78176abd0588c8d129a47f598c183d3e7eae1a93a3b28730461a90` | 6530 |
| `.../CROSS-SCENARIO-GATE/inputs.template.json` | `a29b6426a1215daea909939277c884c43b84e7bd1546c8d4819f2c684c6d90ab` | 928 |
| `.../CROSS-SCENARIO-GATE/scripts/build_template_inputs.py` | `314d8fb9146ab0067ce1c65d71473ef5bf3ef0ad073ba5021c6582bbbc433d32` | 2481 |
| `.../CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py` | `3d7ca62bf1ca217c02aa50ed70425015ffc08d1c34808ab54ebcfc539528f923` | 12674 |
| `.../CROSS-SCENARIO-GATE/gate-result.phase1.json` | `df030db1869055cc15836ae6a819312594f40f2ce9aff83e38d35aa861e1c013` | 10554 |
| `.../CROSS-SCENARIO-GATE/gate-result.real-ncu.json` | `d4c98f92c0873addbda01b28394b292b3fcd4bdec2aa39a25af6b8384ba66461` | 53053 |

**必须显式纳入的未跟踪文件**：`docs/evaluation/gate_v0_3_approved.json`（`b1094cc7…`，5785 B）未跟踪但被门禁当批准配置钉死；冻结时显式 `git add -f` 或按表取件。**D-011/T4-R3 未改该文件一个字节**。

**H2 四件**（仓内；卡本体在保管环境，未读取）：`h2-source-proof.full.json`（喂 `h2.source_proof`）、`h2-composition-aggregate.json`、`cards-index.json`、`h2-source-proof.json`（审计视图，不喂校验器）。

备注：`gate.py` 为 D-004 后交付态（三值见 §16.2）；任务 1/3 文件未改动；`report.md` 自身不入表。

## D-011 口径修订（主人授权，2026-11-21）

**授权**：主人裁定「U 硬门样口径修订 —— 按 suite 计划题数计」。
**性质**：**只改 min-sample 覆盖判定口径**，**不是放宽判据、未改任何配置数值**——`docs/evaluation/gate_v0_3_approved.json` SHA-256 仍为 `b1094cc726230be2ec22ec811d34a948ea4a2fe03aab2c0fcc4f20c99764d961`（5785 B）；`hard_gate_min_sample` / `p2_standards` 数值逐字未动。

### 规则

* 覆盖判定：`suite_planned_cases >= required_min_sample`，其中 `suite_planned_cases` **只从已批准配置的 `p2_standards` 读**（`update_delete_total` 等），不接受调用方/清单自报；
* 八项硬门禁**仍在 run 级子集上实际评估**；`run_level_evaluated` 与 `scored_count` **单列披露**；
* run 级不足导致的 `min_sample_not_met` 在覆盖成立时**只披露不阻断**（记入行内 `disclosed` / 汇总行 `disclosed_unknowns`）。

### 各 suite 覆盖（批准配置）

| suite | `p2_standards.total` | `hard_gate_min_sample` | run 级评估 | 覆盖 |
| --- | --- | --- | --- | --- |
| b0 | 40 | 32 | 40 | ✓ |
| negative（badcase） | 8 | 8 | 8 | ✓ |
| boundary | 6 | 6 | 6 | ✓ |
| update_delete | 10 | 10 | **1** | ✓（D-011） |
| holdout（H2） | 30 | 30 | 聚合 30 | ✓ |

### 固定披露行（实测输出）

```json
{"row_id": "hard_gate_min_sample.run_level_subset",
 "decision": "observed",
 "detail": {"suite": "update_delete", "suite_planned_cases": 10, "required_min_sample": 10,
   "run_level_evaluated": 1, "basis": "suite_planned_cases", "covered": true,
   "scored_count": 1,
   "disclosed_limit": "U 的八项硬门禁在 1 条 run 级样本上评估，其余 9 条为本地控制",
   "authority": "主人 D-011：按 suite 计划题数计覆盖，不改配置数值、不放宽判据"}}
```

`u.hard_gates` 与 `hard_gates` 只有在 ①suite 计划数达标 ②run 级子集门禁无失败 ③必需未知 0 三条同时成立时才转 `pass`（D-011 后实际均为 pass，且上表 run 级=1 的限制如实保留）。

### 三条负例（`test_p2_release_gate_negative.py`，实际执行）

| 负例 | 命令 | 退出码 | 实际拒绝结果 |
| --- | --- | --- | --- |
| ① 把 `update_delete` 的 `p2_standards.total` 改成 9（<10） | `pytest ...::test_d011_suite_planned_below_min_sample_keeps_u_pending -q` | 0（用例通过） | 门禁 **pending**；`u.hard_gates` pending；`hard_gate_min_sample.unmet` 原因码 `hard_gate_min_sample_unmet` |
| ② 自报 `suite_planned_cases` / 加大 run 级数试图伪造覆盖 | `...::test_d011_forged_planned_cases_cannot_fake_coverage -q` | 0 | 覆盖仍按 `p2_standards` 判（9<10 → 不覆盖）；清单注入 `hard_gate_min_sample` 字段 → **blocked / `release_inputs_invalid`** |
| ③ run 级子集注入引用失败（U01 `sources=[]`） | `...::test_d011_run_level_gate_failure_is_not_masked -q` | 0 | `u.hard_gates` **blocked**（`release_hard_failure`）、`hard_gates` blocked、总门 blocked |

### 最终门禁字段（实测）

`decision=pass`、`technical_gate=pass`、`release_allowed=false`、`release_authority=owner`、`owner_release_decision=not_decided`；`38 pass / 0 blocked / 0 pending / 9 observed`，`reason_codes=[]`。**`release_allowed` 未变 true**——发布仍由主人决定。

### 局限（必须披露）

* U 的八项硬门禁实际只在 **1 条 run 级样本**（U01）上评估；9 条本地控制是 pytest 级控制，不产生 cases 行。本口径只解决"覆盖判定用哪个分母"，**不能**让 1 条样本等价于 10 条真实运行证据。
* `card_file_sha256` 与 `suite_planned_cases` 一样存在"仓内不可独立重算"的边界（前者因 D-001，后者只信批准配置文件本身）。

## T4-R3 收尾修正（独立复核：通过带保留）

### 1（代码，必修）：`hard_gates` 汇总行忽略 `unknowns`

* **缺陷**：往 U 的 proof 注入非披露 unknown（如 `gold_missing`）后，`u.hard_gates` → blocked `release_required_unknown`，但 `hard_gates` 汇总仍 pass（只看了 `gate_status`）。
* **修改点**：`p2_release_public.py` 的 `aggregate_hard_gates` 增加 unknowns 判据——任一来源存在非 `min_sample_not_met` 的 unknown → 汇总行 blocked `release_required_unknown`（cause `hard_gate_unknown`）；`min_sample_not_met` 仍作为披露类不阻断（与 `u.hard_gates` 一致，D-011）。方向是**汇总行变严**，未放松任何来源行。
* **实测（注入 `gold_missing`）**：`decision=blocked`；`u.hard_gates` = **blocked / `release_required_unknown`**；`hard_gates` = **blocked / `release_required_unknown`**（`detail.evidence.unresolved` 含 `{"source":"update_delete","gate_id":"gold","case_id":"U01","check_id":"gold_missing"}`）。
* **新增负例**：`test_t4r3_non_disclosure_unknown_blocks_both_u_and_aggregate`（断言两行**双 blocked**、总门 blocked）；`pytest ...::test_t4r3... -q` → exit 0。

### 2（文档，必修）：§0 残留 "剩余 pending"

* §0 第 2 条已改为"**无剩余 pending**：H2 已接线；`hard_gate_min_sample.unmet` 因 D-011 不再出现，run 级子集由 `hard_gate_min_sample.run_level_subset` 披露"。
* 全文扫描（`pending|PENDING`）结果与分类：

| 位置 | 文本 | 分类 |
| --- | --- | --- |
| §0 第 2 条 | "无剩余 pending" | **已改正**（陈述为 0） |
| §1 契约表 | `pending` 段 + `PENDING-TASK2/3` 标记 | 合法：输入契约定义 |
| §2 输出样例 | `"pending":{"h2":"PENDING-TASK2"}` | 合法：B0-only 模板样例 |
| §3 判定表 | 行判定取值说明 | 合法：语义定义 |
| §5 | ~~`PENDING-TASK2`~~ / ~~`PENDING-MASTER-DECISION`~~ | 合法：已解除标记 |
| §14 | `decision=pass`、`0 pending` | 已正确 |
| §15 | `decision:"pending"` 的 `hard_gate_min_sample.unmet` | 合法：**覆盖不成立时**的固定形态 |
| D-011 | 覆盖表与 neg-1 的 pending | 合法：负例场景 |

**结论：无与 "0 pending / technical_gate=pass" 矛盾的残留**；所有 `pending` 字样均为契约、模板、已解除标记或负例形态。

### 3（写明，不必改代码）：披露行不可事后强制

消费方把 `hard_gate_min_sample.run_level_subset` 从 rows 里过滤后门禁仍 pass（observed 9→8）——这是消费者侧行为，门禁自身无法阻止。

已在**最终 JSON 的 `notes`** 写入两条：

> "硬门禁最小样本按 suite 计划题数计（主人 D-011），run 级子集由 hard_gate_min_sample.run_level_subset 披露；该行是要求的输出行，消费方不得删除，冻结时应把行数与行 id 集合一并入册"
>
> "单看 technical_gate=pass 不读 disclosure 行，会误读为'10 条 run 级证据都过了门'——U 的八项硬门禁实际只在 1 条 run 级样本上评估"

本节同样声明：该披露行是**要求的输出行**，消费方不得删除；冻结以**行数与行 id 集合**一并入册；只读 `technical_gate=pass` 而不读该行会误读为"10 条 run 级证据都过了门"。

### 最终 JSON 行清单（供冻结核对）

* 行数：**47**；`row_ids`（排序后，逗号分隔即集合）：
  `applicability.p2-t207-r1-20261111-01, applicability.p2-t207-r2-20261111-01, applicability.p2-t207-r4-20261111-01, b0.admission, b0.exact, b0.execution, b0.ocr, b0.quality, binding.p2-t207-r1-20261111-01, binding.p2-t207-r2-20261111-01, binding.p2-t207-r4-20261111-01, boundary, boundary.hard_gates, candidate.pipeline, evidence_manifest, gate_config, h2.aggregate, h2.annotation_metadata, h2.card.base_b0, h2.card.base_b0_plus_v01, h2.card.post_v05_without_v01, h2.card.pre_v05_without_v07, h2.card_verified, h2.cards_index, h2.coverage, h2.hard_failures, h2.identity.original, h2.identity.release, h2.non_required_axes, h2.quality, h2.required_axes, h2.source_proof, h2.strata, hard_gate_min_sample.run_level_subset, hard_gates, hard_gates.b0, inputs, negative, negative.hard_gates, tallies.formal, tallies.unconditional, u, u.citation, u.coverage, u.hard_gates, u.local, u.overlap`
* 分布：38 pass / 0 blocked / 0 pending / 9 observed。

### 重跑（命令 + 退出码）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `python scripts/wire_real_ncu.py` | **0** | pass；38/0/0/9；47 行；两次重跑字节一致 |
| `pytest test_p2_release_gate_*.py` | **0** | 42 passed（T4-R3 +1） |
| 五条回归 | **0** | 27 / 9 / 15 / 21 / 84 |
| `baseline p2-admit` | **0** | `evidence_sha256=2226fa20…` 不变 |
