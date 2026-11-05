# T006a · 门禁硬层（8 项）+ 退出码 — report.md

## 1. 完成内容

- 新增 `backend/src/mktkb/evaluation/gate.py`：`GateConfig` / `load_gate_config` / `GateResult` / `evaluate_gate`；
  8 项硬门禁按 case 条件适用（not_applicable / unknown / fail），退出码 0/1/3/4，`2` 只留常量无触发路径；
  无 waiver API；trace 只读（`mode=ro`，不信任内容）。
- 新增 `docs/evaluation/gate_v0_1.json`：8 项硬门禁 ID、`min_sample`（b0=32 / badcase=10）、15 个指标的 name/group/direction + 空阈值占位；`status=unapproved`，无绝对阈值。
- 新增 `backend/tests/evaluation/test_gate.py`：72 tests（触发矩阵、退出码矩阵、trace 形态矩阵、gold 形态、配置校验、豁免缺席）。
- 边界：只新增 3 文件 + 本报告 + 4 份证据；未改 `evaluation/*.py`（dataset/gold/scorers/runner/corpus）、
  `observability/**`、conftest、既有断言；无新依赖；零真实模型/OCR/embedding/rerank；未读 `.env`。

## 2. §5 逐条自证

1. **8 项可达**：`test_gate.py:436` 参数化 8 项，逐项断言 `exit_code=1` + 命中 ID + `case_id/check_id/evidence`
   + 其余门禁不误伤；样本 `_hard_failure_inputs:375`。
2. **trace 契约**：`:884` 缺 Span、`:899` reason-aware、`:927` reason 缺省仍要 recall/fuse、`:950` replayed 跳过
   path/outcome+Span、`:965/:989` replayed 仍校 JSON/版本、`:1013` 非法 JSON、`:1029` schema、`:1045` 条件 Span、
   `:1089` legacy 表；实现 `gate.py:1363` / `:1341`。
3. **不依赖内核**：`:1312` 直接构造 `RunManifest(mode="live")` → 4、`:1343` 大小写不敏感；实现 `gate.py:1508`。
4. **退出码**：`:525`(0)、矩阵(1)、`:1217`(3)、`:1312`(4)；`:549` 断言 8 类失败样本都不返回 2、`:1414` 无 waiver；
   优先级 4 → 3(数据/配置) → 1 → 3(unknown) → 0。
5. **PM 口径**：`:1227` min_sample 用 `scored_count`、`:757` `value_no_fabricated` 不参与、`:803/:831`
   citation 要 unit 级且不看 `source_hit`、`:589` security_leak 按解析 unit 映射、`:1184/:1193` record_code → unknown。
6. **测试与回归**：见 §3；`gate_v0_1.json` 可解析且无绝对阈值（`:457`）。

## 3. 实际运行结果

- 包 `pytest ... test_gate.py -q` → **72 passed**（1.63s）；目录 `backend/tests/evaluation -q` → **196 passed**（9.39s）。
- 全量 `pytest backend/tests -q` → **1469 passed, 0 failed/0 error**（393.49s = 6:33；1397 + 72）。
- 真实链路（`02-gate-demo.txt`，run 在 `%TEMP%`）：b0/badcase × local/replay 四个 run 全 **exit 0**；b0 scored
  32/32、badcase 13/10；无硬失败；not_applicable = security_leak/cross_entity/stale_bypass/conflict_not_rejected
  （两侧）+ pagination_contract(b0) / exact_value_contract(badcase)。
- 8 项触发矩阵（构造样本 → 命中 ID → exit 1；证据 `03-trigger-matrix.txt`）：

| 门禁 | 构造样本 | 命中 check_id | exit |
| --- | --- | --- | --- |
| security_leak | forbidden_values 命中回答；forbidden_sources 命中引用（doc / unit_key / locator） | forbidden_value、forbidden_source_citation | 1 |
| cross_entity | 检索项 `hard_filter_violation=cross_entity` | retrieved_hard_filter_violation | 1 |
| stale_bypass | 检索项 `hard_filter_violation=stale` | retrieved_hard_filter_violation | 1 |
| conflict_not_rejected | `expected_kind=conflict` + outcome=answer | conflict_not_rejected | 1 |
| exact_value_contract | `stratum=exact` + 回答缺期望值 | exact_value_miss | 1 |
| pagination_contract | 期望 total=2、实际 total=1 | pagination_contract_violation | 1 |
| citation_required | 无引用 / 引用无 unit_ids / 引用不在 evidence | citation_missing、citation_not_unit_level、citation_not_in_evidence | 1 |
| trace_integrity | 无 trace / 缺 Span / 非法 JSON / 版本漂移 / path 缺失 | trace_missing、required_spans_missing、json_invalid、version_binding、path_outcome_missing | 1 |

- commit `p0/T006a gate hard layer`（单 commit；最终 sha 见 `git log -1 --format=%h`；stat 见 `04-full-regression.txt` 末尾）。

## 4. 偏离与未做

- 质量层未做（T006b）：无 `calibrate_gate` / `GateProposal` / waiver / `max_regression_pp`；`baseline` 被忽略并记
  warning；质量指标只作配置骨架，不返回 2。
- **缺字段 → unknown(3)**：`forbidden_ref_unresolved`、`record_code_only_gold`、`record_code_empty_locator`、
  `min_sample_missing` / `not_met`、`outcome_missing`、`mode_invalid`、`dataset_unreadable` / `dataset_row_mismatch` /
  `row_not_object`、`trace_store_unreadable`、`case_error`。
- **not_applicable**：数据集无 forbidden 引用 / 无 entity filters / 无 as_of / 无 conflict case / 无分页期望 → 不改
  退出码；`cross_entity` / `stale_bypass` 的 case 级字段在 v0.1 契约中不存在，只能按上游 `hard_filter_violation`
  判违规（"跨用户来源"未覆盖）。
- `exact_value_contract` 只作用于 `stratum=exact`（b0 24 题）：Q25/Q26 属 text stratum，其 value_hit 未命中是质量
  指标；若当硬门禁，冻结干净集永远 exit 1，违反 P0 验收"干净集 exit 0"。
- `min_sample` 分母用 `scored_count`（排除 OCR/error）：b0=32；badcase 实测 **13**（含 N10/N12/N13 三条空 gold），配置取 T005 检索分母 10 → 13 ≥ 10 通过。
- `exact_value_contract` / `pagination_contract` 从数据集 + outcome **重算**，不读 run 自报 checks（T005 LOW-3；
  分页复用 `scorers._pagination_checks` 保证口径一致）。未做：diff/baseline（T007）、CLI（T008）、live（禁止）。

## 5. 风险与遗留

- badcase `min_sample=10` 与 `summary.scored_count=13` 有 3 条空 gold 的口径差；T006b 需确认质量指标分母。
- `cross_entity` / `stale_bypass` 的"有 case 却缺字段 → 3"路径当前不可达；P1 新增 entity/as_of 时需补 case 级判定。
- `security_leak` 的敏感模式依赖配置 `sensitive_patterns`（初版空）；跨用户来源未覆盖；gate 只信 `run.cases` +
  trace + 数据集，`run_id`/dataset/index 绑定漂移会 fail（trace 校验）；已知 flake
  `test_g08_short_budget_cancels_inflight_model_call` 本次全量未触发。

### 交接摘要

- commit `p0/T006a gate hard layer`（sha 见 `git log -1 --format=%h`；未 push）。
- 交付：`gate.py`、`gate_v0_1.json`、`test_gate.py`、本报告、`evidence/T006a/`（4 份）。
- 触发矩阵见 §3（8 项各一条）；exit 0 = 四个干净 run；3 = 样本不足/数据不可用/无法解析；4 = `mode=live`。
- 通过数：包 72、目录 196、全量 1469（0 failed / 0 error，6:33）。
- 偏离：质量层/校准/waiver/max_regression_pp 属 T006b；风险：badcase min_sample 口径差 3；
  cross_entity/stale 仅靠上游违规信号；敏感模式未配置。
