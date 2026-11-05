# T007 Baseline + Diff + 报告（P0 第 12 包）开发报告

> 基线：`p0/obs-eval` @ `eb6eeb9`（簿记；代码基线 `5a4c054` T006b）。本包单 commit `p0/T007 baseline diff report`（sha 见交付回执；`git log -1`）。
> 真实 P0 release baseline **未生成**：`gate_v0_1.json` 仍是 `unapproved`，T009 人工门审批阈值后才建立。

## 1. 完成内容

- `backend/src/mktkb/evaluation/baseline.py`：六字段 `baseline_id`、身份自校验、`save_baseline`、`approve_baseline`（`approver`+`reason`+门禁 `exit_code==0`+质量层已评估+`config_status=approved`）、`load_baseline`、`approval.json`、跨版本默认拒绝；无 `copy`/`rename`。
- `backend/src/mktkb/evaluation/report.py`：`diff_runs`（new/fixed/still-failing + 按 stratum/总体的指标差 + 门禁退出码迁移 + 放行资格）、`render_markdown` / `render_html`（同源、单文件、内联 CSS、无 JS/外链、硬门禁置顶）、`require_release_baseline`。
- `backend/tests/evaluation/test_baseline.py`（21 函数/25 项）、`test_report.py`（17 项）：全部合成 run + 合成 GateResult，零真实调用。
- 证据 4 份：`docs/reports/OBS-EVAL/P0/evidence/T007/01..04`；报告本文件。

## 2. §5 逐条自证（≤2 行/条）

1. **baseline 身份**：公式与拼接口径写在 `baseline.py:1-30`，实现 `baseline.py:207`；`test_baseline_id_matches_documented_formula` 用 `hashlib` 重算，`test_baseline_id_changes_when_any_field_changes` 逐字段（含 `pipeline_version`），`test_baseline_id_is_stable_for_same_identity` 验同输入稳定。真实两轮 b0（不同 run_id）→ 同为 `c0ce2856938f`；改 pipeline → `75b435b02b58`（01 证据）。
2. **审批硬约束**：`_reject_approval` `baseline.py:694`、`approve_baseline` `baseline.py:730`；缺 `approver`/`reason`、exit 1/2/3/4、`quality=None`、`quality.config_status != approved` 全部拒绝且不落盘；成功写 8 个必填字段 + `baseline_id`/`gate_exit_code`/`quality_status`（02 证据）。真实干净 b0 + 默认配置 → exit 3，审批被拒并给出"阈值未审批（T009 人工门）"。
3. **跨版本默认拒绝**：`_ensure_comparable` `baseline.py:785` / `load_baseline` `baseline.py:812` 默认抛 `CrossVersionBaselineError`；`diff_runs` `report.py:452` + `require_release_baseline` `report.py:541`。显式 `compare_with=<baseline_id>` 才返回 `comparison="explicit_cross_version"`、`release_allowed=False` 且放行函数拒绝；dataset/corpus/gate 不可比另抛 `BaselineComparabilityError`（测试 + 03 证据）。
4. **diff 完整**：`RunDiff` `report.py:151`、`diff_runs` `report.py:452`；new/fixed/still 按 `case_id`（error 单列），指标差覆盖 15 指标 × `all`/各 stratum，保留分母/样本数；完全相同 → 全空列表、`empty=True` 不异常；`baseline_exit_code`/`current_exit_code`/`gate_exit_transition` 明确 0→2、3→0 等。真实：new Q27、still Q25/Q26/Q31、value_hit(text) −0.125、cost 0/0 unknown。
5. **报告**：`render_markdown` `report.py:808`、`render_html` `report.py:970` 共用 `_report_data` `report.py:575`，首段固定"硬门禁（置顶）"；HTML 单文件 16355 bytes（LF；落盘 CRLF 16392），`<script`=0、外链(http/https/src/href)=0、`<link`=0、内联 `<style>`；gate 源码不含 report，`report.html` 不被读取。
6. **测试与回归**：42 项新测全绿；`backend/tests/evaluation` 275 passed；全量 1548 passed / 0 failed / 0 error（1506+42）；无新依赖、无真实调用、未改既有文件与测试断言。

## 3. 实际运行结果

```text
$ .\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_baseline.py backend/tests/evaluation/test_report.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\baseline-report
  -> 42 passed, 1 warning in 0.83s
$ .\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-all
  -> 275 passed, 1 warning in 13.01s
$ .\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t007-full
  -> 1548 passed, 1 warning in 550.45s (0:09:10); 0 failed / 0 error
```

- commit：`p0/T007 baseline diff report`（只 add 2 src + 2 tests + 4 证据 + 本报告；`git show --stat --oneline HEAD` 可复现）。
- baseline id 样例：`c0ce2856938f`（两轮独立 b0 local：`...56200423` / `...6177f4c2`）；逐字段扰动：dataset `05667cb3145a`、pipeline `75b435b02b58`、mode `ca2c6bb2c80b`、scope `3edc8c9b9d0a`、gate `05570148184a`、corpus `f27b417b5f89`。
- diff 摘要：comparison=`release_baseline`、release_allowed=False（current_gate_exit_2）、new=Q27、fixed=[]、still=Q25/Q26/Q31、gate `0->2`、value_hit all −0.03125 / text −0.125、cost 三 stratum 均 `unknown`（0/0，不补零）、p95 all 16→19（无 SLA 时只展示）。
- HTML 自检：16355 bytes（LF）、`<script`=0、外链=0、`<link`=0、`<!DOCTYPE html>` 开头、内联 `<style>`；md 9680 bytes/138 行。默认配置（真实 P0 状态）报告：exit 3、42 个 `thresholds_unapproved` unknown、`阈值未审批` 与 `无 SLA`/`零样本` 明示、无"质量通过"。

## 4. 偏离与未做

- **真实 baseline 待 T009**：本包只用 `%TEMP%` fixture（12/15 指标：剔除零样本 `cost_per_case_cny`、`refusal_recall`、`refusal_precision`；阈值取观测 min/max、`min_sample` 取最小分母）证明"exit 0 可审批 / exit 3 必拒"；fixture 不写回 `docs/evaluation/gate_v0_1.json`，不构成真实审批。
- 审批比"仅 exit_code==0"更严：额外要求质量层已评估（quality=False 的 0 只代表硬门禁）与 `config_status=approved`（T006b 约束 2/4）；已在 docstring/测试说明。
- `save_baseline` 对"同身份另一 run"拒绝改绑、审批只写一次（防 copy/rename 语义）；`diff_runs` 同时接受 `(baseline, run)` 与计划 Task 6 的 `(run, baseline)`，`render_html` 同时接受 `(summary, diff, gate)` 与 `(diff, gate)`。
- 未做 Task 7 CLI；未改 gate/runner/scorer/dataset/gold/corpus/观测内核/业务代码/既有测试断言/conftest。

## 5. 风险与遗留

- p95 延迟受机器负载影响明显（本轮两轮同配置 b0：16→19ms；另一次 76→51ms）。T009 若把 p95 写成绝对阈值，需要稳定环境或明确 SLA，否则会因噪声抖动。
- `cost_per_case_cny` 在离线 local 下零样本，持续 unknown；报告/diff 不补零。接入真实成本前不能作为放行指标。
- `baseline_id` 用六字段字面拼接（按 handoff 公式）；依赖字段格式稳定（mode 枚举、dataset_version 带分隔、corpus 64-hex）并按非空校验，边界碰撞仅为理论风险，已记录完整 identity 便于复核。
- 全量耗时 9:10（高于 6-7 分钟参考）由会话并行负载导致，非测试回归；已知 flake `test_g08_short_budget_cancels_inflight_model_call` 本轮未命中。

## 交接摘要（≤10 行）

- 交付：`baseline.py` / `report.py` / 42 项测试 / 4 份证据 / 本报告；单 commit，未 push。
- §5 六条均有测试与 `%TEMP%` 真实 b0 链路证据（01 identity+拒绝、02 审批 fixture、03 diff+md/html、04 测试）。
- 真实 P0 baseline 必须等 T009 审批阈值后，用同一 `approve_baseline` 路径生成；当前默认配置必然 exit 3 且被拒。
- 跨版本只能 `compare_with=` 分析；`require_release_baseline` 与 `release_allowed` 对跨版本、未审批 baseline、当前门禁失败均拒绝。
- 报告 HTML 非门禁展示层；gate 不读取，不改变退出码。

## R1 修订（2026-11-05，返工单 R1；新 commit，不 amend）

- **MEDIUM-1（`min_sample` 提示取 0）**：`report.py:693-723` 改为只取 `denominator > 0` 的指标，按指标分组各取最小非零 stratum 分母；零样本指标（所有 stratum 分母 0）不参与提示、不写 0。真实默认配置重渲染：检索/答案 = 8、拒答 = 1、运行 = 8；`cost_per_case_cny`、`refusal_recall` 被显式排除。新增 2 条测试（零样本不出 0；分组最小非零 2/1）。
- **LOW-1**：`evidence/T007/01-baseline-identity.txt:50` 41→42（原地更正并注明）。
- **LOW-2**：报告 diff 说明 + `MetricDelta`/`_delta_status` docstring 澄清 p95 等行的 `regressed/improved` 只是数值方向，不是质量/门禁状态（后者仍 unknown）。
- **证据**：新增 `evidence/T007/05-r1-min-sample.txt`（before/after、fixture 重渲染、测试计数）；03 旧证据不删，05 取代其中 03:91 的默认配置 `min_sample` 陈述。
- 验证：`test_report.py` 20 passed；`backend/tests/evaluation` 278 passed；全量 1551 passed / 0 failed / 0 error（713.90s，1548+3）。
- 未改 `baseline.py`、`diff_runs` gate 参数行为、gate/runner/scorer/dataset/观测/业务代码/既有断言；无新依赖、零真实调用、未 push。
