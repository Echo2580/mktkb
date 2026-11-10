角色：独立验收者（全新上下文），不是开发者/PM。任务 **T108（Holdout 支持与防污染）R1 返工后的复验 R2**。证伪导向。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（review-R2.md 首行注明）。
工作目录 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；R1 交付 commit **`d3b5745`**（父 `b769a28`），工作树应 clean。
（§11A 定向复验：上轮 FAIL 项 + 受影响测试 + 全量 1 次；上轮 PASS 的六项防泄漏/CI/fail-closed 可引用旧 review，仅做抽查复验。）

## 必读
1. `.claude\handoffs\T108-holdout-support\rework-R1.md`（B1/B2/B3 判据与期望）
2. 同目录 `review.md`（上轮 F1 证据：真实 holdout 3/30 error）、`report.md`（只当线索，含 R1 段）、`handoff.md`（§0 PM 口径/§4 验收）
3. `docs\reports\OBS-EVAL\P1\evidence\verify\T108\`（上轮 01/03/04 与 02-probe.py 可参考）
4. 复跑前：`git status --short` clean；`git show --stat d3b5745` 应 5 文件；`git diff b769a28..d3b5745 -- backend/src/mktkb/evaluation/dataset.py backend/src/mktkb/evaluation/gate.py` 应为空。

## 定向复验（逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令或 `文件:行`；不引用 report 作 PASS 证据）
1. **F1（上轮阻塞）真实 holdout 可评分**：用真实 labels 路径 `docs\evidence\LOCAL-R1-20261101\P1-HOLDOUT\labels.jsonl` + 仓库导出 questions 跑 `run --suite holdout --mode local`（默认，输出到 `%TEMP%` 新目录）→ 期望 **30/30 无 `status=error`**（原先 3 个 `should_refuse=true`+`expected_sources=[]`+`relevant_units` 非空案例不再报 `gold_unit_ids_missing`）；核对指标分母=30、拒答相关指标合理；产物仍仅 manifest+summary（无逐题泄漏）。再以 `--allow-holdout-details` 到另一 `%TEMP%` 目录核 30 行、3 个原 error case 现为正常评分（可只报计数/状态，不打印题干/答案）。
2. **B2 out 目录防污染**：复用非空目录（含 `cases.jsonl`/`holdout_audit.json`/`traces.sqlite3` 任一）跑 holdout 默认/details → `HoldoutError`/CLI exit 3、不覆盖旧文件、无新产物；空目录仍可跑。用合成夹具实测。
3. **B3 from-run**：`run --suite holdout --mode local --from-run <任意>` → 明确错误/exit 3、不建 out 目录；补核 CLI 行为。
4. **不变项抽查**：默认聚合不泄漏（合成/真实各抽）；CI 三变量 + details 硬失败；fail-closed 矩阵（缺 labels/label_version/行数/分层/case_id/sha）抽 2–3 项；明细审计仍无题干/答案；导出 fixture sha `a8c8aa7f…6738` 30 行无答案；labels 未入库。
5. **回归/预算**：本包测试 1 次；`backend/tests/evaluation` 1 次；全量 `backend/tests` 1 次（0 failed/0 error；内存 <2GB 轮询；既有 flake 隔离复跑 1 次）；b0/badcase 对 P0（`case_diffs=0`、gate hard `[]`）；regression 对 `17c0e63`（仅 RG006 fail→pass、RG005/RG007 不变、无新 hard）；无 skip/xfail/删断言/新依赖；只改允许路径（5 文件：runner.py、test、report、证据 03/04）；**report 实测约 167 行 > 80 预算，记录为非阻塞观察**；单 dev commit；零真实模型调用。

## 输出与边界
- 写 `.claude\handoffs\T108-holdout-support\review-R2.md`（≤120 行；首行模型标注；含残余/NOT-RUN）。
- 证据 ≤4 份：`docs\reports\OBS-EVAL\P1\evidence\verify\T108-R2\`（建议 01-verdict.md、02-probe.py、03-probe-results.md、04-test-eval-runs.md）。
- 不改交付物；不 commit/push/切分支/stash/reset；不读 `.env`；真实题干/答案只用于受限运行，**不得写入证据/回复**；零真实模型/embedding/rerank/OCR；临时文件只放 `%TEMP%` 或 `backend\.pytest-tmp\T108-R2\`；结束回复 ≤10 行摘要。