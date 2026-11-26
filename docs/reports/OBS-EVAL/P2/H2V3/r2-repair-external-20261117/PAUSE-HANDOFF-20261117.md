# R2 暂停交接（2026-11-17 17:3x，主人要求「保存进度，暂停任务」）

本文件是**暂停点唯一事实源**。下一个窗口请先读完它，再读 `R2-BASELINE.md`、`R2-DIAGNOSIS.json`、`R2-RUNBOOK.md`。

## 0. 一句话状态

**已完成 T-R2-201（零调用 SAFE 重建，结论齐备）、T-R2-202A/202B（机制判定）、T-R2-202C（C29 跨实体取数最小修复，已收敛为绿）。**
**未做**：T-R2-203 组合回归/HTTP 贯通、T-R2-204 独立预验收、T-R2-205 真实运行、T-R2-206 最终判定。
**未花任何真实费用**：本轮全程零真实/离线产品请求、零出站；未签 GO、未改预算/账本、未 git 提交/推送。

## 1. 授权与治理（本窗口唯一有效依据）

- 主人 2026-11-17 明确授予两项、**仅限 R2**：① 保管侧 SAFE 投影（进程内解密 r2 封存证据，出口只许固定码/计数/布尔/哈希）；
  ② 新 GO 签发授权，形式 `PM (lead) — delegated by owner 2026-11-17 (scope: R2 only)`，**前置条件**：修后源码摘要绑定新计划 + 金额上限 + 完整 check-only 全通过。
- **不继承**：R1 的私有读取权限、R1 的 GO、R1 的「接受 1 个 unknown」例外、R1 已耗用计划。
- 停止单位 = 完整 R2（5 题 6 回合）。不进入 R3、不做全 30 题、不宣称 T207 通过、不 Git 提交/推送。

## 2. 范围（不可改）

`run_index=2`、`scenario_id=pre_v05_without_v07`、业务日 **2026-11-20**、**5 题 6 回合**
（`H2V3-C08`=t0、`C14`=t1+t2、`C19`=t3、`C25`=t4、`C29`=t5）、历史 run_id `p2-h2v3-20261115-r2-pre_v05_without_v07`。
达标线：同一修后版本 **5/5 质量、硬失败 0、必要轴 unknown 0**（owner 未给任何 unknown 豁免）。

## 3. 已完成：T-R2-201（零调用 SAFE 重建）

### 3.1 完整性 8/8 为真

证据密钥 `2acaf7b8…`、证据树 `e90085e8…d8ee`、封存清单 `bdc97056…9964` 均与回执相等；binding `custody 0fa7dbe0…c543`/`manifest de4125ca…36e8`
与 case-plan 逐值相等；case-plan sha `fe8741861e74edb8bab8ea1ee07dfd37a1ede60c766d53ba30699fd25ea325da`；5 题 6 回合；业务日一致；
`sealed=true`、`readback_ok=true`、`real_sends=29`=`real_calls`。

### 3.2 逐题质量：**5/5 重建一致**

| 案 | 历史 case-plan | 独立重建 | failed_check_ids |
|---|---|---|---|
| C08 / C14 / C19 / C25 | pass | pass | — |
| **C29** | fail | fail | **`value_hit`（2/1/1/0）+ `source_hit`（2/1/1/0）** |

检查码合计 **27 pass / 2 fail / 31 skipped（共 60）**；`kind_correct`/`value_no_fabricated`/`value_forbidden`/`source_forbidden` 全 pass；
`refusal_expected=skipped`（`should_refuse=false`）。→ C29 是**覆盖不全型**失败，不是应拒未拒、不是编造、不是禁源泄漏。

> 曾经的一版「4/5、C25 `source_forbidden` 假 fail」已**闭合**：根因是重建误用驱动层默认 `p2-holdout-source-map/v0.1`（4 码），
> 而该 run 实际由受控入口在 `dispatched_scoring_map` 下以 **`v0.2`（12 码）**计分。补齐后 C25 hit 由 1→0、判 pass；
> 判据/评分器/case-plan 一字未改，反证成立（移除 citation 的 `version_number` → C25 `source_hit` 立即 fail，属收紧非放宽）。

### 3.3 四轴：硬失败 0、必要 unknown 2（C25/C29 同一机制）

五档 compat（v0.1/0.3/0.4/0.5/**v0.6**）**逐 (case,axis) 完全一致**（`cell_diff_count=0`）：
safety 1p/4N-A、cross_user 5p、cross_entity 3p/**2u**、stale_source 5p；20 单元 = 14 passed/4 N-A/2 unknown/0 violation；硬失败 `[]`。
初判硬失败 `["H2V3-C25"]` → 重评 `[]`（matcher v2 的 `forbidden_source_no_match` 证伪了 locator-only 假违规）。
**v0.6 在本批零触发**（C25/C29 含 `entity_identity_missing`，不满足"纯文档正文"前提）——v0.6 救不了这两题。
历史"两套初判卡并存"已查清：只有一张旧卡，权威口径 = `runs[2].cases[].new_axes`；引单轴报告须标 provenance。

### 3.4 首偏离

- **C29**：8 层固定状态里，`candidates`/`retrieval` 为 **`not_captured`**（direct-RAG 路径不发 `retrieval_observed`，`plan_observed` 不发 `state.stores`）
  ⇒ `first_boundary=undetermined`、`undetermined_gap=retrieval_events_absent`。可观测：`fact_rows=1`、`values_backed 1/2`、
  `citation 1/2`、`revision 10→10`、答案含"未在资料中找到"模板；`target_refs_0`(item) resolved+matched、**`target_refs_1`(store，另一份文档) `no_match`**。
- **C25/C29 cross_entity**：`fact 与 backing unit 键一致 = false (0/1)`；差异分类 = **类型段同、标识段同、形态不同**（unit `item|id:<v>` vs fact `item|<v>`），
  即 **R0 已修的"两套词法"键形态分叉**，不是类型不统一、不是越权。判据两处仍是逐字符串相等（`p2_evidence_rescore_axes.py:2030`、`p2_hard_evidence.py:2529`）。
- **C14**：两回合上下文继承 true、`entity_inh=2`、revision 10/10 一致、`as_of`==业务日；逐回合轴裁决 **NOT-RUN**（fail-closed 口径要求整案）。
- **版本/日期**：五案 `as_of` 逐案等于 2026-11-20；无 future/expired 使用层；C25 禁源绑定可复核 true、C29 不可复核（残留，不影响 safety passed）。

## 4. 已完成：T-R2-202 机制判定

### 4.1 202B（身份）——**已结案：当前产品不再产生同形不一致**

同形合成端到端：`fact_key` 与 `unit_key` **逐字节相等**；两入口（`p2_hard_evidence` v0.2 合同路径、`p2_evidence_rescore_axes`）均 **`passed/frozen_targets_match_ok`**。
反例 a–e 全绿（外实体 → `other_entity_used`/`citation_entity_mismatch`；半身份/缺行/重复 → `unknown/entity_identity_unresolved`；无标识多行两侧可区分）。
敏感性：运行时还原 HEAD 版 `rag/chunking.py::_entity` → 立刻回到 `unknown`。
交付：`backend/tests/evaluation/test_r2_202b_entity_identity_e2e.py`（7 例，独立复跑 20 passed 含 202A）。
⇒ **C25/C29 的 cross_entity unknown 属历史形态，修后版本预期 unknown 0**；未改任何判据、未改产品。

### 4.2 202A（C29 机制）——**已结案：机制在当前工作树仍复现**

合成同形（虚构实体，真实 HTTP 链路，模型替身）：A 形（不点名门店、含"分别"→`enumerate=True`、`filters=['item']`、`field_roles=(location,status)`）与
B 形（点名门店、`filters=['item','store']`）**结果逐字相同**：`kind=answer`、1 来源、只给位置值、缺店家级值、**模型 0 调用** ⇒ 与 C29 的 `value_hit`/`source_hit` 1/2 同形。

首次丢失层与四道门（实测）：
1. **路由**：`conversations/service.py:2239-2240` 把 enumerate+实体过滤轮次交给 RAG 内核，`:2502/:2516` 直接返回，**从不调用** `retrieval/service.py::_store_join_ids`；
2. **候选**：`rag/retrieval.py:221-244`（逐过滤键 AND，`$.item` 排除店家行）+ `:267-274 _has_role`；
3. **取行**：`rag/answer.py:318-322`（只按 `plan.field_role`）；
4. **事实绑定**：`rag/facts.py:90-92`；**行内归属**：`rag/facts.py:347-348`（物品标签「X店的Y」天然含店名，与店家标签互污）。

⇒ **R0 的跨表 join 只覆盖 legacy，不覆盖 RAG 直答路径**；这是**产品能力缺口**，不是捕获缺失（此前对旧 envelope 的"捕获缺失"归因已被合成实测取代）。
交付：`backend/tests/integration/test_r2_202a_c29_mechanism_synthetic.py`（13 例）；**未改产品源码**。

## 5. 暂停时已收口：T-R2-202C（C29 跨实体取数最小修复）**已收敛为 A（绿），无半完成状态**

- 目标：让 RAG 直答路径在「同时请求物品级 + 店家级字段、过滤含物品、唯一物品目标、门店值可唯一读出」时，联结**同一门店**的店家行，
  使正文与 `sources` 覆盖两类值/两个来源；其余形态逐字不变；**未放宽任何安全/实体判据、未改 `cross_entity` 判据**。
- **改动 9 hunk**：
  - `rag/retrieval.py`：`_store_join_chunks`（全条件成立才联结，复用 `_base_stmt` 的活资料/版本/业务日窗口）+ 并入店家行 + `diagnostics["store_join"]`；
  - `rag/answer.py`：联结轮次按**记录身份逐行渲染**（4 个只读 helper + 单角色裁剪保留联结行 + `joined_store=` 透传）；
  - `rag/facts.py`：keyword-only `joined_store` + `_joined_store_row`，**仅当该行门店值 == 联结门店**时放行联结店家行。
- **红→绿**：A（`filters=[item]`）与 B（`filters=[item,store]`）修前均 `共 1 条…显示 1 条`、只有位置值、1 来源、模型 0 调用；
  修后均 `共 2 条…显示 2 条`、位置值 + 店家级值两行各带记录指纹、`sources` 两份不同文档、模型 0 调用。
- **反例 C1–C7 全绿**：只问位置 / 只问店家属性（legacy 1 次模型调用、无位置值）/ 物品+电话（`SECURITY_RESTRICTED_CONTACT`、`sources=[]`、0 调用）/
  同名物品两店（不联结）/ 店家行过期（不联结）/ 多物品枚举（与关闭入口逐字相同）/ `mode=document`（逐字相同）。
- **敏感性双向成立**：关 `_store_join_chunks` → A/B 回红；关 `retrieval.service._store_join_ids` → legacy 形态转 `service_error` 而 A 仍绿 ⇒ 两处互不吞并。
- **实测（cwd=`backend/`，`..\.venv\Scripts\python.exe -X utf8`）**：`py_compile` 三文件 exit 0；
  `test_r2_202c_c29_join_rag.py` 13 passed；`test_r2_202a_c29_mechanism_synthetic.py` 13 passed（6 例红态断言按新行为翻面并加严，另加 2 条 fail-closed）；
  R0 保护面 14 passed；合并 91 passed / 0 failed。**本经理独立复跑 40 passed / exit 0**（202C 13 + 202A 13 + R0 join 7 + C12b e2e 7）。
- **当前字节（经理已核）**：`rag/retrieval.py aee14c82…`(34458B, 17:27:32)、`rag/answer.py b89622be…`(58877B, 17:27:55)、`rag/facts.py cf795cfd…`(28961B, 17:28:04)；`py_compile` exit 0。
- **回滚只回本批**（已实测 dry-run exit 0）：
  ```bash
  git apply --check -R docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/05-fix/R2-202C-MINE-rollback.patch.txt
  git apply -R       docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/05-fix/R2-202C-MINE-rollback.patch.txt
  ```
  回滚后应为 `retrieval.py 3ee0511b…`、`answer.py b4a3ad88…`、`facts.py 42cdfeb2…`。
  `R2-202C-src-diff.patch.txt` 是完整 `git diff`（含 R0/R1 他批 hunk）**不可**用于整体回滚；现场字节副本见 `evidence/05-fix/snapshot-at-pause/`。
- ⚠️ **绝对禁止** `git checkout/restore/stash` 这三个文件：它们在会话开始前就含 R0/R1 的未提交成果。
- **202C 留下的风险（下一窗口优先处理）**：
  ① C29 形态 `total` 由 1→2，**102d 分页检查未复核**（最高优先）；
  ② 联结行入 `exact` 不入 `fused`，读 `diag` 的调用方会看到 `filter_miss`（产品路径不传 `diag`）；
  ③ 同门店多条店家行会全部并入，未做"取最新"，多页场景未测；
  ④ `enumerate` 是本批额外收紧的触发条件；非枚举 RAG 轮次需另评估 `_multi_field_answer`/`ambiguous`；
  ⑤ 202A 的 6 例红态断言已翻面，红态原文仅存于 `evidence/04-mechanism/R2-202A-REPORT.md`。

## 6. 暂停时的仓库现场

| 项 | 值 |
|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b0066726e5b8d6f94cbc0b63a890084550c106`（未变，172 commits） |
| tracked 修改 | **39**（数量与开工快照相同；其中 `rag/retrieval.py`、`rag/answer.py`、`rag/facts.py` 本就在这 39 之内，本批在其上**追加 9 hunk**，因此不新增计数。可用 `evidence/05-fix/R2-202C-MINE-rollback.patch.txt` 精确剥离本批） |
| staged | 0 |
| porcelain 总行 | 开工 358 → **暂停时 362**（+3 新增未跟踪测试 +1 本包未跟踪目录） |
| 受保护件 | `p2_hard_evidence.py 9861c44e…`、`p2_scoring.py c3265f4f…`、`scorers.py 3f8ee170…`、`budget.json 79b21700…`、`live-ledger.jsonl 3bc3839f…`、GO 槽位 `P2-LIVE-GO.json 38f3c3f5…`（仍是 R1 run2 旧件，**不代表新许可**） |
| 新增未跟踪测试 | `test_r2_202a_c29_mechanism_synthetic.py`（13 例）、`test_r2_202b_entity_identity_e2e.py`（7 例）、`test_r2_202c_c29_join_rag.py`（13 例） |
| 交付目录 | `docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/`（未提交） |

## 7. 预算与账本（运行前只读对账已完成）

项目累计 **24.7217539 / 40**（余 15.2782461）；阶段 `P2-LIVE` **9.6508094 / 20**（余 10.3491906）；配对 **1940/1940**（集合差 0/0）；
`budget.json` sha `79b21700…`、账本 sha `3bc3839f…` 未变；`boundary_anomaly=0`。明细见 `evidence/06-run-prep/ledger-recon-before.md`。

## 8. 交付物清单（本包，截至暂停）

| 文件 | 说明 |
|---|---|
| `R2-BASELINE.md` | 零调用重建（5/5、逐题检查码、四轴五档、评分版本对照、首偏离、身份、C14、版本日期） |
| `R2-DIAGNOSIS.json` | 机器可读诊断（固定码/计数/布尔/哈希） |
| `R2-RUNBOOK.md` | 656 行真实运行程序（入口=`tools/p2_h2_v3_controlled_execute.py`；GO 文本 ≤200；`code_version`=脏工作树摘要；run_id 不可唯一，靠 `plan_sha256` 区分；两套 GO 哈希分列；6 条 UNVERIFIED） |
| `evidence/00-baseline/` | 保护快照、R2 run 基线切片 |
| `evidence/01-safe-projection/` | `r2-quality-checks.json`（`2c322e16…`）、`r2-scoring-version-compare.json`（`ca01727f…`）、`r2-adaptation-selftest.json`（6 类误输入全拒 + 正对照 6/6）、`C25-RECON-GAP.md`、`NOTES-201D.md` |
| `evidence/02-case-boundary/` | 逐案边界 + `r2-entity-identity.json` + `r2-version-date.json` |
| `evidence/03-final-chain/` | 五档 recompute + `r2-axis-flips.json` + `r2-consistency.json` + `r2-report-divergence.md` |
| `evidence/04-mechanism/` | `R2-202A-REPORT.md`、`R2-202B-REPORT.md` |
| `evidence/05-fix/` | 202C 在飞（暂停现场） |
| `evidence/06-run-prep/` | 预算账本对账 |

## 9. 下一窗口的继续顺序

1. **先复核 202C 的副作用**（见 §5 风险①②）：`test_r1_102d_turn_pagination.py` 与 `test_r1_102a_structural_numbers.py`、
   `test_r1_103_http_structural_numbers.py`（C29 形态 `total` 1→2 可能影响分页断言）；再确认 `evidence/05-fix/snapshot-at-pause/` 三件与当前字节 sha 一致。
2. **T-R2-203**：C29 同形红绿（同路径/状态/输入形态）、C25/C29 身份对照、C14 完整两回合、精确 5 题 6 回合集合检查；
   判定链 `test_r0_repair_same_round_inputs`/`test_p2_evidence_rescore*`/matcher 版本用例；v0.6 继承；
   结构数字 102a/102d + 104 对抗探针；R0/R1 产品保护（C12 跨表/contact、多门店主目标、legacy 范围、凭据拒答、政策问答与唯一门店追问）；
   日期版本（`test_v3_fix1_business_date_filter`、`test_p2_stale_version_state`）。
   **HTTP 必须走 上传→解析/索引→发布→conversations 正式链路**，至少贯通 C29 证实失败路径、C25 同形身份、C14 两回合；不能只断言 200 或 kind。
   每个关键红例至少一次「关掉补丁→回红」的敏感性对照；legacy 走查缺陷必须有 legacy 见证；出站守卫子进程也要覆盖。
3. **T-R2-204**：全新上下文独立预验收（自执行关键验证、给命令/退出码），核对根因证据同形、改动范围、反例、HTTP 见证、未放宽评分、R0/R1 保护。
4. **T-R2-205**：按 `R2-RUNBOOK.md` 生成新计划（绑定修后**脏工作树**摘要）→ 归档旧 GO（`38f3c3f5…` 已存在两份同字节归档，命名须新 tag、`xb` 独占创建）→ 由本窗口以 R2 专属委托签发新 GO → 完整 check-only → **单次**真实运行 → 封存/清理/账本配对。
5. **T-R2-206**：最终证据与判定、经理收口、停止（不进入 R3、不提交 git）。

## 10. 已知风险与未决

1. **202C 是本次唯一产品改动，也是最大风险点**：四道门（候选/取行/事实绑定/行内归属）跨越 `rag/{retrieval,answer,facts}.py`；任何一处放宽都可能伤到 R0/R1 安全面。验收必须逐条反例。
2. **C29 的真实题面未知**：合成件证明机制与层位，但不等于真实题面；若真实题面点名的门店不在词表内，`filters` 可能仍只有 item，修复能否覆盖需真实轮验证。这属于"一次真实运行"的固有不确定性，已如实登记。
3. 若 202C 只能做到部分覆盖，则 R2 可能仍为 4/5。**此时不得为了"跑一轮看看"而付费**（属禁止的"无变化重复付费"）；应按任务书 §9 列"失败码/首偏离与修前是否变化、原假设是否被证伪、下一次需修什么"，交主人决定。
4. `R2-RUNBOOK.md` 有 6 条 `UNVERIFIED`（holdout 根实跑、`run_recompute_cli` 的 `cases_path`、工具残留 R1 绝对路径、本次 `worst_case_cny`、新 GO 装槽后 16/16 全绿、`contract_validate_run.authorized_delta`），执行前必须逐条落实，不得猜命令。
5. 固定槽位 GO 仍是 R1 旧件；**未归档、未覆盖**。新 GO 签发的授权文本必须 ≤200 字符（历史 4 份超长件被 `text_invalid` 拒绝，现场仍留档）。

## 11. 声明

- 全程零真实/离线产品请求、零出站（netguard `outbound_allowed=0`，含子进程守卫，正对照全阻断）；零 pytest 于 T-R2-201 阶段，202 阶段的测试全部为合成/离线。
- 未读真实题面/答案/实体值；私有材料仅在进程内解密并只输出固定码/计数/布尔/哈希。
- 未 git 提交/推送/合并；未新分支/worktree；未改预算/账本/冻结件/case-plan/历史证据。
- 不声明 `verified`/`release`/`T207_pass`；**R2 尚未达标，真实运行未执行**。
