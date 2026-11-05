# T007 · Baseline + Diff + 报告（P0 第 12 包）

> PM 任务单。基线：`p0/obs-eval` @ T006b 收口 commit（开工前 `git log --oneline -3` 确认）。
> 前置：T001–T006b 已独立验收通过。本包只做 baseline 身份/审批、run diff、Markdown/HTML 报告；不改门禁判定、不改 runner/scorer。
> 完成后由**全新上下文**的独立验收助手按本文件 §5 逐条证伪。

## 1. 目标（一句话）

实现 `baseline_id` 身份绑定与审批（必须带 `approver`+`reason` 且门禁通过）、`diff_runs`（new/fixed/still-failing + 按 stratum 的指标差）、`render_markdown`/`render_html`（单文件、内联 CSS、无 JS、硬门禁置顶），并保证跨版本 baseline 只能显式 `--compare-with` 用于分析、不可放行。

## 2. 交付物（只准写这些路径）

- 新增 `backend/src/mktkb/evaluation/baseline.py`（`baseline_id`、`approve_baseline`、`load_baseline`、`BaselineApproval`）
- 新增 `backend/src/mktkb/evaluation/report.py`（`diff_runs`、`render_markdown`、`render_html`、`RunDiff`）
- 新增 `backend/tests/evaluation/test_baseline.py`、`test_report.py`
- 证据（入库，≤4 份）：`docs/reports/OBS-EVAL/P0/evidence/T007/`
- 报告：`.claude/handoffs/T007-baseline-report/report.md`（五段，≤80 行）

## 3. 输入（只看这些）

1. 设计 §8.3（baseline 身份、首次建立、审批、禁止 copy/rename、跨版本仅分析）、§8.5（产物与 `report.html` 口径）、§7.3（版本字段）。
2. 计划 Task 6 Step 1–5。
3. 已验收代码（只读）：`evaluation/{runner,gate,scorers,dataset}.py`、`docs/evaluation/gate_v0_1.json`。
4. 真实 run 产物（只读，勿入库）：用 T005/T006a 的方式在 `%TEMP%` 重新生成 b0/badcase 的 local run，或用证据目录里已有摘要。

## 4. 允许 / 禁止

**允许**：§2 交付物；本包一个 commit；允许对 `backend/tests/evaluation/conftest.py` **追加** fixture（只增不改）。

**禁止**：
- 不改 `gate.py` 的判定/退出码语义、不改 runner/scorer/dataset/gold/corpus、不改观测内核、业务代码/API/schema、既有测试断言。
- 不提供 `baseline copy` / `baseline rename`；不得允许跨版本 baseline 放行；不得在缺 `approver`/`reason` 或门禁未通过时写 approval。
- 不新增依赖；零真实模型/OCR/embedding/rerank；不读 `.env`；不碰 `docs/evidence/**`、`var/**`、账本/GO、`evidence/verify/**`；不 push。

## 5. 验收标准（逐条可判定）

1. **baseline 身份**：`baseline_id = sha256(dataset_version + pipeline_version + mode + scope + gate_version + corpus_sha256)[:12]`（口径写入 docstring）；同输入稳定；任一字段变（尤其 `pipeline_version`）→ id 变；有测试逐字段验证。
2. **审批硬约束**：`approve_baseline` 缺 `approver` 或 `reason` → 报错；门禁结果 `exit_code != 0`（含未审批阈值导致的 3）→ 拒绝并给明确原因；通过时写 `approval.json`，含 `run_id`、`gate_result_sha256`、`dataset_version`、`pipeline_version`、`corpus_sha256`、`approver`、`reason`、`approved_at`。
3. **跨版本默认拒绝**：加载/比较不同 `pipeline_version` 的 baseline 时，无显式 `--compare-with`（API 参数 `compare_with=`）→ 抛错；显式给出时结果标 `comparison="explicit_cross_version"` 且**不得**被用作放行依据（有测试断言放行路径拒绝）。
4. **diff 完整**：`diff_runs(baseline, run)` 输出 `new_failures`/`fixed_failures`/`still_failing`（按 `case_id`）与按 stratum + 总体的指标差；门禁从 1/2/3 变为 0 等情况有明确字段；空 diff（完全相同）为全空列表而非异常。
5. **报告**：`render_markdown` 首段是硬门禁结果（置顶）；`render_html` 是**单文件**（内联 CSS、无 `<script>`、无外部 http(s)/src/href 资源、无服务依赖），内容与 markdown 同源同数据；两者都不参与门禁判定。
6. **测试与回归（提速策略 A）**：`pytest backend/tests/evaluation -q` 全绿；全量 `backend/tests` 只在提交前跑 1 次，目标 = T006b 基线 + 本包新增、0 failed/0 error；不新增依赖。

## 6. 必须实际运行的检查（输出摘要存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_baseline.py backend/tests/evaluation/test_report.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\baseline-report
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t007-full
git show --stat --oneline HEAD
```

另给真实链路（`%TEMP%`，不 commit）：同一份 b0 local run 生成 baseline（用 fixture 审批配置使门禁 exit 0）→ 改 1 个 case 的结果造 diff → 渲染 md/html 各一份，证据只留摘要（md 前 20 行、html 大小/`<script` 计数/外链计数）。

## 7. 已知边界（必须遵守）

- **阈值审批是 T009 人工门**：真实 P0 baseline 在本包**不生成**（`gate_v0_1.json` 仍是 `unapproved`，门禁 exit 3 → 审批必须被拒）。本包只证明"门禁通过时可审批、未通过时拒绝"的能力，真实 baseline 由主人批阈值后生成。
- 跨版本只分析不放行（设计 §8.3）；`max_regression_pp` 只在同 `pipeline_version` 生效。
- `report.html` 非门禁展示层（设计 §8.5），不得被 gate 读取。
- 指标分母沿用 T005/T006a 口径（`scored_count`，排除 OCR/error）。
- 既有 flake `test_g08_short_budget_cancels_inflight_model_call` 与本包无关；命中则隔离复跑并记录。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T007 baseline diff report`；只 add 本包交付物 + 报告 + 证据；不 push。

## 9. report.md 格式（≤80 行）

五段：1) 完成内容 2) §5 逐条自证（≤2 行/条）3) 实际运行结果（包/目录/全量 + commit sha + stat + baseline id 样例 + diff 摘要 + html 自检计数）4) 偏离与未做（含"真实 baseline 待 T009 审批"）5) 风险与遗留。末尾 ≤10 行交接摘要。
