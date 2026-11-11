# P2-T207-FIX-H2SCORE 开发报告（holdout run 内算 H2 聚合，只写聚合）

**结论**：`p2-run --visibility holdout` 现在在受限进程内用**已解封在内存里的题面** + 本次 run 的逐题/逐轮产品结果
直接算出 H2 聚合，写 `<run_dir>/holdout_scorecard.json`（与 `p2-score --visibility holdout` 同 schema，**只有计数**）。
H2 质量读数不再依赖工作区外的封存逐题行/判定表。零真实调用；未改 `p2_scoring.py`/`scorers.py`/业务代码/fixtures/
账本/GO；未 commit。

## 1. 改动清单
- `p2_runner.py`：新增 H2 聚合段（L1657-2001）——文档代号映射 `holdout_document_codes`、逐题判定
  `_holdout_score_marks`（复用 `p2_score_run.holdout_case_scores_from_rows`+`source_index_from_rows`）、聚合
  `_aggregate_marks`（`aggregate_holdout_bundle`）、泄漏审计 `_assert_holdout_scorecard_payload`、失败降级
  `_blocked_holdout_scorecard`/`_holdout_scorecard_artifact`；`_write_artifacts` holdout 分支写
  `holdout_scorecard.json`（L2318-2338；公开分支同时清该旧产物）；错误码 L129-131。
- 新增 `backend/tests/evaluation/test_p2_holdout_scorecard.py`（10 个定向测试，合成封存 30 题/36 回合）。
- `docs/evaluation/p2-dataset-v0_1.md` §10（additive）：字段/映射/阈值语义/泄漏审计/与 `p2-score` 关系；
  `T207-runbook.md` §8.3/§8.4：run 后直接读 `holdout_scorecard.json`，`p2-score --visibility holdout` 降为可选
  独立复核（需封存输入）。

## 2. 聚合口径与字段
- `card.to_dict()`：`total/executed/errors/passed/failed/min_pass/threshold_met/hard_failures/hard_failures_by_kind/
  by_stratum/thresholds_approved/blocks/release_ready/execution_mode/real_calls/run_id/config_hash`；
  `detail_export=false`；无 `case_id`/题干/答案/逐题。
- 单题评分异常 → 该题 `error` + `holdout_case_unscorable`(unknown)；未执行/error **不计 pass**；来源/安全类结构
  问题 → `holdout_hard_failure_unclassified`（硬失败类别仍由封存标注方判定，本包不代分类）。
- `thresholds_approved` 只在 gate 配置显式 `status="approved"` 时为真：gate_v0_3 现值 unapproved →
  `holdout_threshold_unapproved`(unknown)、`release_ready=false`，但 `passed/failed/errors/by_stratum` 如实可读。
- `execution_mode` 只有 `manifest.execution="live"` 才标 live，否则 `local_mock`；`real_calls` 取本轮实测出站
  （provider 计量 >0 的请求行数，非 live 恒 0）；逐题 `real_calls` 一律 0（不把 run 级调用数放大 N 倍）；
  `run_id`/`config_hash` 取本次 run 的绑定摘要（绑定未完成时 `config_hash=null`，不编造）。

## 3. 文档代号映射（确定、可审）
规范名 = `document_ref`（同槽新版本）> `name`（上传名）> 文件名；代号只取前缀 `[A-Z]NN`（`D01_`/`V03_`）。
规范名/去扩展名、文件名/去扩展名四种形态都登记，与 `p2_scoring._lookup_document_code` 的三级查找对齐；版本文件
（V03/V04/V05→D01 槽、V06→D02 槽）按 `document_ref` 归槽。同一名字两个代号 → `holdout_document_code_ambiguous`；
缺 ingest plan/无前缀 → `holdout_document_code_unmapped`；`expected_sources`+`relevant_units` 的 doc_code 全集必须
可映射，否则出同名 block（evidence 只有 `{"missing": [...], "mapped": N}`）。

## 4. 泄漏审计（写盘前，数据驱动）
用**本次解封在内存里的题面**扫聚合 JSON 文本：任一 `case_id`、长度≥8 的 `question`/`reference_answer` 命中即
`holdout_scorecard_leak`；同时拒收明细字段名（`case_id/question/text/answer/reference_answer/labels`）与 `H2-` 前缀串。
命中/评分异常 → 退化成"全 error + 稳定 block"的聚合，产物照样写出、绝不写明细。证据 `evidence/04-leak-audit.txt`：
6 个产物 × 两类 run，受限内容命中数 = 0。

## 5. 测试与证据
`.venv\Scripts\python.exe -m pytest backend/tests/evaluation/{test_p2_holdout_scorecard,test_p2_runner,test_p2_score_run,
test_p2_dataset,test_p2_live_wiring}.py -q` → **146 passed / 28s**（evidence/01-tests.txt；只跑相关测试，未跑全仓）。
- 合成封存 30 题/36 回合完整 holdout run（Mock）：`total=30, executed=30, passed=0, failed=30, errors=0`（Mock 对
  合成题一律 not_found：30 题都执行、都判 fail，不凭空 pass/error）；by_stratum = 冻结 10/5/5/5/5 且逐层自洽；
  `holdout_threshold_unapproved` 在、`release_ready=false`；`config_hash` 与 `run_manifest.config_hash` 逐值一致
  （evidence/02）。
- 首轮产品 503：`executed=0, passed=0, errors=30`、`holdout_case_error` 在（未执行不计 pass；evidence/03）。
- 合成判定（23 pass/1 fail 带 `safety`/6 error）：计数、`hard_failures_by_kind`、`by_stratum`、`holdout_below_threshold`/
  `holdout_hard_failure`/`holdout_case_error`/`holdout_threshold_unapproved` 全对；阈值未批但 23 可读。fail-closed 覆盖：
  无映射/冲突/无 ingest plan、缺题、单题评分异常、case_id 注入审计、builder 异常降级——全部按 error/unknown 记，无一条变 pass。

## 6. 限制（如实）
- **零真实调用**：只在合成封存 + Mock 产品上验证；真实 H2 的 doc_code 全集、产品回传的 `document_name` 形态未在本机
  验证（三种形态兜不住时按 `holdout_document_code_unmapped` block，不放行）。
- 逐题硬失败类别仍由封存标注方判定；`p2-score --visibility holdout` 保留为可选复核，其封存输入本包不生产；未 commit/push，
  未改 `p2_scoring.py`/`scorers.py`/`p2_live`/业务代码/fixtures/账本/GO，未新增 skip/xfail。
