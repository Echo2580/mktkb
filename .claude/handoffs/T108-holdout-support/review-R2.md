模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T108 R2 独立复验（R1 返工后）

- 对象：`d3b5745`（父 `b769a28`），分支 `p1/fix-retrieval`；复跑时 HEAD `3a422e9`（PM 簿记）。
- 复跑前：`git status --short` 为空；`git show --stat d3b5745` 恰 5 文件；
  `git diff b769a28..d3b5745 -- backend/src/mktkb/evaluation/{dataset,gate}.py` 为空；
  `git rev-list --count b769a28..d3b5745 = 1`。
- 方法：F1 真实 labels 受限运行（默认 + details，`%TEMP%` 新目录，扫描后删除）、B2/B3 合成对抗、
  不变项抽查、全量回归。探针/原始结果：`docs/reports/OBS-EVAL/P1/evidence/verify/T108-R2/`
  （`01-verdict.md`、`02-probe.py`、`03-probe-results.md`、`04-test-eval-runs.md`）。
- 真实题干/答案只作为运行时输入，未写入本文件或证据；未读 `.env`；未改交付物；
  未 commit/push/切分支/stash/reset。

## 总判定：PASS

上轮唯一阻塞 **F1 已收口**；R1 新增 **B2/B3 均按返工单口径拒绝**；上轮六项 PASS 抽查无回归；
全量 1776 passed / 0 failed / 0 error。残余均为非阻塞观察（report 超预算、B2 更严、
3 个拒答题修复后为 fail 的质量问题）。

## 1. F1（上轮阻塞）真实 holdout 可评分 — PASS

- 默认 run（真实 labels + 仓库导出 questions，`--out %TEMP%\T108-R2\real-agg-*`）：
  exit 0；`case_count=30`；`status_counts={fail:23, pass:7}`；**`error_count=0`**；
  `scored_count=30`；`metrics_scope.cases_in_denominator=30`、`excluded_error_count=0`；
  产物仅 `run_manifest.json`、`summary.json`；`holdout={aggregate_only:true,
  details_written:false, traces_persisted:false}`（`03` §A）。
- details run（`--allow-holdout-details`，另一新目录）：exit 0、30 行、`error_count=0`、分母 30；
  原 3 个负样例形态（`should_refuse=true` + `gold.unit_ids=[]` + `relevant_unit_ids` 非空）
  **3/3 现为 `fail`、`error=None` 3/3、`refusal_expected` 非 skipped 3/3**——不再报
  `gold_unit_ids_missing`，已按既有拒答/kind/检索口径评分（`03` §B）。
- 拒答指标：`should_refuse=6`、`refused=6`、TP/FP/FN/TN=`3/3/3/21`；复算
  `refusal_recall=0.5`、`refusal_precision=0.5`、`false_refusal_rate=0.125`，与 summary
  逐项相等；指标有分母、在 `[0,1]`，口径合理（`03` §B）。
- 防泄漏：默认产物对真实 questions/labels 的 `question/turn/case_id/reference_answer` 命中均 0；
  `expected_values` 仅 4 个 **<4 字符**子串命中（`>=4` 字符命中 0），不构成题目/答案泄漏；
  details 的 audit 与 manifest/summary 同样 0/0/0/0（`03` §A/§B）。
- 实现核对：`runner.py:1382-1403` 仅在 `case.expected_sources` 非空时要求 `gold.unit_ids`
  （`:1391`），随后仍要求 `relevant_unit_ids`；`gold.py` 的 `unit_ids` 只来自
  `expected_sources`，与负样例口径一致。补测 `test_holdout_suite.py:750`（负样例可评分）、
  `:775`（`expected_sources` 非空但 `unit_ids` 空仍 error）。
- 观察（非阻塞）：3 题由 error 变 **fail**（不是 pass），`refusal_recall=0.5`；这是 holdout
  质量/模型行为，属 T110/T112 口径；T108 只负责“可评分 + 防污染”。

## 2. B2 out 目录防污染 — PASS

- 实现：`runner.py:491-519` 的 `_assert_holdout_out_dir_fresh`，在 `_run_local_holdout`
  读 labels / 建索引之前调用（`runner.py:543`）；CLI 把 `HoldoutError/ValueError` 映射 exit 3
  （`cli.py:581-583`）。选择“拒绝”而非“写前清理”。
- 合成实测（`02-probe.py` §B2；快照=文件 sha256）：含旧 `cases.jsonl` 跑默认、含旧
  `holdout_audit.json` 跑 details（CLI + runner）、含旧 `traces.sqlite3` 跑默认、含无关文件
  `keep.txt` 的非空目录——全部 **exit 3 / `HoldoutError`**，stderr 明确（“拒绝复用…”/“非空
  out 目录…”），无 traceback，旧文件 **逐字节不变**，无 manifest/summary/audit/cases/trace 新产物。
- 已存在的**空**目录可跑，产物严格 `run_manifest.json` + `summary.json`（`03` §C）。
- 观察（非阻塞）：实现比返工单最低要求更严——拒绝任意非空目录（含只有旧 manifest/summary 的
  目录）；report R1 已披露该取舍，换新目录即可。

## 3. B3 holdout 拒绝 `--from-run` — PASS

- `runner.py:339-343` 在 holdout 分支显式 `raise ValueError`，不再静默忽略。
- runner：`run_suite(..., replay_from=...)` → `ValueError` 含 `replay_from`，out 未创建；
  CLI：`--from-run <任意>` → exit 3、stderr 含 `replay_from`、无 traceback、out 不存在；
  `--mode replay` 仍先命中“只允许 mode='local'”（`03` §D）。
- 补测 `test_holdout_suite.py:873`、`:891`（runner/CLI 两条）。

## 4. 不变项抽查 — PASS

上轮 §1–§6 六项 PASS 不再逐项重跑；本轮抽查（`02-probe.py` §E/§F，`01-verdict.md` §4）：

- 默认聚合不泄漏：合成 3 题（唯一题干/答案标记）与真实 run 均仅两件产物，标记/case_id 命中 0。
- CI + details：`CI` / `GITHUB_ACTIONS` / `MKTKB_CI` 各自设置时 CLI 均 exit 3、stderr 点名变量、
  无 out、无 traceback；CI 下聚合 run 仍可跑（`details=false`）。
- fail-closed 抽查 4 项：缺 labels → exit 3 无 out；篡改 `--dataset`（pinned sha 不符）→ exit 3
  无 out；loader 行数 3≠30、删 `label_version` → `HoldoutError`。
- 明细审计无题干/答案：audit 键无 `question/turns/reference_answer/expected_values/case_id`；
  operator 非空、run_id/created_at 与 manifest 一致、两 sha 与 `label_version` 齐全。
- 导出 / labels：fixture 30 行、13 键、sha `a8c8aa7f…6738`、答案字段 `[]`；
  真实 labels 只算 sha（`8f713a2a…c1bf`，等于常量）；`git ls-files` 与
  `git log --all --name-only` 无 `labels.jsonl`；`fixtures/evaluation` 无 `*labels*`。

## 5. 回归 / 预算 / 形式 — PASS

- 本包 `test_holdout_suite.py` **43 passed**（61.90s）；`backend/tests/evaluation`
  **373 passed**（79.27s）；全量 `backend/tests` **1776 passed / 0 failed / 0 error**（477.53s）；
  无 flake，未触发隔离复跑。内存 ~90s 采样 5 次，峰值 **394.1 MB**（< 2 GB）（`04` §A）。
- b0/badcase 对 P0：`case_diffs=0/40`、`0/13`；gate 均 exit 3、hard `[]`（`04` §B）。
- regression 对 `17c0e63`：基线 pass4/fail3、gate exit 1 hard `['security_leak']`；
  当前 pass5/fail2、gate exit 3 hard `[]`；逐例**仅 RG006** fail/answer → pass/clarification，
  RG005/RG007 签名不变，无新 hard（`04` §C）。
- 形式：单 dev commit、5 文件均在允许路径；`dataset.py/gate.py` 零 diff；依赖零 diff；
  测试删除行仅 2 行（1 import + 1 `_run` 取值），无删断言；无 skip/xfail/skipif。
- 零真实模型/embedding/rerank/OCR：holdout local 强制 offline（`runner.py:580-585`）；
  b0/badcase/regression 走既有 offline 配置；未用 live/replay。
- 观察（非阻塞）：`report.md` 实测 **167 行** > 80 行预算；按提示词记为形式项。

## 残余 / NOT-RUN

- 残余（非阻塞）：① 3 个拒答题修复后为 fail、`refusal_recall=0.5`，拒答质量留 T110/T112；
  ② B2 拒绝任意非空目录（比最低要求更严）；③ report 167 行超 80 行预算。
- NOT-RUN：未抓包证明“零真实调用”（以代码强制 offline + 运行配置为证据）；未逐题阅读真实
  holdout 答案（防污染）；未在父提交 `b769a28` 单独跑 regression（任务只要求 `17c0e63`）；
  未检查本机之外 harness 的命令历史。

**结论：PASS。** F1 的 30/30 可评分、B2 的 out 目录拒绝、B3 的 from-run 拒绝均已实测闭环；
上轮六项防泄漏/CI/fail-closed/导出/回归/形式抽查无回归。建议进入人工审核门。
