# T006a · 门禁硬层 R1 定向复验 review

- 对象：`90d7133`（`p0/T006a gate hard layer R1`，父 `a0d6d0d`）；分支 `p0/obs-eval`。
- 环境：Windows / PowerShell；Python 3.12.7；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；串行 pytest，basetemp 在 `%TEMP%`。
- 复验期间 PM 追加 `a8a04c0`（仅 docs/handoffs）；`git diff 90d7133..a8a04c0 -- backend docs/evaluation` 为空，代码树未变。
- **总判定：PASS（R1 定向）**。3 HIGH + 2 MEDIUM 全部修复，回归与提交边界通过；残留 3 条 LOW（不影响 fail-closed），无新 MEDIUM/HIGH。T006a 可进人工门。

## 1. R1 五项逐条

| 项 | 判定 | 独立复核（命令 / 文件:行） |
| --- | --- | --- |
| HIGH-1 `security_leak` 缺 outcome | **PASS** | 自造 `forbidden_values` + `outcome=None` → `exit=3`、`security_leak=unknown`、`check_id=outcome_missing`、无 failure；`forbidden_sources` 与内存注入 `sensitive_patterns` 两个变体同样 3。实现 `gate.py:872-893`；测试 `test_gate.py:698`；探针 `R1-probe.txt` 的 `pm.security_missing_outcome_*`（3/3）。 |
| HIGH-2 `citation_required` 缺 kind | **PASS** | 期望 answer、无 citations、`kind=None` → `exit=3`、`unknown`、`outcome_kind_missing`、无 failure（不再 `not_applicable`）。实现 `gate.py:1257-1274`；测试 `test_gate.py:917`；探针 `pm.missing_kind_citation_unknown`。 |
| HIGH-3 trace store `schema_meta` | **PASS** | 改 `schema_meta.trace_schema_version=mktkb.trace.v9.9`（TraceRecord 仍 v0.1）→ `exit=1`、唯一 hard=`trace_integrity`、`store_schema_version_mismatch`、`case_id=None`；`DROP TABLE schema_meta` 与删键 → `exit=3`、`trace_store_unreadable`；正常库 → `exit=0`。实现 `gate.py:589-612`、`:1358-1393`；测试 `:1106`/`:1132`；探针 4 项全 PASS。真实 `TraceRepository` 产物（`--real` 四 run）也全部 exit 0，见 `R1-real-runs.txt`。 |
| MEDIUM-1 `evaluated_count` 口径（PM 裁决） | **PASS** | 探针已按裁决改写：**这是口径变更，不是放宽标准**。13 行（10 有 gold + 3 条 N10/N12/N13 形态空 gold）+ 实配置 `badcase=13` → `exit=0`、`evaluated_count=13`；12 行 → `exit=3`、`min_sample_not_met`、证据 `evaluated_count=12,basis=evaluated_count`；13 行 + 2 OCR → 仍 13 且 exit 0；14 行含 1 error → 分母 13、exit 3 仅由 `case_error` 触发（无 min_sample）。b0 实测 32、badcase 实测 13，`min=13`。实现 `gate.py:679-685`、`:1682`、`:1897-1912`；配置 `gate_v0_1.json:15-18`；docstring `gate.py:29-32`、`:1673-1677`；测试 `:1334`/`:1358`/`:1377`。 |
| MEDIUM-2 malformed `pagination` | **PASS** | `pagination` 为字符串与数组两种非 mapping → 均 `exit=3`、`unknown`、`pagination_invalid`，未抛未捕获异常；实现 `gate.py:1141-1172`；测试 `:832`；探针 `pm.pagination_malformed_fail_closed` / `pm.pagination_list_fail_closed`。 |

R1-LOW-1 覆盖：5 项各≥1 测试（8 条新增，72→80），报告 §6 已区分 `TraceRecord` 与 `schema_meta` 两层并写明 `evaluated_count` 定义与 b0/badcase 实测；PASS。

## 2. 回归（沿用首轮 PASS 的 §5.1/§5.3/§5.6，本轮抽查）

- **8 项触发矩阵**：自造 8 个独立样本 → 全部 `exit=1`、命中各自 `check_id`、failure 带 `case_id/check_id/evidence`；集合 `{1}`，无 exit 2。`R1-probe.txt` 的 `gate.*` + `regression.matrix_8_exit1_no_exit2`。
- **live→4**：直接构造 `RunManifest(mode="live"/"LIVE")` → 4，全 `not_evaluated`。`exit.4_live_*`。
- **2 无触发路径**：`EXIT_QUALITY_REGRESSION=2` 仅常量，无 `return 2`；矩阵/失败样本均不产生 2。
- **`value_no_fabricated` 不进硬门禁**：构造 fail check → `exit=0`。`pm.value_no_fabricated_not_hard`。
- **`citation_required` 不靠 `source_hit`**：`source_hit=pass` 但无 citations → `exit=1` 命中 `citation_missing`。`pm.citation_not_source_hit`。
- 首轮已 PASS 的 trace reason/replayed/JSON、record_code、unresolved forbidden 等探针项本轮继续 PASS（62/62）。

## 3. 问题分级

- **LOW-1 · `GateConfig.to_dict` 键名不对称**：`gate.py:242` 仍序列化为 `min_sample`，而加载器只收 `hard_gate_min_sample`（`gate.py:317-328`）。仓库内无调用方，且加载失败是显式 `ValueError`（不是 fail-open）；但若 T006b/CLI 用 `to_dict` 持久化再加载会被拒。建议 T006b 前统一或加映射。
- **LOW-2 · `GateResult.to_dict` 未暴露 `evaluated_count`**：`gate.py:481` 只有 `scored_count`。两者同值且 docstring 已说明（`gate.py:450-472`），但下游若把 `scored_count` 误当质量分母会混淆；T006b 必须按 §5 约束使用。
- **LOW-3 · R1 证据头 provenance 过期**：`05-r1-tests.txt`/`05-r1-probe-rerun.txt` 写 “base f6bb3c4 + R1 working tree on 40b2fd1”，实际 commit 父为 `a0d6d0d`。测试数字已在本 review 于 `90d7133` 独立复现（80/204/1477），故只是标签问题。
- 首轮 `05-r1-probe-rerun.txt` 保留 2 条旧 `badcase=10` 断言的 FAIL；开发已注明属过期断言，与 PM 裁决一致。本 review 的探针已按裁决更新为 62/62 PASS，不构成实现缺陷。

## 4. 未覆盖 / NOT-RUN

- 未执行真实 live / 网络 / 真实 OCR、embedding、rerank；未读 `.env`。live 结论仍来自直接构造 manifest。
- `cross_entity`/`stale_bypass` 的 case 级 entity/as_of 字段在 v0.1 CaseSpec 不存在；只覆盖上游 `hard_filter_violation` 信号。
- `pagination_contract` 仍只覆盖自洽契约；fixtures 的 `expected_pagination` 为 null，未覆盖真实期望 total/returned 口径。
- `security_leak` 跨用户来源、生产敏感模式未覆盖；交付配置 `sensitive_patterns=[]`，探针的 pattern 是内存注入。
- `schema_meta` “不可读”只覆盖缺表/缺键/缺文件，未覆盖损坏 DB 字节；未重跑首轮 04 的变异探针（R1 已改逻辑，04 仅作历史）。
- `evaluate_gate(config=None)` 默认配置损坏时的异常映射未单独复验；本轮只验证正常配置与旧键拒绝。
- 未重跑 `f6bb3c4` 全量；全量 1477 是 `90d7133` 代码树单次。

## 5. 对 T006b 的最终约束

- 硬门禁分母固定 **`evaluated_count`**（`status∈{pass,fail}` 且非 OCR/非 error）：**b0=32、badcase=13**，配置键 `hard_gate_min_sample`；不得再用 `cases_in_denominator`/行数。检索质量分母 = badcase 有 gold 的 **10**，拒答类 = 各自适用样本；**10 与 13 不得混用**。
- `scored_count` 与 `evaluated_count` 同值；T006b 不得把 `scored_count` 当作质量分母，也不得因硬门禁 exit 0 宣称质量通过。
- T006a **无 waiver API、无 baseline 比较、exit 2 无触发路径**；`max_regression_pp` 仍为 null、`status=unapproved`。T006b 必须自建并审批 baseline，质量 waiver 只作用于质量层，不能绕过 8 项硬门禁；硬失败优先于质量结论。
- 字段守恒：`value_no_fabricated` 仅诊断；`citation_required` 必须 unit 级（`source_hit` 不足）；`security_leak` 用解析后 unit 映射，无法解析→3；`record_code`-only/空 locator→3。
- trace 依赖：T006a 现校验库级 `schema_meta.trace_schema_version`；缺表/缺键→3。T006b 若复用旧 trace store，必须先确认 `schema_meta` 存在且为 `mktkb.trace.v0.1`，否则质量结论会继承 exit 3（fail closed）。
- 配置加载只认 `hard_gate_min_sample`，旧 `min_sample` 显式拒绝；`GateConfig.to_dict` 仍输出旧键，不能直接 round-trip。

## 6. 证据与边界

- `R1-probe.txt`：独立探针 62 项，`failed=0`；含 5 项修复 + 8 项矩阵 + live/2/value/citation 回归。
- `R1-real-runs.txt`：离线 b0/badcase × local/replay，四 run 全 exit 0；b0=32、badcase=13、min=13；正常 `schema_meta` 库通过。
- `R1-tests.txt`：`test_gate.py` 80 passed（2.07s）、`backend/tests/evaluation` 204 passed（9.55s）、全量 1477 passed（408.01s，0 failed/0 error）+ `git show --name-status 90d7133` 边界。
- 首次 `test_gate.py` 因 reviewer 的 basetemp 父目录不存在在 fixture setup 中止（78 errors，无断言失败）；建目录后为表中有效结果。
- 提交边界：`90d7133` 仅 4 M（report.md / gate.py / test_gate.py / gate_v0_1.json）+ 3 A（05-r1-*），均在 rework-R1 §2 允许集；未改 conftest/其他模块。
- 验收期间仅改 `probe.py` 并新增本 review 与 3 份 `R1-*.txt`；未改交付物、未 commit/push、未读 `.env`、未动 `_index.md` 或其他包产物。`git status --short` 另见 PM 的未跟踪 `.claude/handoffs/prompts/T006b-dev.md`，非本验收创建。
