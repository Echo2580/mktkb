# P2-T207-FIX-H2SCORE-R1 开发报告（三阻断闭环：内存保留正文 / 结构问题不计 pass / 多轮题面审计）

**结论**：上一轮判返工的 3 项阻断已闭环 —— B1 答案题不再结构性 0 pass（30 题合成实跑 23/30，修复前同批作答
0/30）；B2 引用 superseded/越界等结构问题的题不再计 pass；B3 泄漏审计覆盖每个回合的题面（含 <8 字）与参考答案。
执行期顺带修 N1–N5。零真实调用；未改 `p2_scoring.py`/`scorers.py`/`conversations/*`/`copy.py`/fixtures/账本/预算/GO；
未 commit。

## 1. 改动清单
- `p2_runner.py`：`P2RunLedger.scoring_cases` + `record_scoring_case`（L366/L432，**只在内存**）；`_execute` 在
  holdout 路径留存 `ProductTurn` 并用 `_scoring_case_row`（L1580）重建"公开 run 行同形"的打分行；
  `_holdout_score_marks`（L1802）用它喂 `holdout_case_scores_from_rows`；泄漏审计 `_holdout_leak_needles`（L1967）
  + 阈值 `_HOLDOUT_LEAK_MIN_NEEDLE=2`（L1964）；兜底卡 `_blocked_holdout_scorecard`（L2022）不再经过聚合器；
  `_scorecard_real_calls`（L2128）统一 `real_calls` 口径。
- `p2_score_run.py`：`HOLDOUT_STRUCTURAL_ISSUE_CODES`（L474）+ `holdout_case_scores_from_rows`（L484）把结构
  问题题从 pass 降为 error（CLI 复核路径同口径）。
- `test_p2_holdout_scorecard.py`：+9 条（B1 单变量/23 pass/对照臂、B2、B3、N1、N2、N4、公开 run）；
  `docs/evaluation/p2-dataset-v0_1.md` §10、`p2-live-binding-v0_1.md` §10.9、`T207-runbook.md` §8.4 同步口径。

## 2. B1（核心）：回答正文只在内存，且必须参与打分
- 机制：打分侧只从 `product.text` 取回答（`p2_scoring.py:504/554`），而昨天写盘的 H2 逐题行按 `include_text=False`
  收窄 → 答案题 value_hit 恒 fail。现在 `_execute` 每轮留存 `ProductTurn`，每题结束把完整观测（含
  `text`/`sources`/`evidence`，字段集与公开 `cases.jsonl` 同形）写进 `scoring_cases`；**该容器不被写盘函数读取**，
  run 目录仍只有 `holdout_aggregate.json` + `holdout_scorecard.json`。
- 单变量（01）：同一条产品观测带 text → `passed=1`；去 text → `passed=0 failed=1`。
- 规模（01）：30 题合成封存 + 会作答的 Mock 产品，23 条正确回答逐题 pass：
  `total=30 executed=30 passed=23 failed=7 errors=0`；by_stratum（passed）= paraphrase 10 / multi_turn 5 /
  stale_conflict 5 / cross_doc_security 3 / negative 0；`threshold_met=false`（23<24，读数可判断质量而非假 0）。
- 对照臂（01）：同一批产品观测，仅打分行去掉 text → `passed=0/30`，即修复前形态；`run_dir_leak_hits=0`、
  无 `cases.jsonl`/`requests.jsonl`。测试同时钉住两条（`23 pass` 与 `0 pass`），防再退化成"只测全 fail"。

## 3. B2：结构问题不计 pass，硬失败判定权写明归属
- 逐题行出现 `source_not_active`/`source_forbidden_document`/`source_outside_run`/`citation_not_unit_level` 时，
  该题 `pass → error`（已是 fail/error 的不变），并出 `holdout_hard_failure_unclassified`（unknown），evidence 带
  `codes` / `counted_as=error` / `hard_failures_owner="sealed-labels"`。
- 实测（02）：active 来源 `passed=1`；同题改成 superseded 来源 → `passed=0 errors=1 hard_failures=0` + 上述 block。
- 口径：`hard_failures` 恒 0 只表示"驱动层不代分类"，**不是**"无硬失败"；计数/类别以封存判定表（`p2-score --verdicts`）为准（§10、runbook §8.4）。

## 4. B3：泄漏审计覆盖多轮题面与短题干
- needle 取 `case.question` + **每个回合的** `turns[*].question`/`text` + `reference_answer`；阈值 2 字，1 字不扫
  （产物里只有稳定码/计数/固定说明，1 字无判别力）。
- 矩阵（02）：2 字回合题面 / 9 字回合题面 / 参考答案均命中；干净卡不误报；命中一律 `holdout_scorecard_leak`，
  产物降级为"全 error + 稳定 block"。

## 5. 非阻断（顺手）
- N1：兜底卡直接按分母构造 `P2HoldoutScorecard`（不经聚合器）；若兜底卡又被同一 needle 命中，去掉全部说明文本
  再审计一次 → 产物仍写出（02：`blocks=[holdout_scorecard_leak]`、`passed=0 errors=30`、卡内无 case_id）。
- N2：`holdout_scorecard.real_calls` 改取**实测出站尝试数**（与 `p2-score` 同口径；`network` 不可用时记 0）。
- N3：`thresholds_approved` 来源差异写进 `p2-live-binding-v0_1.md` §10.9（runner 读 gate；p2-score 硬编码 false；
  放行取更保守者）。
- N4：映射本身失败时不再叠第二条同名 unmapped block（02：计数=1）；N5：文档把"四种形态"改为"候选名按 set 去重后
  登记（通常 2–4 个键）"。

## 6. 回归与边界（03）
- `test_p2_holdout_scorecard.py` 19 passed；`test_p2_runner.py` 35 passed；9 个相关模块合计 273 passed（仓库根）。
- 零真实出站：两臂 30 题 E2E 的 `network.outbound_attempts=0`、scorecard `real_calls=0`；未读 .env/真实 H2/key。
- 账本/预算/GO 只读且 sha256/字节数与上一轮 review 记录逐值相同；无新增 skip/xfail；未 commit；未写 H2 逐题行。

## 7. 限制
- 真实 H2 未跑：`doc_code` 全集与产品 `document_name` 形态仍未在本机验证（沿用上一轮限制 1 的建议）。
- `hard_failures` 恒 0 属设计（分类权在封存方）；本包未改 `cli.py`，`p2-score` 的 `thresholds_approved` 仍硬编码 false（契约已写差异）。
