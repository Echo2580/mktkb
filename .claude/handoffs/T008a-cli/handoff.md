# T008a · CLI 与 P0 全流程 run（P0 第 13 包）

> PM 任务单。基线：`p0/obs-eval` @ T007 收口 commit（开工前 `git log --oneline -4` 确认）。
> 前置：T001–T007 已独立验收通过。本包只做 CLI 包装与**真实全流程跑通**（Local/Replay/门禁/校准/报告），不做 P0 七条验收测试（T008b）与收口报告（T008b）。
> 完成后由**全新上下文**的独立验收助手按本文件 §5 逐条证伪。

## 1. 目标（一句话）

提供 `evaluation/cli.py` + `tools/rag_eval.py` 薄包装（`dataset build/validate`、`run`、`gate [--calibrate]`、`baseline approve/list`、`diff`、`export`），把 P0 全流程按计划 Task 7 Step 4 的命令序列真实跑通一次：b0/badcase local → replay → gate（含敏感注入 exit 1 与干净集 exit 0）→ calibrate 提案 → baseline 审批（未批阈值时必须被拒）→ 报告生成，全程零真实调用。

## 2. 交付物（只准写这些路径）

- 新增 `backend/src/mktkb/evaluation/cli.py`（argparse 子命令 + 退出码透传）
- 新增 `tools/rag_eval.py`（薄包装，`main()` 转 cli）
- 新增 `backend/tests/evaluation/test_cli.py`（子命令解析、退出码透传、错误路径；不重复 T008b 的七条验收）
- 证据（入库，≤4 份）：`docs/reports/OBS-EVAL/P0/evidence/T008a/`（命令序列 + 关键退出码 + 报告自检）
- 报告：`.claude/handoffs/T008a-cli/report.md`（五段，≤80 行）

## 3. 输入（只看这些）

1. 计划 Task 7 Step 3/4（子命令清单、命令序列、退出码透传、`--allow-holdout-details` 不存在）。
2. 设计 §8.4（退出码）、§8.5（产物清单）、§10（兼容性契约）。
3. 已验收代码（只读）：`evaluation/{dataset,runner,gate,baseline,report,corpus,scorers}.py`、`docs/evaluation/gate_v0_1.json`。
4. 数据/语料：`fixtures/evaluation/{b0,badcase}.jsonl`、`fixtures/acceptance/`、`corpus/enterprise-20261101/`。

## 4. 允许 / 禁止

**允许**：§2 交付物；本包一个 commit；允许对 `backend/tests/evaluation/conftest.py` **追加** fixture（只增不改）。

**禁止**：
- 不改任何既有 evaluation 模块/观测内核/业务代码/API/schema/既有测试断言；不新增依赖。
- 不实现/不暴露 `--allow-holdout-details`（P0 不存在）；不提供 `baseline copy/rename`。
- 不自动批准阈值、不把 `gate_v0_1.json` 改成 approved；不伪造 baseline。
- 零真实模型/OCR/embedding/rerank；不读 `.env`；不碰 `docs/evidence/**`（只读输入）、账本/GO、`evidence/verify/**`；不 push。
- 运行产物只写 `var/eval/**`（gitignore）或 `%TEMP%`，**不入库**。

## 5. 验收标准（逐条可判定）

1. **子命令齐全**：`dataset build|validate`、`run`、`gate`、`baseline approve|list`、`diff`、`export` 均可用；`python -B tools/rag_eval.py --help` 正常；未知子命令/参数 → 非 0 且不抛栈；`--allow-holdout-details` 不存在（有测试断言参数被拒）。
2. **退出码透传**：`run`/`gate`/`baseline approve`/`diff` 的进程退出码等于对应结果的 `exit_code`（0/1/2/3/4）；测试至少覆盖 0、1、3（4 由 manifest mode=live 覆盖；2 由 T006b 的质量回退覆盖或标 NOT-RUN）。
3. **全流程真实跑通**（命令与产物路径写进报告与证据）：b0 local → badcase local → b0 replay 三件套齐全；`gate --run ... --config docs/evaluation/gate_v0_1.json --calibrate` 生成 `gate_proposal.json`（不改 `gate_v0_1.json`，`status` 仍 `unapproved`）；干净集 gate exit 0（未审批质量阈值下允许 exit 3 的分支要写清——见 §7）。
4. **敏感注入 → exit 1**：用一条临时构造的敏感来源 case（写到 `%TEMP%` 的 run 副本，不改 fixtures）跑 `gate`，进程退出码 1 且 `hard_failures` 含 `security_leak`。
5. **baseline 审批纪律**：`baseline approve` 缺 `--gate`/`--approver`/`--reason` → 非 0 且明确报错；门禁未通过（exit 3）→ 拒绝且给出原因；证据中说明"真实 baseline 待 T009 主人审批阈值后建立"。
6. **测试与回归（提速策略 A）**：`pytest backend/tests/evaluation -q` 全绿；全量 `backend/tests` 只在提交前跑 1 次，目标 = T007 基线 + 本包新增、0 failed/0 error；未新增依赖、未读 `.env`、零真实调用（provider spy=0 / socket guard=0，可用既有 fixture）。

## 6. 必须实际运行的检查（输出摘要存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git rev-parse --short HEAD
.\.venv\Scripts\python.exe -B tools\rag_eval.py --help
.\.venv\Scripts\python.exe -B tools\rag_eval.py dataset validate --suite b0 --path fixtures\evaluation\b0.jsonl
.\.venv\Scripts\python.exe -B tools\rag_eval.py run --suite b0 --mode local --out var\eval\runs\p0-b0
.\.venv\Scripts\python.exe -B tools\rag_eval.py run --suite badcase --mode local --out var\eval\runs\p0-badcase
.\.venv\Scripts\python.exe -B tools\rag_eval.py run --suite b0 --mode replay --from-run var\eval\runs\p0-b0 --out var\eval\runs\p0-b0-replay
.\.venv\Scripts\python.exe -B tools\rag_eval.py gate --run var\eval\runs\p0-b0 --config docs\evaluation\gate_v0_1.json --calibrate
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\eval-all
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t008a-full
git show --stat --oneline HEAD
```

## 7. 已知边界（必须遵守）

- **T007 验收输入约束（2026-11-05，`T007-baseline-report/review.md` §4，CLI 必须照此实现）**：
  1. 可依赖 API：`baseline_id(source)`、`save_baseline(run, root, *, gate=None)`、`approve_baseline(run, gate, root, *, approver, reason)`、`load_baseline(baseline_id, root, *, expected=None, compare_with=None)`、`diff_runs(baseline, run, *, comparison=None, compare_with=None, config=None, gate=None)`、`render_markdown(diff, gate=None, *, summary=None)`、`render_html(summary=None, diff=None, gate=None, *, title=None)`、`require_release_baseline(diff)`。
  2. **`diff` 子命令必须传当前 run 的 `gate=` 并调用 `require_release_baseline`**；否则"已审批 baseline + 无 gate"会 `release_allowed=True`（T007 验收 MEDIUM-2）。门禁非 0 必须阻断放行。
  3. 真实 baseline 缺失时：`load_baseline` 抛 `BaselineError`、`diff_runs(None, run)` 抛 `BaselineComparabilityError`；CLI 必须 **fail closed**（非 0 退出 + 明确提示"baseline 未建立，待 T009"），**不得**自动 `save_baseline`、不得复制/伪造。
  4. `baseline approve` 必须用同一 run 现场 `evaluate_gate(..., quality=True)`，只接受 `exit_code==0` + 质量层已评估 + `quality.config_status=="approved"` + 非空 `approver`/`reason`；1/2/3/4 一律拒绝且不写 `approval.json`；不得把用户给的 gate JSON 当审批依据。
  5. 报告直接写 `render_markdown`/`render_html` 返回值（UTF-8 无 BOM）；默认配置 exit 3、`thresholds_unapproved`、cost/p95 unknown 必须原样呈现，不补零、不写成"质量通过"。
  6. `baseline list` 读 `<root>/<baseline_id>/baseline.json`；无 copy/rename。
- 质量阈值未审批（`gate_v0_1.json status=unapproved`）：干净集 gate 允许返回 **3**（unknown）而不是 0；全流程证据要区分"硬门禁通过（无 hard_failures）"与"质量 unknown"，**不得写成质量通过**。若为演示 exit 0 需要固定阈值，只允许用 `%TEMP%` 里的测试配置，不得改仓库配置。
- `baseline approve` 在未审批阈值下必须被拒；真实 baseline 是 T009 人工门后的事。
- 运行产物（`var/eval/**`）不入库；证据只留命令、退出码、关键摘要与 sha256。
- 不得为"跑通"改 gate/runner/baseline 判定或放宽断言。
- 既有 flake `test_g08_short_budget_cancels_inflight_model_call` 与本包无关；命中则隔离复跑并记录。

## 8. 提交

分支 `p0/obs-eval`，一个 commit：`p0/T008a eval cli`；只 add 本包交付物 + 报告 + 证据；不 push。

## 9. report.md 格式（≤80 行）

五段：1) 完成内容 2) §5 逐条自证（≤2 行/条）3) 实际运行结果（命令序列逐条退出码 + 三件套路径 + proposal 摘要 + commit sha + stat + 全量通过数）4) 偏离与未做 5) 风险与遗留。末尾 ≤10 行交接摘要。
