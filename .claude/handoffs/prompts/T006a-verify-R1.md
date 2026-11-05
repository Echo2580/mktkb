# T006a R1 定向复验提示词（subagent 版，2026-11-05）

角色：独立验收者（全新上下文）。任务 T006a **R1 定向复验**，对象 commit `90d7133`（父 `a0d6d0d`；首轮对象 `f6bb3c4`）。
第一步：读 `.claude\handoffs\T006a-gate-hard\rework-R1.md`（本轮必须满足的行为，含 PM 裁决）、上一轮 `review.md`（FAIL 项定位）、`report.md` 的「R1 修复自证」节。
第二步：只核 R1 的 5 项 + 回归；其余条款沿用上一轮 `review.md` 的 PASS（提速策略：定向复验只跑本包 + 受影响目录 + 全量 1 次）。
必须独立构造样本（不复用交付测试的 fixture）：
1. `security_leak`：case 有 `forbidden_values`、row `status=pass`、`outcome=None` → 必须 `unknown` → exit 3（不得 pass/0）。
2. `citation_required`：期望 `answer`、无 citations、`outcome.kind` 缺失 → 必须 `unknown` → 3。
3. `trace_integrity`：把 trace store 的 `schema_meta.trace_schema_version` 改为 `mktkb.trace.v9.9` → exit 1；`schema_meta` 表/键缺失或不可读 → 3；正常库仍 0。
4. `hard_gate_min_sample` 口径（PM 裁决）：分母 = `evaluated_count`（status∈{pass,fail} 且非 OCR、非 error）；b0=32、badcase=13；OCR 行与 error 行不计；空 gold 计入硬门禁、不计入检索质量分母（10 属 T006b）。核对 `gate_v0_1.json` 字段名/值与 docstring。**若你上一轮的探针仍写死 `badcase=10`，按本裁决更新探针后再跑，并在 review 说明这属口径变更而非放宽标准。**
5. `pagination` 非 mapping → 受控 `unknown`(3)，不得抛未捕获异常。
回归：8 项触发矩阵仍逐项可用；`mode=live` 仍 exit 4；`2` 仍无触发路径；`value_no_fabricated` 仍未进硬门禁；`citation_required` 仍不靠 `source_hit`。
测试（提速策略 A）：`test_gate.py` 1 次 + `backend/tests/evaluation` 1 次 + 全量 1 次（目标 = 1477 + 你补的？不必补；基线 1477，0 failed/0 error）；不重跑 `f6bb3c4` 全量。
提交边界：`git show --name-status 90d7133` 只含 rework-R1 §2 允许路径（gate.py / gate_v0_1.json / test_gate.py / report.md / evidence/T006a 的 05-r1-*）。
证据：`docs\reports\OBS-EVAL\P0\evidence\verify\T006a\` 下新增 `R1-*.txt`（≤3 份，不覆盖首轮证据；可更新你的 `probe.py`）；结论写 `.claude\handoffs\T006a-gate-hard\review-R1.md`（≤120 行）。
不改交付物、不 commit、不 push、不读 `.env`、零真实调用；临时文件只进 `%TEMP%`；串行。
回复末尾 ≤10 行：总判定 + 5 项逐条 + 回归 + 未覆盖 + 对 T006b 的最终约束。
