# T007 Baseline + Diff + 报告 — 独立验收 review

- 对象：`6447b85`（`p0/T007 baseline diff report`，父 `eb6eeb9`）。验证时 HEAD `525aa40`（仅追加 `_index.md` 与 `T007-verify.md` 簿记）；`git diff --stat 6447b85 HEAD -- backend docs/evaluation` 为空，交付树与目标 commit 一致。
- 环境：Windows/PowerShell；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；`.\.venv\Scripts\python.exe -B`；basetemp 全在 `%TEMP%\t007-verify`；包/目录/全量各串行 1 次；零真实模型/OCR/embedding/rerank，未读 `.env`。
- **总判定：PASS（有条件）**。§5.1–§5.6 全部 PASS；无 HIGH。**MEDIUM-1**（报告 `min_sample` 提示取到 0 且 `03-diff-report.txt:91` 陈述不符）须在 T008/T009 前修正；**MEDIUM-2** 是 T008 CLI 必须规避的放行 API 风险。其余为 LOW。

## 1. §5 逐条

| 条 | 判定 | 独立复核（命令 / `文件:行` / 证据） |
| --- | --- | --- |
| §5.1 baseline 身份 | **PASS** | 独立重算 `sha256(六字段)[:12]` 与 `baseline_id()` 一致（`02-functional-probe.txt:9-19`）；六字段逐一扰动均变，`mode=live` 拒绝；同一 manifest 改 run_id/time/path 不变。真实 b0 两轮均 `c0ce2856938f`，逐字段样例与 `01-baseline-identity.txt:23-34` 完全一致（dataset `05667cb3145a`、pipeline `75b435b02b58`、mode `ca2c6bb2c80b`、scope `3edc8c9b9d0a`、gate `05570148184a`、corpus `f27b417b5f89`）。实现 `baseline.py:9-16,177-183,207-210`；测试 `test_baseline.py:235-325`；无 copy/rename API。 |
| §5.2 审批硬约束 | **PASS** | 缺 `approver` / 空 `reason` → `BaselineApprovalError` 且根目录不创建；真实干净 b0 + 默认配置 `quality=True` → `exit=3 / quality=unknown / 42 unknowns`，审批拒绝且不落 `baseline.json`/`approval.json`（`02-functional-probe.txt:20-25,64-69`）。fixture exit 0 审批写出 8 个必填字段；独立重算 `gate_result_sha256=147d94a9...` 与真实 `approval.json` 一致（`:27-28,103`）；审批写一次、不可覆盖。实现 `baseline.py:694-782`；真实拒绝信息含“阈值未审批（T009 人工门）”。 |
| §5.3 跨版本 | **PASS** | 无 `compare_with` 时 `diff_runs` 与 `load_baseline(expected=...)` 均抛 `CrossVersionBaselineError`；显式 `compare_with=<baseline_id>` → `comparison="explicit_cross_version"`、`release_allowed=False`，`require_release_baseline` 拒绝；错误 `compare_with` 也拒绝（`02-functional-probe.txt:31-35`）。实现 `baseline.py:785-851`、`report.py:452-553`；mutation "cross" 使 2 条测试翻红（`03-mutation-probe.txt:20-24`）。 |
| §5.4 diff 完整性 | **PASS** | new/fixed/still 按 `case_id`；相同两轮 → 全空列表、`empty=True`、不异常；stratum `all/exact/text` 与总体指标差正确，分母保留；cost 零样本 `unknown/0/0` 不补零；p95 无 SLA `threshold_configured=False`；门禁迁移 `1->0`、`2->0`、`3->0` 均有显式字段，真实 `0->2`；error 单列（new/resolved/persistent）。`02-functional-probe.txt:36-52,70`；实现 `report.py:306-424,452-538`；真实 new Q27 / still Q25,Q26,Q31。 |
| §5.5 报告 | **PASS**（附 MEDIUM-1） | markdown 首段固定 `## 1. 硬门禁（置顶）`，exit/失败/unknown 置顶；html 单文件、内联 `<style>`、`<script=0`、http(s)=0、`src=`/`href=`/`<link=0`，与 md 同源同数据（`02-functional-probe.txt:51-62`）；真实交付 html `16392` bytes / 37 LF → `16355` LF，计数 0/0/0/1，md `9818`/138 LF → `9680`，与 `03-diff-report.txt:60-64` 一致；gate 源码不含 `report`，渲染纯函数。implement `report.py:575-729,808-1118`。 |
| §5.6 测试/边界 | **PASS** | 独立复跑 `42 passed (0.64s)`、`275 passed (11.71s)`、`1548 passed (528.53s)`，0 failed/0 error（`01-tests-scope.txt:11-24`）；`git show --name-status 6447b85` 仅 handoff §2 允许的 9 文件；未改 gate/runner/scorer/dataset/gold/corpus/conftest/既有测试；`gate_v0_1.json` 相对父提交无 diff，仍 `status=unapproved`、`quality_layer.status=unapproved`、阈值非空计数 0（`01-tests-scope.txt:26-48`）；无新依赖。 |

## 2. 问题分级

- **MEDIUM-1 · 默认配置报告 `min_sample` 提示取到 0（报告正确性 + 证据陈述不符）**：`report.py:686-692` 先取 `dataset_sample > 0`，再按 `denominator` 最小；`cost_per_case_cny/all` 的 `dataset_sample=32` 但 `denominator=0`，于是默认配置报告输出“最小 stratum 分母 = 0（cost_per_case_cny/all）”（实际 `%TEMP%\t007-baseline-report\report-default.md:67`）。`03-diff-report.txt:91` 却写“8（Recall@10/text）”；fixture 报告 `report.md:24` 确为 8。正确做法是排除零分母/零样本指标：按默认配置全部指标最小正分母为 1（refusal_precision），按 T006b 的检索/答案口径为 8；0 绝不可作为 `min_sample` 提示。影响 T009 人工阈值选择，不影响门禁/放行；建议 `item.denominator > 0`（并加零样本 cost 用例），同时更正证据 03:91。
- **MEDIUM-2 · 有利放行路径可在“当前门禁未知”时通过（T008 CLI 风险）**：`report.py:487-494` 在 `gate=None` 且 baseline 已审批时给出 `release_allowed=True`；`require_release_baseline` `report.py:550-553` 仅拒绝 `current_exit_code` 非 None 且非 0。独立探针 `diff_runs(approved, current)` 得 `release_allowed=True / current_exit_code=None` 且 `require_release_baseline` 通过（`02-functional-probe.txt:50,110-112`；交付测试 `test_report.py:407-425` 也显式这样断言）。这与函数 docstring“当前门禁通过”不符；T008 CLI 必须始终从当前 run 计算 `gate` 并传入，否则可能无门禁放行。跨版本仍被拒绝，故不判 §5.3 FAIL。
- **LOW-1 · 证据计数笔误**：`01-baseline-identity.txt:50` 写“41 passed”，实际本包 42 项、`04-tests.txt:8` 亦为 42。
- **LOW-2 · p95 说明与 diff 状态列口径**：报告 unknown 说明称 p95 “状态 unknown”（`report.py:722-727`；`report-default.md:186`），但 diff 表该行 `status=regressed/improved`（`report-default.md:145,160,175`）。应明确“unknown”指质量/门禁状态，diff 列只是方向变化，不能当阈值判定；T008 不要据 `MetricDelta.status` 放行。

## 3. 未覆盖 / NOT-RUN

- 零真实模型/OCR/embedding/rerank；无 live；未读 `.env`；未生成/审批真实 P0 baseline（T009 人工门，仓库内确无 approved baseline）。
- 未重跑 T005/T006 旧基线；未运行业务 CLI（T008 范围）；未在浏览器中打开 html（仅静态字节/计数/同源自检）。
- 未重建真实 badcase 链路（b0 真实链路已用 `%TEMP%` 只读产物复核）；未测并发、p95 机器噪声、异常中断落盘。
- 未修改 `evidence/T007/`；未改交付物；未 commit/push。

## 4. 对 T008a / T008b 的输入约束

1. **可依赖的公开 API（均已独立验证）**：`baseline_id(source) -> str`；`save_baseline(run, root, *, gate=None) -> Baseline`；`approve_baseline(run, gate, root, *, approver, reason) -> Baseline`；`load_baseline(baseline_id, root, *, expected=None, compare_with=None) -> Baseline`；`diff_runs(baseline, run, *, comparison=None, compare_with=None, config=None, gate=None) -> RunDiff`（兼容 `(run, baseline)` 换位）；`render_markdown(diff, gate=None, *, summary=None) -> str`；`render_html(summary=None, diff=None, gate=None, *, title=None) -> str`（兼容 `(diff, gate)`）；`require_release_baseline(diff) -> None`（拒绝时抛 `CrossVersionBaselineError`）。`RunDiff` 提供 `new_failures/fixed_failures/still_failing/new_errors/resolved_errors/persistent_errors/status_changes/metric_deltas/comparison/release_allowed/release_blocked_reason/gate_exit_transition/baseline_exit_code/current_exit_code/empty`。
2. **baseline 落盘布局**：`<root>/<baseline_id>/baseline.json` + `approval.json`；无 copy/rename API，不能用另一 run 改绑同 id。CLI 应按 `baseline_id(run.manifest)` 读，并传 `expected=run.manifest` 触发完整六字段/数据集/corpus/gate 校验；跨版本只在用户显式要求时传 `compare_with=<baseline_id>`。
3. **真实 baseline 缺失时**：仓库当前无 approved 真实 P0 baseline；`load_baseline` 在文件缺失时抛 `BaselineError("baseline 不存在: ...")`，`diff_runs(None, run)` 抛 `BaselineComparabilityError`。CLI 应 fail closed（非零退出、明确“baseline 未建立/待 T009”，不自动 `save_baseline`、不伪造、不复制旧 baseline）。T009 批阈值后才可走 `approve_baseline`。
4. **审批**：CLI 必须用同一 run 现场 `evaluate_gate(..., quality=True)`，只接受 `exit_code==0`、质量层已评估、`quality.config_status=="approved"`（top-level approved）、非空 `approver`/`reason`；exit 1/2/3（含阈值未审批）/4 一律拒绝且不得写 `approval.json`；不要把用户提交的 gate JSON 当审批依据。
5. **diff/放行**：`diff_runs` 必须带当前 run 的 `gate=`，随后 `require_release_baseline`；否则 MEDIUM-2 会在“门禁未知”时给出 `release_allowed=True`。跨版本 `explicit_cross_version` 只能分析，禁止放行；当前门禁非 0 必须阻断。
6. **报告**：直接写 `render_markdown`/`render_html` 返回值（UTF-8 无 BOM）；报告不得回喂 gate。默认配置下 exit 3、42 个 `thresholds_unapproved`、cost/p95 unknown 必须原样呈现，不补零、不写成“质量通过”。`min_sample` 提示在 MEDIUM-1 修复前不可直接用于 T009；修复后应按最小非零 stratum（T006b 检索/答案 b0=8）提示。

## 5. 证据与最终状态

- 证据：`docs/reports/OBS-EVAL/P0/evidence/verify/T007/`：`01-tests-scope.txt`、`02-functional-probe.txt`（63/63 PASS + 真实产物复核）、`03-mutation-probe.txt`（4/4 mutation caught）、`probe_t007.py`；均 UTF-8 无 BOM、ASCII 文件名。探针只写 `%TEMP%`，未改仓库。
- 最终 `git status --short` 仅新增本 review 与 `verify/T007/`；`evidence/T007/`、交付物、`_index.md` 与其他包产物未改；未 commit/push。
