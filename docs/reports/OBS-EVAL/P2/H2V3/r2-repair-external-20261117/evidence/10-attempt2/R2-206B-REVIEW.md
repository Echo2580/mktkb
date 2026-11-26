# R2-206B — 增量独立复验（contact 闸门修复）·外部复验者

- 复验者：本会话执行者（**未参与** 206A/206B 修复实现）。
- 对象：`backend/src/mktkb/rag/query.py` 单 hunk（`+27/−2`，sha256 `bedeedab…6fb0`；改前 `69ab6a8c…0cbd`）。
- 工作树：`D:\GPT项目\市场部AI知识库`（HEAD `97b0066`，含 R0/R1/R2 未提交成果，无 git 写操作）。
- Python：`.venv\Scripts\python.exe -X utf8`；pytest cwd=`backend/`；basetemp 全部在仓库外
  `D:\mktkb-p2-h2v3-r2-20261117\basetemp-206b\*`。
- 改前树：仓库外沙箱 `D:\mktkb-p2-h2v3-r2-20261117\r2-206b\sandbox-pre\backend`
  （`src`/`tests`/`migrations` 逐字节拷贝，`git apply -R R2-206A-MINE-rollback.patch.txt` 反向应用；
  反向应用后 `query.py` sha256 = `69ab6a8cbb6366f6e3674663f7fde624cef9229ab4a03b8e52205ecf951e0cbd`，
  与补丁头声明的 base 逐字符相同）。
- 自建探针：`backend/tests/integration/test_r2_206b_contact_gate_increment.py`（20 用例；
  与 206A 交付测试的实体/值/文档名/问句全部不重叠）。
- 全部实体、值、文档名均为虚构（松涛店/竹溪店、电热壶/文件柜、`020-00000011`、`示范巷27号`、
  `合成负责人·丙`）；未读取 fixtures、题面、真实 case_id 或期望值。

---

## §0 结论

**不放行真实 attempt2**（1 个阻塞项，见下）。A/B/D/E 均通过，C 在 `sources[].locator.cells`
一面失败。

| 项 | 判定 | 一句话依据 |
| --- | --- | --- |
| A 混合形态转绿 | **PASS** | 三角色/四角色混合均 `kind=answer`、正文同时含位置值与状态值、无电话/地址/联系人值、`sources=2`、`plan.field_roles=(location,status)`、模型 0 调用（改前树同两例为 `not_found`+`sources=[]`） |
| B 冻结面 | **PASS** | B1/B2/B3/B4a/B4b 五例在改前/改后两棵树的**全表面规范化快照逐字节相同**（SHA256 同为 `92bc7e76…6858`，40433 B），B4 双角色仍走同一早退分支 |
| C 泄漏面 | **FAIL** | 正文 / facts / 模型证据 / 捕获 envelope 均闭合；但 `sources[].locator.cells[].display`（店家行）**带出电话、地址、联系人三个值**（改前该题整题拒答、`sources=[]` ⇒ 本批首次可达） |
| D 其它安全面 | **PASS** | `conversations/intent.py:507-527` 第二道闸门未被绕过（非枚举混合仍整题拒答）；保护面 **180 passed / 0 failed**；仓库外 M5 **2 passed** |
| E 范围核对 | **PASS（含 2 条保留）** | 会话内被改产品文件恰为声明的 4 个（哈希逐值相符）；评测器三件与 `budget.json` 未变；`live-ledger.jsonl`（19:29:39）与 `P2-LIVE-GO.json`（20:17:41）相对 R2 开工基线已变——见 §3 保留意见 R3/R4 |

### 放行条件（前置）

1. **阻塞项 C-1 必须先裁定**：把受限列从引用 locator 里脱敏（`cells` 只保留被引用的、
   已请求角色的单元格；或对 `电话/地址/联系人` 列做 redaction），并补一条断言
   `sources[].locator` 不含受限值的既有回归；**或**
2. 主人**书面裁定**：`locator` 属"来源指针/非答案内容"，接受该暴露面，并在 attempt2 报告与
   案例口径中登记为已知残留（同时给 follow-up 任务号）。在此裁定缺位前，本复验结论为**不放行**。

---

## §1 A–E 逐条证据

### A 混合形态：转绿且正文不泄漏

命令（改后 = 工作树）：

```
cd backend
..\.venv\Scripts\python.exe -X utf8 -m pytest tests/integration/test_r2_206b_contact_gate_increment.py -q -p no:cacheprovider
```

| 用例 | 结果 | 关键观测（改后） |
| --- | --- | --- |
| `test_a_mixed_roles_answer_without_contact_values[a1_mixed3]` | PASS | `plan.reason=None`、`field_roles=["location","status"]`、`state.field_roles` 同值、`enumerate=True`；`kind=answer`；正文含 `丙区2号架` 与 `合作中`；`sources` = 2 份资料；三受限值均不在正文；模型 0 调用 |
| `…[a2_mixed4]`（再加 address） | PASS | 同上，四角色与三角色 `plan.field_roles`、`facts` 完全同形 |
| `test_a_mixed_roles_are_identical_across_three_and_four_role_forms` | PASS | 三角色/四角色 `field_roles` 与 facts 相等 |
| `test_a_mixed_dump` | PASS（改后）/ FAIL（改前，预期红） | 改前同两题为 `plan.reason=SECURITY_RESTRICTED_CONTACT`、`kind=not_found`、`sources=[]`、模型 0 |

改后正文原文（`R2-206B-mixed-after.json`）：

```
共 2 条，当前第 1 页显示 2 条。
- 松涛店的电热壶：位置 丙区2号架（来源：物品位置台账草案B.xlsx）（记录 …）
- 松涛店：合作状态 合作中（来源：合作店家名册草案B.xlsx）（记录 …）
已显示全部。
```

退出码：改后 `1`（仅 2 例 C-1 失败，见 §1 C）；改前 `1`（8 例失败，其中 4 例是 A 的预期红态）。

### B 冻结面：与改前逐字节相同

对照方法（两棵树、同一探针、同一数据集）：

| 树 | `mktkb` 实际 import | `query.py` sha256 |
| --- | --- | --- |
| 改前（沙箱 + 反向补丁） | `…\sandbox-pre\backend\src\mktkb\__init__.py` | `69ab6a8c…0cbd` |
| 改后（工作树） | `D:\GPT项目\市场部AI知识库\backend\src\mktkb\__init__.py` | `bedeedab…6fb0` |

快照 `R2-206B-dump-{before,after}.json` 覆盖**全表面**（不是只有 kind/text/sources）：
`prepare` 计划（reason/mode/field_roles/state_field_roles/enumerate/filters）＋ `qa.answer()`
（kind/text/reason/answer_source/facts/citations.locator/diagnostics）＋ HTTP `AskResult`
（kind/text/sources.document_name+version_number+status+locator/candidates/missing_fields/
pagination）＋ 本次新增的模型调用（purpose/question/evidence.text/evidence.fields）＋
捕获 envelope 全部事件（`plan_observed`/`direct_rag_answer`/`answer_result`/…）。
仅剔除 id/时间戳/`elapsed_ms`/`evidence_ids` 等单次运行易变身份。

| 用例 | 改前 | 改后 | 改前 vs 改后 |
| --- | --- | --- | --- |
| `test_b1_item_plus_phone_only_still_refused` | `not_found` / 同一拒答文案 / `sources=[]` / facts=[] / citations=[] / 模型 0 | 同左 | **逐字节相同** |
| `test_b2_item_plus_contact_only_still_answered` | `answer` / 同一正文 / `sources=["物品位置台账草案B.xlsx"]` / 模型 1 次 | 同左 | **逐字节相同** |
| `test_b3_credential_family_still_refused` | `not_found` / `SECURITY_RESTRICTED_CONTACT` / 位置值与状态值也不出现 / 模型 0 | 同左 | **逐字节相同** |
| `test_b4_dual_role_mixed_still_refused[b4a]`「位置 + 联系电话」 | `plan.reason=SECURITY_RESTRICTED_CONTACT`、`field_roles=[]`、`not_found`、`sources=[]`、模型 0 | 同左 | **逐字节相同** |
| `test_b4_dual_role_mixed_still_refused[b4b]`「找谁对接 + 电话和地址」 | 同左（`others=1`） | 同左 | **逐字节相同** |

- 快照 SHA256（两棵树完全相同）：`92bc7e7668e3bbfd86a86752167bdc420e96e7425af2b68b7c5e7c08622b6858`，
  各 40433 B（`Get-FileHash` 实跑）。
- 阈值证据（机制级，不依赖文案）：`rag_query.field_roles_for_question("…放在什么位置，联系电话是多少？")`
  的 `others = set(roles) - {phone,address}` 长度为 **1**；B4 两例因此 `mixed_restricted_roles=False`
  ⇒ 走原早退分支（不是被下游文案兜底）。四角色混合的 `others` 长度 = 2 ⇒ 放行，符合声明。
- **不是"偷偷放宽"**：改前树里这两题本来就拒答，改后树全表面同哈希；且 `others≥2` 的判定在
  `test_b4_threshold_is_two_others_not_one` 里被单独测到（`others=1` vs `others=2` 的分界）。

### C 泄漏面（最关键）：**FAIL**

| 面 | 判定 | 证据 |
| --- | --- | --- |
| C-1 正文 | PASS | `丙区2号架`/`合作中` 在；`020-00000011`/`示范巷27号`/`合成负责人·丙` 均不在 |
| **C-2 `sources[].locator.cells`** | **FAIL** | 见下（HTTP 原始 `AskResult` 内） |
| C-3 facts | PASS | `facts` 角色集合 = `{location,status}`，值集合与三受限值不相交 |
| C-4 模型证据字段 | PASS | 混合形态结构化枚举 ⇒ **模型 0 调用**，证据面不可达；对既有非混合放行面（只问对接人）实测模型只收到物品行 `{门店,物品,标识,位置,数量}`，无电话/地址 |
| C-5 捕获 envelope | PASS | `plan_observed.field_roles` 无 phone/address；`direct_rag_answer.facts` 只含 location/status；整个事件流序列化后不含三受限值 |
| C-6 `requested_fields` | PASS | envelope 中**不存在**该键（本仓角色码键是 `plan_observed.field_role(s)`）；显式断言所有事件均无该键 |

C-2 实测（`R2-206B-mixed-after.json` 的 JSON 路径，逐条命中）：

```
.a1_mixed3.body.sources[1].locator.cells[2].display = 合成负责人·丙
.a1_mixed3.body.sources[1].locator.cells[3].display = 020-00000011
.a1_mixed3.body.sources[1].locator.cells[4].display = 示范巷27号
.a1_mixed3.rag.citations[1].locator.cells[2..4].display = 同上
.a2_mixed4.* 同形（共 12 处命中）
改前同两题：命中 0 处（整题拒答、sources=[]）
```

- 命中的是**店家行**（`合作店家名册草案B.xlsx` 第 4 行，列 A–F = 标识/店家/联系人/电话/地址/合作状态）。
  该行被 202C 的「物品行 + 同门店」联结拉入取证面后，作为第 2 条来源引用返回；
  `locator.cells` 是**整行**单元格的值快照（`display` 为真实值，不是区间字符串）。
- 归因（防止夸大）：**店家级问题（本批未改动的既有放行面）同样带出整行值**——
  `test_c_store_level_citation_locator_is_a_preexisting_surface` 在改前/改后两棵树都输出
  `STORE_ONLY_LOCATOR_LEAK ["020-00000011","示范巷27号","合成负责人·丙"]`。
  ⇒ 泄漏机制是既有 citation 设计；**本批的贡献是让一个原本整题拒答的混合题首次走到该面**。
- 影响面：`value_forbidden`（`evaluation/scorers.py:700-708`）只对 `text` 做 `check_value`，
  **不会**扫 `sources`；因此 C29 的冻结质量检查会把该形态判绿，`source_forbidden` 也只比来源身份。
  "C29 转绿"**不能**当作"无泄漏"的证据。

### D 其它安全面

1. 第二道闸门（`conversations/intent.py:507-527`，`RESTRICTED_CONTACT_FIELDS={联系人,电话,地址}`）：
   - `test_d_legacy_second_gate_still_refuses_non_enumerated_mixed` PASS：
     该题 `plan.reason=None`、`enumerate=False`、`_rag_owns_turn()=False`（改后），
     而 `conv_intent.parse_question("…放在哪个位置，合作状态如何，电话是多少？")`
     返回 `security_refusal="SECURITY_RESTRICTED_CONTACT"` 且 `requested_fields` 含「电话」；
     用户面仍是同一拒答文案、`sources=[]`、模型 0 调用、位置值/状态值也不出现。
   - 改前树里同一用例在**规划层**就早退（`reason=SECURITY_RESTRICTED_CONTACT`）⇒ 两道闸门是
     "或"关系，本批只是把第一道收窄，第二道仍在原位、未被绕过。
   - 附带观测：`others=2` 但**非枚举**的形态（「位置 + 数量 + 电话」）规划层已放行，
     用户面仍被第二道闸门拒答 ⇒ 本批"转绿"只对 `_rag_owns_turn` 为真的枚举轮次生效。
2. 保护面（自跑，20 个文件，cwd=`backend/`）：
   `tests/rag/test_r0_c12_join_synthetic.py`、`tests/integration/test_r0_c12b_t7_boundary_e2e.py`、
   `tests/rag/test_r0_c12b_boundary_synthetic.py`、
   `tests/rag/test_r0_c12_legacy_trim_identifiability_synthetic.py`、
   `tests/rag/test_r0_11_contact_family.py`、`tests/integration/test_r2_202c_c29_join_rag.py`、
   `tests/integration/test_r2_202d_uniqueness.py`、`test_r2_203c_f1..f4`、
   `tests/rag/test_r1_102b/102c/106a/106b`、`tests/evaluation/test_p1_refusal_controls.py`、
   `tests/integration/test_v3_safety_fix_e2e.py`、`tests/unit/test_v3_safety_fix_policy.py`、
   `tests/rag/test_t207_security_precedence_synthetic.py`、
   `tests/unit/test_t207_v8_safety_contract_synthetic.py`
   ⇒ **180 passed / 0 failed，退出码 0，113.45 s**（`R2-206B-protection-suite.log`；收集数 180 = 通过数）。
3. 仓库外 R1-101 M5（`docs/reports/OBS-EVAL/P2/H2V3/r1-repair-external-20261117/work/r1_mechanism_repro/test_r1_101_m5_payment_scope_refusal.py`）：
   **2 passed，退出码 0，1.75 s**（`R2-206B-m5.log`）。
4. 零出站 / 零子进程：自建探针挂 `t09_network_guard` + 自备 `no_subprocess`，显式断言
   `external == []`、子进程 0 次（`test_offline_chain_zero_external_and_zero_subprocess` PASS）。

### E 范围核对

基线：`evidence/00-baseline/protection-snapshot.txt`（sha256 `5e0e4d46…a668`，17 项受保护件）。

| 项 | 结果 |
| --- | --- |
| `rag/retrieval.py` | `9fae019a…` → `d4353092…` ✓ 与声明一致 |
| `rag/answer.py` | `a7c0bdcd…` → `b89622be…` ✓ |
| `rag/facts.py` | `da4a7eec…` → `cf795cfd…` ✓ |
| `rag/query.py` | `69ab6a8c…` → `bedeedab…` ✓ |
| 其余 3 个产品保护件（`intent.py`/`conversations/service.py`/`entity_identity.py`） | 未变 |
| 评测器三件 | `p2_hard_evidence 9861c44e…`、`p2_scoring c3265f4f…`、`scorers 3f8ee170…` **未变** |
| 契约/授权/live/适配器 | `p2_contracts`/`p2_authorization`/`p2_live`/`product_adapter` 均未变 |
| `budget.json` | 未变（`79b21700…`） |
| `live-ledger.jsonl` | **已变**（`3bc3839f…` → `e1257f5d…`，mtime 19:29:39） |
| `PM/P2-LIVE-GO.json` | **已变**（`38f3c3f5…` → `8bffc492…`，mtime 20:17:41） |
| attempt2 case-plan / plan-index | 9 个文件均 mtime 20:17:35（单次生成事件），`plan-index.json` sha256 `976c967b…55e9`；**无可比基线** ⇒ 见 NOT-RUN |

产品文件 mtime 佐证批次窗口：`query.py` 19:54:51（本批）、`retrieval.py` 19:08:18、
`answer.py` 17:27:55、`facts.py` 17:28:04（均为本批之前）。完整哈希表：`R2-206B-scope.json`。

---

## §2 自建对抗探针清单与结果

文件：`backend/tests/integration/test_r2_206b_contact_gate_increment.py`（20 用例）。

| # | 用例 | 改后 | 改前 | 目的 |
| --- | --- | --- | --- | --- |
| 1 | `test_a_mixed_roles_answer_without_contact_values[a1_mixed3]` | PASS | FAIL（预期红） | 三角色混合转绿 + 正文不泄漏 |
| 2 | `…[a2_mixed4]` | PASS | FAIL（预期红） | 四角色（加地址）复验 |
| 3 | `test_a_mixed_dump` | PASS | FAIL（预期红） | 混合形态改前/改后行为快照 |
| 4 | `test_a_mixed_roles_are_identical_across_three_and_four_role_forms` | PASS | FAIL（预期红） | 三/四角色同形 |
| 5 | `test_b1_item_plus_phone_only_still_refused` | PASS | PASS | 冻结拒答面（含零事实零引用） |
| 6 | `test_b2_item_plus_contact_only_still_answered` | PASS | PASS | 冻结放行面 |
| 7 | `test_b3_credential_family_still_refused` | PASS | PASS | 凭据族拒答 |
| 8 | `test_b4_dual_role_mixed_still_refused[b4a]` | PASS | PASS | `others=1` 仍拒答 |
| 9 | `test_b4_dual_role_mixed_still_refused[b4b]` | PASS | PASS | `others=1`（contact+phone+address）仍拒答 |
| 10 | `test_b4_threshold_is_two_others_not_one` | PASS | FAIL（预期差异） | 阈值 ≥2 的机制分界 |
| 11 | `test_b_dump_frozen_surfaces` | PASS | PASS | 五例全表面快照（跨树比对用） |
| 12 | `test_c_locator_cells_must_not_expose_restricted_values[a1_mixed3]` | **FAIL（C-1）** | FAIL（红态前置） | `sources[].locator.cells` 不得含受限值 |
| 13 | `…[a2_mixed4]` | **FAIL（C-1）** | FAIL（红态前置） | 同上 |
| 14 | `test_c_store_level_citation_locator_is_a_preexisting_surface` | PASS（记录泄漏） | PASS（同记录） | 归因：店家级既有面同样带出整行值 |
| 15 | `test_c_closed_surfaces_text_facts_model_capture[a1_mixed3]` | PASS | PASS | 正文/facts/模型/捕获四面闭合 |
| 16 | `…[a2_mixed4]` | PASS | PASS | 同上 |
| 17 | `test_c_multi_turn_inherited_state_does_not_leak_phone` | PASS | PASS | 被拒轮次把 phone 写进 state 后的裸追问不泄漏 |
| 18 | `test_d_legacy_second_gate_still_refuses_non_enumerated_mixed` | PASS | FAIL（改前在规划层已拒，机制断言不适用） | 第二道闸门未被绕过 |
| 19 | `test_zz_tree_identity` | PASS | PASS | 记录本次 import 的 `mktkb`/`query.py` 摘要 |
| 20 | `test_offline_chain_zero_external_and_zero_subprocess` | PASS | PASS | 零出站、零子进程 |

合计：**改后 18 passed / 2 failed（退出码 1，12.79 s）**；
**改前 12 passed / 8 failed（退出码 1，12.49 s）**——改前 8 个失败中 4 个是 A 的预期红态、
1 个是阈值机制差异、1 个是 D 的机制前置、2 个是 C 用例的"改前红态前置"（断言 `kind=answer`
先失败），**不是改前的泄漏**。

---

## §3 保留意见

- **R1（阻塞项 C-1 的定性）**：`sources[].locator.cells` 的整行值快照是**既有** citation 设计
  （店家级问题在改前树同样带出），本批不是写了泄漏代码，而是让原本拒答的混合题首次走到该面。
  但复验要求"任何路径都进不了 `sources[].locator.cells`"，实测**进入了**；且冻结评分器
  `value_forbidden` 只扫正文，**不会**因此判红。裁决权在主人：要么脱敏 locator，要么书面接受。
- **R2（判定用集合而非请求项，且只看本轮）**：`len(other_roles) >= 2` 用的是**角色集合**，
  不是"用户请求了几件事"；它只看**本轮** `field_roles`。我实测了两条边界外形态：
  (a) `others=2` 的非枚举题（位置+数量+电话）规划层放行、用户面仍被第二道闸门拒答；
  (b) 已拒的"只问电话"轮次把 `phone` 留在 `state.field_roles`，后续裸追问（"还有呢？"）
  与"那位置呢？"均未泄漏受限值（`test_c_multi_turn_inherited_state_does_not_leak_phone` PASS），
  但**未穷举**所有继承组合（见 NOT-RUN）。
- **R3（"转绿"的语义副作用）**：混合形态把用户**明确问到的**电话/地址**静默丢弃**——正文、facts、
  捕获里都没有"该字段不提供/未记录"的 `missing_fields` 或说明。C29 的冻结标签只要求"答案不含电话值"，
  所以能判绿；但这是一处"少答且不告知"的体验/忠实度风险，建议在 copy 层补固定说明
  （不改判据、不改词表）。
- **R4（E 的账本/GO 保留）**：`live-ledger.jsonl`（19:29:39）与 `P2-LIVE-GO.json`（20:17:41）
  相对 R2 开工基线 `00-baseline/protection-snapshot.txt` 已变，均**早于**我本次会话的首个命令
  （20:17:5x）且 `query.py` 的改动在 19:54:51 ⇒ 不能归因给本批代码；但"账本/GO 未变"这一条
  我只能给到"**不是我这次复验改的、也不是 206A/206B 代码改动时间内改的**"，无法证明 206B 执行者
  在 19:54–20:17 之间没碰过它们。需要 lead/保管侧用回执哈希补证。
- **R5（attempt2 case-plan "未变"不可证）**：`D:\mktkb-p2-h2v3-r2-20261117\attempt2\plan\**`
  9 个文件 mtime 全部 20:17:35，是一次性重新生成的形状；仓库内没有 attempt2 plan 的**前置**哈希
  基线，因此我无法做"逐字节未变"对照，只能记录当前哈希（`R2-206B-scope.json`）。
- **R6（探针覆盖面）**：我的 20 例是**对抗抽样**，不是全量；保护面只跑了任务列出的 20 个文件
  （180 例），没有跑 `tests/` 全量（206A 报告称全量有 3 例改前即红，我未复现该结论）。

---

## §4 NOT-RUN

1. **真实 attempt2 run**：未执行、未发任何真实/离线产品请求、未使用 GO 槽位、出站 0。
2. **attempt2 case-plan / plan-index 的"逐字节未变"对照**：仓库内无 attempt2 plan 的前置哈希基线
   （只有 attempt1 的 `plan-receipt-r2-attempt1.json`），故只登记当前哈希与 mtime。
3. **`tests/` 全量**：只跑任务列出的 20 个保护面文件 + 自建探针 + 仓库外 M5；其余测试未跑。
4. **attempt2 证据投影（`db_projection.units[].locator`）是否同样带出受限值**：未实跑 201/202 的
   捕获链；只证明了同源 `unit.locator` 经 `qa.answer().citations[].locator` 已带出整行值
   （同一 locator 结构，5 键）。若 attempt2 证据包含该 unit，其 `units[].locator.cells` 将同形。
5. **真实模型 provider 路径**：全程 offline 可控网关（`EvidenceEchoGateway`），未验证真实
   provider 下的模型证据面。
6. **其它混合组合的穷举**：`others≥2` 且 `is_policy_question=false` 的全部角色组合、跨轮继承组合、
   分页/截断组合，未穷举。
7. **`r1_mechanism_repro` 全部用例**：只跑了任务点名的 `test_r1_101_m5_*`（2 passed）；
   该目录其它文件未跑。
