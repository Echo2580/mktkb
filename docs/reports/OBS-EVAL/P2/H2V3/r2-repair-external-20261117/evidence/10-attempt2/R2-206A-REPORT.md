# R2-206A — contact 闸门过度拒答最小修复（C29）执行报告

- 任务：T-R2-206A，让「混合角色」不再整题拒答（fail-closed 地只丢掉受限角色），把 C29 从
  `SECURITY_RESTRICTED_CONTACT` 整题拒答翻回正常作答。
- 工作树：`D:\GPT项目\市场部AI知识库`（base `97b0066`，`rag/query.py` 含 R0/R1 未提交成果）。
- Python：`.venv\Scripts\python.exe -X utf8`；pytest cwd=`backend/`；basetemp 全在仓库外
  `D:\mktkb-p2-h2v3-r2-20261117\basetemp-206a\`。
- 改动面：**只有** `backend/src/mktkb/rag/query.py` 一处早退点（1 hunk，+27/−2 行）+ 新增
  `backend/tests/integration/test_r2_206a_contact_gate.py`（10 例）。`retrieval.py` / `answer.py` /
  `facts.py` / 评测器 / 分类器 / 冻结合同 / 既有测试 / `docs/evidence/**` / `fixtures/**` /
  `docs/evaluation/**` / 账本 / 预算 / GO 槽位 **一律未动**。无 git 写操作、无 `checkout/restore/stash`。

## 0. 结论

| 项 | 结果 |
| --- | --- |
| G1（物品 + 位置 + 合作状态 + 电话，三/四角色混合） | **红 → 绿**：`kind=answer`、位置值+状态值都在、电话/地址/联系人值一个都不出现、`sources=2`（两份资料） |
| G2（物品 + 只问电话） | 与改前逐字节相同（`not_found` / 同一拒答文案 / `sources=[]`），模型 0 调用 |
| G3（物品 + 只问 contact） | 与改前逐字节相同（`answer` / 同一正文 / 同一 `sources`） |
| G4（凭据族） | 与改前逐字节相同（整题拒答），模型 0 调用 |
| 敏感性（强制走原早退） | G1 回红（`not_found` + `sources=[]` + 零模型调用）；撤销即绿 |
| 回归 | rag 81 passed / integration 70 passed / unit+eval 202 passed / 仓库外 M5 2 passed；`tests/rag|unit|integration` 全量 **1527 passed / 3 failed（3 例改前即红）** |
| 出站/子进程 | 新用例挂 `t09_network_guard` + 自备 `no_subprocess`，显式断言 `external == []`、子进程 0 次 |
| 偏离 | **一处语义收窄**（见 §8）：不是「restricted 之外非空」，而是「restricted 之外 ≥2 个可答角色」。字面语义会让 4 个既有冻结安全用例转红，任务同时禁止改既有测试且禁止放宽安全断言，故取最窄实现并在此登记 |

## 1. 已确证前提（未重做）

真实 R2 attempt1（修后版本）质量 4/5、硬失败 0、必要轴 unknown 0；唯一失败 C29，失败码
`value_hit`,`source_hit`,`kind_correct`,`refusal_unexpected`；响应 `kind=not_found`、facts=0、
`source=refusal`、`reason=SECURITY_RESTRICTED_CONTACT`、值 0/2、来源 0/2。冻结标签
`should_refuse=false`/`expected_kind=answer`/2 个文本值/数字期望 0 ⇒ 期望答案不含电话值。

首偏离层 = 计划层，站点 `backend/src/mktkb/rag/query.py:1812-1822`（改前行号）：
C29 抽出 `field_roles=(location, phone, status)` ⇒ 命中 `phone` ⇒ 整题拒答。早退发生在
`index.search` 与本批（202C/202D）联结之前 ⇒ 非本批引入。

## 2. 红态（改前）原文

改前 bytes = `query.py` sha256 `69ab6a8cbb6366f6e3674663f7fde624cef9229ab4a03b8e52205ecf951e0cbd`。
交付测试文件在**改前 bytes** 上运行（`R2-206A-red-final.log`）：

```
6 failed, 4 passed, 1 warning in 15.59s          [exit code: 1]

_ test_g1_mixed_roles_are_answered_without_contact_values[青禾店的折叠桌放在哪个位置，合作状态分别是什么，电话是多少？] _
question = '青禾店的折叠桌放在哪个位置，合作状态分别是什么，电话是多少？'
        _dataset(chat_app, chat_admin)
        info = _ask_info(chat_app, chat_employee, question)
        # 计划层：早退点不再把整题判成受限；受限角色不进 field_roles / requested_fields。
>       assert info["reason"] is None, info
E       AssertionError: {'body': {..., 'kind': 'not_found', 'text': '该请求要把物品记录与店家联系人、电话或地址等
                 个人联系信息合并提供，属于受限个人信息范围，不能据此作答；这不是资料中没有答案，也不代表该信息
                 未被登记；请改为只询问物品位置等非个人联系信息后重新提问。', ...}}
E       assert 'SECURITY_RESTRICTED_CONTACT' is None
tests\integration\test_r2_206a_contact_gate.py:291: AssertionError
```

同一红态里**通过**的 4 例正是「必须保持」的四条：G2、G3、G4 的逐字节断言 + 零出站用例。
规划层直接证据（`R2-206A-plan-probe.txt`，改前 bytes 实测）：

```
甲店立牌放在哪个位置，合作状态分别是什么，电话是多少？      | SECURITY_RESTRICTED_CONTACT | ('location','phone','status')
甲店立牌放在哪个位置，合作状态分别是什么，电话和地址是多少？| SECURITY_RESTRICTED_CONTACT | ('location','phone','address','status')
```

## 3. 改法

文件：`backend/src/mktkb/rag/query.py`，唯一 hunk 落在 `parse_query` 的安全早退点
（改后行号 **1812–1847**；被替换的旧判据即 1812–1822）。新增 27 行、删 2 行（含注释块）。

```python
    restricted_roles = set(field_roles) & REFUSAL_CONTACT_ROLES              # 1823
    other_roles = set(field_roles) - REFUSAL_CONTACT_ROLES                   # 1824
    mixed_restricted_roles = (                                               # 1825
        bool(restricted_roles) and len(other_roles) >= 2 and not is_policy_question(question)
    )
    if not is_policy_question(question) and (                                # 1828  ← 原条件保留
        is_contract_credential_question(question)                            # 凭据族：始终整题拒答
        or (
            (bool(item_hits) or identifier is not None)
            and restricted_roles
            and not mixed_restricted_roles                                   # 只问电话/地址、或“1 个角色 + 电话/地址”仍拒答
        )
    ):
        return QueryPlan(..., reason="SECURITY_RESTRICTED_CONTACT")          # 原样逐字
    if mixed_restricted_roles and (bool(item_hits) or identifier is not None):  # 1843
        field_roles = tuple(role for role in field_roles if role not in REFUSAL_CONTACT_ROLES)
        field_role = field_roles[0]
        state.field_roles = field_roles                                      # 请求角色集合本身被剔除
        state.field_role = field_role
```

剔除方式（fail-closed 丢弃，不是“渲染时跳过”）：

- 受限角色从**本轮请求角色集合**里删掉，且**同时**写回 `state.field_roles` / `state.field_role`
  （`state` 在 1781 的 `_new_state(...)` 里已经带着完整角色，所以这里必须回写，否则计划尾部
  `field_roles=state.field_roles`（2248）仍会把 phone 带出去）。
- 之后的答案/事实/检索三处取值面全部只认 `plan.field_roles`：
  `answer.py:855`（`requested_roles`）、`facts.py:100/158`、`retrieval.py:274-279`
  （`_requested_roles` 会并上 `plan.field_role`，所以 `field_role` 也一并重算）。
  ⇒ `requested_fields` 里不会出现 phone/address，取证与渲染面无从取到这两个角色的值。
- 本地 `field_roles` 变量同步替换，保证 1999–2124 之间所有依赖 `field_roles` 真假的分支
  走原路（混合形态下替换前后都非空，分支结果不变）。
- **未改**：`REFUSAL_CONTACT_ROLES` / `RESTRICTED_CONTACT_ROLES` / `FIELD_WORDS` /
  `is_contract_credential_question` / `is_policy_question` / 答案层与检索层任何字节。

G2/G3/G4 为什么逐字节不变：

| 用例 | 改前 `field_roles` | `restricted` | `other` | 走哪条 |
| --- | --- | --- | --- | --- |
| G2 只问电话 | `('phone',)` | `{phone}` | `∅`（0 个） | `mixed=False` ⇒ **原早退分支逐字不变** |
| G3 只问 contact | `('contact',)` | `∅` | `{contact}` | 原判据里 `restricted` 为空 ⇒ 本来就不早退；`mixed=False` ⇒ 新分支也不触发 |
| G4 凭据族 | `('location','contact')` | `∅` | — | `is_contract_credential_question` 在 `or` 的第一项、**先于**混合判断 ⇒ 原拒答不变 |

`is_policy_question(question)` 仍是两层门（早退分支与 `mixed` 定义里各一处），政策/法规题行为不变。

## 4. 绿态关键计数

改后 bytes = `query.py` sha256 `bedeedaba966209ea26a37fd3bee60fdb96fea21c87ac33dd7dce5ceb3db6fb0`。
交付测试文件：**10 passed**（`R2-206A-green.log`，exit 0）。G1 实测（plan 摘要 + 正文原文）：

```
kind = answer
plan_field_roles = state_field_roles = ("location", "status")      # 无 phone / address
mode = record ; enumerate = True ; filters = ["item", "store"] ; reason = None
sources = ["物品位置台账.xlsx", "合作店家信息.xlsx"]                 # 2 条、两份资料
text = 共 2 条，当前第 1 页显示 2 条。
       - 青禾店的折叠桌：位置 甲区1号架（来源：物品位置台账.xlsx）（记录 cbbfdcaa）
       - 青禾店：合作状态 合作中（来源：合作店家信息.xlsx）（记录 dedddaaa）
       已显示全部。
电话值 010-00000001 / 地址值 示例路18号 / 联系人值 合成对接人·甲：正文均不出现
facts 角色集合 = {"location","status"}；facts 值与上述三值不相交；模型 0 调用
```

G1 四角色形态（再加地址）与三角色形态同形同结果（另一条参数化用例）。

## 5. G2 / G3 / G4 逐字节对照（两路证据）

1. **跨版本冻结基线**：`BEFORE` 常量取自改前 bytes 的实测三元组 `(kind, text, sources)`；
   改后运行断言 `BEFORE[name] == observed`，全部相等：
   - G2：`not_found` / 拒答文案（`REFUSAL_TEXT`）/ `[]`
   - G3：`answer` / `根据资料：门店：青禾店；物品：折叠桌；标识：P01；位置：甲区1号架；数量：4` / `["物品位置台账.xlsx"]`
   - G4：`not_found` / 同一拒答文案 / `[]`
2. **同 app 同题对照（改前等价控制）**：把 `REFUSAL_CONTACT_ROLES` 在运行时扩到本轮全部角色，
   使 `restricted - others` 恒为空 ⇒ `parse_query` 走**改前的整题早退分支**；G2、G4 该控制的
   `(kind,text,sources)` 与实际答案逐一相等。G3 不做该控制（把 contact 也算受限会改变改前行为，
   不构成改前等价），G3 只靠 (1) 的跨版本基线 + 改前红跑里同一断言已通过。

## 6. 敏感性

`test_g1_sensitivity_forcing_original_early_return_restores_red`：同一 app、同一题、同一数据集。
把 `REFUSAL_CONTACT_ROLES` 扩到 `{phone,address,location,status}` ⇒ `restricted` 之外没有可答角色
⇒ 判定恒走原早退：

- 红：`reason=SECURITY_RESTRICTED_CONTACT`、`kind=not_found`、`sources=[]`、位置值与状态值均不在正文、
  模型 0 调用；
- 撤销（`MonkeyPatch.undo()`）后同题重问：`reason=None`、`kind=answer`、位置值+状态值都在。

## 7. 回归表

| # | 节点 | 命令要点（cwd=`backend/`） | 退出码 | 通过数 | 转红？/是否本批 |
| --- | --- | --- | --- | --- | --- |
| E | 本批交付用例 | `pytest tests/integration/test_r2_206a_contact_gate.py` | 0 | 10 passed | 本批（红跑见 §2：6 failed / 4 passed） |
| A | `tests/rag` 10 个节点 | `test_r0_c12_join_synthetic.py`(7)、`test_r0_c12b_boundary_synthetic.py`(12)、`test_r0_c12_legacy_trim_identifiability_synthetic.py`(10)、`test_r0_11_contact_family.py`(13，C27)、`test_r0_12_candidate_drop_reason_retrieval.py`(8)、`test_r1_102b_cross_turn_store_scope.py`(6)、`test_r1_102c_restricted_multifield.py`(7)、`test_r1_106a_legacy_store_scope.py`(4)、`test_r1_106b_primary_store_target.py`(8)、`test_t207_security_precedence_synthetic.py`(6) | 0 | **81 passed** | 无转红 |
| B | `tests/integration` 10 个节点 | `test_r0_c12b_t7_boundary_e2e.py`(7)、`test_r2_202c_c29_join_rag.py`(**13**)、`test_r2_202d_uniqueness.py`(**14**)、`test_r2_203c_f1_http_join_witness.py`(**5**)、`test_r2_203c_f2_identity_http.py`(**3**)、`test_r2_203c_f3_multiturn_http.py`(**7**)、`test_r2_203c_f4_caseplan_set.py`(**6**)、`test_r1_103_http_scope_and_refusal.py`(3)、`test_v3_safety_fix_e2e.py`(9)、`test_p1_refusal_scope_http.py`(3) | 0 | **70 passed** | 无转红（202C/202D/203C 计数与任务给定 13/14/5/3/7/6 一致） |
| C | `tests/unit` + `tests/evaluation` 7 个节点 | `test_v3_safety_fix_policy.py`、`test_t207_v8_safety_contract_synthetic.py`、`test_t207_v8_followup_synthetic.py`、`test_p1_refusal_controls.py`、`test_r0_repair_refusal_compat.py`、`test_r0_12_candidate_drop_reason.py`、`test_r0_9_plan_observed_roles.py` | 0 | **202 passed** | 无转红 |
| D | 仓库外 R1-101 M5 | `pytest docs/reports/OBS-EVAL/P2/H2V3/r1-repair-external-20261117/work/r1_mechanism_repro/test_r1_101_m5_payment_scope_refusal.py`（cwd=仓库根） | 0 | **2 passed** | 无转红 |
| F | `tests/rag` + `tests/unit` + `tests/integration` 全量（改后） | 一次 pytest | 1 | **1527 passed / 3 failed** | 3 例**改前即红**（见下） |
| G | `tests/evaluation` 全量（改后） | 一次 pytest | 1 | 2556 passed / 49 failed / 74 errors | **非本批**（见下） |

F 的 3 个失败（改前 bytes 复现：`R2-206A-reg-full-3fails-pre.log`，同一 3 个 node → 3 failed）：

1. `tests/rag/test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan`
   —— 读 `docs/evidence/.../S2-LIVE-GO.json` 与共享预算冻结件的一致性；本批未动 GO/预算。
2. `tests/unit/test_s2h_r3_official_profile.py::test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552`
   —— 官方档位额度常量比对；与本批无交集。
3. `tests/integration/test_s2b_intent_semantics.py::test_ambiguous_identifier_candidates_converge`
   —— `标识 IB-777 在哪里？` 返回 `conflict` 而非 `clarification`；该问句 `field_roles=('location',)`，
   `restricted` 为空，本批分支不触发；改前同红。

G 的失败/错误全部集中在评测工具链的**私钥/冻结包解封**路径（`load_private_bundle` 的
`scenario_key_invalid` / `annotation_decrypt_failed` 一类），与本批判据面无交集。为免只凭推断，
把出现失败最多的 6 个文件在**改前 bytes** 上重跑：**49 failed / 127 passed / 15 skipped**，
与改后 49 failed（26+9+5+5+3+1）逐文件计数一致 ⇒ 非本批。

## 8. 与任务字面语义的偏差（一处，需 lead 决策）

任务写的是「若 `restricted` 非空且 `set(field_roles) - REFUSAL_CONTACT_ROLES` **非空** ⇒ 不早退」。
本实现把「非空」收窄成「**≥2 个**可答角色」。原因是字面语义与两条不可违反的约束冲突：

- 既有冻结安全断言里有一条**恰好是被字面语义放宽的面**：
  `test_r0_c12b_boundary_synthetic.py::test_item_plus_phone_or_address_still_refused` 的
  「甲店立牌的位置和联系电话是多少？」（`('location','phone')`，others=1）与
  「甲店立牌找谁对接，电话和地址是多少？」（`('contact','phone','address')`，others=1），
  以及 `test_cross_entity_phone_still_refused`（`('location','phone')`，others=1）、
  `test_r0_11_contact_family.py::test_c27_item_plus_contact_ask_still_security_refused`
  （`('contact','phone')`，others=1）。
- 任务同时要求：既有测试一律不动、不得为了让 G1 绿而放宽任何安全断言。

实测（字面语义临时应用到同一工作树后运行，`R2-206A-literal-vs-narrow.log`）：

```
4 failed, 37 passed, 1 warning in 7.09s      [exit code: 1]
FAILED tests/rag/test_r0_c12b_boundary_synthetic.py::test_item_plus_phone_or_address_still_refused[甲店立牌的位置和联系电话是多少？]
FAILED tests/rag/test_r0_c12b_boundary_synthetic.py::test_item_plus_phone_or_address_still_refused[甲店立牌找谁对接，电话和地址是多少？]
FAILED tests/rag/test_r0_c12b_boundary_synthetic.py::test_cross_entity_phone_still_refused
FAILED tests/rag/test_r0_11_contact_family.py::test_c27_item_plus_contact_ask_still_security_refused
```

（该次临时改动后已按字节还原：`query.py` sha256 回到 `69ab6a8c…`，随后才落最终 hunk。）
收窄实现下同一批文件全绿（§7 批次 A 81 passed），且 G1/C29 形态仍转绿。因此：

- 采用 **others ≥ 2**：只有「受限角色之外还剩两个以上可答角色」才视为“顺带抽取的干扰角色”，
  才允许剔除作答；「另一个角色 + 电话/地址」的双角色形态一律维持原拒答。
- 若 lead 判定必须按字面「非空」执行，则**必须**同时改上述 4 条既有断言（本批禁止），且需重新
  评估 R0/C12 安全面的收窄是否可接受。对应 hunk 文本见 §12 附录，一行即可切换。

## 9. 出站 / 子进程守卫

- 新用例模块级 `pytestmark = pytest.mark.usefixtures("t09_network_guard", "no_subprocess")`；
  `no_subprocess` 本文件自备，封死 `subprocess.Popen` / `subprocess.run` 并断言调用计数为 0。
- `test_offline_chain_has_zero_external_network_and_no_subprocess` 跑完 G1–G4 后**显式**断言
  `t09_network_guard.snapshot()["external"] == []` 且 `no_subprocess == []`（绿跑通过）。

## 10. 残留与风险

1. **非枚举混合形态仍拒答（fail-closed，未修复也未放宽）**：不带枚举词的混合题（例如
   「青禾店的折叠桌放在哪个位置，合作状态如何，电话是多少？」）在本批之后**规划层不再早退**，
   但产品层旧有的第二道闸门 `conversations/intent.py:507-527`（`RESTRICTED_CONTACT_FIELDS`，
   本批不在可改面内）仍整题拒答。已用同 app 对照验证：该形态 `(kind,text,sources)` 与改前
   **逐字节相同**（`test_g1_non_enumerate_mixed_shape_is_unchanged_fail_closed`）。
   C29 的捕获形态是 `plan_enumerate_count=1`（`evidence/02-case-boundary/H2V3-C29.json`），
   走 RAG 直答 ⇒ 本修复覆盖；若真实题面走 legacy 形态，则本修复不生效（但绝不会放宽）。
2. **电话值是否可能进正文**：混合形态下 phone/address 已从 `field_roles`/`state.field_roles`/
   `requested_fields` 全部剔除，检索取证面与渲染面都取不到该角色；测试对 3 个值
   （电话、地址、未请求的联系人姓名）逐条断言不在正文、不在 facts、不在模型证据字段里。
   另有一处**既有**、本批未改的面：无物品/标识的纯店家题（如「甲店找谁对接，电话和地址是多少？」）
   在改前就作答并渲染电话/地址（`tests/rag/test_r0_11_contact_family.py` 的 C27 用例）；
   本批不放大也不修补它。
3. **规则形状是“≥2”而非“非空”**：见 §8。这是本批唯一需要 lead 决策的偏离。
4. 未穷举多轮继承：`_new_state` 会继承上一轮 `field_roles`，但本批分支要求**本轮**出现
   `item_hits` 或 `identifier`；拒答轮的 `plan.field_roles` 为空（角色只在 `state`），
   未观察到“继承 + 混合”把 phone 带进答案的路径，但**未做穷举验证**（NOT-RUN）。
5. 未做真实 R2 复跑（外部 run 不在本任务范围）：本报告只证明合成同形（G1）与既有面不变，
   真实 C29 是否回到 `value_hit 2/2 + source_hit 2/2` 需下一次真实 attempt。

## 11. NOT-RUN

| 项 | 原因 |
| --- | --- |
| `tests/acceptance/**` | 不在任务回归清单；本次覆盖 rag/unit/integration/evaluation 与仓库外 M5 |
| `tests/evaluation` 全量逐条归因 | 49 failed / 74 errors 全在私钥门控解封路径；已用 6 个文件的改前/改后计数对照（49/49）证非本批，未逐条归因 |
| 非枚举混合形态的修复 | 第二道闸门在 `conversations/intent.py`，超出本批唯一可改文件 |
| 多轮“继承 + 混合”穷举 | 见 §10.4 |
| 真实 R2 attempt2 复跑 | 不在本任务范围 |

## 12. 交付物

| 文件 | 说明 |
| --- | --- |
| `R2-206A-src-diff.patch.txt` | `backend/src/mktkb/rag/query.py` 整文件补丁；头部 `batch hunks: 1`；base `69ab6a8c…` → after `bedeedab…`；+27/−2 |
| `R2-206A-MINE-rollback.patch.txt` | 内容同上（回滚用）；`git apply --check -R` **exit 0** |
| `R2-206A-REPORT.md` | 本报告 |
| `R2-206A-red-final.log` | 改前 bytes 上运行交付测试：6 failed / 4 passed（exit 1） |
| `R2-206A-green.log` | 改后 bytes 上运行交付测试：10 passed（exit 0） |
| `R2-206A-plan-probe.txt` | `parse_query` 改前/改后 10 个问句对照（只有 2 行改变） |
| `R2-206A-literal-vs-narrow.log` | 字面语义的 4 个既有安全用例转红证据 |
| `R2-206A-reg-batches.log` | 批次 A/B/C/D 原始输出 + `--collect-only` 计数 |
| `R2-206A-reg-full.log` / `R2-206A-reg-full-3fails-pre.log` | 全量 rag+unit+integration（改后 3 failed）与同 3 例改前复现 |
| `R2-206A-reg-evaluation.log` / `R2-206A-reg-evaluation-pre.log` | 评测全量失败清单（改后）与 6 个文件改前计数对照 |
| `R2-206A-regression-summary.txt` | 回归表机器可读版 |

新测试：`backend/tests/integration/test_r2_206a_contact_gate.py`（10 例；其中 G1 参数化 2×2、
G2/G3/G4 各 1、非枚举 fail-closed 1、敏感性 1、零出站 1）。

交付字节 sha256：

```
backend/src/mktkb/rag/query.py                                bedeedaba966209ea26a37fd3bee60fdb96fea21c87ac33dd7dce5ceb3db6fb0
backend/tests/integration/test_r2_206a_contact_gate.py        9a3f1d16cf098acbe491199daa15a183a74f997e50300bf092ab571d4f0f75aa
```

最后一轮聚焦复跑（交付字节上，含本批 10 例 + 8 个关键节点）：`85 passed`，exit 0。

`rag/query.py` 新 sha256：

```
bedeedaba966209ea26a37fd3bee60fdb96fea21c87ac33dd7dce5ceb3db6fb0
```

### 附录：若改用字面语义（others 非空）的 hunk

只需把 §3 的 `mixed_restricted_roles` 判据改一处（其余字节不变）：

```python
-    mixed_restricted_roles = (
-        bool(restricted_roles) and len(other_roles) >= 2 and not is_policy_question(question)
-    )
+    mixed_restricted_roles = (
+        bool(restricted_roles) and bool(other_roles) and not is_policy_question(question)
+    )
```

即 `mixed = restricted 非空 and other_roles 非空`。它会把 §8 列出的 4 条既有安全断言打开，
必须同步修改既有测试（本批禁止），因此本批未采用。
