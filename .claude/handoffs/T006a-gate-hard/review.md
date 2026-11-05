# T006a · 门禁硬层（8 项）+ 退出码 — 独立验收 review

- 对象：`f6bb3c4`（`p0/T006a gate hard layer`，父 `ad615fb`）；分支 `p0/obs-eval`。
- 环境：Windows / PowerShell；Python 3.12.7；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；串行 pytest；临时目录在 `%TEMP%`。
- **总判定：FAIL**。正常样本的 8 项触发矩阵、0/1/3/4 退出码、72/196/1469 测试和 8 文件提交边界均通过；但独立探针发现 3 条 HIGH false-pass、1 条 MEDIUM 分母错误、1 条 MEDIUM 输入异常崩溃，§5.2/§5.4/§5.5 不能判 PASS。

## 1. §5 逐条判定

| 条 | 判定 | 独立复核（命令 / 文件:行） |
| --- | --- | --- |
| 5.1 8 项硬门禁可达 | **PASS** | 独立 `probe.py` 自造 8 个互不共用 fixture 的失败样本；8 项均 `exit=1`、命中正确 ID，且 failure 带 `case_id/check_id/evidence`，其余门禁未被误伤。见 `02-independent-probe.txt`；交付测试亦见 `test_gate.py:435`。 |
| 5.2 trace_integrity 契约 | **FAIL** | `reason=trace.reason`（`DOCUMENT_NOT_FOUND`/`KNOWLEDGE_CHANGED_AT_COMMIT`）、未知 reason 仍要 recall/fuse、`replayed` 跳过 path/outcome/Span、replayed 非法 JSON/版本、普通行非法 JSON、TraceRecord schema 漂移均按预期；但 **`schema_meta.trace_schema_version` 漂移仍 `exit=0`**。`gate.py:530-555` 的 `ensure_ready` 只检查 traces/spans 表及 traces 列，从未读取 `schema_meta`；`docs/evaluation/trace_schema_v0_1.md:279-280` 明确要求门禁 fail closed。证据 `02-independent-probe.txt:46`。 |
| 5.3 live 不依赖内核 | **PASS** | 直接构造 `RunResult`（`RunManifest(mode="live")`，绕过 `run_suite`）→ `exit=4`、全部 `not_evaluated`、无 hard/unknown；`LIVE` 同样 4。`gate.py:1508-1526`；`02-independent-probe.txt` 的 `exit.4_live_*`。 |
| 5.4 退出码映射完整互斥 | **FAIL** | 正常路径：clean=0、8 个硬失败=1、min_sample/record_code/corrupt dataset/error row=3、live=4；`2` 无触发路径，无 waiver API/参数，`baseline` 仅 warning。但 **缺字段并未统一 unknown→3**：见 §5.5 的 HIGH-1/HIGH-2；分页输入非对象时抛出未捕获 `ValueError`（`gate.py:1054-1055`），不是 3；badcase `min_sample` 见 MEDIUM-1。证据 `02:47-50`。 |
| 5.5 PM 裁决口径 | **FAIL** | 通过的：`value_no_fabricated` 不进硬门禁；`citation_required` 不靠 `source_hit`；`security_leak` 的 unit_ids-only 引用对 unit_key forbidden 能命中；无法解析的 forbidden 引用→3；`record_code`-only / `record_code`+空 locator→3；无该类 case→`not_applicable` 且 exit 0。失败的：`citation_required` 在 `outcome.kind` 缺失时直接跳过→exit 0；`security_leak` 在 forbidden_values 存在而 outcome 缺失时判 pass→exit 0。均违反“有 case 缺字段→unknown→3”。`gate.py:1140-1141`、`gate.py:806-808`；证据 `02:47-48`。 |
| 5.6 测试 / 回归 / 边界 | **PASS** | 独立复跑：`test_gate.py` **72 passed**（1.99s）；`backend/tests/evaluation` **196 passed**（9.48s）；全量 `backend/tests` **1469 passed, 0 failed/0 error**（389.18s，0:06:29）。`gate_v0_1.json` 可解析、`status=unapproved`、8 个 ID、`min_sample={b0:32,badcase:10}`、全部阈值占位为 null。`git show --name-status f6bb3c4` 只有 8 个 A 路径，均在 handoff §2；无 conftest/旧代码改动。见 `01-tests.txt`、`02-independent-probe.txt` 的 config 段。 |

## 2. 问题分级

- **HIGH-1 · `security_leak` 缺 outcome 时 fail-open**：case 有 `forbidden_values`，row `status=pass`、`outcome=None`；`gate.py:806-808` 把缺失当空文本，`_match_forbidden` 也没有 missing-outcome 分支，结果 `security_leak=pass`、总 `exit=0`。触发 `pm.security_missing_outcome_unknown`（`02:48`）。按 PM 裁决应为 `unknown`→3。
- **HIGH-2 · `citation_required` 缺 kind 时跳过**：case 期望 answer、无 citations，但 `outcome.kind` 缺失；`gate.py:1140-1141` 将空 kind 当非 answer，`citation_required=not_applicable`，总 `exit=0`。触发 `pm.missing_kind_citation_unknown_or_fail`（`02:47`）；无法证明“answer 无引用”，应 unknown 或 fail。
- **HIGH-3 · `trace_integrity` 不校验 store 的 `schema_meta`**：把 `schema_meta.trace_schema_version` 改成 `mktkb.trace.v9.9` 后，TraceRecord 仍为 v0.1，门禁 `exit=0`。`gate.py:530-555` 未读取该表；与 `trace_schema_v0_1.md:279-280` 冲突。触发 `trace.store_schema_meta_mismatch`（`02:46`）。
- **MEDIUM-1 · badcase 分母把空 gold 当可评分**：`gate.py:1505` 只按 `status in {pass,fail}` 计 `scored_count`；`gate.py:1720` 与配置 10 比较。构造 8 条有 gold + 3 条空 gold（N10/N12/N13 形态）→`scored_count=11`、exit 0；T005 review 的 badcase 口径是 **10**（排除 3 条空 gold，`T005-runner/review.md:22`）。报告 `report.md:61` 也承认 13/10 差异；这是 `min_sample` 的 false-pass 风险，需 PM 明确“scored_count”定义。证据 `02:50`；真实 badcase 实测 13/10（`03-real-runs.txt:10`）。
- **MEDIUM-2 · malformed pagination 崩溃而非 exit 3**：`outcome.pagination` 为非 mapping（例如字符串）时 `gate.py:1054-1055` 的 `dict(...)` 抛 `ValueError: dictionary update sequence ...`；未返回 3，违反“数据不可用 fail closed”。触发 `pm.pagination_malformed_fail_closed`（`02:49`）。
- **LOW**：`report.md` 的“schema 漂移”只验证 TraceRecord，未列出 `schema_meta`；`test_gate.py` 也没有覆盖上述三类缺字段/非 mapping。不是独立实现缺陷，但说明自测缺口。

## 3. 未覆盖 / NOT-RUN

- 未执行真实 live / 网络 / 真实 OCR、embedding、rerank；未读 `.env`。live 结论来自直接构造 RunManifest 与 gate 自身分支，不是真实调用。
- `cross_entity` / `stale_bypass` 的 case 级 entity/as_of 字段在 v0.1 CaseSpec 中不存在；只覆盖上游 `hard_filter_violation` 信号，不能声称覆盖“跨实体来源/effective 日期”语义。
- `pagination_contract` 的真实期望值：fixtures 的 `expected_pagination` 全为 null，仅覆盖自洽契约；不覆盖期望 total/returned 的真实口径。
- `security_leak` 的跨用户来源、敏感模式实际配置未覆盖；默认 `sensitive_patterns=[]`。
- 未重跑 T005 旧提交基线全量；本 review 的 1469 是 `f6bb3c4` 代码树单次全量。
- `evaluate_gate(config=None)` 在默认配置损坏时的异常映射未作为独立的 exit-code 用例验证；本次仅验证 `load_gate_config` 的 fail-closed 校验与正常配置。

## 4. 对 T006b 的输入约束

- **可用 summary 字段**：`run_manifest` 的身份字段；`summary.status_counts/scored_count/skipped_ocr_count/error_count`；`summary.metrics` 与 `metrics_scope`；`declarations`；`cases.jsonl` 的 `status/checks/metrics/outcome/gold/error`。质量层不得把 T006a 的 `exit=0` 当作质量通过。
- **分母**：b0 = **32**（40 行排除 8 OCR）；badcase 质量指标/门槛口径 = **10**（排除 N10/N12/N13 空 gold）。不得使用 `metrics_scope.cases_in_denominator` 的 40/13，也不得用当前 gate 实际显示的 `scored_count=13`。若 T006b 需要 `min_sample`，先按 `gold_units>0`（或 T005 的逐行口径）重算，并让 PM 确认。
- **baseline 不可用**：T006a 的 `baseline` 参数只记 warning，无 baseline 读取/比较；`gate_v0_1.json` 的 `max_regression_pp` 全 null、`status=unapproved`。T006b 必须自建并审批 baseline，不能复用 T006a 硬门禁的 exit 0 冒充“质量放行”；不得在硬门禁失败前返回 2。
- **硬门禁不可豁免**：无 waiver API；T006b 的质量 waiver 只能作用于质量层，不能作用于这 8 项。
- **字段守恒**：`value_no_fabricated` 仅诊断，不得进入 `exact_value_contract`/`security_leak`；`citation_required` 必须使用 unit 级 citations（`source_hit` 不足）；`security_leak` 必须用解析后的 unit 映射，无法解析→unknown；`record_code`-only / 空 locator→unknown/3。
- **T006b 前置修复**：若质量层依赖 trace，先修 `schema_meta` 校验和缺字段 fail-closed（HIGH-1/2/3）；否则 T006b 的 trace/质量结论会继承 false-pass。
- `gate_v0_1.json` 的质量阈值需在 T006b `--calibrate` 提案 + 主人审批后填写，审批前不得改 `status` 冒充 approved。

## 5. 证据与边界

- `docs/reports/OBS-EVAL/P0/evidence/verify/T006a/01-tests.txt`：72/196/1469 + commit 边界。
- `.../02-independent-probe.txt`：49 项独立检查，`failed=5`（5 项均在上文定位）。
- `.../03-real-runs.txt`：b0/badcase × local/replay 四个真实离线 run 均 exit 0；badcase 实测 13/10。
- `.../04-mutation-probes.txt`：required_spans 少一项、replayed 不跳过、min_sample=40、live 放行四种仓库外变异均使探针翻红。
- `.../probe.py`：唯一探针；自造 CaseSpec/RunManifest/RunResult/trace，不导入包内测试 helper（49 项检查，5 项失败）。
- 验收期间只新增本 review 与 `evidence/verify/T006a/`；未改交付代码/测试/conftest，未 commit/push，未读 `.env`，未动 `_index.md` 或其它包产物。`git status --short` 另见一个与本验收无关的未跟踪 `.claude/handoffs/T007-baseline-report/`，非本验收创建。
