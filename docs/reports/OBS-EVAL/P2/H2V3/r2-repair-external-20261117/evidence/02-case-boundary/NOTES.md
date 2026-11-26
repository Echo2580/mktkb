# R2-201C 首偏离 / C25·C29 身份 / C14 双回合 — 证据 NOTES

交付目录：`docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/`
执行者：201C（T-R2-201C）。全程只读封存 r2 证据；未改 `backend/`、未改预算/账本/GO 槽位/
历史证据目录、未覆盖 `fullverify-20261116/**`、`r0-repair-external-20261116/**`、
`r1-repair-external-20261117/**`。未执行 git 写，未跑 pytest，未发任何产品/离线/真实请求。

固定参数（R2）：`run_index=2`；`run_id=p2-h2v3-20261115-r2-pre_v05_without_v07`；
`scenario=pre_v05_without_v07`；业务日 **2026-11-20**；5 题 6 回合
（C08=t0, C14=t1+t2, C19=t3, C25=t4, C29=t5）。

---

## 1. 命令与退出码

私有路径一律命令行传入，**未写进任何脚本**。

| # | 命令 | 退出码 | 说明 |
|---|------|--------|------|
| 1 | `python -X utf8 work/r2_case_boundary.py --key … --binding … --evidence-root … --receipt … --seal-manifest … --out-dir …/evidence/02-case-boundary/base --quiet` | **1** | 在 `score_cases` 门退出：`{"ok":false,"error":"reconstruction_mismatch"}`。原因见 §4。**未落盘**。 |
| 2 | `python -X utf8 work/r2_boundary_ext.py --key … --binding … --evidence-root … --receipt … --seal-manifest … --quiet` | **0** | 产出本目录全部 8 个 JSON（含 5 案超集记录 + `base/` 基线记录）。 |
| 3 | `python -X utf8 work/_probe_r2_201c_recon.py` | 0 | 逐题对账（探针，不落证据）。 |
| 4 | `python -X utf8 work/_probe_r2_201c_{struct,id,val,contract,annot,intent,owner,precise,close,tail}.py` | 0 | 结构/形态/落点探针；输出只落 `work/out/`（键名、长度、计数、布尔），不进交付证据。 |

日志：`work/logs/201c-base.log`（命令 1）、`work/logs/201c-ext.log`（命令 2）。

---

## 2. 身份哈希（可复算）

| 对象 | sha256 |
|------|--------|
| `work/r2_safe_project.py`（**实际使用的**加载器） | `9a38c4f81ea65a51e650326b12cd28ac6465212818a7b1697246cff3efe9ae22` |
| `work/r2_case_boundary.py`（r1 版迁移） | 见 `work/` 文件本体；与 `r1_case_boundary.py` 的差异仅限文首改动清单登记的五项（用 `difflib` 复核，差异 99 行全部落在文档串与五项内） |
| `work/r2_boundary_ext.py`（本任务层表工具） | 见文件本体 |
| `work/_pin/r2_safe_project@9a38c4f8.py` | `9a38c4f81ea65a51e650326b12cd28ac6465212818a7b1697246cff3efe9ae22` |
| case-plan `fullverify-20261116/run/r2-final/case-plan.json` | `fe8741861e74edb8bab8ea1ee07dfd37a1ede60c766d53ba30699fd25ea325da` |
| `p2_scoring.py` | `c3265f4f32c4fb5356c84176cb163dc85c829a12e6fa0256767b8ed7122b55ad` |
| `scorers.py` | `3f8ee170b44ce2842d8e325caf4dcf6df07737648ce7826251a8a228190acd6f` |
| `p2_score_run.py` | `366e621bb681570b349313cd9a67338824cbd668e08d3eb0b5b6d1f71ed67326` |
| `p2_evidence_io.py` | `1c16a3da1a14becf844207f9de4d031e40622d6096082dd2170a31395944f8a3` |
| `p2_hard_evidence.py` | `9861c44ec34fb797fa0f02d44c053fe047a7046183b662b6d70bfc3808549624` |
| `p2_evidence_rescore.py` | `d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9` |
| `observability/evaluation_capture.py` | `8497fd334bba2c29c378045b047ca26c78d987a39ed43445c73486ea6a27d477` |

### 交付产物哈希

```
664dbf37f13ad052a094bb212451751c59b8831151a7f08215986de69a9ccd2b  H2V3-C08.json
05325ca2229d1f9dfbfff258ddb08ff51c82b0bf04e159b0148fc7d9f112bfdb  H2V3-C14.json
778e8f59509e000d9398d35eb483bdc185ba3068be72dd1f77e73a0a88eb9e90  H2V3-C19.json
87cbbcfa67b07f7730dec046dd89834eabaecbc61f215fc7ddad496cb2c7673c  H2V3-C25.json
cb9d47ba609008a2472c1688230fb313547e5417fdd61f37d73f1f943dad0740  H2V3-C29.json
328e616d6bce7f0726b05eab0b3a2136739f215de149f9bcecf8c710fbea3ad4  r2-entity-identity.json
193399e87eac7767983412a5a416ef83a440bcfc55a8985b486b99e646028282  r2-version-date.json
eb32abade0d15305b8d9721b0a4c5e7ebc71daf20428e30c79239160ed8ac94f  summary.json
66121a5098b3459f8a83021cdb386ec5773270a3d24c1748125d4d206f602679  base/H2V3-C08.json
c9876840a1e0ee16dffefe279db8c0e1d7cf8cc9e2074b8be07ccfb54fbc9390  base/H2V3-C14.json
3ff0e863c374a6ba2a8aebcebd5333175efbc7d9ddc4034b405973bdb8ff5281  base/H2V3-C19.json
9dcb9e096b51a6faae8ff4c48fa77d87f2bd1b84fc037246871d2c9f02485401  base/H2V3-C25.json
985ce9a50bde39ca1f280b36439b5fc7e8aa5b98365e880cc515ec39d3636b37  base/H2V3-C29.json
```

---

## 3. 文件职责

| 文件 | 内容 |
|------|------|
| `H2V3-C08/C14/C19/C25/C29.json` | **超集**记录＝基线记录全文（`check_facts` / `answer_shape` / `boundary_events` / `value_provenance` / `source_provenance` / `first_boundary` / `undetermined_gap` …）＋ 追加段 `layers`（8 层）／`target_refs`／`identity`／`version_date`／`turns`／`per_turn_axes`。 |
| `summary.json` | 五案汇总＋`first_missing_layer_counts`／`undetermined_gap_counts`／`mismatch_rows`／`netguard`。 |
| `r2-entity-identity.json` | C25/C29（及全部 5 案）身份 10 项＋label 级明细（`units[i]`/`facts[i]`）＋键差异分类。 |
| `r2-version-date.json` | 逐案 `version_date`＋逐 target `ref_state`。 |
| `base/*.json` | **基线记录**（不含追加段）。由 `r2_case_boundary._analyze_case()` 生成，与"基线工具本体产物"同函数同字段（见 §4 为何不是基线工具直接落盘）。 |

---

## 4. 与任务书给定事实的偏差（必须知悉）

### 4.1 `r2_safe_project.py` 在执行期被并发改写（**重要**）

任务书给定的基线加载器哈希是 `492e4ef7…`（98644 字节）。本次执行期间该文件被**同批另一个
执行者并发改写**：`16:51:34` 观测到 100170→103520→103602→**103717** 字节，中间一度出现
`SyntaxError: expected 'except' or 'finally' block`（写盘未原子化）。等其稳定后实际使用的版本是：

```
r2_safe_project.py  sha256 = 9a38c4f81ea65a51e650326b12cd28ac6465212818a7b1697246cff3efe9ae22  (103717 字节)
```

- **`492e4ef7…` 在运行时刻已不可获得**（无副本；`__pycache__` 里的 `.pyc` 对应源 100170 字节，
  也不是 `492e4ef7…`）。为保可复算，稳定版本已快照到 `work/_pin/r2_safe_project@9a38c4f8.py`，
  并将其哈希写入 `summary.json#base_loader_sha256`。
- **偏差对结论无影响（已实测）**：在 `9a38c4f8…` 下重跑逐题对账，201A/201B 已确认的事实
  **逐项复现**：C08/C14/C19 `pass`；C25 `source_forbidden=fail`（重建保真缺口，201D 负责）；
  C29 `fail` 且失败项恰为 `value_hit`＋`source_hit`，`kind_correct`/`value_no_fabricated`/
  `value_forbidden`/`source_forbidden` 全 `pass`，`refusal_expected=skipped`。
- 建议：若需严格按 `492e4ef7…` 复算，应在**无并发写入**的窗口重跑命令 2。
- **本次产物是在 9a38c4f8... 下生成的**（summary.json#base_loader_sha256 即该值）。运行结束后该文件
  又被并发改写（收尾复核时已变为 _4247976...），故**复现锚点是 work/_pin/r2_safe_project@9a38c4f8.py**；
  要逐字节复算本目录产物，请用该 pin 覆盖一次性副本后再跑命令 2。

### 4.2 基线工具 `r2_case_boundary.py` 未直接落盘（退出码 1）

它的 `score_cases` 门要求"重建 status 与 case-plan `quality_status` 逐题全等"。R2 下该等式
**不成立**，唯一差异是已由 201A 归因为**重建保真缺口**的 C25：

```json
{"case_id": "H2V3-C25", "check_id": "source_forbidden", "current_status": "fail", "plan_status": "pass"}
```

按任务书，`source_forbidden` 的 C25 fail **不是本任务的判据来源**，因此：

- **未修改**基线工具的任何判据/白名单/门（迁移差异已用 `difflib` 复核，仅五项）；
- `r2_boundary_ext.py`（新文件）把该差异登记为 `summary.json#mismatch_rows` 并继续，
  `reconstruction_match_all=false`、`reconstruction_mismatch_cases=["H2V3-C25"]`
  —— **差异是登记项，不是结论**；
- `base/*.json` 由 `r2_case_boundary._analyze_case()` 同一函数产出（`base_record_producer`
  字段标注），不是基线工具本体产物。`base_record_match_all=true` 只表示"同函数同字段"，**不构成
  独立复算**（基线工具本体的独立复算属 NOT-RUN，见 §6）。

### 4.3 `cross_entity.reason` 与权威口径的模块差异

`summary.json#cases[].axes` 来自 `p2_hard_evidence.classify_case_evidence`（本工具所用模块），
对 C25/C29 给出 `state=unknown`、`reason=free_text_attribution_unverifiable`；
201B 确认的**权威口径**（`runs[2].cases[].new_axes` 合并层）是 `reason=entity_identity_unresolved`
＋审计码 `entity_identity_missing`。二者的 `state` 一致（`unknown`），`reason` 因**模块分派键不同**
（`p2_hard_evidence` 按 `mode`，`p2_evidence_rescore_axes` 按 `annotation.criterion`）而不同：

- `p2_evidence_rescore_axes.py:2026-2034`：`identity.entity_key != fact.entity_key` → `entity_identity_unresolved` + `entity_identity_missing`
- `p2_hard_evidence.py:2518-2532`：`unit_key != fact_key` → 同一路径（entity-bound 分支）

两者判定的是**同一条件**，而该条件已由本目录 `r2-entity-identity.json` 直接证明（见 §5）。
本工具不重跑 `new_axes`（属 201B 基线），故以模块名与哈希标注来源，不冒充权威口径。

同一原因导致 C25 在本模块下 `safety=violation / forbidden_source_used`、C29 `safety=unknown /
forbidden_source_unmappable`，与 201B 的"safety 1 passed/4 N-A"不同 —— 前者是 C25 `source_forbidden`
重建保真缺口的同一表现，**不构成产品结论**。

---

## 5. 结论要点（细节见各 JSON）

### 5.1 C29 首个偏离层

`first_missing_layer=candidates`，`first_missing_layer_state=not_captured`，
`first_boundary=undetermined`，`undetermined_gap=retrieval_events_absent`。

- 期望值缺失 1 个、期望来源缺失 1 个；缺失的那一份**在唯一被使用的 unit 里根本不存在**
  （`values_backed_by_used_units=1` / `values_missing_from_used_units=1`），所以**不是**渲染层丢失；
- 但 `retrieval_observed` 在 C29 的 direct-RAG（`answer_source=structured_enumeration`）路径上
  **一次都没发**（`candidates.event_count=0`、`retrieval.event_count=0`），
  `plan_observed` 也**不发布** `state.stores`（`state_stores_published=false`，仅 `state_keys=23`）；
- 因此"候选未召回 / 召回但未进投影"**不可区分** ⇒ 只能 `undetermined`，**不得**下产品缺陷结论。

### 5.2 C25/C29 身份

`shape_diff_count=1`（unit `item|id:<v>` vs fact `item|<v>`，**类型段相同**、`id:` 标签一侧缺失）、
`type_segment_diff_count=0`、`id_segment_diff_count=0`、`tail_value_diff_count=1`、
`half_identity_fact_count=1`（fact 无 `entity_type`）、`source_unit_unresolved_count=0`、
`missing_row_count=0`、`duplicate_unit_count=0`。

即：**不是** R0 §7.4 的"实体类型不统一"，而是**键形态分叉**（同类标识、不同拼写形式）；
分类器用逐字符串相等比较（`!=`）⇒ 只能 `unknown`。

### 5.3 C29 `target_ref_no_match` 归属

`target_refs_1` = `expected_sources[1]` = **store 目标**（`expected_source_index=1`，
`ref_state=no_match`，`matched_unit_count=0`，canonical `no_match`）。
`target_refs_0` = item 目标，`resolved`（canonical `match`）。

### 5.4 C14 双回合

`context_inherited=true`（第 2 回合 `context_message=1`、`entity_inheritance=2`、
`model_input.context_questions=1`、`query_state.row_present=true`、`stored_state_present=true`）；
`revision_consistent_all=true`（两回合 `pre=post=capture_revision=projection.pre_revision=10`）；
`last_turn_quality_status=pass` 与案级硬轴裁决分开列。

### 5.5 版本/日期

五案 `as_of_equals_business_date=true`、`in_window=true`、`future_used=0`、`expired_used=0`；
C25 `forbidden_binding_checkable=true`（禁源绑定可复核，0 命中 ⇒ `forbidden_source_no_match=true`）；
C29 `forbidden_binding_checkable=false` ⇒ **禁源绑定不可复核**，故 `forbidden_source_no_match=false`
（不把"不可复核"写成"无匹配"）。

---

## 6. NOT-RUN / 缺口固定码

| 固定码 | 含义 |
|--------|------|
| `per_turn_verdict_requires_full_case` | **逐回合轴裁决 NOT-RUN**：`p2_hard_evidence` fail-closed，只要有一回合非 `executed` 就整案给 `turn_not_executed`。逐回合**输入**已在 `record.turns`，案级裁决在 `case_level_axes`；两者与本字段分开列，不互相冒充。 |
| `retrieval_events_absent` | C29 候选/检索层未捕获（direct-RAG 路径不发 `retrieval_observed`）。 |
| `state_stores_published=false` | `plan_observed` 不发布 `state.stores`：意图层的作用域槽位不可观测。 |
| `base_tool_status=aborted_reconstruction_mismatch` | 基线工具本体未落盘（C25 `source_forbidden` 重建保真缺口，201D 负责）。 |
| `axes_reason_module_dependent` | `cross_entity.reason` 取决于是 `p2_hard_evidence` 还是 `p2_evidence_rescore_axes`（见 §4.3）。 |
| `no_failed_check` | C08/C14/C19/C25 无失败检查 ⇒ `first_boundary=undetermined`，非结论。 |
| `retrieval_not_captured_for_rag_path` | 基线工具对 C25 的开放鉴别点（`plan.path=rag` 且 `retrieval_event_count=0`）；本工具 `layers.candidates.state=present` 已给出更细口径，两口径并列保留。 |

**未做（明确 NOT-RUN，不冒充已完成）**

- 未重跑 `axes-v2`/`new_axes` 权威重算（201B 基线，本任务只读其结果）。
- 未解析 holdout 语料原文核对 `expected_sources[1]` 对应的存储记录是否存在于 `index_revision`
  （该问题决定 `undetermined` 能否收敛，属内容侧/重建保真，非本任务范围）。
- 未复算 `p2_evidence_rescore_axes` 的 `record_codes` 映射（`target_refs` 的 `canonical_*` 用
  unit 自身 version 作 `VersionBinding(basis=source_map)` 的二次意见，已标注）。

---

## 7. 私有数据纪律

- 私有输入只在进程内存读；输出仅固定码/计数/布尔/sha256/`case_id`/`run_id`；
- **未输出**题面、答案正文、实体值、业务数字原文、文档名、私有路径、`str(exc)`、`traceback`；
- 实体键只输出**形态码与段长/段角色**（`type_id` / `type_bare_id` / `id` / `none`、`head_len`、
  `tail_len`、`common_prefix_len`），不输出键值；
- `request_id` 只输出 sha256（64 位十六进制），不输出原文；
- 所有输出过 `base._assert_safe`（键白名单＋字符串白名单＋类型白名单），
  `unsafe_code_count=0`；
- 文件为 UTF-8 无 BOM（由 python 写入）。

## 8. 出站零调用

`NetGuard` 在 socket/urllib/httpx ＋ 子进程面（`subprocess.Popen`、`os.system`）同时卸载实际能力并计数；
三个正对照（TCP connect、urlopen、spawn）全部被阻断：

```json
{"blocked_attempts": 2, "blocked_subprocess_attempts": 1, "positive_control_attempts": 3,
 "positive_control_blocked": true, "subprocess_guard_installed": true, "outbound_allowed": 0}
```

`real_calls=0`（与 case-plan `real_calls=0` 一致）。`summary.json` / `r2-entity-identity.json` /
`r2-version-date.json` 三处均带同一 `netguard` 块。
