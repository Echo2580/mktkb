# REPRO-REPORT：R1 五机制在当前工作树的复现判定（T-R1-101）

日期 2026-11-17。判定对象：`R1-BASELINE.md` §5（C05/C07/C13/C22/C28 的机制定位）。
约束：只新增测试文件与本报告；`backend/src/mktkb/**` 零改动（`git status --porcelain -- backend/src`
在首轮交付时前后均 45 条、逐行相同；返工后新增的 102a 并行改动见 §4）；无 git 写操作；无网络（`provider_mode=offline`、`embed=False`、不读 `.env`/`var/`）；
所有实体与值均为合成（甲店/乙店、立牌、甲区/乙区、两件、甲某、SEQ-0001）。

## 1. 判定表

> 2026-11-17 口径更新：M1/M2 的 red 判定已被 T-R1-102a 取代，现行结论见 §4（本表保留为当时判定记录）。

| 机制（源码位置） | 当前 | 关键断言（失败⇒未修） | 证据（文件::用例） | 判定 |
|---|---|---|---|---|
| M1 整行渲染含结构数字（`rag/answer.py:594-608`、`rag/facts.py:31-44`） | **red** | 答案正文不出现 `第 {十进制} 行`；`value_no_fabricated` 的 `extra` 不含行号 `7` | `test_r1_101_m1_row_marker_digits.py::test_m1_record_line_has_no_decimal_row_number`、`::test_m1_scoring_does_not_count_row_number_as_fabricated` | 仍复现（行号半）；`（记录 {ref}）` 半**已由 R0-4/C02 修复**（`::test_m1_record_reference_marker_carries_no_decimal_digits` 绿，指纹 `[a-f]{8}`） |
| M2 枚举页头计数（`rag/answer.py:728` + `evaluation/scorers.py:446`） | **red** | 页头 `共 2 条，当前第 1 页显示 2 条` 的计数不得进 `extra`，`value_no_fabricated` 应 pass | `test_r1_101_m2_enumeration_header_digits.py::test_m2_enumeration_header_counts_are_not_scored_as_fabricated` | 仍复现（`extra=['1','2']`）；`::test_m2_page_counts_are_absent_from_scoring_number_keys` 绿，锁定“评分只收 citation.text + locator 字符串”口径 |
| M3 回合间门店范围丢失（`rag/query.py:parse_query/_new_state` + `filters`） | **red** | 第 3 回合 `filters["store"]` 仍为 `甲店`；答案不得含 `乙区` 或他店事实 | `test_r1_101_m3_turn_scope_loss.py::test_m3_store_scope_is_still_known_on_later_turn`、`::test_m3_later_turn_does_not_answer_with_another_store` | 仍复现：t2（无实体换话题轮）后 `filters={}`，t3 `filters={'item':'立牌'}`，枚举式追问直接列出 甲区+乙区 |
| M4 “位置/哪 + 生效”只取 `effective_from`（`rag/query.py:_match_fields` :1169 起） | **green** | 混合问法下 `field_roles ⊇ {effective_from, location}` 且正文含 `甲区`；只问生效时不夹带位置 | `test_r1_101_m4_location_with_effective.py`（4 种问法 + 1 条反例，5 passed） | **已由既有修复覆盖**：R0/C21（`query.py:1189-1203`），单测 `backend/tests/rag/test_r0_10_effective_role_not_swallow.py` |
| M5 含“完整合同/结算账号”应拒未拒（`rag/answer.py:658-665`、`rag/query.py:1647`） | **red** | `kind=="no_answer"` 且 `reason` 以 `SECURITY_` 开头；账号值不得出现在正文 | `test_r1_101_m5_payment_scope_refusal.py::test_m5_contract_and_settlement_account_question_is_refused` | 仍复现（`kind=answer`，只渲染 位置+联系人）；`::test_m5_position_plus_contact_only_still_answers` 绿，R0/C12 放行面未收窄 |

实测要点（去标识化）：
- M1：`… / 合成表 第 7 行（记录 dbebbfdf）：门店=甲店；物品=立牌；数量=两件；位置=甲区`，`extra=['1','7']`（`1` 来自枚举页头，`7` 来自行号）。
- M2：`value_hit` 仍 pass，只有页头计数被算成编造（`extra=['1','2']`）。
- M3：t3 正文 `共 2 条，当前第 1 页显示 2 条。 - 甲店的立牌：甲区 - 乙店的立牌：乙区`；非枚举问法（`立牌放在哪？`）当前收在 `MULTIPLE_ENTITIES` 澄清，不混店。
- M5：`kind=answer`、`reason=None`，正文 `…位置：甲区，联系人：甲某。`，未拒答、未泄露账号值。

## 2. 运行命令与结果（全部实际执行；`pytest` 前缀 = `.\.venv\Scripts\python.exe -B -m`）

| # | 命令（工作目录=仓库根，除 #7） | 退出码 | 结果 |
|---|---|---|---|
| 1 | `pytest <…>\r1_mechanism_repro\test_r1_101_m1_row_marker_digits.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\r1101` | 1 | 2 failed, 1 passed |
| 2 | 同上，`…test_r1_101_m2_enumeration_header_digits.py` | 1 | 1 failed, 2 passed |
| 3 | 同上，`…test_r1_101_m3_turn_scope_loss.py` | 1 | 2 failed, 1 passed |
| 4 | 同上，`…test_r1_101_m4_location_with_effective.py` | 0 | 5 passed |
| 5 | 同上，`…test_r1_101_m5_payment_scope_refusal.py` | 1 | 1 failed, 1 passed |
| 6 | `pytest <…>\r1_mechanism_repro -q -p no:cacheprovider --basetemp backend\.pytest-tmp\r1101`（五文件合计） | 1 | 6 failed, 10 passed（6 条全部为预期红例） |
| 7 | `cd backend; pytest tests\rag -q -p no:cacheprovider --basetemp .pytest-tmp\r1101-rag` | 1 | 1 failed, 552 passed —— 失败为**既有且无关**：`test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan`（只读 `docs/evidence/**` 的 GO/budget，实得 40、期望 20.0；本包未触碰该文件，也未读取） |

`<…>` = `docs\reports\OBS-EVAL\P2\H2V3\r1-repair-external-20261117\work`。

## 3. 未覆盖 / 缺口（NOT-REPRODUCED）

1. **M3 产品层未跑**：只在 `mktkb.rag` 层复现“门店范围丢失”。`conversations/service.py:_load_context` 与 legacy
   检索的跨店作答未装配（缺 conversations 层夹具与 legacy 索引），基线 C13 的产品层首偏离未复验。
2. **M4 的跨店半未单列**：基线 C22 的 `cross_entity` 侧在当前代码里与 M3 走同一入口（回合范围丢失），
   没有独立的“位置+生效”触发路径，故未单独立红例。
3. **M1 依赖 P2 引用投影**：合成引用按 R0-4 同口径传 `text=""`、locator 的 `row` 为 int；若真实投影把
   chunk 正文写进 `citation.text`，行号数字会进允许集合，该红例不成立（需真实投影复核）。
4. 未跑全量 pytest、未起服务、未发任何真实/离线产品请求；出站 0。

## 4. 口径更新（返工追加，2026-11-17）

T-R1-102a 已批准评分侧结构数字增量：`value_no_fabricated` 允许集合 = 金标/问题/参考答 ∪ `citation_number_keys` ∪ 结构 token（`citation_structural_number_keys` 的 locator 整数 + `outcome.pagination` 的 total/page/page_size/returned/next_page，仅 int）。据此把 3 条过期红例改成当前口径的回归证据（产品仍写 `第 N 行` 属既定行为）：
- M1 `::test_m1_row_number_is_grounded_by_locator_structure`：`value_no_fabricated=pass`、`structural_numbers>=1` → **pass**；
- M1 `::test_m1_without_structural_source_the_row_number_is_extra` / `::test_m1_ungrounded_number_still_fails`：抽掉结构来源→`extra` 含 `7`；写未背书 `9`→`extra==["9"]`，均 fail → **pass**；
- M2 `::test_m2_enumeration_header_counts_are_not_scored_as_fabricated`：页头计数由 `outcome.pagination` 背书→pass、`structural_numbers>=2`；对照 `::test_m2_header_claiming_more_than_pagination_still_fails`、`::test_m2_header_without_pagination_still_fails` 仍 fail → **pass**。

命令：`.\.venv\Scripts\python.exe -B -m pytest <…>\r1_mechanism_repro -q -p no:cacheprovider --basetemp backend\.pytest-tmp\r1101`
结果：**19 passed，exit 0**（逐文件 M1 4 / M2 5 / M3 3 / M4 5 / M5 2，均 exit 0）。
M3、M5 红例未改断言，随 T-R1-102b/102c 落地已转绿（t3 `filters={"store":"甲店","item":"立牌"}`；M5 `no_answer`/`SECURITY_RESTRICTED_CONTACT`）。
产品代码仍未改：本轮只动 2 个测试文件与本报告；`backend/src` 相对首轮快照仅新增 `M scorers.py`（T-R1-102a 并行改动），本包未写入任何 `backend/src/**`，未动 102a–d 新测试。
