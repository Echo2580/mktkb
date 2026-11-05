# T009 · 独立验收与 P0 收口（P0 第 15 包 / 人工门前置）

> PM 任务单。基线：`p0/obs-eval` @ T008b 收口 commit（开工前 `git log --oneline -5` 确认；HEAD 可能是 PM 簿记 commit，代码以最近一个 `p0/T00x` commit 为准）。
> 前置：T001–T008b 已逐包独立验收通过。本包是**全新上下文**的 P0 总验收 + 收口产物；不做新功能、不改代码。
> 完成后由 PM 汇总提交主人人工审核门（G5）；主人决策前不合并 `main`、不 push 之外的动作。

## 1. 目标（一句话）

对 `p0/obs-eval` 的 P0 全部交付做一次独立总验收：按设计 §11 七条 + 逐包验收标准复跑关键项，产出 `docs/reports/OBS-EVAL/P0/{review.md,anchors.json}` 与 `evidence/T009/`，给出可交给主人的总判定（PASS / FAIL / 有保留 PASS）与未覆盖清单。

## 2. 交付物（只准写这些路径）

- `docs/reports/OBS-EVAL/P0/review.md`（总验收报告：逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令与 `文件:行`；≤150 行）
- `docs/reports/OBS-EVAL/P0/anchors.json`（版本/哈希锚：dataset_version 与 sha256、corpus manifest sha256、pipeline_version、gate_version、8 项硬门禁 ID、T001–T008b commit 列表、测试通过数、关键文件 sha256）
- `docs/reports/OBS-EVAL/P0/evidence/T009/`（≤4 份复跑证据）
- **不写** `.claude/handoffs/**`（PM 负责 `_index.md` 与交接）

## 3. 输入（只看这些）

1. 设计 §11（P0 七条验收）、§10（兼容性），计划 `P0 验收映射`。
2. 各包 `handoff.md` §5 与 `review*.md`（T001–T008b；你的任务是**复核结论是否仍成立**，不是重做全部）。
3. `docs/reports/OBS-EVAL/P0/p0-report.md`（T008b 产物，只当线索，不当作 PASS 证据）。
4. `docs/reports/OBS-EVAL/P0/evidence/`（开发证据）与 `evidence/verify/`（各包验收证据）。

## 4. 允许 / 禁止

**允许**：§2 两文件 + 证据目录；只读整个仓库；`%TEMP%` 临时产物。

**禁止**：
- 不改任何代码/测试/配置/fixtures/`docs/evidence/**`/`var/**`/账本/GO；不 commit、不 push。
- 不改 `gate_v0_1.json` 的 `status` 或阈值（审批是主人的人工门）。
- 不引用开发 `report.md` 作为 PASS 证据；不复用其他验收者的 `review.md` 代替自己的复跑（可引用其**已复跑事实**但关键项必须自己跑）。
- 零真实模型/OCR/embedding/rerank 调用；不读 `.env`。

## 5. 验收标准（逐条可判定）

1. **七条 P0 验收逐条复跑**（设计 §11）：
   (1) 业务行为不变（golden + 既有 integration 全绿）；
   (2) 每次执行尝试可用 `trace_id` 关联完整阶段（真实 HTTP 探针或 T003d 证据复核）；
   (3) B0 40 与 Bad Case 13 可独立回归（local/replay 三件套复跑）；
   (4) 结果绑定 `dataset_version`/`index_revision`/`pipeline_version`；
   (5) 可生成 baseline、diff、JSON 报告（用 `%TEMP%` 审批配置；真实 baseline 缺失必须如实记录）；
   (6) 硬门禁失败返回非零退出码（8 项各 1 次注入）；
   (7) 零真实模型调用、零 Token 费用（provider spy=0、socket guard=0）。
2. **全量回归 1 次**：`pytest backend/tests`（约 7–12 分钟）0 failed / 0 error；不重跑旧 commit 基线全量，用"当前通过数 + 各包新增数 + 改动范围"证明无回归。
3. **契约一致性抽查**：`trace_schema_v0_1.md` 的 reason-aware 行与 gate 实现一致（抽 2–3 行）；`gate_v0_1.json` 仍 `unapproved`、阈值空；分母口径（b0 32 / badcase 10、硬门禁 32/13）在 gate 与报告一致。
4. **零越界**：`git log --oneline main..p0/obs-eval` 全部 commit 的改动路径均在 P0 允许范围（`observability/`、`evaluation/`、`tools/`、`tests/`、`docs/evaluation/`、`docs/reports/OBS-EVAL/P0/`、`.claude/handoffs/`、`fixtures/evaluation/`）；无业务 API/Body/schema/依赖清单改动。
5. **收口产物完整**：`review.md` 与 `anchors.json` 可解析、数字与实际一致；`anchors.json` 的 sha256 与实测一致。
6. **诚实呈现未覆盖**：真实 OCR/embedding/rerank/模型、live、P1 质量、阈值与 baseline 审批（主人人工门）必须列为 NOT-RUN/未覆盖，不得写成通过。

## 6. 必须实际运行的检查（输出摘要存证据目录）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git log --oneline main..p0/obs-eval
git status --short
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t009-full
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t009-eval
.\.venv\Scripts\python.exe -B tools\rag_eval.py run --suite b0 --mode local --out $env:TEMP\t009-b0
```

以 `%TEMP%` 审批配置跑 `gate`（exit 0）与未审批配置（exit 3）各一次；8 项硬门禁注入各一次（exit 1）；`mode=live` 一次（exit 4）。

## 7. 已知边界（必须遵守）

- 阈值/baseline 审批是**主人人工门**：`gate_v0_1.json` 必须保持 `unapproved`；不得替主人批。
- 质量指标在未审批下恒 `unknown`（exit 3），这是设计约束，不是缺陷；`quality=False` 的 0 只代表硬门禁。
- 各包已知非阻断遗留（`_index.md` 遗留项 1–34）逐条判断"是否仍存在"，列入 `review.md` 的 NOT-RUN/遗留节，不重复返工。
- 运行产物只写 `%TEMP%`；证据只留命令、退出码、摘要与 sha256。

## 8. 提交

**不 commit、不 push**。交付物由 PM 在收口 commit 中统一入库（`.claude/handoffs/**` 之外的文件由 PM 提交）。

## 9. review.md 格式

总判定（PASS / FAIL / 有保留 PASS）+ 七条逐条表（判定/命令或 `文件:行`）+ 全量回归结果 + 契约抽查 + 越界检查 + 未覆盖/NOT-RUN + 给主人的 ≤10 行摘要。
