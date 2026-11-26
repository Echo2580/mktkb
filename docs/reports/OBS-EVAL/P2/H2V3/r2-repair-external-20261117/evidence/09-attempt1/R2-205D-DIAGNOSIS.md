# R2-205D：attempt1 新证据「C29 首偏离」层位诊断

- 日期：2026-11-17（任务 T-R2-205D）
- 机器可读件：`R2-205D-DIAGNOSIS.json`（同目录）
- 零真实调用：本诊断全部离线读封存件与跑点名合成节点；出站守卫 `outbound_allowed=0`、正对照成立（见 §7）。
- 占位符与 `R2-RUNBOOK.md` 一致：`<RUN_ROOT>`＝仓外工作根，`<ATTEMPT1>`＝`<RUN_ROOT>\attempt1`，`<HOLDOUT_ROOT>`＝v3 封存根。本文件不写私有路径明文。
- 未触碰 `<ATTEMPT1>` 的任何字节（只读解密；`seal-manifest`/`evidence tree` 与回执一致，见 JSON `integrity`）。产品源码、评分器、既有测试、账本/预算/GO 槽位一律未改。

## 1. 结论（一句话）

C29 现在的失败**不是**跨实体取数（202C/202D）失效，而是**计划层（`intent_fields`）的安全早退**：`rag/query.py:1812-1822` 的 R0/C12「物品 + 电话/地址 ⇒ 整体拒答」闸在本次真实题面上触发，计划在**任何检索之前**就返回 `reason=SECURITY_RESTRICTED_CONTACT`（`filters={}`、`field_roles=()` 是该早退的两处硬编码/默认值），于是 `no_answer`→公开 `kind=not_found`、零事实零引用、渲染 98 字的固定拒答模板。该闸属**既有 R0/R1 改动**，**不在本批（retrieval/answer/facts 三文件）改动面内**。

## 2. 新 envelope 的 C29 八层固定状态（与旧 envelope 逐项对比）

新件：`evidence/09-attempt1/02-case-boundary/H2V3-C29.json`（sha256 `736fc610…`，由 `work/r2_boundary_ext.py` **原样**执行，只换 CLI 路径/输出名）。
旧件：`evidence/02-case-boundary/H2V3-C29.json`（sha256 `cb9d47ba…`，同一投影代码；旧轮 loader 与当前 loader 的差异仅为 6 处 `_fail` 的 `where` 标签，已逐行核对）。

| 层 | 旧 envelope（2026-11-16） | 新 envelope（attempt1） | 同/异 |
|---|---|---|---|
| `intent_fields` | path=`rag`、mode=`record`、enumerate=true、as_of=true、terms=12、state_keys=23、`state_stores` 未发布、**filters=1〔`item`〕** | 同左，但 **filters=0〔〕**；`field_role=location`、**`field_roles=0`** | **异** |
| `candidates` | `not_captured`（0 事件） | `not_captured`（0 事件） | 同 |
| `retrieval` | `not_captured`（0 事件） | `not_captured`（0 事件） | 同 |
| `model_input` | `not_applicable`（0 事件） | `not_applicable`（0 事件） | 同 |
| `fact_admission` | `present`；fact_rows=1、cited=1、`answer_source=structured_enumeration`、projection_units=1；该唯一 fact 的 `entity_key`/`source_unit_id` 均在场（1/1），`field_role=location` | **`empty`**；fact_rows=0、cited=0、**`answer_source=refusal`、`reason=SECURITY_RESTRICTED_CONTACT`**、projection_units=0 | **异** |
| `render` | kind=`answer`、81 字、数字 token=5、缺值标记 `absent_marker_3`×1、value 1/2 | **kind=`not_found`**、98 字、数字 token=**0**、缺值标记×**0**、value **0/2** | **异** |
| `citation` | `present`；source_ids=1（1/2） | **`empty`**；source_ids=0（0/2） | **异** |
| `commit` | kind=`answer`/requested=`answer`、81 字、rev 10→10 | kind=`not_found`/requested=`not_found`、98 字、rev 10→10 | **异** |

**第一处不同的层 = `intent_fields`（计划层）**，具体字段是 `filters_count 1→0` 与 `filter_codes {"item"}→{}`。
但要读准：这两处**不是**意图解析算法变了，而是 `query.py:1816-1822` 的早退计划把 `filters` 硬编码成 `{}`、并且**没有传 `field_roles=`**（`QueryPlan` 默认 `()`）。正常末尾构造会传 `state.field_roles`（本题复算为 `(location, phone, status)`，见 §3/§4）。因此 `intent_fields` 的差异是**症状**，机制在该层的安全早退分支。

新增证据（未改判据的独立探针 `work/probe_c29_layers.py`，输出只有固定码/计数/布尔/哈希）：`03-c29-probe/c29-layers.json`。

## 3. 拒答来源判定（逐条给证据）

**判定：计划层安全拒答**（五选一的第 1 类「计划层/意图层」中的安全早退；非候选/取行、非事实准入、非模型契约）。

| 候选来源 | 判定 | 固定码 / 计数 |
|---|---|---|
| 计划/意图层 | **命中** | `reason=SECURITY_RESTRICTED_CONTACT`；站点 `rag/query.py:1812-1822`；`filters=0`、`field_role=location`、`field_roles=0`、`terms=12`、`state_keys=23` |
| 候选/取行（联结空转） | 排除 | 新旧 `retrieval_observed` 事件均为 **0**（direct-RAG 路径本就不发），且旧轮同样 0 事件却正常作答；早退在 `index.search` 之前 |
| 事实准入（`validate_fact` / `_reject`） | 排除 | `fact_rows=0`、`fact_count=0`；`reason` 不属于 `FactRejected` 码域（`STALE_SOURCE`/`FORGED_VALUE`/`CROSS_ENTITY`/`CROSS_FIELD`/`UNSUPPORTED_CLAIM`/`FACT_REJECTED`）；`_reject`（`answer.py:1349-1360`）要求已有 facts |
| 模型输出契约 | 排除 | `model_input=0`、`model_output=0`、`model_output_error_codes=[]`；结构化作答，模型面结构上不适用；无 `MODEL_OUTPUT_INVALID` |
| 既有 R0/R1 改动 | **命中（就是它）** | R0/C12 联系族闸；`REFUSAL_CONTACT_ROLES={phone,address}`、题面复算 `field_roles=(location, phone, status)` ⇒ 交集非空 |

**同层内其它早退分支也被排除**：`answer.py:842-849` 的同码拒答要求 `not plan.field_role`，而本轮 `field_role=location`（旧轮 facts 的 `field_role_codes=["location"]` 亦同）；legacy 侧 `intent.py:526`/`service.py:2228` 只在 legacy 路径生效，本轮 `path=rag`；`DOCUMENT_NOT_FOUND`/`UNKNOWN_STORE`/`EMPTY_QUERY`/`MULTIPLE_ENTITIES`/`PRIMARY_STORE_TARGET`(106b) 都会给出各自不同的 `reason`，本次 `reason` 唯一。

**渲染面闭合证据（不回显文本）**：本次答案文本 sha256 前 16 位 `2ad69949b4b55fdf`，与产品固定模板 `copy.text("SECURITY_RESTRICTED_CONTACT")`（98 字、无数字、1 行）的 sha256 前 16 位**完全相同**；`answer_result` 与 `commit_observed` 文本逐字节相等。即渲染的就是该固定模板，没有任何事实值。

**打分是机械后果**：`no_answer`→`conversations/service.py:2260` 的 `_RAG_KIND_MAP` 映射成公开 `not_found`；`should_refuse=false` ⇒ `kind_correct` fail + `refusal_unexpected` fail；零值零引用 ⇒ `value_hit`/`source_hit` fail。四项失败与 `01-safe-projection/r2-quality-checks.json` 完全一致（`value_expected 2 / matched 0`、`source_expected 2 / matched 0`）。

## 4. 合成绿 vs 真实拒答：差异清单

三个点名节点在**当前代码**上全绿（离线，netguard fixture 生效）：

| 节点 | 结果 | 退出码 |
|---|---|---|
| `backend/tests/integration/test_r2_202c_c29_join_rag.py` | **13 passed / 0 failed** | 0 |
| `backend/tests/integration/test_r2_202d_uniqueness.py` | **14 passed / 0 failed** | 0 |
| `backend/tests/integration/test_r2_203c_f1_http_join_witness.py` | **5 passed / 0 failed** | 0 |

⇒ **同形合成输入仍是 2 值 2 来源（不是拒答）**：`filters==["item"]`、facts/citations 覆盖两行实体、联结轮 0 模型调用，这些断言全部仍成立。**合成绿而真实拒答**，说明真实题面与合成形态**不同形**。

用产品**纯谓词**对真实题面与合成题面各求一次（只输出角色码/布尔/计数，`03-c29-probe/`）：

| 形态 | `field_roles` | 角色数 | 含 phone | C12 闸 | 期望行为 | 实际行为 |
|---|---|---|---|---|---|---|
| 合成联结 A / B | `location, status` | 2 | false | 不触发 | answer | answer |
| 合成 C1（只问位置） | `location` | 1 | false | 不触发 | answer | answer |
| 合成 C2（只问店家属性） | `status` | 1 | false | 不触发 | answer | answer |
| 合成 C3（物品+电话，冻结安全反例） | `phone` | 1 | true | **触发** | 拒答 | 拒答 |
| **真实 C29** | **`location, phone, status`** | **3** | **true** | **触发** | **answer（`should_refuse=false`）** | **拒答** |

差异清单（布尔/计数）：
1. 角色集合大小：合成联结形态 **2**，真实 C29 **3**；
2. 是否含 `phone`：合成联结形态 **false**，真实 **true**；
3. 合成件里的拒答反例只有 **phone-only**（C3），**没有** “location+phone+status” 这种混合形态 ⇒ 该组合形态是未覆盖区；
4. 真实 C29 的两个期望值都是**非数字文本**（`numeric_expected_count=0`、`text_expected_count=2`）⇒ 被判分的期望值里**没有纯数字串**，`phone` 角色与被判分值无关，属“顺带被请求到的角色”；
5. `is_contract_credential_question=false`（凭据词族命中 **0**）、`is_policy_question=false`、`is_regulation_question=false` ⇒ 触发的是**第一个析取项**（物品/标识已被点名 ∧ 角色∩{phone,address}），不是 R1/102c 凭据族。

其它四案同一谓词复算（对照，说明闸只对 C29 触顶）：C08/C19/C25 `field_roles=["location"]`、闸不触发；C14 为两回合案，契约无单一 `question` 字段 ⇒ `case_question_absent`（NOT-RUN）。

## 5. 是否「本批引入」

**否。** 三条独立证据：

1. **改动面**：本批可剥离补丁只有三个文件（`evidence/05-fix/R2-202C-MINE-rollback.patch.txt`、`R2-202D-MINE-rollback.patch.txt`），命中的 `rag/query.py` **不在其中任何一个**；
2. **hunk 行号**：本批 `answer.py` 的 hunk 头是 `-284,6`、`-318,7`、`-822,6`、`-843,17`、`-892,7`，全部落在安全早退分支（`answer.py:124-141`）**之外**；
3. **规则自述与时间线**：规则本体注释即 `R0/C12 (2026-11-16)` 与 `R1/T-R1-102c (2026-11-17)` 的产物（`query.py:34-61`）；旧 envelope 产生于 `2026-11-16T01:49Z`（本地 09:49），R0 首个仓外工作目录出现于本地 `2026-11-16 16:11`、R1 于 `2026-11-17 10:45` —— 全部**晚于**旧 envelope。旧轮签名也吻合：`kind=answer`、facts 的 `field_role_codes=["location"]`、`filters=1`。

⇒ 结论：**既有 R0/R1 改动的过拒**，本批 202C/202D 代码在一次真实 C29 里**根本没有被执行**。

**必须保留的不确定（不粉饰）**：本次可证的是“C12 联系族闸在本次题面上触发”；无法区分“闸门新增”与“请求角色集合扩张（把 `phone` 认了出来）”谁先变 —— 旧 `code_version e3b4b29…` 不在仓库，旧轮 envelope 也未投影 `field_roles`。此点标 `undetermined` + 缺口码 **`old_code_version_unavailable`**。

**红例（非本批，但会在任何一次真实 C29 重跑上复现）**
- 形态：`field_roles = (location, phone, status)` 且物品/标识被点名 ⇒ `query.py:1812` 触发 ⇒ 计划层 `SECURITY_RESTRICTED_CONTACT`。
- 最小复现（离线、零调用、不改产品）：
  1) `cd backend`；`..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_202c_c29_join_rag.py -q -p no:cacheprovider --basetemp=<OS_TEMP>\r2-205d-pytest\202c` ⇒ 13 passed（同形合成不拒答，含 C3 phone-only 拒答）；
  2) `..\.venv\Scripts\python.exe -X utf8 docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/09-attempt1/work/probe_c29_plan_predicate.py --binding <ATTEMPT1>\plan\bindings\run2-pre_v05_without_v07.binding.json --case H2V3-C29` ⇒ `field_roles=(location, phone, status)`、`contact_disjunct=true`、`is_contract_credential_question=false`；
  3) 把第 2 步的角色集合与 `query.py:1812-1822` 的析取项对照 ⇒ 闸必然触发，与检索/事实/模型无关。

## 6. 下一次最小修法候选（**不实施**）

| # | 修点 | 一句话 | 预期效果 | 风险 |
|---|---|---|---|---|
| **F1** | `backend/src/mktkb/rag/query.py:1812-1822` | 把“物品 + 联系族角色 ⇒ 整体拒答”改为“联系族是**唯一**请求面时才整体拒答；同时请求非联系角色时，剔除 `phone`/`address` 角色后继续作答” | C29 得到正常计划（`filters` 含 `item`、`field_roles=(location,status)`），202C 联结 / 202D 唯一性守卫按设计生效 ⇒ 期望 2 值 2 来源 | 触碰 R0/C12 冻结面：C12 t7（物品+对接人+合作状态，`should_refuse=false`）与 C3（物品+电话 ⇒ 拒答）必须逐条复验；若题面真在索取电话值，会从“整体拒答”退化为“少渲染”，需口径确认 |
| **F2** | `backend/src/mktkb/rag/query.py:62-85`（`FIELD_WORDS["phone"]` 等词条） | 复核 `phone` 词表是否把非电话诉求误判成 `phone` 请求；若属误命中，**只**收窄该词条 | `field_roles` 不再含 `phone` ⇒ 闸不触发，按原名计划作答 | R0/C27 正是为让 contact 列进证据面而补这类泛词；收窄会回退 C27（`value_hit` 缺值 / `role_missing`） |
| **F3** | — | `insufficient_evidence`：证据不足以在 F1/F2 之间定夺 | — | 需最小补采：①取回 `code_version e3b4b29`（或 r0/r1 轮 `query.py`）快照，对同一题面离线复算 `field_roles` 与 C12 闸，判定先后；②在 202C 合成件补 `location+phone+status` 三形态并按冻结口径断言；③由可读题面者确认该题是否真在问电话/联系方式 |

两候选都不改判据、不改期望、不动评分器；也不需要在 202C/202D 的联结代码上做任何修补（本症状与之无关）。

## 7. 出站守卫与 NOT-RUN

守卫（`r2_safe_project.NetGuard`，每次工具运行都装一次并做正对照）：

```json
{"socket_blocked": true, "urllib_blocked": true, "httpx_blocked": true,
 "subprocess_guard_installed": true, "outbound_allowed": 0,
 "blocked_attempts": 2, "blocked_subprocess_attempts": 1,
 "positive_control_attempts": 3, "positive_control_blocked": true}
```

以上数字在四处独立落盘件里一致：`01-safe-projection/r2-quality-checks.json`、`02-case-boundary/summary.json`、`03-c29-probe/c29-layers.json`、`03-c29-probe/c29-plan-predicate.json`。

NOT-RUN / 缺口：

| 项 | 原因 | 缺口码 |
|---|---|---|
| 真实 R2 重跑 / 真实模型调用 | 已由上游执行；本诊断零真实调用 | `none` |
| 全量 pytest | 任务约束：只跑点名节点 | `none` |
| 旧 envelope 重解封 | 旧轮证据 key 不可得（在 `<RUN_ROOT>` 旧轮与 `<HOLDOUT_ROOT>` 内按回执 `evidence_key_sha256` 搜索无命中） | `old_evidence_key_unavailable` |
| 旧轮 `plan.field_roles` / `plan.reason` | 旧轮 8 层投影不含这两个字段 | `old_layer_not_projected` |
| 旧 `code_version e3b4b29` 复算 | 未提交工作树、无快照 | `old_code_version_unavailable` |
| C14 计划谓词 | 两回合案在契约里无单一 `question` 字段 | `case_question_absent` |
| C29 分页检查 | 从未进入检索，无分页输入 | `not_reached` |

## 8. 复现命令（占位符见文首）

```powershell
# 0) 逐层事实 + 8 层表（原工具，只换路径/输出名；不覆盖旧目录）
.venv\Scripts\python.exe -X utf8 docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/work/r2_boundary_ext.py `
  --key <ATTEMPT1>\ev.key `
  --binding <ATTEMPT1>\plan\bindings\run2-pre_v05_without_v07.binding.json `
  --evidence-root <ATTEMPT1>\evidence\p2-h2v3-20261115-r2-pre_v05_without_v07 `
  --receipt <ATTEMPT1>\seal\p2-h2v3-20261115-r2-pre_v05_without_v07\run-receipt.json `
  --seal-manifest <ATTEMPT1>\seal\p2-h2v3-20261115-r2-pre_v05_without_v07\seal-manifest.json `
  --case-plan <ATTEMPT1>\out\controlled\case-plan.json `
  --out-dir docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/09-attempt1/02-case-boundary `
  --base-dir docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/09-attempt1/02-case-boundary/base `
  --quiet

# 1) C29 结构探针（固定码/计数/布尔/哈希）
.venv\Scripts\python.exe -X utf8 docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/09-attempt1/work/probe_c29_layers.py `
  --key <ATTEMPT1>\ev.key --case-plan <ATTEMPT1>\out\controlled\case-plan.json `
  --evidence-root <ATTEMPT1>\evidence\p2-h2v3-20261115-r2-pre_v05_without_v07 `
  --case H2V3-C29 --out docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/09-attempt1/03-c29-probe/c29-layers.json

# 2) 计划层谓词复算（只出角色码/布尔/计数）
.venv\Scripts\python.exe -X utf8 docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/09-attempt1/work/probe_c29_plan_predicate.py `
  --binding <ATTEMPT1>\plan\bindings\run2-pre_v05_without_v07.binding.json --case H2V3-C29 `
  --out docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/09-attempt1/03-c29-probe/c29-plan-predicate.json

# 3) 点名合成节点（cwd=backend；basetemp 放 OS 临时区，仓库外；本诊断逐节点执行：13 / 14 / 5 passed）
cd backend
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_202c_c29_join_rag.py -q -p no:cacheprovider --basetemp=<OS_TEMP>\r2-205d-pytest\202c
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_202d_uniqueness.py -q -p no:cacheprovider --basetemp=<OS_TEMP>\r2-205d-pytest\202d
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_203c_f1_http_join_witness.py -q -p no:cacheprovider --basetemp=<OS_TEMP>\r2-205d-pytest\203c
```

## 9. 产物清单

| 文件 | sha256（前 16） |
|---|---|
| `01-safe-projection/r2-quality-checks.json`（上游产出，本诊断只核 sha） | `76b04e8a63fd3ab3` |
| `02-case-boundary/summary.json` | `2a8c425359d5db6a` |
| `02-case-boundary/H2V3-C29.json` | `736fc61065af1172` |
| `02-case-boundary/base/H2V3-C29.json` | `b7ebcf2770650a6d` |
| `03-c29-probe/c29-layers.json` | `0ae348e519218724` |
| `03-c29-probe/c29-plan-predicate.json` | `aaa03bd8548235b7` |
| `03-c29-probe/plan-predicate-{C08,C19,C25}.json` | `da1f4fea…` / `898347e0…` / `5bcfe64f…` |
| `work/probe_c29_layers.py` | `352dc0ac8761df8a` |
| `work/probe_c29_plan_predicate.py` | `5cc8a5e6427b6905` |
| `R2-205D-DIAGNOSIS.json` | 见 JSON `hashes` 段（本文件不自我入表） |
