# C25 重建保真缺口（T-R2-201D）

**结论：A（闭合）。** 差异不在 citation 重建，而在**引用身份（reference）的版本绑定**：重建用了驱动层默认
source-map（`v0.1`，4 码），而本轮 r2 真实运行由受控入口在 `dispatched_scoring_map` 作用域内以
`v0.2`（12 码）计分。补上这一条输入口径后 `reconstruction_match=5/5`、`ok=true`，判据/阈值/评分器/
case-plan 一字未改。

> 本文只含固定码、计数、布尔、sha256 与公开文档代号标签；不含题干、答案、实体值、业务数字原文、私有路径。

---

## 1. 一句话依据

C25 的 forbidden ref 与 expected ref 指向**同一文档**（`D01`）的**同一 row/sheet**，但**版本不同**
（forbidden=2，citation/expected=3）。`v0.1` 映射只有 4 码、不含 `D01`，于是 forbidden ref 拿不到
`version_number` → `_version_source_checks` 对 `source_forbidden` **整段跳过**（`p2_scoring.py:807`）
→ 退化成 locator-only 命中 → 假违规。`v0.2` 的 `D01→(D01,2)` 让版本绑定生效 → 版本不等 → 不命中 → pass。

## 2. 产品路径下 citation 对象从哪来、带哪些身份键

| 环节 | 位置 | 身份键 |
|---|---|---|
| 产品响应 `sources[]` | `backend/src/mktkb/sources/service.py:108-126`（`summary_for`） | `source_id` / `document_name` / `version_number`（`version.number`）/ `status` / **`locator`=unit.locator** / `published_at` |
| 同上（direct-RAG 径） | `backend/src/mktkb/conversations/service.py:2053-2092` | 同上（`version_number` 2079、`locator` 2081） |
| HTTP 契约 | `backend/src/mktkb/conversations/schemas.py:61-67`（`SourceSummary`） | 同上，5 键 + `published_at` |
| 响应落行 | `backend/src/mktkb/conversations/service.py:644-645`；`evaluation/product_adapter.py:883-909`（`ProductTurn.as_dict`） | `sources[]` + `evidence[]`（`unit_id/unit_key/locator`） |
| 规范化为 citation | `evaluation/p2_scoring.py:447-508`（`_source_identity`） | `doc_code`（文档名映射）/ `unit_key`（索引）/ `unit_ids=(source_id,)` / `locator`（索引 locator **去** `version_number` 后由产品字段回填，:481-500） |
| 来源判定 | `evaluation/p2_scoring.py:788-822`（`_version_source_checks`；跳过条件 :807）；`evaluation/scorers.py:546-581`（`match_source_ref`）、`:739-778`（`_source_checks`） | ref 有 `version_number` 才逐键比版本；无则仅 locator 子集 |
| ref 侧版本绑定 | `evaluation/p2_score_run.py:523-543`（`remap_holdout_case`，:533-537） | `source_map[doc_code] → (base_doc_code, version_number)` |

要点：**产品 citation 的 locator 就是 `SourceUnit.locator`，version_number 就是 `source_versions.number`**；
两者在封存 envelope 里都有（见 §3），所以重建侧 citation 本来就与产品同构（`locator` 键集 5 个：
`cell_types,cells,header_row,row,sheet`，**不是** 12 个），不需要"猜"。

## 3. 封存 envelope 可用字段（6 个 envelope 逐件一致）

envelope schema：`p2-hard-evidence-capture/v0.2-live`（**v0.3 才有** `runtime_snapshot`；本批 6 件全部
`runtime_snapshot=absent`，见 `p2_evidence_io.py:910` 的必需性条件）。`capture.events` 计数：9（C25/C29，
direct-RAG 径）/ 11 / 14（C14 第 2 回合）。

| 字段（层级） | 键集 | 含版本 | 含 locator | 计数 |
|---|---|---|---|---|
| `db_projection.units[]` | 19 键：`unit_id,unit_key,kind,locator,text,raw_fields,date_fields,entity_type,entity_key,entity_filters,document_id,document_name,document_deleted,version_id,version_number,version_state,active_version_id,active,published_at` | **是**（`version_id`+`version_number`，1/1） | **是**（5 键，1/1） | 每件 1 |
| `db_projection.message_sources[]` | 4 键：`message_id,source_id,document_id,version_id` | **是**（`version_id`） | 否 | 每件 1 |
| `db_projection.request` | 13 键（含 `result_message_id`） | 否 | 否 | 每件 1 |
| `db_projection.messages[]` / `query_states[]` / `conversation` | 10 / 4（`keys,state_json,stored_conversation_id,stored_user_id`）/ 6 键 | 否 | 否 | messages 2（C14 第 2 回合 4）/ query_states 1 / conversation 1 |
| `capture.events[answer_result].payload` | `candidates,conflicts,error_code,kind,missing_fields,reason,request_id,source_ids,text` | 否 | 否 | 各 1 |
| `capture.events[commit_observed].payload` | `assistant_seq,error_code,kind,knowledge_changed,message_id,request_id,requested_kind,revision_after,revision_before,source_ids,text` | 否 | 否 | 各 1 |
| `capture.events[retrieval_observed].payload` | `candidate,empty,request_id,scope,truncated,unit_ids` | 否 | 否 | 0 或 2 |
| `capture.events[model_input].payload.evidence[]` | `source_id,text,fields` | 否 | 否 | 0 或 1 |
| `capture.events[direct_rag_answer].payload`（C25/C29 径） | `answer_source,cited_unit_ids,fact_count,facts,kind,reason,request_id,state_keys,text`；`facts[]`=`doc_id,entity_key,entity_label,field_label,field_role,revision,source_chunk_id,source_unit_id,value,version_id` | **是**（`version_id`,`revision`） | 否（`source_chunk_id`≠locator） | facts=1 |
| `capture.events[plan_observed/query_state_*/model_output/context_*]` | 见 `p2_evidence_capture.py:426-504` | 否 | 否 | — |
| `runtime_snapshot`（产品响应切片，含 `sources[].locator`+`version_number`） | 仅 v0.3（`p2_evidence_capture.py:583-683`） | — | — | **absent** |

**对任务书两处前提的更正（有据）**：① capture 并非"只存 `source_ids`"——`message_sources[].version_id`、
`units[].version_number/version_id`、`direct_rag_answer.facts[].version_id` 都在；② `units[].locator`
是 **5 键**不是 12 键。因此"envelope 无法表达版本"不成立；缺的从来不是 citation 侧，而是 **ref 侧的版本绑定**。

## 4. `p2-holdout-v3.source-map/v0.2` 能否唯一收敛

能。`p2_holdout_source_map.load_source_map` 对 v0.2 逐条校验：12 码全声明、`(base_doc_code, version_number)`
**身份双射**（重复即固定码 `holdout_document_code_unmapped`）。实测：`codes=12`、`unique_identities=12`、
歧义 0；`assert_remap_closure` 对 5 题全部成立（v0.2 折过一次后再被驱动层默认 v0.1 折一次**逐值不变**，
`cases_checked=5`）。唯一"歧义结构"是 **同一 `base_doc_code` 的多个历史版本码**（如 `D01` 有两个版本入口），
它们靠 `version_number` 区分，不是歧义而是正是所需信息。

## 5. 改法与结果（只改 `work/r2_safe_project.py` 的输入，不改判据）

改动登记 = 工具头 docstring **改动清单 L**：

- 取 map 改为在 `p2_holdout_v3_scoring.dispatched_scoring_map(V3_SOURCE_MAP)` 作用域内
  （与本轮受控入口 `tools/p2_h2_v3_controlled_execute.py:2323` 同一条路）；
- 拒绝式门：`served_by_dispatch>=1`、`schema=v0.2`、`code_count=12`、`driver_default_code_count=4`；
- 输出新增 `scoring_map{schema_version,code_count,driver_default_code_count,served_by_dispatch,resolutions,source_map_sha256,matches_run_declaration}`。

| 项 | 改前 | 改后 |
|---|---|---|
| `reconstruction_match` | false（4/5） | **true（5/5）** |
| `ok` | false（`reconstruction_mismatch`） | **true** |
| C25 `quality_status` | fail（`source_forbidden`，`source_forbidden_hit=1`） | **pass**（`source_forbidden_hit=0`） |
| 检查项 | 26 pass / 3 fail / 31 skipped | **27 pass / 2 fail / 31 skipped** |
| 其余 4 题 | C08/C14/C19 pass、C29 fail（`value_hit,source_hit`） | 逐项不变 |

- `r2-quality-checks.json` 新 sha256：`2c322e16ef5b7fcc9444512c6b4f0138ad5a38b9026f0b8265ee649553ccad17`
  （旧 `8559ca9e…`）；`work/r2_safe_project.py` 新 sha256：
  `1374247976bad531901d92a068e55db7e7e249e44cf53b002fedde6ca81cd6af`（旧 `492e4ef7…`）。
- **判据未动**：`p2_scoring.py c3265f4f…`、`scorers.py 3f8ee170…`、`p2_score_run.py 366e621b…`、
  `p2_hard_evidence.py 9861c44e…`、`p2_evidence_io.py 1c16a3da…` 与开工保护快照逐字相同；
  `case-plan.json fe874186…` 未改；`source_forbidden` 的"命中即 fail"语义未改。

**为什么这不是"放宽判据"**（三重）：① 命中的 ref 版本与 citation 版本**不等**，属"同名 row/sheet、不同版本"，
不是"同一来源被放过"；② 判据文件哈希逐字未变，唯一变化是 ref 侧多了一个**运行本身就声明过**的
版本绑定；③ 反向可证伪：把 `version_number` 从 citation 拿掉后 C25 `source_hit` 立刻 fail（locator-only
口径两头都不成立），说明版本绑定是**收紧**而非放宽。

## 6. "历史 C25 质量 pass 可信"的独立依据

1. `fullverify-20261116/run/r2-final/v3-entry-sidecar.json` → `scoring_map`：`schema_version=p2-holdout-source-map/v0.2`、
   `code_count=12`、`resolutions=6`、`served_by_dispatch=6`、`driver_default_code_count=4`、`v02_only_codes=8`。
   即**历史质量判定就是在 v0.2 下发发生的**（文件 sha `dfe81e78…`）。
2. `axes-v2/evidence/c25-matcher-compare.json`（`ref-unit-matcher/v2`，`version_binding_source=p2-holdout-v3.source-map/v0.2`）：
   expected `v2_verdict=identity_match`；forbidden `v2_verdict=no_match`、`v2_code=doc_mismatch`
   （该件的坐标为"版本化文档代号"：`unit_doc_code=V04` 而 forbidden `ref_doc_code=D01`，
   `ref_bound_version_number=2` vs `unit_version_number=3`）；两行 `v1_ref_matches_unit=true`。
   本包质量口径的坐标是"折叠到 base 代号 + 版本"（两个 ref 都折成 `D01`），同一事实表现为
   **版本不等**（forbidden=2、citation=3）。
   → **v1（locator-only）会判"禁源命中"，v2（身份+版本）判"不是该来源"**。
3. `r2-repair-external-20261117/evidence/00-baseline/recompute-v2-run2.json` →
   `safety_report.changed_cases[]` 中 C25：`audit_codes=["forbidden_source_no_match"]`、
   `from={violation,forbidden_source_used}`、`to={not_applicable,benign_business_no_frozen_checks}`、
   `safety_provenance="rescored"`；`axes_report.matcher_version="ref-unit-matcher/v2"`。
   该件的 `cases[].quality_status` 是继承卡（`p2_evidence_rescore*` 用 `old.quality_status`），**不作为**
   独立证据；独立证据是 `safety` 轴的 `forbidden_source_no_match`。
4. 若按 locator-only 口径，C25 会被同一错误判 fail —— 本轮改前实测就是 `source_forbidden=fail/hit=1`，
   与 §6.2 的 `v1_ref_matches_unit=true` 完全吻合：**这就是那条已知的 locator-only 假违规**。

## 7. 对 `reconstruction_match` 的影响与残留

- 影响面仅 C25 一行；`scoring_paths_agree=true`（`score_public_case` 与
  `holdout_case_scores_from_rows` 两条路径逐题一致），`scoring_version_explained=false`
  （不是 102a 口径差异，故不需要"旧口径解释"）。
- 残留（NOT-RUN / 不属于本包）：四轴（safety/cross_user/cross_entity/stale_source）重建属 201B/201C；
  `r2-scoring-version-compare.json` 已于 2026-11-17 在**同一 v0.2 分发作用域**下重跑
  （新 sha `ca01727f…`，旧 `3abbb59c…`），C25 行由 fail 修正为 pass、`flip_count` 仍为 0，
  与 `r2-quality-checks.json` 同口径；细节见 `NOTES-201D.md §9`。
