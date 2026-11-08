# T108 R2 复验：判定与逐项结论

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

- 对象：`d3b5745`（父 `b769a28`）；分支 `p1/fix-retrieval`；HEAD `3a422e9`（PM 簿记）。
- 复跑前：`git status --short` 为空；`git show --stat d3b5745` 恰 5 文件；
  `git diff b769a28..d3b5745 -- backend/src/mktkb/evaluation/dataset.py backend/src/mktkb/evaluation/gate.py` 为空；
  `git rev-list --count b769a28..d3b5745 = 1`。
- 方法：F1 真实 labels 受限运行（默认 + details，`%TEMP%` 新目录，扫描后删除）+ B2/B3 合成对抗
  + 不变项抽查 + 全量回归。探针 `02-probe.py`，原始结果 `03-probe-results.md`、`04-test-eval-runs.md`。
- 真实题干/答案只作为运行时输入；本目录与 `review-R2.md` 只记录计数/结构/状态，不含题干、答案、
  `case_id` 原文。未读 `.env`；未改交付物；未 commit/push/切分支/stash/reset。

## 总判定：**PASS**

上轮唯一阻塞 F1 已收口；R1 新增 B2/B3 均按返工单口径拒绝；上轮六项 PASS 抽查无回归；
全量 `backend/tests` 1776 passed / 0 failed / 0 error。残余均为非阻塞观察（report 行数预算、
B2 比最低要求更严、3 个拒答题修复后为 fail 的质量问题）。

| 项 | 判定 | 关键证据 |
| --- | --- | --- |
| F1 真实 holdout 可评分 | PASS | 默认/details 均 30/30、`error_count=0`、分母 30（§1） |
| B2 out 目录防污染 | PASS | 三类旧详情 + 任意非空目录均 exit 3 / `HoldoutError`，旧文件 hash 不变（§2） |
| B3 from-run | PASS | runner `ValueError`、CLI exit 3、out 不创建（§3） |
| 不变项抽查 | PASS | 默认聚合/审计/CI/fail-closed/导出/labels 均抽查通过（§4） |
| 回归 / 预算 / 形式 | PASS | 全量 1776 passed、b0/badcase 0 diff、仅 RG006 变化（§5） |

## 1. F1 真实 holdout 可评分 — PASS

命令（cwd=仓库根；labels 只作参数，输出 `%TEMP%\T108-R2\real-*` 新目录）：

```text
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite holdout --mode local ^
  --holdout-labels docs\evidence\LOCAL-R1-20261101\P1-HOLDOUT\labels.jsonl --out %TEMP%\T108-R2\real-agg-<id>
# details 同命令 + --allow-holdout-details，另换新目录
```

- 默认 run：exit 0；`case_count=30`；`status_counts={fail:23, pass:7}`；`error_count=0`；
  `scored_count=30`；`metrics_scope.cases_in_denominator=30`、`excluded_error_count=0`；
  产物仅 `run_manifest.json`、`summary.json`；`holdout={aggregate_only:true, details_written:false,
  traces_persisted:false, metadata_mismatch_count:0, strata=10/5/5/5/5}`。
- 原 3 个 error case（details 逐行核，仅计数）：`should_refuse=true` + `gold.unit_ids=[]` +
  `relevant_unit_ids` 非空 = **3/3**；现 `status=fail` **3/3**、`error=None` **3/3**、
  `refusal_expected` 非 skipped **3/3**、`unit_ids` 空 **3/3**、`relevant_unit_ids` 非空 **3/3**。
  即 3 题不再 `gold_unit_ids_missing`，已按既有拒答/kind/检索口径评分并进入分母（27→30）。
- details run：exit 0、`cases.jsonl` 30 行、`error_count=0`、分母 30、产物含
  `cases.jsonl/holdout_audit.json/run_manifest.json/summary.json/traces.sqlite3`。
- 拒答指标：`should_refuse=6`、`refused=6`、TP/FP/FN/TN=`3/3/3/21`；
  复算 `refusal_recall=0.5`、`refusal_precision=0.5`、`false_refusal_rate=0.125`，与 summary
  逐项相等（`02-probe.py` 的 `refusal_metrics_match` 全 true）。指标在 [0,1] 且分母可解释。
- 防泄漏：默认产物对真实 questions/labels 的 `question/turn/case_id/reference_answer` 命中均 0；
  `expected_values` 仅 4 个 <4 字符子串命中（>=4 字符命中 0），不构成答案/题目泄漏。
  details 的 audit 与 manifest/summary 同样 0/0/0/0；audit `expected_values` 2 个 <4 字符、
  >=4 字符 0；audit 无 `question/turns/reference_answer/expected_values/case_id` 等键。
- 实现：`runner.py:1382-1403`（`expected_sources` 非空才要求 `unit_ids`，`refusal` 负样例走
  `relevant_unit_ids`）；补测 `test_holdout_suite.py:750`（负样例可评分）与 `:775`
  （`expected_sources` 非空但 `unit_ids` 空仍 error）。
- 观察（非阻塞）：3 题由 error 变 **fail**（不是 pass），`refusal_recall=0.5`；这是 holdout
  质量/模型行为，属 T110/T112 口径，T108 只负责“可评分 + 防污染”。

## 2. B2 out 目录防污染 — PASS

实现：`runner.py:491-519` 的 `_assert_holdout_out_dir_fresh`，在 `_run_local_holdout` 读 labels /
建索引之前调用（`runner.py:543`）；CLI 经 `ValueError/OSError` 映射 exit 3（`cli.py:581-583`）。
选择“拒绝”而非“写前清理”（report R1 §6.2 已披露）。

合成实测（`02-probe.py` §B2；目录快照按文件 sha256 前后比对）：

| 场景 | 结果 |
| --- | --- |
| 复用含旧 `cases.jsonl` 目录跑默认 | CLI exit 3、stderr 含“拒绝复用”、无 traceback、旧文件不变、无 manifest/summary |
| 复用含旧 `holdout_audit.json` 目录跑 details | CLI exit 3；runner `HoldoutError`；旧文件不变 |
| 复用含旧 `traces.sqlite3` 目录跑默认 | CLI exit 3、旧文件不变 |
| 复用仅含无关文件 `keep.txt` 的非空目录 | CLI exit 3（“非空 out 目录”）、旧文件不变 |
| 已存在的**空**目录 | 可跑；产物仅 `run_manifest.json`、`summary.json` |

- 5 类场景均“无新产物、无覆盖”；空目录路径仍可用（与真实 run 的新目录一致）。
- 观察（非阻塞）：实现比返工单最低要求更严——拒绝任意非空目录（含只有旧 manifest/summary
  的目录），换目录即可；report 已披露该取舍。

## 3. B3 holdout 拒绝 `--from-run` — PASS

- 实现：`runner.py:339-343` 在 holdout 分支显式 `raise ValueError`，不再静默忽略。
- runner：`run_suite("holdout","local",replay_from=...)` → `ValueError` 含 `replay_from`，
  `out` 目录未创建（`02-probe.py` §B3）。
- CLI：`run --suite holdout --mode local --from-run <任意> --out <新目录>` → exit 3、
  stderr 含 `replay_from`、无 traceback、out 不存在。
- `--mode replay` 仍先命中“holdout 只允许 mode='local'”（exit 3），口径未被放宽。

## 4. 不变项抽查 — PASS（上轮六项 PASS 的抽查复验）

- 默认聚合不泄漏：合成 3 题（含唯一题干/答案标记）产物仅 manifest+summary，
  `question/answer/case_id` 命中 0；真实默认 run 同上（§1）。
- CI 三变量 + details：`CI` / `GITHUB_ACTIONS` / `MKTKB_CI` 各自设置时，CLI 均 exit 3、
  stderr 点名变量、无 out、无 traceback；CI 下聚合 run 仍可跑（产物两件、`details=false`）。
- fail-closed 抽查 4 项：缺 labels → CLI exit 3、无 out；篡改 `--dataset`（pinned sha 不符）→
  exit 3、无 out；loader 行数 3≠30 → `HoldoutError`；删 `label_version` 键 → `HoldoutError`。
- 明细审计：audit 含 operator（非空/非 unknown）、run_id/created_at 与 manifest 一致、
  两 sha（`a8c8aa7f…` / `8f713a2a…`）、`label_version=holdout-2026-11-04`；无题干/答案/case_id。
- 仓库导出：`fixtures/evaluation/holdout-questions.jsonl` = 30 行、13 键、sha
  `a8c8aa7f028ce14047173e3e57db36dda72d3a13b3578ad82ec8cd1b86cd6738`、答案字段 `[]`；
  真实 labels sha `8f713a2a22fe605cad53cec7c2679c0e5606421d2ac6baa34d17521650f4c1bf`（只算 sha）。
- labels 未入库：`git ls-files` 与 `git log --all --name-only` 均无 `labels.jsonl`；
  `fixtures/evaluation` 无 `*labels*` 文件；`docs/evidence/` 被 `.gitignore` 覆盖。
- 合成拒答负样例（`expected_sources=[]` + `relevant_units` 非空 + `should_refuse`）：
  `status=fail`、`error=null`、分母 3/3、`refusal_recall=0.0`（可评分，非 error）。

## 5. 回归 / 预算 / 形式 — PASS

- 测试：本包 `test_holdout_suite.py` **43 passed**（61.90s）；`backend/tests/evaluation`
  **373 passed**（79.27s）；全量 `backend/tests` **1776 passed / 0 failed / 0 error**
  （477.53s）。无 flake，未触发隔离复跑。
- 内存：全量期间 ~90s 间隔采样 5 次，python 进程峰值 **394.1 MB**（< 2 GB）。
- b0 / badcase 对 P0：逐例签名（status、outcome.kind、每 check 的 check_id/status、error.code）
  **case_diffs=0/40**、**0/13**；summary 状态计数一致；gate 均 exit 3、hard `[]`。
- regression 对 `17c0e63`（既有 worktree，`mktkb.__file__` 指向该 worktree）：基线 pass4/fail3、
  gate exit 1、hard `['security_leak']`；当前 pass5/fail2、gate exit 3、hard `[]`；
  逐例**仅 RG006** `fail/answer/(value_forbidden=fail, kind_correct=fail)` →
  `pass/clarification/(…=pass)`；RG005/RG007 签名不变；无新 hard。
- 范围/形式：`d3b5745` 单 dev commit、5 文件（`runner.py`、`test_holdout_suite.py`、
  `report.md`、T108 `03/04`），均在允许路径；`dataset.py/gate.py` 零 diff；依赖文件零 diff；
  测试删除行仅 1 个 import 与 1 个 `_run` 取值行；无 `pytest.mark.skip/xfail/skipif`；
  `git status --short` 仅本复验新增的未跟踪 `review-R2.md` 与证据目录。
- 零真实模型/embedding/rerank/OCR：holdout local 强制 `provider_mode='offline'`
  （`runner.py:580-585`）；b0/badcase/regression 走既有 offline 配置；本次未使用 live/replay。
- 观察（非阻塞）：`report.md` 实测 **167 行** > 80 行预算；按提示词记录为形式项，
  不影响功能判定。

## 残余 / NOT-RUN

- 残余 R1（非阻塞）：3 个拒答题修复后为 fail、`refusal_recall=0.5`——可评分性已解决，
  拒答质量留给 T110/T112；B2 拒绝任意非空目录（比最低要求更严）；report 超 80 行预算。
- NOT-RUN：未抓包证明“零真实调用”（以代码强制 offline + 运行配置为证据）；未逐题阅读真实
  holdout 答案（防污染）；未在父提交 `b769a28` 单独跑 regression（任务只要求 `17c0e63`）；
  未检查本机之外 harness 的命令历史。
