# T207 修复范围（供后续 T207-FIX 开发的最小清单）

- 本文件只给「改哪里、怎么验证」，本包**没有改任何代码/测试/夹具**（真实调用 0，未 commit）。
- 每条格式：现象/证据 → 复现命令与预期失败 → 根因（文件:函数，读到行号）→ 最小修复方向 → 允许改文件 → 禁止改项 → 验证命令 → 回归风险。
- BLOCKER = 不解决就不能宣称矩阵跑完/达标；非 BLOCKER = 影响可读性/口径一致性。

---

## A 返工②：`run_result` 只有 answer 单侧范围

**现象/证据**：`T206/PILOT/run_result.json` 为 `requests_reserved=6 / requests_sent=3 / by_operation={"answer":6} / by_center_cny.ocr=0`，
而 `gate.json` 记 42 次底层尝试（含 OCR 0.5 元）。同一 run 的两份产物给出两个"规模"。

**复现命令**（离线，零真实调用）：`evidence/validate-plan.py` 之外的 runner 单测路径：
`python -m pytest backend/tests/evaluation/test_p2_live_wiring.py -q` 后读临时 run 的
`run_result.json` 与 `gate.json`，断言 `run_result.requests_reserved` 是否等于 gate 的唯一 reservation 数。
预期失败：pilot 实测 6 ≠ 42。

**根因**：`p2_runner.py:319-446`（`P2RunLedger` 只由 `_execute` 的 answer 轮 ticket 记账；
`reserved/settled_cny/by_center_cny` 均只累加 answer 轮），`p2_runner.py:421-446`（`result()` 直接搬这些计数），
而逐次尝试在 `p2_live.py:367-663`（`GateAttemptLedger`）与 `_attempt_audit`（`p2_runner.py:929-1011`）里。

**最小修复方向**：`P2RunResult` 增加 **additive** 字段（新 schema `p2-run-result/v0.2` 或新增键，向后兼容）：
`attempts_reserved / attempts_by_operation / attempts_by_center_cny`，由 `attempt_audit` 填；
`requests_reserved/by_operation` 保留 answer 口径但在 `summary.json` 里显式标注 `scope="answer_turns"`，
并在 `run_result` 里加 `attempts_scope="all_attempts"`。**不改** answer 口径的既有键语义。

**允许改文件**：`p2_contracts.py`（P2RunResult 新键 + `_RESULT_KEYS`）、`p2_runner.py`（result/_write_artifacts）、
`test_p2_runner.py`/`test_p2_live_wiring.py`（新断言）、`p2-runner-contract-v0_1.md`。
**禁止**：改 `_attempt_audit` 的核对语义、改 answer 轮计数、给 `gate.json` 增设"看起来像账单"的字段。

**验证**：`pytest backend/tests/evaluation/test_p2_runner.py -q`（旧断言不得回退）+ 新增断言
`run_result.attempts_reserved == gate_reservation_count`。**回归风险**：低（additive），但 gate/基线读取方若按`_RESULT_KEYS`做严格集合校验需同步。

---

## B 返工③：`summary.settled_failure` / 账本 `status=failed` / `requests.jsonl billed` 三口径混用

**现象/证据**：pilot 3 笔零 chat 拒答 → 账本写 `status=failed` + `P2_NO_PAID_ATTEMPT:*`（`p2_authorization.py:1249-1275`），
`summary.requests.settled_failure=3`（`p2_runner.py:1728`），`unused_no_paid_attempt=3`（:1731），
但 `billed_cny` 只统计 `provider_calls.outbound>0` 的行（`p2_runner.py:1540-1542`）→ 同一批 3 笔在三个地方三种读法；
`gate._settled_cny` 把 close_unused 的全额上界也加进"settled"（`p2_authorization.py:1272`）。

**复现命令**：`pytest backend/tests/evaluation/test_p2_live_wiring.py -q -k close_unused`；读临时 run 的
`summary.requests` 与账本尾部 3 行，比较 `settled_failure`/`billed_cny`/`status`。
预期失败：三者没有统一命名（settled/failed/billed 各说一套）。

**根因**：`p2_authorization.py:1218-1247`（settle_failure 才叫 failure）、`:1249-1275`（close_unused 也写 `status=failed`）、
`p2_runner.py:1313-1332`（`paid_attempt=False` 的轮次走 close_unused）、`p2_runner.py:1540-1542/1728-1731`（summary 分组）。

**最小修复方向**：在 `summary.requests` 下明确三段、互不冒充：
`conservative_held_cny`（账本保守占用总量）/ `provider_billed_cny`（仅在拿到真实 usage 时非空）/ `unpaid_rounds`（零付费轮），
并把 `settled_failure` 改名或加注释为 `no_paid_attempt_rounds`（保留旧键做兼容别名）；
账本侧不改 schema（`status=failed` 是既有语义），但在 `p2-authorization` 契约里写清「failed ≠ 供应商失败 = 未发生付费或失败保守留账」。

**允许改文件**：`p2_runner.py`（summary 组装）、`p2-runner-contract-v0_1.md`、`test_p2_live_wiring.py`。
**禁止**：改账本事件字段/状态集合、把 failed 改成 succeeded、把保守占用写成 0、动 `rag/budget.py` 结算规则。

**验证**：新增断言「3 笔零付费轮：`unpaid_rounds=3`、`provider_billed_cny=0`、账本 3 行 `status=failed`、
`conservative_held_cny=3×上界`」。**回归风险**：中（summary 是 gate/报告输入；只加键不改旧键值）。

---

## C 返工⑤：`output_valid` / `paid_attempt` 语义

**现象/证据**：pilot report 记「`output_valid=false` 是 dataclass 默认（非质量信号）」。实际：
`UsageEvidence.output_valid` 默认 **False**（`rag/settlement_policy.py:479`），而结算要求它为 True（`:713`，`output_invalid`）；
构造 chat 证据的 `build_chat_evidence`（`rag/controlled_usage.py:311-338`）**没有传 output_valid**。
`paid_attempt` 是 runner 轮次标签（`p2_runner.py:1313-1332`），零付费轮为 False。

**复现命令**（离线、零真实调用）：
```python
from mktkb.evaluation.p2_live import chat_usage_evidence
ev = chat_usage_evidence(request_sha256="0"*64, usage={"prompt_tokens":10,"completion_tokens":5,"total_tokens":15})
print(ev.output_valid)   # 预期 False -> 结算侧 output_invalid
```
预期失败：True 才是"拿到完整输出"。若实测 False，则 live chat 结算会保守留账（pilot 的 billed 偏小/偏保守就来自这里）。

**最小修复方向**：`p2_live.chat_usage_evidence` 显式传 `output_valid=True`（只在 `finish_reason=="stop"`、内容非空、
JSON 解析成功时才置 True），并把该判断写进 `p2-live-binding-v0_1.md`；`paid_attempt` 在契约里写明
「False = 本轮零付费结局（合法拒答/澄清/未找到/知识变更），不是输出无效」。

**允许改文件**：`p2_live.py`、`p2-live-binding-v0_1.md`、`test_p2_live_wiring.py`。
**禁止**：改 `settlement_policy.py` 的校验规则（那是 P1 冻结口径）、为凑金额把 output_valid 恒置 True。

**验证**：`pytest backend/tests/evaluation/test_p2_live_wiring.py -q`（新增：usage 完整→output_valid True；
缺 finish_reason/空内容→仍 fail-closed）+ `tests/rag/test_budget_settlement*.py` 不回退。
**回归风险**：中（结算金额会从"保守全额"变成"按 usage"，金额变小但仍是真账；须在报告里对比前后）。

---

## D Q01 版本槽（B0 同槽「历史版 → 当前版 → 未生效版」）

**现象/证据**：T206 pilot Q01 返 `conflict`；V03 与 D01 是两份 active 文档、各 version=1（`T206/PILOT/cases.jsonl`）。
**根因**：驱动层缺「作为既有资料的新版本」与「不发布」两个入口——`cli.py:598-603` 只造 `IngestSource(path=…)`；
产品侧 `documents/service.py:656-833` 完全支持（`document_id` + `expected_active_version_id` → `number=latest+1`），
`IngestSource` 也已有 `document_id/expected_active_version_id/publish`（`product_adapter.py:300-333`）。

**最小修复方向**（详见 `T207-import-recipe.md` §2）：`IngestSource` 加可选 `document_ref: str | None`；
`ProductEvalAdapter.ingest()`（`product_adapter.py:1736-1768`）把每次回执的 `document_id` 按 `name` 记入本地表，
遇到 `document_ref` 解析成 `document_id` 走「新版本」上传；`cli.py` 新增 `--ingest-plan <json>`（与 `--ingest` 互斥）。
产品代码 0 改动。

**允许改文件**：`product_adapter.py`、`cli.py`、`test_p2_product_e2e.py`（新增版本槽用例）、`p2-runner-contract-v0_1.md`。
**禁止**：用 `allow_same_name` 代替版本（会建第二份文档）；改 `documents/service.py` 的上传/发布规则；
把 V04 当 B0 的当前有效内容（`fixtures/acceptance/manifest.json` 的 `b0_initialization.forbidden`）。

**验证**：新增离线用例（Mock provider，零出站）：三步上传后断言
`latest_version_number=3 / active_version_number=2 / v3.state=review_required / revision 只 +2`，
且 Q01 仍答 `B区1号货架第二层`、来源 `version_number=2`、不含 V04 的 D 区位置。
**回归风险**：中（`ingest()` 是既有入口，须保证 `--ingest` 旧路径逐字不变）。

---

## E 公开财务反例 4 个（+ 正向对照）

**现象/证据**（T205 report §4、`T205/evidence/02-reproduction.txt`，全 Mock）：

| # | 问题 | 现行回答 | 评测判定 |
|---|---|---|---|
| E-1 | E10「陈列达标率的计算口径和年度目标」 | 只给月份+指标+口径，**缺 90%** | fail（value_hit） |
| E-2 | W03「单场预算 8000 元由谁审批」 | 整条第六条，含**其他分档**的「事业部总经理」 | fail（value_forbidden） |
| E-3 | E03「2026 Q4 档期特价」 | **缺 2.99**，检索同时带 2025 旧行 | fail（value_hit） |
| E-4 | E03「咸味饼干 120g 批发价」（价目表无此商品） | 回**启沣柠檬茶** SKU 行 | fail（kind_correct） |
| 正向 | W03「活动结束后几日内上交结案报告」 | 6 个自然日（第五章） | **pass** |

**复现命令**：`pytest backend/tests/integration/test_p2_public_controls.py -q -k "decoy or supported or f01 or year" `
（`test_year_decoy_price_row_is_rejected` 在 `test_p2_public_controls.py:347`；正向在 `:312/321`）。
预期失败：4 个诱饵分支走"产品答错 → 判 fail"的 if 分支（断言本身通过，产品是红的）。

**根因（读到行号）**：
- 数值/度量字段整类缺失：`retrieval/index.py:22-38`（`HEADER_ROLES` 只有 store/item/alias/location/contact/phone/address/status，
  **没有数值/目标/价格/日期角色**）→ `retrieval/index.py:72-81`（`resolve_requested_role` 返回 None）→
  `conversations/service.py:626-646`（`_facts` 把这些字段记进 `missing`）→
  `conversations/service.py:1399-1406`（`_record_answer_text` 跳过 `role is None` 的字段，**不原值回显**）。
  ⇒ E-1/E-3 的「数值被丢掉」是同一根因。
- 分档越界：`conversations/service.py:1136-1191`（`_match_record_clause` 只按"整条子句"匹配，不比较档位数值区间）→
  `service.py:1054-1078`（`_record_statement_bodies` 把同条其它分档一起带出）。
- 他实体越界：`service.py:932-947`（`_record_units` 只在 `plan.entities["item"]` 命中时过滤；
  商品名不在词表 → 无过滤）→ 任何 SKU 行都可以给回答背书。意图侧见 `conversations/intent.py`（实体词表/别名抽取）。

**最小修复方向（按"最小定点"排序，逐条可独立验收）**：
1. `HEADER_ROLES` 增加**只读**数值/日期角色（如 `metric_value / target_value / price / effective_date`），
   `resolve_requested_role` 认这些表头；`_record_answer_text` 对"已知角色但未被问"的字段保持现行为，
   对"本次问到的角色"**必须**原值回显（E-1/E-3）。
2. `_record_units` 增加"实体未识别即拒答"分支：问题里出现商品/门店名但词表未命中的，按 `not_found` 处理，
   **不得**退化成"任选一行"（E-4）。判据只用公开语料（价目表/主数据表）里的名称，不引入隐藏集。
3. `_match_record_clause` 增加档位约束：问题含数值时，只保留"该数值落在其区间"的分档子句（E-2）。
4. 年份/有效期：`_record_units` 增加 `effective_date <= business_date` 过滤，且同一 SKU 多行时取**生效行**（E-3 的 2025 旧行）。

**允许改文件**：`retrieval/index.py`、`conversations/service.py`、`conversations/intent.py`（若需实体词表扩展）、
`test_p2_public_controls.py`（把"产品答错→fail"的 if 分支改成"必须 pass"）+ 对应单元测试。
**禁止**：改 `fixtures/evaluation/*`、`fixtures/acceptance/*` 的期望/标签；改 `scorers.py`/`gold.py`；
把诱饵写进 `reference_answer` 或放宽 `value_forbidden`；新增 skip/xfail。

**验证：走离线控制用例，不跑真实矩阵**（任务书 §4）：
`pytest backend/tests/integration/test_p2_public_controls.py -q`（4 个诱饵必须 pass、正向仍 pass）
+ `pytest backend/tests/evaluation/test_p2_scoring.py -q`（冻结诱饵文本仍判 fail）+ `probe_t205.py`（出站 0）。
**回归风险**：**高**——这四条都动规则路径的核心（字段角色、实体判定、子句匹配、有效期过滤），
会改变大量既有 B0/acceptance 期望的通过面；必须每次只改一条、跑 `test_p0_acceptance.py` + `test_t09_mutation.py` 后再改下一条。

---

## F 矩阵可执行性缺口（必须用代码证明；逐项给最小方案）

### F1【BLOCKER】H2 逐 case 计划项 vs 隐藏 case_id 的矛盾

- **证明**：`p2_runner.py:1057`（`items = _answer_items(plan, dataset)`）→ `:1073-1083`：dataset 里每个 case 的每一轮
  都必须在计划里有 `(case_id, turn)` 的 `answer` 项，否则 `plan_item_missing` 直接停；
  `p2_live.py:241-245`（`PlanIndex.answer_item` 查不到即 `attempt_item_unknown`，**发送前**拒）。
  而 H2 的 `case_id` 只存在于密文里（`p2_dataset.py:666-672`，`_validate_questions` 从解密行取 `case_id`），
  manifest 只有计数/分层/turn_stats（`docs/evaluation/p2-holdout-v2.manifest.json`）。
  ⇒ 「不读题干就写出含 case_id 的计划」在结构上不可能；`GO.scope.plan_sha256` 又必须绑定计划。
- **最小方案（推荐）**：**封存进程内生成计划**：用 `load_p2_dataset(visibility="holdout")` 得到的 36 个回合
  生成 `P2RunPlan`（每回合 4 项 + 1 个 `index_embedding` 项），计划文件只写在封存目录/工作区外，
  仓库内只留 `plan_sha256`（64 hex，不泄漏）。GO 绑定该 sha。模板见 `PM/T207-plan-h2-v0_1.template.json`。
  需要新增一个 ~100 行的生成器（`evaluation/p2_holdout_plan.py` 或 `tools/`），**不读题干、只读回合结构**。
- **替代方案**（若禁止新增生成器）：给 `_answer_items`/`PlanIndex` 加"通配计划项"（`case_id="H2-*`"），
  按 `visibility=="holdout"` 且显式开关启用，配额按 `requests=每回合数×回合数`。**反对**：等于放宽
  「计划逐项可审」，且 `_attempt_audit` 的 `receipt_item_unknown` 会拒掉通配项。
- **不做**：不把 H2 case_id 落进仓库、不写进报告/日志/文件名。

### F2【BLOCKER（数据保管面）】H2 语料包没有声明

- **证明**：全仓只有任务书 §4.2 一句「H2 在同一个已声明、可预算语料包内独立命题」；
  `grep 语料包` 命中仅任务书；`corpus/enterprise-20261101/manifest.json` 只有 9 个阶段的通用导入配方，
  没有「H2 用哪些 code」。⇒ 计划里的 `index_embedding.requests` 与 OCR 页数无从确定。
- **实算的可行域**（`evidence/estimate-out.json` 的 `corpus_envelope`）：全 corpus（不含 11 份 boundary）= **994 批**；
  请求侧 547+255+144+994 > 1600；资金侧（含 12 页 OCR）≈23.2 > 20。⇒ 全量包**不可行**。
- **最小索取清单（交给保管方，仓库可安全存放）**：一个 `p2-holdout-v2.corpus.json`，字段只要
  ① 参与命题的 corpus `code` 列表（如 `["E01","E02","W03",…]`）；② 是否含扫描件/图片页（`codes` + 页数）；
  ③ 导入顺序（按 manifest 的 `import_recipe` 阶段号即可）。**不含题干/答案/case_id**，可以进仓库。
- 在拿到该文件前：H2 计划只能停在模板，**不得**用「全 corpus」当默认（会超限且等于替保管方选题材）。

### F3 N8/C6 如何进入 `P2CaseScore` 与 `score_public_suites`

- **证明**：`score_public_suites` 的分母是冻结 id 集（`p2_scoring.py:137-146`），要求 `N01–N08`、`C01–C06` 全部出现
  （`_tally`：`missing_case` 阻断、`case_error/case_not_executed` 阻断，`:1002-1033`）；
  而 N/C 只有 `fixtures/acceptance/questions.json`（`group=negative/ambiguity_conflict`），
  **不是** `CaseSpec` 行，也没有 `fixtures/evaluation/` 版本。
- **最小方案**：新增一个**只读转换器**（如 `evaluation/p2_public_matrix.py`）：
  `load_acceptance_cases(questions.json) -> tuple[CaseSpec, ...]`，映射规则固定且可审：
  `id→case_id`、`question→question`、`group→suite`（negative/ambiguity_conflict）、`expected_kind`、`expected_values`、
  `expected_sources`（空）、`requires_ocr=False`、`labeler="acceptance-fixture"`、`label_version=questions.json.version`；
  C05/C06 的 `scenario.actions` 不进 CaseSpec，改由**独立 run 的 ingest 计划**表达（见 §D 与 cost §3）。
  转换后 `validate_case` 必须 30/30 通过（64 条里只取 N/C）。
- **禁止**：把 acceptance 题目复制成新的冻结 fixture；改 `questions.json`；给 C05/C06 编造 `expected_sources`。
- **验证**：`pytest backend/tests/evaluation/test_p2_scoring.py -q` + 新转换器用例（64 条里 N8/C6 逐字段等于源文件）。

### F4【BLOCKER（口径）】U10 的 L/R 标记与 `execution_mode_mixed`

- **证明**：`p2_scoring.py:1178-1182`：同一张公开矩阵里若逐题 `execution_mode` 混用 → 直接抛 `execution_mode_mixed`；
  `_execution_mark`（`:214-233`）又禁止非 live 声称 `real_calls>0`。
  而任务书 §5 明确：U 用 **隔离 HTTP + Mock 控制竞态**，只有「计划绑定的有限真实更新 smoke」可以算 R，
  未真实执行的 U 行标 **L**。⇒ 设计上就要求"同一张矩阵里既有 live 行又有 local_mock 行"。
  另外 U07/U08/U09 根本没有 `question`（`expected_kind: undefined`，见 `fixtures/acceptance/questions.json`），
  无法作为 `CaseSpec` 走 p2-run；U10 要求同一 `client_request_id` 三次不同载荷，而 runner 的 id 是
  `uuid5(run_id, case_id, turn)`（`p2_runner.py:294-295`）——**同一 run 内不可能重复同一 id**。
- **最小方案（不改冻结门槛）**：
  1. `P2CaseScore`/`P2PublicScorecard` 增加`evidence_basis`（`live_run` / `product_mutation_test`）并**逐题必填**；
  2. `score_public_suites(..., allow_mixed_basis=True)` 只在「每条都声明 basis + 每个 suite 内 basis 一致」时放行，
     scorecard 输出 `bases: {suite: basis}`；缺 basis → `evidence_basis_missing`（unknown，不放行）；
  3. U01–U06/U10 的 verdict 复用 `backend/tests/acceptance/test_t09_mutation.py`（现已存在，逐 case 有断言），
     由一个小导出器把 pytest 结果写成 `{case_id: pass/fail}`（不作为"真实模型能力"计）；
  4. U07/U08/U09 同样只从该测试取 verdict，报告里标 `L`，**不**宣称 R 覆盖。
- **禁止**：把 local_mock 标成 live（`_execution_mark` 已拒）；删掉 `execution_mode_mixed` 检查；
  把 U07–U09 塞进 p2-run 造"真实"行。
- **验证**：`pytest backend/tests/evaluation/test_p2_scoring.py -q -k execution`（混用仍报错的那条改为"混用且有 basis 才放行"）
  + 新用例：缺 basis→unknown；同 suite 混 basis→报错。

### F5【BLOCKER】run 产物 → 评分/门禁的驱动不存在

- **证明**：`score_public_case`/`score_public_suites`/`aggregate_holdout`/`build_gate_run` 在 `backend/src` 里
  **只有定义、没有任何调用者**（调用者全在 `backend/tests/**`）。即：跑完 `p2-run` 只得到
  `cases.jsonl/summary/gate/run_result`，没有任何东西把它变成 `P2PublicScorecard` 或 `P2GateDecision`。
- **最小方案**：新增 `evaluation/p2_score_run.py`：
  `score_run(run_dir, *, cases_path, document_codes, execution_mode, real_calls) -> (P2PublicScorecard, [P2CaseScore])`，
  逐 case 调 `score_public_case`（`p2_scoring.py:757`）+ `_resolved_without_index`，缺 case 行 → `not_executed`
  （不补、不猜）；再新增 `decide_run(...)` 调 `evaluate_p2_gate`（`p2_scoring.py:1650`）写 `p2_decision.json`。
  再给 CLI 加 `p2-score --run-dir … --cases … --out …`（只读 run 产物，不重跑产品）。
- **禁止**：在驱动里"补"缺失 case 或把 error 当 fail/pass；改 `score_public_case` 的判定。

### F6 gate 判定链能否产出 `release_ready`

- **结论：不能，且这是设计如此**。`gate_v0_3` 的 `status=unapproved`（`docs/evaluation/gate_v0_3.json:213`），
  `evaluate_p2_gate` 对未审批配置一律加 `gate_config_unapproved`（`p2_scoring.py:1688-1696`，unknown/exit 3），
  `P2GateDecision.release_allowed` 恒 False。T207 能产出的是：`execution_exit_code`（run 是否跑完）+
  `quality_exit_code`（分母/证据/硬门禁）+ 逐项 blocks。**放行权在 T209（主人批准阈值）**。
- 因此 T207 的收口语必须写成「执行完成 + 观测值」，不得写"质量达标/放行"。gate 行里的
  `citation_evidence_complete`/`trace_integrity` 各自独立，不互相折算。

### F7 多 run 共用一张计划/一扇门的计数口径

- **证明**：`p2_runner.py:835-840`：`gate_reserved = _gate_reservation_count(gate)`（gate 的**累计**计数）
  与 `attempt_audit.expected_reservations`（**本 run** 期望）比较，不等即 `attempt_accounting_mismatch` 停。
  ⇒ 若为了节省授权次数在同一进程里用同一扇门跑 R1/R2/R3，第 2 个 run 必定判不一致。
  另有 `preflight_p2` 的 `plan.total_requests ≤ max_requests - reservation_count`（`p2_authorization.py:365-372`），
  使「同一张计划反复授权」在 1000 硬顶下只能发生在前 153 次请求内。
- **最小方案**：给 `P2Gate` 加 `run_baseline()` 快照（open 时记 reservation 计数），`_gate_reservation_count` 改成
  「累计 − run 起点」；或（更省事、推荐）**每次 run 新开一扇门**并按 §6 的计划 `max_requests` 预留重授权余量。
- **禁止**：放宽 `attempt_accounting_mismatch`；用同一扇门跑两次而不改口径。

---

## G 若提 `HARD_MAX_REQUESTS`：改动清单（只给 diff 方案，本包未改）

| # | 文件:位置 | 现值 | 拟改 | 说明 |
|---|---|---|---|---|
| G1 | `backend/src/mktkb/evaluation/p2_contracts.py:87` | `HARD_MAX_REQUESTS = 1000` | `1600` | 附注释：实算 1,281 + 20% 余量（cost §6） |
| G2 | `backend/src/mktkb/live_authorization.py:94` | `MAX_GO_REQUESTS = 1000` | `1600` | 必须同步：`tests/evaluation/test_p2_authorization.py:481` 断言两者相等 |
| G3 | `docs/evaluation/p2-run-contract-v0_1.md` §1.3（第 14–15 行） | 「硬顶 `HARD_MAX_REQUESTS = 1000`…T201 不提高该值」 | 「硬顶 1600（2026-11-11 主人预授权 ≤2000 内由经理落盘）」+ 依据与到值即停 | 契约文本须与常量逐值一致 |
| G4 | 同上 §3 表格 `max_requests` 行（第 56 行） | 「≤ 1000」 | 「≤ 1600（= `HARD_MAX_REQUESTS`）」 | |
| G5 | `docs/reports/OBS-EVAL/P2/T207/PM/T207-cost-and-quota.md` §6 | — | 追加「已落盘」记录（经理填） | 治理变更须有落盘记录 |

- **跨范围影响（必须写进记录）**：`MAX_GO_REQUESTS` 同时是 **P1 live_authorization** 的上限
  （`live_authorization.py:160/200/567/710`）。把它提到 1600 会让 P1 的**天花板**也变成 1600，
  但 P1 已签 GO 里的 `max_requests` 仍是它自己的硬约束（引擎/闸门取 `min`），所以不构成对 P1 的追加授权；
  只是"借用同一个常量"的副作用。若不接受这点，替代方案是**拆成两个常量并改 G2 的测试不变式**——
  那会削弱「P2 与 P1 用同一只账本/同一个请求硬顶」这条不变量，**不建议**。
- **到值即停**：累计突破 1600 时 `request_limit` 在任何发送前拒绝；任一计划自身 `max_requests` 是更早的闸。
