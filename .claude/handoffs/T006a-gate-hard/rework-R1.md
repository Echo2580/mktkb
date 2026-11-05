# T006a 返工单 R1（2026-11-05，第 2 轮）

> 触发：独立验收 `review.md` 判 **FAIL**（对象 `f6bb3c4`）。上一轮 §5.1/§5.3/§5.6 PASS，§5.2/§5.4/§5.5 FAIL。
> 本轮只修下列 5 项 + 1 项覆盖补强；**不改**已 PASS 的 8 项触发矩阵、live 判定、退出码优先级、提交边界。
> 完成后仍是单 commit（**新 commit，不 amend**）：`p0/T006a gate hard layer R1`；随后做定向复验（FAIL 项 + 受影响测试 + 全量 1 次）。

## 1. 必须修复（逐条验收）

### R1-HIGH-1 · `security_leak` 缺 outcome 时 fail-open
- 现象：case 有 `forbidden_values`，row `status=pass`、`outcome=None` → `security_leak=pass`、总 `exit=0`（`gate.py:806-808`）。
- 期望：**有 forbidden 约束但无法取得回答/引用内容 → `unknown` → `exit_code=3`**；不得把"缺失"当"空文本"。
- 证据：`evidence/verify/T006a/02-independent-probe.txt:48`（`pm.security_missing_outcome_unknown`）。

### R1-HIGH-2 · `citation_required` 缺 `outcome.kind` 时跳过
- 现象：case 期望 `answer`、无 citations，`outcome.kind` 缺失 → `citation_required=not_applicable`、总 `exit=0`（`gate.py:1140-1141`）。
- 期望：期望 answer 却拿不到 `kind`/citations → **`unknown` → 3**（无法证明"answer 无引用"时不得放行）。
- 证据：`02-independent-probe.txt:47`（`pm.missing_kind_citation_unknown_or_fail`）。

### R1-HIGH-3 · `trace_integrity` 不校验 trace store 的 `schema_meta`
- 现象：`schema_meta.trace_schema_version` 改成 `mktkb.trace.v9.9`（TraceRecord 仍 v0.1）→ gate `exit=0`；`gate.py:530-555` 只查表/列，从不读 `schema_meta`。
- 期望：读 `schema_meta.trace_schema_version`，与 `TRACE_SCHEMA_VERSION` 不一致 → **`trace_integrity` 硬失败（exit 1）**；`schema_meta` 缺失/不可读 → `unknown`（3）。依据 `docs/evaluation/trace_schema_v0_1.md:279-280`。
- 证据：`02-independent-probe.txt:46`（`trace.store_schema_meta_mismatch`）。

### R1-MEDIUM-1 · `min_sample` 分母口径（PM 裁决，按此实现并写文档）
- **定义 `evaluated_count`**：参与硬门禁评估的 case 数 = `cases.jsonl` 中 `status ∈ {pass, fail}` 且非 `skipped_requires_ocr`、非 runner `error` 的行。
- 硬门禁 `min_sample` 用 `evaluated_count`：**b0 = 32、badcase = 13**（badcase 的 N10/N12/N13 空 gold 仍参与 kind/拒答校验，计入）。
- **质量指标（T006b）另用各自分母**：检索类 = 有 gold 的 case（badcase 10）；拒答类 = 适用样本；不得混用。
- 落地：`gate_v0_1.json` 里把字段改名为 `hard_gate_min_sample`（或加 `basis: "evaluated_count"`），并在 `gate.py` docstring + 报告写清；测试断言（a）OCR 行不计入，（b）badcase 13 与 b0 32 与文档一致，（c）空 gold 行在硬门禁计数内、在检索分母外。
- 证据：`02-independent-probe.txt:50`、`03-real-runs.txt:10`、`review.md` MEDIUM-1。

### R1-MEDIUM-2 · malformed `pagination` 未捕获异常
- 现象：`outcome.pagination` 为非 mapping（如字符串）时 `gate.py:1054-1055` 的 `dict(...)` 抛 `ValueError`，不返回 3。
- 期望：**类型非 mapping → `unknown` → 3**（或按 `pagination_contract` fail，但必须是受控退出，不得抛未捕获异常）。
- 证据：`02-independent-probe.txt:49`（`pm.pagination_malformed_fail_closed`）。

### R1-LOW-1 · 自测覆盖与报告
- 为上述 5 项各补至少 1 条测试（`test_gate.py` 内追加）；报告 §3 的"schema 漂移"要明确区分 `TraceRecord` 与 `schema_meta` 两层。
- 报告需写清 `evaluated_count` 定义与 b0/badcase 实测值。

## 2. 允许 / 禁止（本轮）

- **允许改**：`backend/src/mktkb/evaluation/gate.py`、`docs/evaluation/gate_v0_1.json`、`backend/tests/evaluation/test_gate.py`、`.claude/handoffs/T006a-gate-hard/report.md`、`docs/reports/OBS-EVAL/P0/evidence/T006a/`（新增 R1 证据，不覆盖旧证据）。
- **禁止**：改其他模块/包；弱化 8 项触发矩阵；把缺字段改回 pass；引入质量层（T006b）；改既有断言使其接受 fail-open；新增依赖；push。

## 3. 复验口径（定向）

- 只核 R1-HIGH-1/2/3、R1-MEDIUM-1/2、R1-LOW-1 + 受影响测试（`test_gate.py`）+ 全量 1 次（目标 = 1469 + 新增，0 failed/error）；其余条款沿用 `review.md` 的 PASS 结论。
- 证据新增 `docs/reports/OBS-EVAL/P0/evidence/T006a/05-r1-*.txt`；旧证据保持不动。

## 4. 模板（report 追加一节即可）

```text
R1 修复自证：
- HIGH-1 security_leak 缺 outcome → unknown(3)：<命令/文件:行>
- HIGH-2 citation_required 缺 kind → unknown(3)：<...>
- HIGH-3 schema_meta 版本漂移 → exit 1：<...>
- MEDIUM-1 evaluated_count 定义 + b0=32/badcase=13：<...>
- MEDIUM-2 pagination 非 mapping → unknown(3)，无未捕获异常：<...>
- 测试与全量：<passed 数 / 耗时>
```
