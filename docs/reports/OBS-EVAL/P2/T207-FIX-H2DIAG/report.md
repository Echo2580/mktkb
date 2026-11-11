# P2-T207-FIX-H2DIAG 开发报告（H2 聚合诊断：只出代码/计数）

> **最终状态：拒收并撤回（2026-11-11）**。全新独立验收见 `review.md`：ASCII 敏感片段可进入诊断输出，隔离约束未满足。
> 主人选择 A，经理未派新修复，已将三份源码/测试和两份契约精确恢复至 `93a89ec`，并撤回 runbook 的诊断承诺。
> 本页及原开发 evidence 均为被拒提案的历史声明，不代表当前具备该功能或独立验收通过。
> 被验 diff/hash、独立复现和回退证明保留于 `evidence/verify-current/`；探针依赖被拒提案，不应在已回退源码上宣称可复跑。

**结论**：`holdout_scorecard.json` 新增 `diagnostics`（`p2-holdout-diagnostics/v0.1`）：kind 矩阵 / 拒答矩阵 / 失败 check /
来源映射 / 错误码 × 分层计数。只有稳定代码、计数与布尔 —— 无题干/答案/`reference_answer`/`case_id`/locator/逐题行；
泄漏审计扩到诊断子树（形态白名单，命中自由文本即 fail-closed）；aborted 也写。零真实调用；未改
`p2_scoring.py`/`scorers.py`/业务代码/fixtures/账本/预算/GO；无新增 skip/xfail；未 commit。

## 1. 改动清单
- `p2_runner.py`：新段 `T207-FIX-H2DIAG`（L1937–2276）`_HoldoutScoring`/`_HoldoutDiagCase` + `_diag_code`（自由文本→固定占位）
  + `_case_actual_kind/_case_error_code/_case_failing_checks/_case_source_failed_codes`（L2022–2100）+ `_holdout_diag_cases`（L2102）
  + `_diag_tally`（L2136）+ `_source_mapping`（L2166）+ `_holdout_diagnostics`（L2210）+ `_assert_holdout_diagnostics`（L2236）；
  `_holdout_score_marks`（L1817）返回诊断上下文（逐题 `P2CaseScore` 只读观察口 `score_sink`，L1882）；`_holdout_scorecard` 挂诊断（L2334）；
  兜底卡挂最小诊断（L2464）；`_assert_holdout_scorecard_payload`（L2359）先审诊断子树、再逐题扫 needle。
- `p2_score_run.py`：`holdout_case_scores_from_rows(..., score_sink=None)`——可选只读出口，**返回形状不变**，CLI 路径不受影响。
- 测试 `test_p2_holdout_scorecard.py` §6 +6 条；文档 `p2-dataset-v0_1.md` §11、`p2-live-binding-v0_1.md` §10.11、`T207-runbook.md` §8（additive）。

## 2. 诊断字段口径
- `kind_matrix`：expected_kind → actual_kind → 题数；actual 取**末轮** `product.kind`，无产品结局用固定占位码（`error`/`not_executed`/`unknown`）。
- `refusal_matrix`：`should_refuse`(true/false) → `refused`/`not_refused`；只统计**有产品结局**的题（`ends_observed` 是分母），
  未执行/执行失败不计成"没拒答"。`failing_checks`：失败 check_id → 次数（只留 id，不带 evidence）。
- `source_mapping`：`doc_codes_available`（= 既有 unmapped block 的 `mapped`）/`doc_codes_expected`/`doc_codes_missing`/
  `expected_cases`/`expected_cases_mapped`/`source_hit_failed_cases` + `by_doc_code{code:{expected_cases,source_hit_failed,mapped}}`；
  `source_hit` 失败按 `missing_index` 归到**没命中的**期望来源（期望 D01+D02 只中其一时只记 D02），归位不到才退化为全部期望码。
- `errors_by_code`：错误码 → 题数，每题只记**首因** ⇒ `sum == scorecard.errors`；未执行记 `not_executed`，行内无码退到隔离问题码
  （如 `source_not_active`）。`by_stratum`：上述四表按层拆开。

## 3. 合成封存逐值验证（evidence/01、02）
- 30 题合成封存（10-5-5-5-5）：`kind_matrix`= answer{answer 18, error 1, not_executed 1, not_found 1}/conflict{4}/refusal{answer 1, not_found 4}；
  `refusal_matrix`= true{refused 4, not_refused 1}、false{refused 1, not_refused 22}；`failing_checks`={source_hit 4, value_hit 2, kind_correct 2,
  refusal_expected 1, refusal_unexpected 1}；`source_mapping`= D01 21/3、D02 1/1、V06 1/1（`mapped=false`，与
  `holdout_document_code_unmapped{missing:["V06"],mapped:8}` 同源）；`errors_by_code`={MODEL_OUTPUT_INVALID 1, not_executed 1,
  source_not_active 1} == `errors`=3。不变量：kind 覆盖全题、拒答矩阵=有结局题、错误码和=errors。
- aborted（第 1 次 chat 503）：`stop_code=product_service_error`、aggregate `executed=1`，卡仍写诊断 —— `errors_by_code`=
  {MODEL_UNAVAILABLE 1, not_executed 29}（和=30=`errors`）、`kind_matrix`=answer{not_executed 24, service_error 1}+refusal{not_executed 5}、
  `ends_observed=0`、无 case_id/题干命中、run 目录无 `cases.jsonl`/`requests.jsonl`。

## 4. 泄漏审计扩展（fail-closed）
- `_assert_holdout_diagnostics`：顶层键固定白名单；嵌套键与叶子字符串必须是稳定代码形态 `[A-Za-z][A-Za-z0-9_.:-]{0,63}`；
  只允许 int/bool/同形态字符串。数组、未登记键、`H2-` 前缀、任何自由文本（空白/CJK/超长）→ `holdout_scorecard_leak`，
  产物退化成"全 error + 稳定 block"（测试覆盖 6 种坏形态 + 正常诊断 0 误报）。
- 诊断子树不套用"明细字段名"规则：kind 名 `answer` 本身在 `_HOLDOUT_FORBIDDEN_KEYS` 里，套用会把**正常卡**判成泄漏；
  改用这条更严的形态白名单，逐题 needle 扫描与 `H2-` 前缀检查照旧覆盖诊断。生成侧同时收口：产品回自由文本 `kind` → 记 `unknown`。

## 5. 回归与限制
- `test_p2_holdout_scorecard.py` 27 passed（21 旧 + 6 新）；相邻 6 个模块 173 passed；零真实出站（`t09_network_guard`）；未读 .env/真实 H2/key。
- 限制：`diagnostics` 只加在 runner 的 H2 卡上（`p2-score` CLI 复核卡不变）；兜底卡只给"原因码 × 总数"；`hard_failures` 语义不变；
  真实 H2 未重跑，诊断价值待下次 H2 run 按真实 kind/check/doc_code 分布确认。
