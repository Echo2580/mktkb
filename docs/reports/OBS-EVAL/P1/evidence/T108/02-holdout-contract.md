# T108 证据 02：holdout 数据契约与 fail-closed 矩阵

## A. 冻结契约（`dataset.py`）

| 维度 | 值 | 常量 |
| --- | --- | --- |
| 题量 | 30 | `HOLDOUT_CASE_COUNT` |
| 分层 | paraphrase 10 / multi_turn 5 / negative 5 / stale_conflict 5 / cross_doc_security 5 | `HOLDOUT_STRATA` |
| label_version | `holdout-2026-11-04` | `HOLDOUT_LABEL_VERSION` |
| questions sha256 | `a8c8aa7f…6738` | `HOLDOUT_QUESTIONS_SHA256` |
| labels sha256 | `8f713a2a…c1bf` | `HOLDOUT_LABELS_SHA256` |
| questions 键 | 13（题干+元数据） | `HOLDOUT_QUESTION_FIELDS` |
| labels 键 | 11（答案+标注，可选 `label_version`） | `HOLDOUT_LABEL_FIELDS` |
| 答案字段黑名单 | reference_answer / expected_values / expected_sources / relevant_units / forbidden_* | `HOLDOUT_ANSWER_FIELDS` |

`HoldoutPolicy` 的默认值 = 上表；`None` 表示该维度不钉死，**只**给合成夹具测试用
（生产 CLI 不暴露该参数；测试通过 `run_suite(holdout_policy=…)` 注入 3 条合成 case）。

## B. fail-closed 矩阵（每条都有测试）

| # | 条件 | 出口 | 消息要点 | 测试 |
| --- | --- | --- | --- | --- |
| 1 | 缺 labels（flag/env 都没有） | 非零（CLI 3） | `holdout 缺少 labels` | `test_missing_labels_is_rejected` |
| 2 | 缺/空 `label_version` | HoldoutError | `label_version 不能为空` | `test_missing_label_version_is_rejected` |
| 3 | `label_version` 与契约不一致 | HoldoutError | `与数据集契约不一致` | `test_wrong_label_version_is_rejected` |
| 4 | 行数 ≠ 契约 | HoldoutError | `行数 N != 契约 M` | `test_row_count_must_match_contract` |
| 5 | 分层 ≠ 10-5-5-5-5 | HoldoutError | `分层不符` | `test_strata_must_match_contract` |
| 6 | questions/labels 的 case_id 集合不等 | HoldoutError | `case_id 集合不相等` + 差集（只列 id） | `test_case_id_sets_must_match` |
| 7 | questions/labels sha256 不符 | HoldoutError | `questions/labels sha256 不符` | `test_sha_mismatch_is_rejected` |
| 8 | questions 出现答案字段 | HoldoutError | `出现答案字段` | `test_questions_cannot_carry_answers` |
| 9 | 未知字段 / 重复 case_id / 非法引用（UUID） | HoldoutError | `不允许的字段` / `重复` / `合并后不合规` | `test_questions_reject_unknown_fields_and_duplicates`、`test_labels_reject_unknown_fields_and_bad_refs` |
| 10 | CI/门禁环境（`CI`/`GITHUB_ACTIONS`/`MKTKB_CI`）带 `--allow-holdout-details` | HoldoutError（非零，不执行 case） | `CI/门禁环境禁止` + 变量名 | `test_details_flag_fails_closed_in_ci`（3 变量参数化）、`test_cli_details_flag_hard_fails_in_ci` |
| 11 | holdout flag 用于 b0/badcase/regression | ValueError | `只用于 --suite holdout` | `test_holdout_flags_are_rejected_for_other_suites`、`test_cli_rejects_holdout_flag_for_b0` |
| 12 | holdout + `mode=replay` | ValueError | `只允许 mode='local'` | `test_holdout_replay_is_rejected` |
| 13 | 聚合 run 目录里出现 `cases.jsonl` | ValueError | `不应包含 cases.jsonl` | `test_aggregate_run_rejects_smuggled_cases_jsonl` |

## C. 合并口径

- `questions` = 题目/元数据权威（case_id/suite/split/stratum/business_date/question/turns/
  requires_ocr/labeler/label_version/notes）；`labels` = 答案/标注权威（expected_kind/
  expected_values/expected_sources/relevant_units/reference_answer/should_refuse/
  refusal_reason/forbidden_*）。
- 两文件重叠的 `expected_kind`/`should_refuse` 若不一致：**以 labels 为准**，只计
  `metadata_mismatch_count`（写入 summary/audit），不中断运行——T108 不新增未经验证的结构性拒绝；
  计数为 0 才是干净数据（真实文件未读，故不预设）。
- `turns` 是字符串数组（命题协议 §4.1）；T108 只做显式规范化
  `{"question": <turn>}`，仍按单轮执行（`multi_turn_verified=false`），多轮执行属 T109。
- `refusal` 是命题协议允许的 case 级 kind，`OutcomeKind` 枚举无同名成员 →
  `ALLOWED_KINDS` 增加 `COMPATIBLE_EXPECTED_KINDS={"refusal"}`（scorer 的 `REFUSAL_KINDS`
  已按拒答处理；既有 b0/badcase/regression 数据不含该值，字节不变）。`kind_correct`
  仍是严格相等——holdout 不进门禁，该严格性留给 T110/T112 决定。
- labels 的 `notes`（答案出处说明）**不合并**进 CaseSpec，避免答案侧文本进入任何 Case 字段。

## D. 产物与 gate

| run 类型 | 落盘 | gate `--run` |
| --- | --- | --- |
| 默认（聚合） | `run_manifest.json`、`summary.json`（trace 在临时目录，随运行删除） | 可用：exit 3 + `unknown(gate_id=holdout, check_id=holdout_aggregate_only)`，`hard_failures=[]` |
| `--allow-holdout-details` | 上述 + `cases.jsonl`、`traces.sqlite3`、`holdout_audit.json` | 一律拒绝：exit 3 + `holdout_details_not_gated`；CI 环境改记 `holdout_details_forbidden_in_ci`（reason 写变量名） |

选择说明（handoff §0.4 二选一）：采用「拒绝」而不是「仅用聚合」，因为 gate 要按数据集重算
gold/forbidden 就必须读 labels，T108 明确不引入 gate-time labels；且逐题产物不得进入 CI/门禁。
dev 与 CI 都拒绝，CI 只是把命中的环境变量写进 reason，便于审计区分。
