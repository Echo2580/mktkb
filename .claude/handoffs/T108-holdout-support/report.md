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
