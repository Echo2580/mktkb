模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T108 独立验收 review（Holdout 支持与防污染）

- 对象：`af08848`（父 `31143f2`），分支 `p1/fix-retrieval`；验收开始 `git status --porcelain` 为空。
- 方法：合成夹具 + 真实 holdout 受限运行（labels 只作为运行时输入；真实题干/答案未写入本文件/证据）+
  逐项 fail-closed 注入 + 全量回归。探针与原始结果：`docs/reports/OBS-EVAL/P1/evidence/verify/T108/`。
- 未改交付物；未 commit/push/切分支/stash/reset；未读 `.env`。

## 1. 默认聚合 — PASS（残余 R1）

- 合成 3 条 holdout：`run_suite(... local ...)` 产物严格为 `run_manifest.json`、`summary.json`；
  `cases.jsonl`/`traces.sqlite3` 均不存在；题干标记、答案标记、3 个 case_id 在产物中命中 0；
  `summary.holdout={aggregate_only:true,details_written:false,traces_persisted:false}`
  （`02-probe.py` A；`03` §A）。CLI 面：`test_cli_run_holdout_aggregate_stdout_has_no_details`
  （`test_holdout_suite.py:649-679`）；实现 `runner.py:484-599`、`:1463-1503`、`:1558-1574`。
- 真实 labels 受限运行（`--holdout-labels docs\evidence\...\labels.jsonl`，`--out %TEMP%`）：
  exit 0；产物仅同两文件；对真实 questions/labels 的 question/turn/case_id/reference_answer 命中 0；
  only 2 条 2 位数字子串落在 64 位 sha 字段内部（非独立答案值）。`gate --run` exit 3、hard `[]`、
  unknown `holdout_aggregate_only`、无 traceback（`03` §B；`gate.py:2881-2925`、`:3469-3537`）。
- 残余 R1（低-中）：复用已有 out 目录时，默认 run 不清理旧 details 的 `cases.jsonl`/`holdout_audit.json`/
  `traces.sqlite3`（实测 `03` §H）；新目录验收通过，gate 会因聚合目录含 `cases.jsonl` 拒绝
  （`gate.py:2894-2899`），但文件已落盘。建议后续拒绝非空 out 目录或清除详情三件套。
  若 PM 口径要求“任意 out 目录（含复用）都不得残留详情”则改判 FAIL；当前按“新目录默认 run”判 PASS。

## 2. details + audit — PASS（真实 run 逐题 error 见 F1）

- 合成 details run：出现 `cases.jsonl`、`traces.sqlite3`、`holdout_audit.json`；审计含 operator/
  created_at/parameters/run_id/两 sha/label_version，且题干/答案/正文均不出现（`02-probe.py` C；
  `test_holdout_suite.py:264-287`；实现 `runner.py:498-504`、`:587-646`）。
- 真实 details run（`--allow-holdout-details`，`%TEMP%`，扫描后删除）：exit 0、30 行；
  审计 `questions_sha256=a8c8aa7f…6738`、`labels_sha256=8f713a2a…c1bf`、
  `label_version=holdout-2026-11-04`、operator/time/run_id 齐全；题目/turn/reference_answer 命中 0，
  `expected_values` 仅 2 条 2 位数字子串落在 qsha/lsha/run_id 内部（非独立值，`03` §C）。
  真实 run 的 3 个 `error` 属 F1（可评分性），不影响 audit 本身的 PASS 判定。

## 3. CI 硬失败 + gate — PASS

- `CI`/`GITHUB_ACTIONS`/`MKTKB_CI` 单变量与三项组合 + `--allow-holdout-details`：exit 3、
  错误点名命中变量、无 out 目录；聚合 run 在这些变量下仍可跑（`02-probe.py` E；CLI 复验见 `03` §D）。
- `gate --run` 聚合 run：exit 3、hard `[]`、唯一 unknown `holdout_aggregate_only`、无异常、无逐题
  （`03` §B；`test_holdout_suite.py:346-375`）。details run：dev → `holdout_details_not_gated`；
  CI → `holdout_details_forbidden_in_ci` 且 reason 写变量名（`03` §C；`test_holdout_suite.py:377-390`）。
  实现选择“详情 run 一律拒绝”，report §4 已披露，符合 handoff §0.4 的二选一。

## 4. fail closed — PASS（说明 G1）

逐项实测（合成夹具；`02-probe.py` F/G，`03` §E）：

| 条件 | 结果 |
| --- | --- |
| 缺 labels | runner `HoldoutError`；CLI exit 3、无 out、无 traceback |
| 缺/空 `label_version` | `HoldoutError`；删键由 13 键白名单拒绝（`dataset.py:712-714`） |
| 错 `label_version`（questions 或 labels） | `HoldoutError`（`dataset.py:747-751`、`:827-833`） |
| 行数 3≠30 | `HoldoutError`（`dataset.py:776-779`） |
| 分层 2/1≠10/5/5/5/5 | `HoldoutError`（`dataset.py:801-807`） |
| case_id 集合不等 | `HoldoutError`（`dataset.py:945-952`） |
| questions/labels sha 不符 | `HoldoutError`（`dataset.py:638-647`） |
| 题目带答案字段 | `HoldoutError`（`dataset.py:650-655`、`:711`） |

- G1：单测 `test_missing_label_version_is_rejected` 用空串而非删键；删键已由验收探针实测拒绝。
  `labels` 的 `label_version` 按协议可选（真实 labels 11 键无此键），因此拒绝条件是 questions/数据集
  契约的 `label_version`，不会误伤真实 labels。
- CLI 层非零：缺 labels 与篡改 `--dataset`（sha 不符）均 exit 3、无产物；其余维度在 runner/loader
  边界抛 `HoldoutError`，CLI 对 `ValueError/OSError` 统一 exit 3（`cli.py:566-586`）。

## 5. 仓库导出 — PASS

```text
fixture: lines=30, sha256=a8c8aa7f028ce14047173e3e57db36dda72d3a13b3578ad82ec8cd1b86cd6738,
         keys=13, answer_fields=[], 与 PM 副本及真实 questions.jsonl 逐字节相同
labels: sha256=8f713a2a22fe605cad53cec7c2679c0e5606421d2ac6baa34d17521650f4c1bf（只算 sha）;
        fixtures/evaluation 无 labels 文件；git ls-files / git log --all --name-only 无 labels.jsonl
```

- 导出命令 `dataset export-holdout-questions` 的合成测试见 `test_holdout_suite.py:588-646`；
  仓库 fixture 未在验收中被重写。

## 6. 回归 / 预算 / 形式 — PASS

- 测试：本包 **34 passed**（59.81s）；`backend/tests/evaluation` **364 passed**（78.16s）；
  全量 `backend/tests` **1767 passed / 0 failed / 0 error**，两次（429.07s、429.39s）。
  内存峰值 **465.9 MB**（5s 轮询，< 2 GB）；未复现 report 所述既有 flake，无需隔离复跑（`04` §A）。
- b0/badcase 对 P0：`case_diffs=0/40`、`0/13`；gate 均 exit 3、hard `[]`（`04` §B）。
- regression 对 `17c0e63`：仅 **RG006** fail/answer → pass/clarification；RG005/RG007 签名不变；
  gate hard 由 `['security_leak']` 收缩为 `[]`，**无新 hard**（`04` §C）。
- 无新增 `pytest.mark.skip/xfail/skipif`；测试删除行仅 1 个被替换断言 + 1 个非法 suite 占位值；
  无新依赖（pyproject/lock 无 diff）；单 commit（`git rev-list --count 31143f2..af08848` = 1）；
  13 个改动文件均在 handoff §3 允许路径；report 80 行、交付证据 4 份。
- 零真实模型/embedding/rerank/OCR：holdout local 强制 `provider_mode='offline'`
  （`runner.py:541-546`）；P0 suite local 走既有 offline 配置；本次未使用 live/replay。
## F1. 真实 holdout run 可评分性 — FAIL（阻塞）

- 真实默认 run（`run --suite holdout --mode local --holdout-labels ...`）exit 0、仅聚合，但
  **3/30 case `status=error`**，`error.code=gold_unit_ids_missing`（7 pass/20 fail/3 error）；
  只有 27/30 进入指标分母（`03` §B）。
- 逐条关联（真实 details run，仅输出计数，不打印 case_id/题干/答案）：
  **3/3** error case 都是 `should_refuse=true`、`expected_sources=[]`、`relevant_units` 非空；
  **3/3** 错误消息是 `unit_ids 为空`（不是 `relevant_unit_ids 为空`）。与设计 §4 PM 口径
  “负样例允许 `expected_sources` 为空、可用 `relevant_units`”直接冲突。
- 根因：`runner.py:1343-1358` 的 `_assert_gold_unit_ids` 在任意 ref 存在时都要求 `gold.unit_ids`
  （只来自 `expected_sources`）；`gold.py:230-241` 对 `expected_sources=[]` 返回 `unit_ids=()`。
  T108 复用了该 P0 断言，未覆盖 holdout 的 relevant-units-only 拒答题。
- 影响：3 个合法拒答题不可评分，holdout 真实 run 不能声称“30 题均可运行/可评分”。修法建议：
  仅当 `case.expected_sources` 非空时要求 `gold.unit_ids`（或对 `should_refuse` 跳过该断言），
  并加一条 `expected_sources=[]` + `relevant_units` 非空的合成测试。
- 若 PM 明确把“真实 run 逐题可评分”划给 T110/T111 且书面接受 27/30 分母，可把 F1 降级为已知
  限制；按本验收提示词的真实 holdout 受控运行口径，当前判 FAIL。

## 残余 / NOT-RUN

- R1：复用 out 目录的旧 details 三件套（见 §1）；R3（低，边界）：holdout `mode=local` 未显式拒绝
  `replay_from`（`runner.py:331-353`），CLI `--from-run` 会被静默忽略，不在本包验收项内。
- NOT-RUN：未在父提交 `31143f2` 单独跑 regression（任务只要求对 `17c0e63`；b0/badcase 0 差异 +
  holdout 按 suite 隔离）；未逐题阅读真实答案（防污染）；未抓包证明零真实调用；PSReadLine 历史无
  `P1-HOLDOUT`/`questions.jsonl`/`labels.jsonl` 命令，但不覆盖其他 harness。

**总判定：FAIL（F1 阻塞）**。六项防泄漏/CI/fail-closed/回归验收均 PASS；真实 holdout run 有 3/30
合法拒答题因 `_assert_gold_unit_ids` 过严而 error，须修复或将 F1 明确划归 T110/T111 并书面接受
27/30 分母。R1/R3 为残余加固项。
