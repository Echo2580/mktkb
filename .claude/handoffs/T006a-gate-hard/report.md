# T006a · 门禁硬层（8 项）+ 退出码 — report.md

## 1. 完成内容

- 新增 `backend/src/mktkb/evaluation/gate.py`：`GateConfig` / `load_gate_config` / `GateResult` / `evaluate_gate`；
  8 项硬门禁按 case 条件适用（not_applicable / unknown / fail），退出码 0/1/3/4，`2` 只留常量无触发路径；
  无 waiver API；trace 只读（`mode=ro`，不信任内容）。
- 新增 `docs/evaluation/gate_v0_1.json`：8 项硬门禁 ID、`hard_gate_min_sample`（分母
  `evaluated_count`；b0=32 / badcase=13）、15 个指标的 name/group/direction + 空阈值占位；
  `status=unapproved`，无绝对阈值。
- 新增 `backend/tests/evaluation/test_gate.py`：80 tests（R1 追加 8 条：五项修复 + 旧配置键拒绝）。
- 边界：只新增 3 文件 + 本报告 + 7 份证据（R1 新增 `05-r1-*` 3 份）；未改 `evaluation/*.py`（dataset/gold/scorers/runner/corpus）、
  `observability/**`、conftest、既有断言；无新依赖；零真实模型/OCR/embedding/rerank；未读 `.env`。

## 2. §5 逐条自证

1. **8 项可达**：`test_gate.py:436` 参数化 8 项，逐项断言 `exit_code=1` + 命中 ID + `case_id/check_id/evidence`
   + 其余门禁不误伤；样本 `_hard_failure_inputs:375`。
2. **trace 契约**：缺 Span、reason-aware、replayed 跳过 path/outcome+Span、replayed 仍校 JSON/版本、
   非法 JSON、TraceRecord schema 漂移、条件 Span、legacy 表均有测试（`test_trace_integrity_*`）；
   R1 追加 trace store 的 `schema_meta.trace_schema_version` 漂移 → exit 1、表缺失 → unknown
   （`test_gate.py:1106`/`:1132`；实现 `gate.py:589`/`:1358-1393`）。
3. **不依赖内核**：`test_gate.py:1472` 直接构造 `RunManifest(mode="live")` → 4、`:1503` 大小写不敏感；实现 `gate.py:1685`。
4. **退出码**：`test_gate.py:535`(0)、矩阵(1)、`:1323`(3)、`:1472`(4)；`:559` 断言 8 类失败样本都不返回 2、`:1574` 无 waiver；
   优先级 4 → 3(数据/配置) → 1 → 3(unknown) → 0。
5. **PM 口径**：`test_gate.py:1358` `min_sample` 用 `evaluated_count`（b0=32 / badcase=13）、
   `:791` `value_no_fabricated` 不参与、`:850/:878` citation 要 unit 级且不看 `source_hit`、
   `:599` security_leak 按解析 unit 映射、`:1290/:1299` record_code → unknown；
   R1 追加缺 outcome/缺 kind/非 mapping 分页 → unknown（`:698`/`:917`/`:832`）。
6. **测试与回归**：见 §3；`gate_v0_1.json` 可解析且无绝对阈值（`:457`）。

## 3. 实际运行结果

- 包 `pytest ... test_gate.py -q` → **80 passed**（1.76s）；目录 `backend/tests/evaluation -q` → **204 passed**（9.08s）。
- 全量 `pytest backend/tests -q` → **1477 passed, 0 failed/0 error**（389.61s = 6:29；1469 + 8）。
- 真实链路：上一轮 `02-gate-demo.txt`（f6bb3c4）四个 run 全 **exit 0**，b0 scored 32、badcase rows/scored 13
  （`03-real-runs.txt`）。R1 未重跑真实链路；按 `evaluated_count` 口径 b0 32≥32、badcase 13≥13，分母契约不变。
  not_applicable = security_leak/cross_entity/stale_bypass/conflict_not_rejected（两侧）+
  pagination_contract(b0) / exact_value_contract(badcase)。
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
| trace_integrity | 无 trace / 缺 Span / 非法 JSON / TraceRecord 版本漂移 / schema_meta 版本漂移 / path 缺失 | trace_missing、required_spans_missing、json_invalid、schema_version_mismatch、version_binding、store_schema_version_mismatch、path_outcome_missing | 1 |

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
- `min_sample` 分母用 `evaluated_count`（`status ∈ {pass,fail}` 且非 OCR/error）：b0=32、badcase=13
  （含 N10/N12/N13 三条空 gold 的 kind/拒答校验）；配置字段 `hard_gate_min_sample`。T006b 检索质量
  分母 = 有 gold 的 badcase 10，不得复用硬门禁 13。
- `exact_value_contract` / `pagination_contract` 从数据集 + outcome **重算**，不读 run 自报 checks（T005 LOW-3；
  分页复用 `scorers._pagination_checks` 保证口径一致）。未做：diff/baseline（T007）、CLI（T008）、live（禁止）。

## 5. 风险与遗留

- R1 已把硬门禁分母固定为 `evaluated_count`（badcase 13），质量分母（检索 10 / 拒答适用样本）仍属
  T006b；两套口径不得混用。R1 未重跑真实链路：T005 产物的 trace store 由 `TraceRepository` 建表，
  含 `schema_meta`；若历史产物缺该表，R1 后 trace_integrity 会 unknown(3)（fail closed，符合要求）。
- `cross_entity` / `stale_bypass` 的"有 case 却缺字段 → 3"路径当前不可达；P1 新增 entity/as_of 时需补 case 级判定。
- `security_leak` 的敏感模式依赖配置 `sensitive_patterns`（初版空）；跨用户来源未覆盖；gate 只信 `run.cases` +
  trace + 数据集，`run_id`/dataset/index 绑定漂移会 fail（trace 校验）；已知 flake
  `test_g08_short_budget_cancels_inflight_model_call` 本次全量未触发。

## 6. R1 修复自证（2026-11-05，返工单 R1）

- **HIGH-1 security_leak 缺 outcome → unknown(3)**：`gate.py:869-893`（有 forbidden 引用/敏感模式且
  `outcome is None` → `outcome_missing`，不再当空文本）；`test_gate.py:698`；probe
  `pm.security_missing_outcome_unknown` PASS（`05-r1-probe-rerun.txt`）。
- **HIGH-2 citation_required 缺 kind → unknown(3)**：`gate.py:1257-1274`（期望 answer 且 `kind` 空 →
  `outcome_kind_missing`，不再按非作答跳过）；`test_gate.py:917`；probe PASS。
- **HIGH-3 schema_meta 版本漂移 → exit 1**：`gate.py:589` 读 `schema_meta.trace_schema_version`，
  `gate.py:1358-1393` 不一致 → `store_schema_version_mismatch` 硬失败、表/键缺失或不可读 →
  `trace_store_unreadable` unknown(3)；`test_gate.py:1106`/`:1132`；probe
  `trace.store_schema_meta_mismatch` PASS。
  - **两层区分**：`TraceRecord.trace_schema_version`（每行，`schema_version_mismatch`）与
    `schema_meta.trace_schema_version`（库级，`store_schema_version_mismatch`）分别校验；上一轮
    §3 的"版本漂移"只覆盖了前者。
- **MEDIUM-1 evaluated_count 口径 + b0=32/badcase=13**：`gate.py:679` 定义（`status ∈ {pass,fail}`、
  非 `skipped_requires_ocr`、非 error），`:1682` 计数；`gate_v0_1.json:15-18` 字段改名
  `hard_gate_min_sample`，badcase=13；`test_gate.py:1358`（OCR/error 排除）、`:1377`（13 含空 gold；
  检索分母 10 仅作对照，归 T006b）。probe 的 `config.min_sample` 与 `pm.badcase_denominator_10_not_13`
  仍写死旧值 10，属过期断言（`05-r1-probe-rerun.txt` 头注），不是实现失败。
- **MEDIUM-2 pagination 非 mapping → unknown(3)**：`gate.py:1142-1172` 显式类型检查 →
  `pagination_invalid`，不再 `dict(...)` 抛 `ValueError`；`test_gate.py:832`；probe
  `pm.pagination_malformed_fail_closed` PASS，无未捕获异常。
- **测试与全量**：包 80 passed（1.76s）、目录 204 passed（9.08s）、全量 1477 passed（389.61s），
  0 failed / 0 error；证据 `05-r1-tests.txt`、`05-r1-targeted-tests.txt`。

### 交接摘要

- commit `p0/T006a gate hard layer R1`（sha 见 `git log -1 --format=%h`；未 push）。
- 交付：`gate.py`、`gate_v0_1.json`、`test_gate.py`、本报告、`evidence/T006a/`（7 份，R1 新增 3 份）。
- 触发矩阵见 §3（8 项各一条）；exit 0 = 四个干净 run；3 = 样本不足/数据不可用/无法解析；4 = `mode=live`。
- 通过数：包 80、目录 204、全量 1477（0 failed / 0 error，6:29）。
- R1：5 项 fail-open/口径已修（HIGH-1/2/3、MEDIUM-1/2），各配测试；质量层/校准/waiver/max_regression_pp
  仍属 T006b；风险：cross_entity/stale 仅靠上游违规信号；敏感模式未配置。
