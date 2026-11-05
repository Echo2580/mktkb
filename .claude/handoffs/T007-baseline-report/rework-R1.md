# T007 返工单 R1（2026-11-05，第 2 轮，窄修）

> 触发：独立验收 `review.md` 判 **PASS（有条件）**，2 条 MEDIUM。本轮只修 MEDIUM-1 与证据一致性；MEDIUM-2 属 T008a 的调用约束（已写入 T008a handoff），本包不改 `diff_runs` 默认行为。
> 本轮仍单 commit（新 commit，不 amend）：`p0/T007 baseline diff report R1`；定向复验只核下列项 + 受影响测试 + 全量 1 次。

## 1. 必须修复

### R1-MEDIUM-1 · `min_sample` 提示取到 0
- 现象：默认配置下报告里 `min_sample` 提示出现 `0`（`report.py:686-692`；实测 `%TEMP%\t007-baseline-report\report-default.md:67`），而 `evidence/T007/03-diff-report.txt:91` 与 fixture 报告写 `8`。
- 期望：提示必须取**该指标最小非零分母**（如 b0 检索/答案的最小 stratum = 8；badcase 检索最小 = 2），**排除零样本指标**（`cost_per_case_cny` 分母 0 → 不给提示或标 `unknown`，不得写 0）。
- 落地：修 `report.py` 的提示选择逻辑 + 补 1 条测试（零样本指标不出 0；多 stratum 取最小非零）；更新 `evidence/T007/03-diff-report.txt` 中被证伪的 `8` 行或追加说明（不得删旧证据，追加 `05-r1-*.txt` 亦可）。

### R1-LOW-1 · 证据数字
- `evidence/T007/01-baseline-identity.txt:50` 的 "41 passed" 应为 42（若属笔误直接改；若属旧跑追加说明）。

### R1-LOW-2 · p95 diff 行状态语义
- 在报告/代码 docstring 里澄清：p95 行的 `regressed/improved` 是数值方向，不是质量/门禁状态（后者仍是 `unknown`）。

## 2. 允许 / 禁止

- **允许改**：`backend/src/mktkb/evaluation/report.py`、`backend/tests/evaluation/test_report.py`、`.claude/handoffs/T007-baseline-report/report.md`、`docs/reports/OBS-EVAL/P0/evidence/T007/`（追加 `05-r1-*`）。
- **禁止**：改 `baseline.py` 的审批/身份语义、不改 `diff_runs` 的 gate 参数行为（MEDIUM-2 由 T008a 传参解决）、不改其他模块/包/既有断言、不新增依赖、不 push。

## 3. 复验口径

`pytest backend/tests/evaluation/test_report.py` + `backend/tests/evaluation` + 全量 1 次（目标 = 1548 + 新增，0 failed/error）；其余条款沿用 `review.md` 的 PASS。
