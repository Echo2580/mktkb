# C1-P2 空集闭包证明：全新独立验收报告

主人，本报告是 **C1-P2（Q1A-EVAL-REPAIR）的全新独立验收**：非开发、非经理、与开发无共享历史。验收对象是 `p2_empty_scope_proof.py` + 合成测试 + 开发报告与证据；只读参考是 C 冻结 12 对象中的 `p2_hard_evidence.py` / `p2_evidence_rescore.py` / `p2_evidence_rescore_axes.py`。本报告**不写** T207 通过、不写 release/阈值/基线批准、不写 P2 完成、不写 C1-2 可跑。

## 0. 基线与边界（实测）

| 项 | 实测 |
|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b0066726e5b8d6f94cbc0b63a890084550c106`（前后一致） |
| 暂存区 / commit | `0` / `172`（前后一致，未新建 commit） |
| 15 tracked modified | 15/15 路径与 `axes/evidence/04-protected-hashes-before.json` 逐字节一致 |
| C 冻结 12 | 12/12 一致；`p2_hard_evidence.py = fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b` |
| 只读参考 | `p2_evidence_rescore.py = d8260256…f3e9`、`p2_evidence_rescore_axes.py = 57495943…f08e`，前后一致 |
| 验收对象 SHA | 模块 `1f503d16…f28ea` / 35240 B；测试 `a2b20218…85a1` / 50710 B；与开发报告 §1.1 逐值一致 |
| 本会话写入 | 仅 `c1-1/p2/independent/` 与 `c1-1/p2/{independent-review.md,review-aggregate.json}`；未改开发文件/冻结件 |
| 数据边界 | 只用合成/公共数据；未读真实 H2 题面/标签/答案/私有密文/key/`.env`/保管会话；私密外部项只重算 SHA256/字节数，未解密 |
| 零真实调用 | socket/DNS/httpx/socket.connect 全 0；正对照拦截并记账（见 §2.6） |

## 1. 一句话结论

**`PASS_WITH_DISAGREEMENTS`（有条件通过）。**

- **技术门全过**：72 例差分逐例复算一致（12 both proven / 48 both not proven / 11 本实现 proven / 1 更严 / 0 未编码）；267 个 fail-closed 探针 0 偏离；88 项测试 0 skip/xfail；C 冻结 12/12、15 tracked、外来 untracked 2086 文件、7 个私密外部项全部不变；零调用有 3 路正对照。
- **实质分歧 2 例**：12 个分歧中 **9 例合法覆盖扩展 + 1 例合法更严 + 2 例过度宽松**。过度宽松的是 `frozen_requires_retrieval_marker_for_legacy_no_model`（2 例）：它把 v0.3 `candidate_observation = not_observed / no_retrieval_observed` 当作“无检索”的正证据；而合同 §3.2 明确写 **`not_observed` 的 `candidates=[]` 不是“空候选”证据**。该标记又是这 2 例从 not proven 翻成 proven 的**唯一**差别（去掉标记即 fail-closed），因此它不是“合法覆盖扩展”，而是把“没观察到”升级成“已证明”。
- **若按开发自报把 11 例全量接入 C1-2**：这 2 例会构成假 proven 风险，该接入方案应判 **FAIL**。本包本身**未接入**消费侧（开发已承认 R-C1P2-01），作为未接入的独立对象，技术门通过，故给 `PASS_WITH_DISAGREEMENTS`。**接入前必须把 class C 降级为 unknown（或等合同修订）**；否则不得签 C1-2 GO。

## 2. 逐项验收

### 2.1 差分等价复算：**PASS**

独立复算（`independent/11-divergences.py` / `11-divergences.json`，冻结原语只读 import，前后 SHA 均 `fba6e606…`）：

| 类别 | 例数 | 与开发自报 |
|---|---:|---|
| 一致且 both proven | 12 | 一致 |
| 一致且 both not proven | 48 | 一致 |
| 本实现 proven / 冻结 not proven | **11** | 一致 |
| 本实现 not proven / 冻结 proven | **1**（entity_inheritance） | 一致 |
| 未编码的不一致 | **0** | 一致 |

- 72 例逐例复算；`uncoded_divergences = []`；固定码分布 `frozen_retrieval_candidates_are_usage 7`、`frozen_query_state_candidates_are_usage 2`、`frozen_requires_retrieval_marker_for_legacy_no_model 2`、`frozen_does_not_track_entity_inheritance 1`。
- **归因精度**：7+2 是“主因归类”，不是互斥结构计数。结构上 `retrieval_observed.unit_ids` 非空的有 **8** 例（含 `multi_turn_partial_empty`），`query_state` 候选非空的有 **2** 例，其中 1 例两者重叠。该重叠不影响裁决，但报告的 7/2 不应被读成“互斥形状计数”（残余 R-C1P2-V-07，低）。

### 2.2 覆盖率：**PASS（真实，但非穷尽）**

`independent/13-coverage.py` / `13-coverage.json`：

- **72 例 / 22 shape 标签**均为实测：22 = 17 个 `branch/retrieval/outcome` 组合 + 5 个缺口标签（`branch_evidence_missing`、`branch_evidence_inconsistent`、`evidence_incomplete`、`unknown_usage_field`、`model_events_missing`）。因此“22 个 shape 标签”字面成立，但其中 5 个不是形状组合，而是缺口诊断；不应把它们当作 22 种业务形状。
- **7 类要求形状 7/7 覆盖**：无检索（3 例）、检索为空（2）、检索有结果但未使用（4+）、多轮部分轮空（3）、拒答/无事实（3，含反例）、clarification（3）、model_events 缺失（3）。
- **未覆盖/弱覆盖的合理形状**（不构成 7 类要求形状的遗漏，但影响“全部形状”的强度）：
  1. `query_state_observed/saved/cleared` **事件路径 0/72**——72 例只通过 `db_projection.query_states` 构造候选，事件分支未被测试（我的 fail-closed 探针补了 `query_state_observed`，但 `saved/cleared` 仍未覆盖）；
  2. 多轮“当前回合使用源”组合缺失（有历史消息的例都不使用源；使用源的例都没有历史消息）；
  3. RAG `query_expansion` 带非空 evidence 缺失（只有空 evidence 的正例）；
  4. 合法多检索事件缺失（仅有 2 例“未知键 + 第二检索事件”的反例）。
- 结论：**要求形状覆盖真实；但“全部形状”未被穷尽**，属于测试覆盖缺口，不是已证伪的语义错误。

### 2.3 fail-closed：**PASS**

`independent/12-failclosed.py` / `12-failclosed.json`：**267 个探针，0 偏离**。

- 非 mapping/空输入（None/[]/{}/0/"x"/object/bool/float）→ 全部 `empty_set_not_proven`。
- 11 个扩展例逐个删除每个适用 usage 容器 → 全部 not proven；逐个注入使用 id / 不可归因投影行 / 实体继承 → 全部 not proven。
- 坏类型：`source_ids` 为 str/None/int/bool/dict/`[""]`/`[1]`/`[None]`；`message_sources` 非 list/行非 mapping/`source_id` 空或非 str；`units`/`unresolved` 行坏形状；`retrieval.unit_ids` 非 list/含非 str/空串；`query_state.state_json` 非 mapping/`candidates` 非 list/`row_present` 非 bool；`completeness` 缺失/坏 status；`capture.events/errors` 缺失/坏类型；`query_states_available` 非 True；`truncations/errors` 非空；未知 envelope/capture/turn/event/payload/projection/行键；未知 event kind；必需事件缺失/重复；`capture_error` 事件；模板不匹配；answer/commit 文本或 kind 不一致；claim/request/message 身份不一致——全部 not proven。
- **默认 proven 路径**：AST 显示模块内只有 1 处 `proven=True`（成功返回，位于模板身份检查之后）；`except _ProofGap` 与兜底 `except Exception` 都返回 `_not_proven`；无 `return True` 证明路径；无网络 import。唯一“返回 True”的是模板匹配辅助函数，不构成证明。
- **已知缺口（与冻结原语同源，非本实现新增）**：`state_json` 内部的未知键不 fail-closed（`{"candidates": [], "used_sources": ["u-hidden"]}` 仍可 proven）。冻结原语同样只检查 `candidates`；本实现没有加重也没有修复。记为 R-C1P2-V-01（低）。

### 2.4 测试质量：**PASS（有 2 个可修弱点）**

- `pytest --collect-only`：**88 tests collected**；运行：**88 passed, 1 warning, exit 0**（`independent/05-pytest-independent.txt`）。
- 静态检查：**0** 个 `pytest.mark.skip` / `pytest.skip` / `xfail`；**0** 个 `assert True`；2 个 parametrize 块（23 proven + 49 not proven）。
- 差分测试**真把冻结原语当对照**：`from mktkb.evaluation.p2_hard_evidence import _empty_use_scope_proof`，逐例调用，前后断言冻结模块 SHA；不是只比自建期望值。
- 弱点 1：差分汇总只断言 `extension_proven > 0`，不钉 `== 11`（逐例 parametrize 已钉住 11 例，删例会同时减少 collected 数，但与开发报告的 88 无自动交叉校验）。低。
- 弱点 2：`query_state` 事件路径、`multi_turn + current usage`、RAG `query_expansion` 带 evidence 未覆盖（见 §2.2）。中/低。
- 测试中的 `t09_network_guard` 是真实闸门（external 非空即 teardown fail），不是空断言。

### 2.5 冻结件与保全：**PASS**

`independent/10-snapshot-{start,end}.json` / `15-final-compare.json`：

| 组 | 实测 |
|---|---|
| C 冻结 12 | 12/12，`p2_hard_evidence.py = fba6e606…`、`p2_evidence_capture.py = 601096bc…`、`p2_evidence_io.py = 1c16a3da…` |
| R2 保护 28 文件 | 28/28（含 `p2_evidence_rescore.py`、`p2_evidence_rescore_axes.py`、契约 v1、旧卡/回执） |
| Q1a-1 保护 38 + 只读参考 2 | 38/38 + 2/2（对 `axes/evidence/04-protected-hashes-before.json`） |
| 15 tracked modified | 15/15（对 axes 基线） |
| 开发文件 14 项 | 模块/测试/dev-report/evidence 全部与开工时一致（我开工时实测的 SHA） |
| 外来 untracked | R2 基线 **2086/2086 文件逐字节相等**；无 missing/changed |
| 本会话写入 | 仅 `c1-1/p2/independent/**` + 两份报告；无其他新增/改动 |
| git | HEAD/分支/暂存/commit 数前后一致；未 stage/commit/push；未新建 worktree/切分支 |

- 自 R2 基线以来新增的 82 个 untracked 文件全部落在预期产物前缀：`Q1A-EVAL-REPAIR/rescore/**` 59、`c1-1/**` 15、`scope-contract/**` 2、manager-receipt 2、taskbook 1、开发模块/测试 2、P1 合同 v2 1；**无非预期新增**。
- 并行 C1-P1 在本会话期间新增 3 个产物（`c1-1/p1/independent-review.md`、`c1-1/p1/manager-acceptance.json`、`c1-1/p1/review-aggregate.json`）；`15-final-compare.json` 把它们单列为 `concurrent_products`，不计入我的写入，也未改动其内容。
- 我自己的新增在 `15-final-compare.json` 的 `my_products` 中逐条列出（25 项），未混入开发/外来文件；`unexpected_new = []`，终态 `verdict = true`。

### 2.6 零真实调用 + 正向控制：**PASS**

`independent/14-netguard-run.py` / `14-zero-call.json`，三个独立子进程（都带 `sitecustomize` 进程级守卫）：

| 子进程 | 结果 |
|---|---|
| **control**（故意发起出站） | `socket.create_connection(203.0.113.1:9)`、`DNS example.invalid`、`httpx.HTTPTransport` **三路全部被拦并记账**（`blocked=3`，details 保留目标）；证明守卫有效，不是“没尝试” |
| **suite**（88 项正式测试） | **88 passed, exit 0**；退出时 socket/connect/connect_ex/create_connection/DNS/http.client/httpx **全 0**；`external` 无任何记录 |
| **isolated**（stub `mktkb` 只 import 新模块） | 最小可证明 envelope proven；**未加载** `p2_hard_evidence` / `p2_evidence_capture` / `p2_evidence_io` / `mktkb.providers`；外部计数全 0 |

- 说明：suite 进程会因测试本身 import 冻结模块与 `mktkb.providers`（import 不是调用）；零调用的判据是**出站计数 0**，不是“未 import”。isolated 子进程证明新模块本身不拉起 provider/冻结模块。
- 与开发 `zero-call.json` 的差异：开发是隔离探针；我的是“正式 88 项 + 正式守卫 + 3 路正对照”，更强。

### 2.7 私密外部项重读（开发自报弱项）：**PASS**

开发报告 §6 明确说 `old_run_tree`、`holdout_root`、`custody_annotations`、`contract_ciphertext`、`r1_private_detail` **未重读**，只引用 R2 基线 hash。我按要求**实际重读（受控只读，只算 SHA256/字节数，不解密）**：

| 项 | 实测 | 与 R2 基线 |
|---|---|---|
| 合同密文 | `467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461` / 47012 B | 一致 |
| custody annotations | 4 文件 / 84920 B | 逐文件一致 |
| holdout root | 5 文件 / 53485 B | 逐文件一致 |
| old run tree | 72 文件 | 逐文件一致 |
| R1 evidence tree | 13 文件 | 逐文件一致 |
| R1 私有明细 | `2f6f4d85026d4b3fb654e17f9ebbb0baac923dd93dc6fa326bb9325fdd69dacc` / 74488 B | 一致 |
| NOT-RUN evidence tree | 19 文件 | 逐文件一致 |

- 结论：开发自报的“未重读”弱项**已由独立重读关闭**；7/7 全部与 R2 基线逐字节一致，未发现私密外部项被改动。
- 我只输出路径/字节数/SHA256，未输出任何密文内容、标签、题面或答案。

## 3. 12 个分歧的逐类裁决

裁决口径（按任务单）：
- **合法覆盖扩展**：能从证据契约证明该形状下使用集确实为空，且不是“没看到使用”；
- **过度宽松**：把缺失/未解析/未观察当成空，可能造成假 proven；
- **无法判定**：证据不足，不能裁。

| # | 固定码 | 例数 | 形状 | 本实现 / 冻结 | 裁决 | 依据 |
|---|---|---:|---|---|---|---|
| A | `frozen_retrieval_candidates_are_usage` | 7 | 检索候选非空、所有使用层显式空；legacy_no_model / legacy_model_answer / rag / clarification / no_answer / knowledge_changed / with_unresolved | proven / not proven | **合法覆盖扩展** | 合同 §3.1 明确：层名 `candidate`（检索候选，**不是使用**）、`model_evidence`、`direct_rag_fact`、`direct_rag_citation`、`final_citation`、`inheritance`。11 例的适用 usage 容器**都存在且为空 list**（不是缺字段）；删字段/坏类型/注入使用 id 全部 fail-closed（§2.3）。冻结原语把候选当使用是保守过严，不是合同语义。 |
| B | `frozen_query_state_candidates_are_usage` | 2 | 会话级 `query_states[].state_json.candidates` 非空、当前回合使用层空；其中 1 例为多轮（同时含 retrieval 候选） | proven / not proven | **合法覆盖扩展** | 同上；query_state 候选是**后续回合**的检索候选，不是本回合已使用来源。`query_states_available` 必须为 True；`state_json` 缺失/坏类型/`candidates` 坏类型全部 fail-closed。 |
| C | `frozen_requires_retrieval_marker_for_legacy_no_model` | 2 | legacy 无模型、**无 retrieval_observed 事件**、v0.3 `candidate_observation=not_observed/no_retrieval_observed`、使用层显式空、固定无事实模板 | proven / not proven（`model_events_missing`） | **过度宽松（会造成假 proven）** | 合同 §3.2 原文：`not_observed` 的 `candidates=[]` **不是“空候选”证据**；`candidate_observation=not_observed` 只表示“没观察到检索”，不表示“没有检索”。该标记是 v0.3 从“无 retrieval_observed 事件 + path≠rag”**确定性派生**的（`p2_evidence_capture.build_runtime_snapshot`），不是独立观察；而它正是这 2 例从 not proven 翻成 proven 的唯一差别（无标记即 fail-closed）。冻结原语要求一个**实际存在的 retrieval_observed 观察**，新实现用“没观察到”替换了它——这正是任务单列出的“把‘没有检索事件’当成‘未使用源’”。使用层虽显式空，但方向是放宽，不能作为“已证明”接入。**建议保留 2 例为 unknown，或要求 retrieval_observed（空 unit_ids）后再证明。** |
| D | `frozen_does_not_track_entity_inheritance` | 1 | `entity_inheritance.source_unit_id` 非空、其余使用层空 | not proven / proven | **合法（更严方向）** | 合同 §3.1 把 `inheritance` 列为使用层；冻结原语漏计，本实现计为使用，只会更严，不会产生假 proven。 |

**分布：合法 10（其中 9 例覆盖扩展 + 1 例更严）/ 过度宽松 2 / 无法判定 0。**

**12 例逐例清单**（`independent/11-divergences.json`）：

| # | 用例 | 本实现 | 冻结原语 | 裁决 |
|---:|---|---|---|---|
| 1 | `retrieval_candidates_unused_legacy_no_model` | proven | not proven (`empty_set_not_proven`) | 合法覆盖扩展 |
| 2 | `retrieval_candidates_unused_legacy_model` | proven | not proven | 合法覆盖扩展 |
| 3 | `retrieval_candidates_unused_rag` | proven | not proven | 合法覆盖扩展 |
| 4 | `retrieval_candidates_unused_clarification` | proven | not proven | 合法覆盖扩展 |
| 5 | `retrieval_candidates_unused_no_answer` | proven | not proven | 合法覆盖扩展 |
| 6 | `retrieval_candidates_unused_with_unresolved` | proven | not proven | 合法覆盖扩展 |
| 7 | `retrieval_candidates_unused_knowledge_changed` | proven | not proven | 合法覆盖扩展 |
| 8 | `query_state_candidates_unused` | proven | not proven | 合法覆盖扩展 |
| 9 | `multi_turn_partial_empty` | proven | not proven | 合法覆盖扩展（同时含 retrieval 候选） |
| 10 | `no_retrieval_positive_snapshot_legacy_no_model` | proven | not proven (`model_events_missing`) | **过度宽松** |
| 11 | `no_retrieval_positive_snapshot_with_context` | proven | not proven (`model_events_missing`) | **过度宽松** |
| 12 | `entity_inheritance_without_projection_row` | not proven | proven (`empty_use_scope_ok`) | 合法（更严） |

补充：
- 9 例候选层扩展的“使用层显式空”已逐例验证（`independent/11-divergences.json` 的 `all_applicable_usage_explicit_empty = true`），不是“没看到使用”。
- 9 例中 `multi_turn_partial_empty` 同时有 retrieval 候选与 query_state 候选；开发把它归到 query_state 主因。结构计数应为 7 例 retrieval-only + 1 例 query_state-only + 1 例两者重叠（残余 R-C1P2-V-07，低）。
- 2 例 class C 的 `retrieval_absent` 形状标签也**过度声称**（`not_observed` 不是 absence），即使只读标签也不应写成 `retrieval_absent`；这是同一缺陷的另一面。

## 4. 若接入，R2 的哪几条轴会翻、翻转是否成立

R2 公开聚合（`rescore-aggregate-r2.json`）的实测口径：

- 36 回合：冻结原语 `proven 2` / `empty_set_not_proven 32` / `model_events_missing 2`。
- `stale_source` 17 unknown = `source_unresolved 13` + `empty_set_not_proven 2` + `model_events_missing 2`；`empty_scope_not_proven` 审计引用 4。
- `cross_entity` 审计引用 `empty_scope_not_proven 1`；该轴轴级 reason 不是 `empty_set_not_proven`（是 targets_unresolved / free_text）。
- 题级：`pass 1 / unknown 29 / hard failure 0`。

| 轴 | 任务口径可翻 | 公开聚合可定位 | 我的裁决 |
|---|---:|---|---|
| `stale_source` | **6** | 轴级 2 条 `empty_set_not_proven` + 2 条 `model_events_missing`；审计引用 4（可能与轴级重叠）；其余 2 条公开侧不可定位 | **可确认不成立 2**（`model_events_missing` = class C，标记是唯一差别）；**部分成立 ≤2**（`empty_set_not_proven` 只有在该回合是 A/B 形状且使用层显式空时才成立；公开数据不能确认）；**无法判定 ≤2**（任务上限 6 中无法定位的其余） |
| `cross_entity` | **1** | 审计引用 1；轴级 reason 是 targets_unresolved/free_text | **部分成立/无法判定**：若是 A/B 形状可翻到 pass 或 N/A；若是 class C 则**不成立**。公开数据不能确认；且该轴所属题仍受合同实体 targets / free_text 阻断，翻轴不等于题级合格 |
| **合计** | **7** | — | **可确认成立 0；部分成立 ≤3（stale 2 + cross_entity 1）；可确认不成立 2；无法判定 ≤2** |

**题级影响**：R2 §10.5 已说明 9 条 stale 转移**没有**改变题级 pass（cross_entity 仍 unknown）。本次即使 2 条 stale + 1 条 cross_entity 全部按 A/B 成立，题级合格上界也只是 **2/30**（cross_entity 那 1 条所属题若其余 required 轴全 pass），仍远低于 24/30；若 class C 被接入，多出来的 2 条 stale 翻转是**假通过**，不是可判化收益。

**结论**：这 11 例若被采用，**不会**把 R2 从 29 unknown 大幅降到可判；可确认成立的轴是 **0**，可确认不成立的是 **2**，其余最多 3 条依赖逐回合形状（私有明细，本验收不读）。因此“接入后 6 条 stale + 1 条 cross_entity 多半翻 pass”的说法**不成立**；至少 2 条是方向错误的放宽。

## 5. 残余 R 码（本验收新增，不替代开发 R-C1P2-01..08）

| id | 严重度 | 内容 |
|---|---|---|
| R-C1P2-V-01 | low | `state_json` 内部未知键不 fail-closed（`{"candidates": [], "used_sources": [...]}` 仍可 proven）；冻结原语同源，非本实现新增，但与本模块“未知键 fail-closed”的声明不一致。 |
| R-C1P2-V-02 | **high** | class C（2 例）把 v0.3 `candidate_observation=not_observed` 当“无检索”正证据，与合同 §3.2 冲突；该标记是翻 proven 的唯一差别。**接入前必须降级为 unknown 或等合同修订。** |
| R-C1P2-V-03 | low | `shape` 标签混合 17 个 `branch/retrieval/outcome` 组合与 5 个缺口标签；开发报告的“22 shape 标签”字面成立，但不是 22 种业务形状。 |
| R-C1P2-V-04 | medium | 72 例未覆盖 `query_state_observed/saved/cleared` 事件路径（0/72）；只覆盖 `db_projection.query_states`。`saved/cleared` 分支未被任何测试或探针覆盖。 |
| R-C1P2-V-05 | low | 未覆盖：多轮“当前回合使用源”、RAG `query_expansion` 带非空 evidence、合法多检索事件；这些是合理形状，不属 7 类要求形状的遗漏。 |
| R-C1P2-V-06 | medium | 所有 not proven 统一 `empty_set_not_proven`，丢失冻结原语的 `model_events_missing` / `branch_evidence_missing` 等细分；若 C1-2 继续用 reason 作固定码，R2 的 `empty_set_not_proven 32 / model_events_missing 2` 会塌成 34/0，诊断不可追溯（开发已承认 R-C1P2-03）。 |
| R-C1P2-V-07 | low | `multi_turn_partial_empty` 归因到 query_state，但结构上同时含 retrieval 候选；7+2 不是互斥形状计数。 |
| R-C1P2-V-08 | low | 差分测试 summary 只断言 `extension_proven > 0`，不钉 `== 11`；逐例 parametrize 已钉住，但删例不会触发汇总断言。 |
| R-C1P2-V-09 | info | 未接入 `p2_evidence_rescore.py` / `p2_evidence_rescore_axes.py`（开发已承认 R-C1P2-01）；本包不产生真实 R2 数字，这是范围不是缺陷。 |
| R-C1P2-V-10 | low | `entity_inheritance` 计为使用更严；可能把一些真实回合从 proven 变 not proven（保守方向，不产生假 pass）。 |

## 6. 边界声明

- **只读/合成**：本验收只使用合成 envelope 与仓内公共证据；未读真实 H2 题面/标签/答案/私有密文/key/`.env`/保管会话。私密外部项只重算 SHA256/字节数，未解密、未输出内容。
- **不改**：未改开发文件、C 冻结 12、Q1a-1/1b 模块与契约、旧卡/账本/GO/预算、合同密文；未改 15 tracked modified。
- **不提交**：未 stage/commit/push/合并/部署；未新建 worktree/切分支。
- **零真实调用**：socket/DNS/httpx 全 0；3 路正对照证明守卫有效。
- **不主张**：T207 通过、P2 完成、release/阈值/基线批准、C1-2 可跑；不主张 11 例扩展在真实证据上一定成立；不主张真实 R2 会翻几条轴（只给公开聚合的可定位上界）。

## 7. 最终结论

**`PASS_WITH_DISAGREEMENTS`**。

- 作为**未接入**的独立量具对象：技术门（差分、fail-closed、测试、冻结、保全、零调用、私密重读）全部通过；9 例候选层扩展合法，1 例更严合法。
- 作为**C1-2 接入方案**：**不通过**——class C 的 2 例是过度宽松，接入会把“没观察到检索”伪装成“已证明空集”，对应 R2 的 2 条 `model_events_missing` stale 轴翻转**不成立**。
- **放行条件**：把 class C 的 2 例保留为 `empty_set_not_proven`（或改为要求 `retrieval_observed` 空 unit_ids），并在接入包里补 `query_state` 事件路径与细分 reason 的薄适配；满足后可再走一次限定验收。
