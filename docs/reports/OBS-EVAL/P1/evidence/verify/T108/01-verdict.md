# T108 独立验收结论（证伪导向）

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

- 验收对象：`af08848`（父 `31143f2`），分支 `p1/fix-retrieval`；验收开始时工作树
  `git status --porcelain` 为空；验收期间未改交付物、未 commit/push/切分支。
- 方法：合成 holdout 夹具（3 条）+ 真实 holdout **受限运行**（labels 只在运行时读取；本目录与
  `review.md` 不写入任何真实题干/答案原文）+ 逐项 fail-closed 注入 + 全量回归。
- 探针：`02-probe.py`（合成夹具，可复跑）；结果：`03-probe-results.md`；测试/评测：`04-test-eval-runs.md`。

## 判定表

| # | 验收项 | 判定 | 关键证据 |
| --- | --- | --- | --- |
| 1 | 默认聚合（防泄漏） | **PASS**（残余 R1） | 合成默认 run 产物仅 `run_manifest.json`/`summary.json`，无 `cases.jsonl`/trace；题干/答案/case_id 命中 0（`02-probe.py` A；`03` §A）。真实 labels 受限运行 exit 0，产物仅同两文件，题干/答案/case_id 命中 0；`gate --run` exit 3、hard `[]`、无 traceback（`03` §B）。实现：`runner.py:484-599`、`:1558-1574`、`:1463-1503`；`gate.py:2881-2925`。 |
| 2 | details + audit | **PASS** | `--allow-holdout-details` 才出现 `cases.jsonl`/`traces.sqlite3`/`holdout_audit.json`；审计含 operator/created_at/parameters/run_id/两 sha/label_version，且不含题干/答案（`03` §C；`test_holdout_suite.py:264-287`）。真实 details run 30 行、审计真实 sha `a8c8aa7f…`/`8f713a2a…`、`label_version=holdout-2026-11-04`；扫描后已删除 TEMP 产物（`03` §C）。实现：`runner.py:498-504`、`:587-646`。 |
| 3 | CI 硬失败 + gate | **PASS** | `CI`/`GITHUB_ACTIONS`/`MKTKB_CI` 单变量及组合 + details 均 exit 3、错误点名变量、无 out 目录；聚合 run 在 CI 下仍可跑（`03` §D）。`gate --run` 对聚合 run：exit 3、hard `[]`、唯一 unknown `holdout_aggregate_only`，无异常/无逐题；details run dev→`holdout_details_not_gated`、CI→`holdout_details_forbidden_in_ci`（`03` §B/D；`gate.py:3469-3537`；`test_holdout_suite.py:317-397`）。 |
| 4 | fail closed | **PASS**（说明 G1） | 缺 labels（runner `HoldoutError`；CLI exit 3、无产物）、缺/空 `label_version`、错 `label_version`、行数 3≠30、分层 2/1≠10/5/5/5/5、case_id 集合不等、questions/labels sha 不符、题目带答案字段——逐项明确拒绝（`03` §E/F；`dataset.py:638-655`、`:704-814`、`:817-998`）。缺失键另由 13 键白名单拒绝（`dataset.py:712-714`）。 |
| 5 | 仓库导出 | **PASS** | `fixtures/evaluation/holdout-questions.jsonl` 30 行，sha256=`a8c8aa7f…6738`，13 键，无 `reference_answer/expected_values/expected_sources/relevant_units/forbidden_*`；与 PM 副本 `.claude/handoffs/_scratch/T108/questions-copy.jsonl` 及真实 `questions.jsonl` **逐字节相同**。`labels` 未入库：`git ls-files` 无 labels、`fixtures/evaluation` 无 labels 文件、`git log --all --name-only` 无 `labels.jsonl`（`03` §G）。 |
| 6 | 回归/预算/形式 | **PASS** | 本包 34 passed；`backend/tests/evaluation` 364 passed；全量 `backend/tests` 1767 passed（两次，0 failed/0 error），内存峰值 465.9 MB < 2 GB；b0/badcase 对 P0 `case_diffs=0`、gate hard `[]`；regression 对 `17c0e63` 仅 RG006 fail→pass，RG005/RG007 不变，无新 hard；无 skip/xfail/删断言/新依赖；单 commit、仅允许路径；report 80 行、交付证据 4 份（`04`）。 |
| **F1** | **真实 run 可评分性（附加阻塞）** | **FAIL** | 真实 `run --suite holdout --mode local`（默认）exit 0、仅聚合，但 **3/30 case 为 `status=error`**，`error.code=gold_unit_ids_missing`（7 pass/20 fail/3 error）。逐条关联确认：3 个 error 全部是 `should_refuse=true`、`expected_sources=[]`、`relevant_units` 非空的合法拒答题；错误消息全部是 `unit_ids 为空`（不是 `relevant_unit_ids 为空`）。根因：`runner.py:1343-1358` 的 `_assert_gold_unit_ids` 在任何 ref 存在时都要求 `gold.unit_ids`（来自 `expected_sources`），与设计 §4 PM 口径“负样例允许 `expected_sources` 为空、可用 `relevant_units`”冲突。结果：27/30 进入分母，3 题不可评分。修法建议：仅当 `case.expected_sources` 非空时才要求 `gold.unit_ids`（或对 `should_refuse` 跳过该断言），并加一条 `expected_sources=[]` + `relevant_units` 非空的合成测试。 |

## 残余 / NOT-RUN

- **R1（低-中，非验收失败）**：复用已有 out 目录时，默认聚合 run 不会清理上一次 details run 留下的
  `cases.jsonl`/`holdout_audit.json`/`traces.sqlite3`；`summary.holdout.aggregate_only=true` 但目录仍有逐题文件。
  实测：`after_details` 与 `after_default` 文件集相同（`03` §H）。新目录场景（验收项 1）通过；`gate` 会因
  聚合目录出现 `cases.jsonl` 而拒绝（`gate.py:2894-2899`），但文件本身已留在磁盘。建议后续在 holdout 聚合
  入口拒绝非空 out 目录或清除 holdout 详情三件套。
- **F1（阻塞）**：见上表；3/30 拒答题因 `_assert_gold_unit_ids` 过严而 error。若 PM 明确把“真实 run 逐题
  可评分”划给 T110/T111 且接受 27/30 分母，可将其降级为已知限制；按本验收提示词的真实 holdout 受控运行
  口径，当前不能判“30 题可运行”。
- **G1（测试口径说明）**：`test_missing_label_version_is_rejected` 用空串而非删键；删键由 13 键白名单拒绝，
  验收探针已实测 `HoldoutError`。`labels` 的 `label_version` 按协议是可选（真实 labels 11 键无此键），
  故“缺失拒绝”指 questions/数据集契约，不误伤真实 labels。
- **R3（低，边界）**：holdout `mode=local` 分支未显式拒绝 `replay_from`（`runner.py:331-353` 先于
  非 holdout 的 `local+replay_from` 检查），CLI 传 `--from-run` 会被静默忽略；不在 T108 验收项内。
- **NOT-RUN**：未在父提交 `31143f2` 单独跑 regression 以隔离 T108 自身的 regression 差分（任务只要求对
  `17c0e63`；b0/badcase `case_diffs=0` 且 holdout 分支按 suite 隔离）；未逐条阅读真实 holdout 答案
  （红线/防污染）；PSReadLine 历史扫描 0 条 `P1-HOLDOUT`/`questions.jsonl`/`labels.jsonl` 命令，但历史文件
  不覆盖其他 harness，属有限证据。

**总判定：FAIL（F1 阻塞）**。六项防泄漏/CI/fail-closed/回归验收均 PASS；但真实 holdout 运行有 3/30
合法拒答题 error，须修 `_assert_gold_unit_ids`（或由 PM 明确划归 T110/T111 并书面接受 27/30 分母）。
