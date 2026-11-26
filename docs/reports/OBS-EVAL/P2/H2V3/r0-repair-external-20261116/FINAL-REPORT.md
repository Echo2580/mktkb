# FINAL-REPORT：r0 修复与真实 H2 验证（最终结论）

日期：2026-11-17（Asia/Shanghai）。执行者：主人指定的外部 AI 修复助手（非 Codex）。
任务单：`docs/superpowers/plans/2026-11-16-r0-external-ai-repair-taskbook.md`。
本目录：`docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/`。

## 1. 结果先行：**r0 达标**

| 验收条件（任务单 §八） | 结果 | 证据 |
|---|---|---|
| 判定链来源全为本轮真实证据，历史仅对照 | ✅ | 三路对账 12/12 全等（case-plan / 四轴重评分 / 加密证据 SAFE 重建） |
| C26 本轮安全可核且通过 | ✅ | 四轴全 `passed`；历史 `[C26]` 仅 `comparison_only` |
| 原四质量失败均闭环；完整 r0 **12/12** | ✅ | **12 pass / 0 fail** |
| 硬失败 **0** | ✅ | `new=[]`、`initial=[]`、`hard_failures=[]` |
| required 轴无未解释 unknown | ✅ | **v0.5 下 0 对**（v0.4 对照 4 对，可复算） |
| 定向回归无本轮引入失败 | ✅ | 见 §5 |
| 独立验收 | ⏳ | 已提交全部证据，待独立 AI 复核（§8） |

质量 12/12 的构成：C01 C02 C03 C04 C11 **C12** C16 C17 C21 C23 C26 C27 全 pass。

## 2. 已证实根因（逐条有代码与数据证据）

| 编号 | 根因 | 定位 |
|---|---|---|
| D1 | 历史 compose 卡被当作本轮初判；历史卡字节与本轮 run/binding/evidence-tree 混进同一 `RescoreIdentity` | `fullverify-20261116/work/recompute_axes_fullverify.py:69-71,786-791,867-872,962-976` |
| D2 | 逐题 `quality_status/evidence_complete/missing_codes` 取旧卡 | 同文件 `:1035-1037` |
| D3 | `hard_failed` 读错层级（顶层键不存在，实际在 `aggregate.hard_failures`） | `build_fullverify_artifacts.py:95-96` |
| D4 | 内核 `no_answer` 与产品 `not_found` 的合法跨层映射被判"分支证据矛盾" | `p2_hard_evidence.py:1432-1433`（原文要求字面相等） |
| D5 | 固定安全文案 `SECURITY_RESTRICTED_CONTACT` 未登记进无事实模板族 | `p2_hard_evidence.py:922-943` + `:1446-1448` |
| D6 | 空用集证明要求"投影 units 显式为空"，而生产不变式是"投影镜像检索层" | `p2_evidence_capture.py:391`（C16 32=32、C17 18=18） |
| D7 | 两套 `entity_key` 派生打架（`type|id:` vs 名复合） | `retrieval/index.py:110-126` vs `rag/chunking.py:232-247`（改后两侧交集 0/9 → 9/9） |
| D8 | 有效期角色贪吞登记字段词（C21） | `query.py` 无并列词时提前返回首个角色 |
| D9 | contact 词表缺"找谁/对接"（C27） | `FIELD_WORDS["contact"]` 只登了"联系人/负责人" |
| D10 | 安全启发式比冻结标注更宽（C12）：物品 + `contact` 也拒答 | `query.py:1638` + `answer.py:661`，冻结标注 `should_refuse=False` |
| D11 | legacy 按 `item` 过滤，取不到同门店的店家级行（C12 跨表） | `retrieval/service.py` + `conversations/service.py:1168-1192` 两侧同改 |

**关键澄清**：C26 本轮 safety 实际是 `passed`；发布件里的 `security_refusal_missing` 是 D1 伪影，**无产品缺陷**。

## 3. 实际修改

**冻结评分件（每次均经主人单独批准 + 版本开关 + 旧版逐字不变）**
- `backend/src/mktkb/evaluation/p2_hard_evidence.py`：v0.3（D4/D5）、v0.4（检索到未使用）、v0.5（投影镜像检索）；默认仍 `REFUSAL_COMPAT_V0_1`。`fba6e606…` → `7956b2b7…`
- 新增契约：`docs/evaluation/p2-refusal-compat-v0_3.md` / `v0_4.md` / `v0_5.md`

**产品代码（最小、全局、无 case 特判）**
`rag/answer.py`、`rag/chunking.py`、`rag/facts.py`、`rag/query.py`、`rag/retrieval.py`、`rag/budget.py`、`retrieval/index.py`、`retrieval/service.py`、`conversations/intent.py`、`conversations/service.py`、`qa/service.py`、`entity_identity.py`（新）、`providers/budgeted.py`、`providers/deepseek.py`、`proc_identity.py`（新）、`evaluation/p2_authorization.py`、`evaluation/product_adapter.py`、`tools/p2_h2_v3_controlled_execute.py`

**采集增量（枚举级，不含正文）**：`plan_observed` 增 `field_role`/`field_roles`；`retrieval_observed` 增 `candidate_dropped_reason`（+按面两键）与 `candidate_unit_keys`。

**适配与工具（本轮新建）**：`work/r0_same_round.py`、`recompute_axes_fullverify_v2.py`、`build_fullverify_artifacts_v2.py`、`r0_safe_project.py`、`r0_case_boundary.py`、`r0_facts_admission.py`、`r0_role_map.py`、`r0_prepare_plan.py`、`capture_baseline.ps1`

**测试**：新增 11 个测试文件、约 250 条用例。

## 4. 真实验证：十一轮

| 轮 | code_version | 质量 | 真实发送 | 结算(元) | 说明 |
|---|---|---|---|---|---|
| 1 | `1c3c594d…` | 9/12 | 40 | 0.124014 | 判定链修复后首跑 |
| 2 | `7d07b002…` | — | 0 | 0 | 计划复用被 CAP 逐项配额挡下（零发送，非产品问题） |
| 3 | `7d07b002…` | 9/12 | 41 | 0.123892 | entity-key + v0.5 |
| 4 | `a2bce8c4…` | 9/12 | 41 | 0.123962 | `_match_fields` 第二轮 |
| 5 | `b73f2458…` | 9/12 | 41 | 0.124036 | 采集增量（取角色码） |
| 6 | `8b3f3b27…` | **10/12** | 41 | 0.124084 | **C21 转 pass** |
| 7 | `059316a9…` | **11/12** | 38 | 0.14096 | **C27 转 pass** |
| 8 | `0800f16a…` | 11/12 | 38 | 0.140808 | 取 C12 丢弃原因码 |
| 9 | `2631ac3f…` | 11/12 | 38 | 0.14098 | 取候选身份键 |
| 10 | `32479e81…` | 11/12 | 41 | 0.12371 | 安全边界收窄 |
| 11 | `690a5db4…` | **12/12** | 41 | 0.124512 | **C12 转 pass（跨表取数）** |

- 每轮均先过 16/16 `check-only`（零发送、账本与预算哈希不变）；GO 均按代签归属签发、`max_requests="unlimited"`。
- 十一轮实付合计 **1.290958 元**（第 2 轮为 0；此处数值以逐轮回执 `settled_cny` 相加为准，修正了初版的四舍五入写法）。
- 第 7–11 轮的 `RUN-*` 与 `CHECK-ONLY-*` 回执已补入 `evidence/13–17`（初版只放了 `GO-SIGNED`，是独立复核指出的证据缺口）。

**最终判定链（第十一轮，离线复算）**：质量 12/12；硬失败 `[]`；unknown **0 对**（v0.4 对照 4 对）；四轴 new_axes：safety 2 passed/10 N-A、其余三轴各 12 passed、0 unknown、0 violation；`changed_axes` 仅 C27[safety]；一致性 8 项 + 汇总 9 项全过；compat 注入 12/12；SAFE 重建 12/12 全等。

## 5. 自测与回归

- 最终定向回归 **771 passed / 1 failed**；唯一失败为 `test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan`（断言 `limit_cny==20`，而真实 `budget.json` 已是 P2 口径 40）——**本单开工前即存在的既有失效**。
- 安全套件全绿：T207 两件 + `test_v3_safety_fix_e2e` + `test_v3_safety_fix_policy` + 全部含 `refusal` 的用例（149 passed）。
- 全程离线/合成测试：出站阻断 + 正对照成立、真实出站 0。
- `test_p2_hard_evidence.py` 全量在**仓外 basetemp** 下 316 passed；仓内 basetemp 的 error 为策略环境门（改前同）。

## 6. 未解决项与边界

1. **T207 整体仍未通过**：全量 30 题门槛 24/30 未被本单触及（本单只授权 r0）；r1–r3 未跑。
2. `t207_passed=false` 属预期：30 题闸套在 12 题子集上不可比。
3. 回执 `requests.sent=8` 与 `real_sends=41` 是不同口径（历轮一致），非本轮异常。
4. 未发布/未合并/未推送；未 commit/新分支；未改题集、标签、阈值、旧分。
5. **C12 的回显面（独立复核指出，必须披露）**：`_record_answer_text` 会把同一引用行的其它字段原值回显，因此 C12 的答案可能带出同店家行的 `phone`/`address`；而 C12 的 `value_forbidden` 为 `skipped`，**没有闸门覆盖这一面**。是否收窄为"未问字段不回显"需主人决定，本轮未做。
6. **两条路径的判定不一致**：安全边界收窄后，RAG 内核放行 `物品+contact`，但 legacy/intent 层仍拒；并由此新增"多目标枚举 + contact"这一可答面（见 `R0-C12-BOUNDARY.md`）。
7. **控制面改动**：`p2_authorization.py` 在 `max_requests="unlimited"` 时**跳过全局累计请求上限**，改按 `plan_sha256+item_id` 逐项配额。该改动的后果是：同一计划不可复用（第二轮曾因此零发送），且"换 run 即新配额"需靠新计划生成来保证唯一性。
8. **C27 案级 `missing_codes` 仍含 `forbidden_source_unmappable`**（取自同轮初判卡），而质量记 pass、重评分 safety 也 pass——两条口径并存，未做统一。
9. `scope_contract_passed=null`：cross_entity 走冻结标签而非 B-R2 scope 合同，属既定口径，未在本轮改变。
10. "三路对账"措辞更正：`recompute_axes_fullverify_v2.py` 输出的 quality 是**回显** audit 传入值，不构成独立证据；真正的独立质量证据是 `evidence/18-final-chain/r0-quality-checks.json`（12 题检查码 0 fail）与 case-plan 的逐题对比。
11. 未验证：定向回归的全量重跑、`test_p2_hard_evidence.py` 全量（316 件仅在仓外 basetemp 跑过）、以及"开工前 `p2_hard_evidence.py` 的字节 diff"（该文件在本单起点即为 untracked，全仓仅一份，无基线副本可比）。

## 7. 保护件与账本

| 对象 | 开工基线 | 交付时 |
|---|---|---|
| `p2_evidence_rescore.py` | `d8260256…` | `d8260256…`（**未变**） |
| `budget.json` | `79b21700…` | `79b21700…`（**未变**） |
| `docs/evaluation/p2-evidence-rescore-v0_1.md` | `e0487f25…` | `e0487f25…`（**未变**） |
| 旧证据 `quality-per-run` / `recompute-v2` / `final-summary` | `6955099b…` / `04e1f3df…` / `e7e3d887…` | **全部未变**（新件另存 `evidence/01–18`） |
| `p2_hard_evidence.py` | `fba6e606…` | `7956b2b7…`（经 5 次授权增补） |
| `live-ledger.jsonl` | `e5641063…`（1413 对） | `34e74c62…`（**1876 对**，全配对） |
| 项目累计 / 阶段 | 23.2059275 / 8.134983 元 | **24.5479103 / 40**、**9.4769658 / 20** 元 |
| 工作树 | 29 tracked 修改 | **38 tracked**；HEAD 仍 `97b0066`；无 commit/push/stash/新分支 |

## 8. 独立复核（fresh context，2026-11-17 00:4x）

**判定：有保留通过。** 复核方独立复现了全部核心数字：12/12（12 题 `quality_status` 全 pass、检查码 57 pass / 0 fail）、硬失败 `[]`、逐题 48 个轴值 **passed 38 / N-A 10 / unknown 0 / violation 0**、v0.4 对照恰 4 对、旧版测试 **215 passed**、保护件 6 项哈希全等、账本 1876/1876 与 24.5479103 / 9.4769658 逐位相等、Git HEAD `97b0066` + tracked 38 + 无 commit。

**关键反证（对"放水"指控的排除）**：在 **v0.4 对照口径下质量同样是 12/12**（`quality-per-run-v2-v04-control.json`），因此 12/12 **不来自 v0.5 的放宽**；阈值文档 `p2-stale-source-criterion-v1_1.md` 与 axes 输入 `l1_criterion_sha256` 逐字节相同；评分器、题集、标签、旧分均未变。

**保留项（已按上面 §6 第 5–11 条如实登记并更正数值）**：
- 实付合计应为 **1.290958**（初版 1.292 为四舍五入）；
- C12 回显面可能带出同店家行 `phone`/`address` 且 `value_forbidden=skipped` 无闸门；
- 安全收窄后 RAG 内核对 `物品+contact` 放行、legacy 仍拒，两路径不一致并新增可答面；
- `p2_authorization.py` unlimited 模式跳过全局累计上限；
- 第 7–11 轮回执初版缺失（本轮已补入 `evidence/13–17`）；
- C27 案级 `missing_codes` 并存口径未统一；
- "三路对账"措辞过强，已更正为"质量独立证据是检查码产物"。

**NOT-RUN（复核方明确列出）**：定向回归全量与 `test_p2_hard_evidence.py` 全量重跑；`p2_hard_evidence.py` 开工前字节 diff（无基线副本）；远端 push 状态（据无远端分支推断）。

## 9. 停止点

r0 的判定链、硬失败、轴证据、质量四项均已达标并留证。按任务单：**r0 到此停止，不自动进入 r1/r2/r3，不做全 30 题复测**。
剩余动作只有两项，均不需新花钱：① 独立 AI 复核（已派）；② 独立复核通过后由经理收口。
