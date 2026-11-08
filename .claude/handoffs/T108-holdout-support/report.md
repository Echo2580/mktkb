# T108 report — Holdout 支持与防污染（P1 第 9 包）

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## 1. 完成内容

- `dataset.py`：holdout 冻结契约与加载/合并/导出——`HOLDOUT_*` 常量（sha/30 题/10-5-5-5-5/
  label_version，dataset.py:483-530）、`HoldoutPolicy`（:566）、`ci_environment`（:555）、
  `load_holdout_questions`（:769）、`load_holdout_labels`（:873）、合并 `load_holdout_dataset`（:934）、
  `export_holdout_questions`（:898）；答案字段黑名单与 11/13 键白名单。
- `runner.py`：`suite=holdout` 走 `_run_local_holdout`（runner.py:484）——默认只写
  `run_manifest.json`+`summary.json`（不写 `cases.jsonl`，trace 落临时目录随删）；
  `--allow-holdout-details` 才写逐题 + `holdout_audit.json`（:602）；CI 带 flag 抛 `HoldoutError`；
  聚合 summary 把逐 case 列表换成计数（`_redact_case_ids`，:1482）；manifest 增
  `holdout_details`/`holdout_labels_sha256`（:177）。
- `cli.py`：`--holdout-labels`、`--allow-holdout-details`（cli.py:525）；`dataset validate --suite holdout`
  （:155）只校验无答案导出；`dataset export-holdout-questions`（:191）逐字节导出并校验 sha/无答案。
- `gate.py`：`load_run_result` 允许聚合 run 缺 `cases.jsonl`、拒绝聚合目录里出现它（gate.py:2881）；
  `_holdout_gate_result`（:3469）聚合→exit 3 `holdout_aggregate_only`，详情→一律拒绝
  （CI 环境记 `holdout_details_forbidden_in_ci` 并写明变量名）。
- 仓库导出 `fixtures/evaluation/holdout-questions.jsonl`：30 行、sha `a8c8aa7f…6738`、13 键、无答案字段（=PM 副本逐字节）；labels 只以 sha 常量存在，永不入库。
- 测试：新增 `test_holdout_suite.py` 34 条（全合成夹具）；既有 `test_cli.py`（2 处）、`test_regression_suite.py`（1 行）按新契约最小同步。

## 2. 验收自证（handoff §4）

1. 默认聚合：`test_default_run_writes_aggregate_only_and_never_leaks_text`（test_holdout_suite.py:234）
   断言产物仅 manifest+summary、无 `cases.jsonl`、题干/答案/case_id 均不出现；探针见证据 03-A。
2. details+audit：`test_details_flag_writes_cases_and_audit_without_leaking_into_audit`（:264）——
   逐题落盘 + 审计含操作人/时间/参数/run_id/两 sha/label_version，且审计不含题干/答案。
3. CI 硬失败：`test_details_flag_fails_closed_in_ci`（:318，三变量参数化）、
   `test_cli_details_flag_hard_fails_in_ci`（:682）；`test_gate_cli_on_aggregate_run_is_usable`（:367）
   证明 `gate --run` 对聚合 run 不报错（exit 3 + 显式 unknown，不泄漏逐题）。
4. 拒绝条件逐项：缺 labels（:405）、缺/错 `label_version`（:433/:441）、行数（:449）、
   分层（:455）、case_id 集合（:461）、sha（:470）、题目带答案字段（:478）。
5. 仓库导出：`test_repository_export_is_answer_free_and_pinned`（:552）校验 sha/30 行/13 键/无答案字段，并断言 `fixtures/evaluation` 下无任何 labels 文件。
6. 回归/预算：b0/badcase 逐例 `case_diffs=0` 且 gate hard `[]`；regression 对 `17c0e63` 仅 RG006
   fail→pass、RG005/RG007 不变、无新 hard 名；全量 1767 passed；无 skip/xfail/删断言/新依赖。

## 3. 运行结果

| 范围 | 结果 |
| --- | --- |
| 本包 `test_holdout_suite.py` | 34 passed（60.20s）；与 cli+regression 合跑 79 passed（60.83s） |
| `backend/tests/evaluation` | 364 passed / 0 failed / 0 error（74.99s） |
| 全量 `backend/tests` | 1767 passed / 0 failed / 0 error（447.66s）；30s 轮询 14 样本，pytest 峰值 492 MB |

- b0：`b0-local-20261108T122104278059Z-3ed1ce55`，pass 29/fail 3/skipped 8，gate exit 3 hard `[]`，
  对 `var/eval/runs/p0-b0` **case_diffs=0/40**；badcase：`…b975e8eb`，pass 9/fail 4，gate exit 3 hard `[]`，
  对 `p0-badcase` **case_diffs=0/13**。
- regression：基线 `17c0e63`（临时 worktree）`…ff43b577` pass 4/fail 3，gate exit 1 hard `['security_leak']`；
  当前 `…5eca2fac` pass 5/fail 2，gate exit 3 hard `[]`；逐例**仅 RG006** `fail/answer`→`pass/clarification`，
  RG005/RG007 仍 fail，无新增 hard 名。
- 既有 flake：首次全量 `test_g08_short_budget_cancels_inflight_model_call` 失败一次（`len(calls)==0`），
  隔离复跑 1 次即过，最终全量通过；与本次改动无因果（未动 `conversations/`）。
- 提交：单 commit `p1/T108 holdout support + anti-leak guardrails`；sha 与 `--stat` 见交付回复
  （单 commit 无法在文件内自引用自身 sha，同 T107 做法）。

## 4. 偏离 / 未做

- gate 对**详情** run：选择「一律拒绝」而非「仅用聚合」（handoff §0.4 二选一）；dev 与 CI 都拒绝，
  CI 只是把命中的环境变量写进 reason。理由：gate 要按数据集重算 gold 就必须读 labels，T108 不引入
  gate-time labels，且逐题产物不得进入 CI/门禁。
- holdout 只允许 `mode=local`；`replay` 需要源 run 的 `cases.jsonl`（聚合 run 没有），显式拒绝、不降级。
- `turns` 只做 `{"question": turn}` 规范化并声明单轮（`multi_turn_verified=false`）；多轮执行属 T109。
- 未运行真实 holdout（红线；由验收方提供 labels 路径执行）；本包只证明缺 labels 时 exit 3、无产物。
- 未改 `corpus.py`（不在交付清单）：holdout 语料复用 `load_suite_corpus("regression", …)`
  的全量企业语料装配口径（引用 doc_code 必须全部解析成功）。
- `refusal` 加入 `ALLOWED_KINDS`（命题协议允许的 case 级 kind，scorer 的 `REFUSAL_KINDS` 已按拒答
  处理）；b0/badcase/regression 数据字节与 `dataset_version` 不变。内存：pytest 峰值 492 MB（<2GB），
  期间系统空闲内存一度 ~0.3 GB（其它进程），未影响结果。

## 5. 风险

- 未读真实 labels：questions/labels 重叠字段（`expected_kind`/`should_refuse`）以 labels 为准，差异只计
  `metadata_mismatch_count` 并写入 summary/audit（不阻断）。若真实数据有差异，验收方能看到计数，
  但不会得到逐题差异（防污染取舍）。
- `kind_correct` 对 `expected_kind=refusal` 仍是严格相等；产品若返回 `no_answer` 会判 fail。
  holdout 不进门禁，该口径留给 T110/T112 决定。
- 聚合 run 不落 trace：holdout 聚合没有逐题 trace 证据；需要 trace 必须开 details（受限环境）。
- 真实 holdout 的分数/阈值解释不在本包；`gate_v0_2` 校准（T112）前只能作为观察性证据。

## 6. R1 返工（`rework-R1.md`，2026-11-08）

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`。基线 `af08848`，本轮单 commit
`p1/T108 R1 fix holdout refusal-case scoring + out-dir guard`。

### 6.1 B1（F1 阻塞）拒答负样例不可评分 — 已修

- 根因（与 review F1 一致）：`_assert_gold_unit_ids` 只要任一 ref 存在就要求 `gold.unit_ids`，
  而 `gold.py:240-241` 的 `unit_ids` 只从 `expected_sources` 汇总；真实 3/30 是
  `should_refuse=true` + `expected_sources=[]` + `relevant_units` 非空，合法拒答题被判
  `gold_unit_ids_missing`，27/30 进分母。
- 修法（`runner.py:1382`）：**仅当 `case.expected_sources` 非空**才要求 `gold.unit_ids`；
  `expected_sources+relevant_units` 存在时仍要求 `relevant_unit_ids` 非空；
  `record_code_only_gold`（`runner.py:1367` 起）与 replay 的同一断言未放宽。
- 合成 before/after（探针 `backend\.pytest-tmp\T108-R1\probe_b1.py`，3 条合成 case，S03 改成
  `expected_sources=[]` + `relevant_units` 非空 + `should_refuse=true`）：

  | 时点 | status_counts | error | S03 | 分母 | refusal_recall | 产物 |
  | --- | --- | --- | --- | --- | --- | --- |
  | 修复前（`af08848`） | `{error:1, pass:2}` | `gold_unit_ids_missing` | error | 2/3 | `None` | manifest+summary |
  | 修复后 | `{fail:1, pass:2}` | `error=None` | fail（已评分） | 3/3 | `0.0` | manifest+summary |

  S03 的 `refusal_expected`/`kind_correct` 走既有拒答与 kind 口径，`gold.unit_ids=[]` 而
  `relevant_unit_ids` 非空；fail 是离线替身没有拒答的真实评分结果，不是 error。修复后聚合
  仍不写 `cases.jsonl`（防污染口径不变）。
- 防回归测试：`test_refusal_case_with_relevant_units_is_scored_not_error`
  （`test_holdout_suite.py:750`）断言非 error、3/3 进分母、`excluded_error_count=0`、
  `refusal_recall`/`Recall@10` 非 None；`test_expected_sources_still_require_unit_ids`（`:775`）
  只抽掉 S01 的 `unit_ids`，断言仍 `gold_unit_ids_missing`，同轮负样例不 error；
  既有 replay 断言测试 `test_replay_fails_closed_on_missing_unit_ids` 仍通过。
- **真实 30/30 由验收 R2 用 labels 路径执行**：本包未读真实 holdout 内容，未运行真实 run。

### 6.2 B2（review R1）out 目录防污染 — 采用「拒绝非空目录」（不清理）

- `runner.py:112` 新增 `HOLDOUT_DETAIL_FILES`（`cases.jsonl` / `holdout_audit.json` /
  `traces.sqlite3`）；`_assert_holdout_out_dir_fresh`（`:491`）在 `_run_local_holdout`（`:522`）
  读 labels / 建索引**之前**执行：
  - `--out` 不存在或存在且为空 → 允许（空目录是显式新建的合法目标）；
  - 目录含旧详情三件套 → `HoldoutError`，点名已存在的文件；
  - 目录非空但无详情 → `HoldoutError`，点名条目数/前 5 项。
- 默认聚合与 `--allow-holdout-details` 同口径（details 更严于 rework 的最低要求「拒绝已存在
  detail 文件」）：detail 三件套必须来自本次 run，避免新旧混合与 `holdout_audit.json` 失真。
  二选一里选择「拒绝」而非「写前删除」，因为删除会掩盖误复用、且无法审计旧详情来源。
- 测试：`test_holdout_rejects_out_dir_with_old_details`（`:796`，旧 `cases.jsonl` 原样保留、
  无 manifest/summary 落盘）、`test_holdout_rejects_reused_nonempty_out_dir`（`:811`）、
  `test_holdout_details_flag_rejects_dir_with_old_details`（`:822`）、
  `test_holdout_accepts_existing_empty_out_dir`（`:833`）、CLI 面
  `test_cli_holdout_rejects_reused_out_dir`（`:845`，exit 3、stderr 含「拒绝复用」、无 traceback、
  旧文件不动）。

### 6.3 B3（review R3）holdout local 静默忽略 `--from-run` — 已拒绝

- `run_suite` 的 holdout 分支（`runner.py:341`）在 `mode` 校验后新增：
  `holdout 不接受 replay_from（--from-run）：聚合 run 没有 cases.jsonl 可重放，不得静默忽略`。
  CLI 走既有 `ValueError` → exit 3，out 目录不创建。
- 测试：`test_holdout_local_rejects_from_run`（`:873`）、
  `test_cli_holdout_rejects_from_run`（`:891`，exit 3、stderr 含 `replay_from`、无 traceback）。
  既有 `test_holdout_replay_is_rejected`（`mode=replay`）仍先命中「只允许 mode='local'」。

### 6.4 R1 运行数字（全部实跑）

| 范围 | label | 结果 |
| --- | --- | --- |
| 本包 `test_holdout_suite.py` | `t108r1-pkg` | **43 passed**（62.01s；R1 前 34） |
| `backend/tests/evaluation` | `t108r1-eval` | **373 passed / 0 failed / 0 error**（77.06s；R1 前 364） |
| 全量 `backend/tests` | `t108r1-full` | **1776 passed / 0 failed / 0 error**（472.26s；R1 前 1767） |

- 内存：约 30s 间隔轮询 5 个样本，python 进程组峰值 **446.9 MB**（< 2 GB）；无 flake，未触发隔离复跑。
- b0：`b0-local-20261108T133817641064Z-e68c2ef8`，pass 29 / fail 3 / skipped 8，gate exit 3 hard `[]`，
  对 `var/eval/runs/p0-b0` **case_diffs=0/40**；badcase：
  `badcase-local-20261108T133825980216Z-845c1411`，pass 9 / fail 4，gate exit 3 hard `[]`，
  对 `p0-badcase` **case_diffs=0/13**。
- regression 对 `17c0e63`（worktree `%TEMP%\t105-r1-baseline-wt`，已打印
  `mktkb.__file__=…\t105-r1-baseline-wt\backend\src\mktkb\__init__.py`）：基线
  `…a7661903` pass 4/fail 3、gate exit 1 hard `['security_leak']`；当前 `…88c06963`
  pass 5/fail 2、gate exit 3 hard `[]`；逐例**仅 RG006** `fail/answer`→`pass/clarification`，
  RG005/RG007 签名不变，**无新 hard**。

### 6.5 R1 残余 / 偏离

- 真实 holdout 30/30 的可评分性与通过率：**NOT-RUN（红线）**，由验收 R2 用 labels 路径跑；
  R1 只证明同一形态的合成负样例不再 error 并按既有口径评分。
- B2 比 rework 最低要求更严：details run 也拒绝任何非空目录（不只是含详情文件的目录）。
  代价是复用「只有旧 manifest/summary」的目录也会被拒绝；换来 holdout 产物可追溯、不混代。
- 未改 `dataset.py` / `gate.py`（B1–B3 均可在 runner 层收口）；gate 对 details run 的拒绝口径不变。
- 真实 run 的 3 个拒答题修复后是否 pass（模型/管线是否真拒答）仍由 R2 观察；本包不预测分数。
