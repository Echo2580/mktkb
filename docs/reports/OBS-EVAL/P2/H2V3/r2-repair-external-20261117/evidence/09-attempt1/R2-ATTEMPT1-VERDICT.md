# R2 attempt1 真实运行判定与失败闭环（2026-11-17）

## 1. 运行身份（一次，无重试）

| 项 | 值 |
|---|---|
| run_id / run_index / 场景 / 业务日 | `p2-h2v3-20261115-r2-pre_v05_without_v07` / **2** / `pre_v05_without_v07` / **2026-11-20** |
| plan_id | `P2-H2V3-20261115-r2-pre_v05_without_v07` |
| **plan_sha256** | `4dffad90cb6a43dc24cd222bae0acb21a70ffcd19fab5e4394d23feb7e4ad365` |
| **code_version**（脏工作树摘要） | `b45f1ea9aef47104650cd0897edcdaed4c696b00cf0a0ba03103551fb996d32a` |
| binding_sha256 | `9647e6fb1af3867e1addbc42925ee023b4a05fe506fb247e0bdf0059822ede53` |
| attempt_scope_sha256 | `8e87f00f736d7ec8f0208b42074474d09d7d2f9fd2c99431c6b2b6b11e003222` |
| GO 内容规范化摘要（`bindings.go_sha256`） | `7a618a84da1e6d0d3abe8c1cb0e5fdbe94a0cad7d04e67994d97abffde1a332d` |
| GO 文件字节摘要（`P2-LIVE-GO.v3-r2.pending.json`，与固定槽位逐字节相同） | `35ece3ebc7e9e0a3b96d347f8758d342a90251201fa015b2d91d71be978764f7` |
| 证据密钥 SHA-256 前缀 | 本 attempt 新生成 `ev.key`（未复用历史 key） |
| 证据树 SHA-256 | `429e92cd9db9dc3584dca65dccc59ec46ac9abf1a95ec25828315229aace1637` |
| 封存清单 SHA-256 | `cf39ae8e987ce2ea4c18a13ec2e8c7cd9df8c6d32a4386276bc47965a1e9580d` |
| out 树 SHA-256 | `33624ba337affd7e7775d72ea05ce1db1b1e49da6bc9813aa04d3c0019f59343` |
| 回执 | `ok=true`、`status=succeeded`、`real_sends=27`、6/6 回合 `executed`、`sealed`、`readback_ok=true` |
| 请求 | planned **37**、attempts_reserved **29**、real_sends **27**、settled **0.0431940 元**、reserved_cny 0.1121280 |
| 清理 | `business_db_removed=true`、明文终扫 clean（`hit_count=0` / needles 66 / 扫描 2 件） |
| 时长 | 26048 ms |

> ⚠️ **已知产物缺陷（须在最终件中标注）**：`attempt1\v3-entry-p2-h2v3-…json` 是**首次被拒尝试**（`go_plan_id_mismatch`、零发送）留下的旧 sidecar；
> 成功运行的 sidecar 因 `output_already_exists` 未被覆盖，进程退出码为 2。**权威件是 `seal/<run_id>/run-receipt.json`**（`ok=true`），
> sidecar 不参与任何判定。这不是运行失败，也不是"重试"：第一次是签名绑定错误（零发送），第二次是唯一一次真实执行。

## 2. 判定结果

| 判定 | 结果 |
|---|---|
| 质量 | **4 pass / 1 fail**（C08/C14/C19/C25 pass；**C29 fail**） |
| 硬失败 | **0** |
| 20 个 (case,axis) 单元 | **19 passed / 4 not_applicable / 0 unknown / 0 violation**（四态合计：safety 4 N-A + 1 passed；cross_user 5 passed；cross_entity 5 passed；stale_source 5 passed） |
| 必要轴 unknown | **0** ← 历史 C25/C29 的 cross_entity unknown **已消失**，与 202B 的"历史键形态"判定一致 |
| 一致性门 | `consistency` 8 项检查通过；单 run 隔离成立（`runs` 只含 run 2） |
| T207 | 未通过（30 题门槛不适用于 5 题子集） |

> 公开件 `new_axes` 与 `axes_report.axes` 两列仍并存（旧卡列 `recorded_old` 带 1 个 safety violation）；
> **权威口径是逐题合并层 `runs[2].cases[].new_axes`**（本表取该层）。引单轴报告必须标 provenance。

## 3. C29 失败闭环（与修前对照）

| 项 | 修前（2026-11-16） | attempt1（2026-11-17） | 变化 |
|---|---|---|---|
| failed_check_ids | `value_hit`,`source_hit` | **`value_hit`,`source_hit`,`kind_correct`,`refusal_unexpected`** | **机制已变** |
| 响应 kind | `answer` | **`not_found`** | 变 |
| 覆盖 | 值 1/2、来源 1/2 | 值 0/2、来源 0/2 | 变 |
| 事实 | facts=1、`structured_enumeration` | facts=0、`source=refusal` | 变 |
| 首偏离层 | `candidates`（未捕获） | **`intent_fields`（计划层）** | 变 |

**新根因（205D 零调用诊断）**：`backend/src/mktkb/rag/query.py:1812-1822` 的安全早退
（`not is_policy_question(question) and ((item_hits or identifier) and set(field_roles) & {phone,address}) or is_contract_credential_question(question)`）
对被问实体命中、且抽取出的 `field_roles` 含 `phone` 的问题**整体拒答**（`reason=SECURITY_RESTRICTED_CONTACT`）。
C29 的抽取角色为 `(location, phone, status)`，因此整题被拒；渲染的正是该固定模板（文本 sha 前缀 `2ad69949b4b55fdf` = `copy.text("SECURITY_RESTRICTED_CONTACT")`）。
**不是本批（2022C/202D）引入**：`rag/query.py` 不在本批补丁面内，早退发生在 `index.search` 与本批联结代码之前；旧轮此码不存在（早于 R0/C12 与 R1/102c）。
无法区分"闸门新增"与"角色集合扩张把 phone 认出来"谁先变：旧 `code_version e3b4b29…` 不在仓库、旧轮未投影 `field_roles` ⇒ 缺口码 `old_code_version_unavailable`。

## 4. 结论：**R2 未达标**（质量 4/5）

- 已达：硬失败 **0**、必要轴 unknown **0**、5 题 6 回合、封存与清理完成、账本全配对。
- 未达：质量 **4/5**。
- 剩余唯一阻塞是一个**安全闸门与冻结算例标签的冲突**，不是检索/事实/模型缺陷，也不是本批补丁缺陷。

## 5. 为什么不再直接花第二轮（交主人决策）

两个候选修法都触及 R0/R1 建立的安全面，取舍不能由执行方单方面决定，且需要题面语义才能定夺（执行方不得读题面）：

| 候选 | 改法 | 预期 | 风险 |
|---|---|---|---|
| **F1** `rag/query.py:1812-1822` | 只有"请求角色全部属于 `{phone,address}`"时才整体拒答；混合角色时**剔除受限角色**后继续作答（凭据族 `is_contract_credential_question` 保持整体拒答） | C29 得到正常计划 → 202C/202D 按设计生效 → 2 值 2 来源 | 可能放宽 R0/C12 的"物品 + 电话"保护面（`test_item_plus_phone_still_refused_before_model` 与 202C 的 C3 反例需逐条复验）；若题面确实索取电话值，会从"拒答"退化为"少渲染" |
| **F2** `rag/query.py:62-85` `FIELD_WORDS["phone"]` 词条 | 若属泛词误命中，只收窄该词条 | C29 不再抽出 `phone` 角色 → 闸门不触发 | R0/C27 正是为把 contact 列纳入证据面而补泛词，收窄可能回退 C27（`value_hit` 缺值） |
| 决定前提 | 需要知道 C29 题面是不是**真在问电话/联系方式** | — | 执行方无题面读取权限（这是 R2 授权边界） |

**不做**：不改 labels/expected、不删禁源、不为"跑一轮看看"再付费（属禁止的无变化重复付费）。

## 6. 证据位置

- 运行原件（仓外）：`D:\mktkb-p2-h2v3-r2-20261117\attempt1\{plan,preflight,out,evidence,seal,ev.key}`
- 本轮质量码：`evidence/09-attempt1/01-safe-projection/r2-quality-checks.json`
- 本轮边界与身份：`evidence/09-attempt1/02-case-boundary/`
- 本轮四轴（v0.6，单 run 隔离）：`evidence/09-attempt1/03-final-chain/recompute-v2-r2-attempt1-v06.json`
- 首偏离诊断：`evidence/09-attempt1/R2-205D-DIAGNOSIS.md` / `.json`
- 账本对账：`evidence/06-run-prep/ledger-recon-after-attempt1.md`
- 计划回执：`evidence/06-run-prep/plan-receipt-r2-attempt1.json`
- 预检回执：`attempt1\preflight\check-only-run2-v2.json`（16/16 全绿）
