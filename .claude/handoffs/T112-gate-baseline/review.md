模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T112 独立验收结论

**结论：PASS（功能/事实 6/6，无阻断）。** 1 条 MEDIUM 流程偏差：R1 commit 实际
9 paths（4 个交付 + 5 个 `.claude/handoffs/**` PM 簿记），与“R1 只改 4 文件”字面不符，
report §6 未逐字披露；若按 commit 内容严格判，该项应记流程 FAIL，需 PM 记录/裁定。
其余 5 项无保留 PASS。以下均为独立复跑/只读核对，不引用 report 作 PASS 证据。

## 逐条验收

| # | 结论 | 自跑命令 / 证据 |
| --- | --- | --- |
| 1 审批阈值一致 | **PASS** | `gate_v0_2.json:4` approved；8 硬门禁与 v0.1 逐项相等（`:12`）；`suites=[b0,badcase,regression]`（`:27`）；retrieval 5 指标 `min_sample=8`、R/M/nDCG `absolute_min=0.855`、hard_filter `absolute_max=0.02`、empty_recall `absolute_max=0.145`、`max_regression_pp=2.0`（`:52-97`）；answer/refusal/runtime 10 指标四字段全 null；approved 配置对 R0 live run **exit 0 / quality=pass / 15 条全 pass / hard=[]**；逐字节 R0 unapproved 配置 **exit 3 / quality=unknown**。 |
| 2 校准可复现 | **PASS** | R0 未审批配置连续两次 `--calibrate`：proposal sha 均 `0E7D641F…`，与 run 内 R0 proposal 逐字节一致；配置 sha 前后均 `2A86D922…`；`write_gate_proposal` 拒绝覆盖 v0.1/v0.2（`gate.py:3181`）。proposal 含 run_id / `gate_config_hash=5362de3c…` / strata=all,exact,text。 |
| 3 baseline 审批/身份 | **PASS** | `approval.json`：approver=主人、reason 与 `handoff.md:69-70`（§7）逐字一致、baseline_id=`bc6f6f906db1`、gate_result_sha256=`c9fcbb…`、gate_exit_code=0、quality_status=pass；六要素与 manifest 全等，重算 id 一致；`baseline list` approved=yes；仅 `var/eval/baselines/bc6f6f906db1` 一条，P0 baseline 未创建/未 copy；`diff --baseline 000000000000` exit 3；跨版本无 `compare_with` 拒绝、显式 compare_with 标 `explicit_cross_version`/`release_allowed=False`、`require_release_baseline` 拒绝。scratch 重跑 approve 仅 `approved_at` 不同。 |
| 4 live 真实性与合规 | **PASS** | 40 题、32 计分/8 OCR、`aborted=false`、error=0；manifest dataset sha/corpus sha/pipeline/gate/index 与冻结数据一致；每行 versions 11 字段且 40 行一致；指标 all/exact/text：Recall=MRR=nDCG `0.96875/1.0/0.875`，hard_filter `0/0/0`，empty_recall `0.03125/0/0.125`；账本按 run_id 独立统计 140 行 = reserved 70（embedding 39/rerank 31/chat 0）+ result 70（同分布），每 id 恰 1 result、全 200、零 retry；`conservative_charge_cny` 合计 `0.0090459` 元、预检 `0.771174`；账本 435→505/1000；`provider_billed_cny=null`。5 个 `--allow-full-live` 负例（默认关闭/错 suite/39 题/sha 变/与 pilot 互斥）均 exit 3。 |
| 5 回归/预算 | **PASS（带 MEDIUM 路径偏差）** | 本包 13 passed；evaluation 433 passed；全量两次 **1933 passed / 0 failed / 0 error**（622.41s、735.21s），Python 进程 WorkingSet 合计峰值 **594.9MB < 2GB**；local b0/badcase/regression 对 P0/T114 `signature_diffs=0`、`retrieved_diffs=0`、gate exit 3/hard `[]`；无 skip/xfail/新依赖/真实 chat；report 105 行，:101 已披露超 80 行。R1 commit 实际 9 paths（见下）。 |
| 6 范围诚实 | **PASS** | badcase/regression/holdout live 与 P0 跨版本比较均登记 NOT-RUN（report §5/§R1、证据 04 §D）；answer/refusal/runtime 未审批项仍 null，未声称通过；P1 baseline 仅 b0 live。 |

## 证伪检查（均成立/已澄清）

- **未审批 ≠ 通过**：同一 run 用 R0 逐字节 unapproved 配置 exit 3；approved 配置才 exit 0。
  不是 gate 恒通过，也不是把 unapproved 当 pass。
- **校准未写回**：连续两次 proposal 与 R0 落盘 sha `0E7D641F…` 完全一致，配置字节未变。
- **baseline 审批不可空转**：未审批配置现场重算 exit 3 → approve 拒绝且不写 approval；
  空 approver/reason 被 argparse/库层拒绝；同 run scratch 重跑仅时间戳不同。
- **P0 未被污染**：交付 baseline 目录仅 P1 一条；P0 只作为 run 目录对照，未建 baseline。
- **live 成本不虚报**：账本按 run_id 可逐笔核到 70 个 reservation/result；
  `provider_billed_cny` 全 null，`conservative_charge_cny` 与 stage 增量精确等于 `0.0090459`。
- **全量守卫非空壳**：5 个负例均在读凭据/GO 之前拒绝；`validate_full_live_dataset` 同时
  校验 suite、40 题、冻结 sha（`live.py:677`；`runner.py:1052`）。
- **local 对照非指标伪装**：b0/badcase 指标与 P0 旧评分口径不同，但签名/retrieved 0 diff；
  对 T114 指标一致（仅 latency 不同），故以签名/retrieved 为准。
- **R0 未 amend**：reflog 仅一次 `7f46121` 创建（19:48:20），父 `cd1b3ca`；R1 父 `6b614b5`。
- **R1 测试适配**：仅 3 处 approved 相关（契约断言 + 两个 unapproved 用例改临时副本），
  未删断言、无 skip/xfail。

## 残余 / 偏差（不阻断功能）

- **MEDIUM-1（R1 commit 路径）**：`git diff --name-status 7f46121 4c2b7ba` = 9 paths：
  4 个交付（report/test/config/证据 03）+ 5 个 PM handoff（pause handoff、T112 handoff、
  `_index`、prompts R1、prompts verify）。全部额外路径在 `.claude/handoffs/**`，无代码/
  配置；report §6 只列 4 个交付，未披露这 5 个文件。若“只改 4 文件”按 commit 内容判，
  该项为流程 FAIL；按 dev 交付/PM 簿记分开判则 PASS。建议 PM 在 review/index 明示。
- **LOW-1（live 派生产物被改写）**：R1 为满足“现场 gate 必须 exit 0”重写了 run 的
  `gate.json`（exit 3→0）；manifest/cases/summary 未变、baseline artifact 摘要一致，
  report §R1 已披露。与“不动 live 产物”的字面要求有偏差；原 exit 3 仅存于 R0 证据 02。
- **LOW-2（证据措辞）**：证据 01 §C 写每行 versions“十项”，实际 11 字段
  （多 `dataset_sha256`）；字段齐全，不影响判定。
- **LOW-3（审批时间口径）**：`approval.json.approved_at=2026-11-09T12:00:14Z`
  （20:00:14+08，R1 执行时间）；主人书面批准 19:54 记录在 config `approval.approved_at`
  与 handoff §7；两处时间不同，无字段互证，但 approver/reason/结果均一致。
- **LOW-4（工作树）**：开工 clean；验收期间 PM 于 20:16:14 将 `_index.md` 改为
  “T112 独立验收中”，当前 `git status` 有该 1 个未提交 `.claude/handoffs/**` 变更；
  HEAD 未变，非交付路径、非本次写入。
- **LOW-5（config hash 口径）**：审批落盘使 loader `config_hash` 由 handoff §7 记录的
  审批前 `5362de3c…` 变为 `b5bfdb49…`（整份 JSON 哈希，R1 报告已披露）；baseline 六要素
  不含 config hash，approval 绑定的是 `gate_result_sha256`，故不构成批准值不符。
- **LOW-6（NOT-RUN 理由过时）**：R0 §5 把“与 P0 baseline 的跨版本比较”登记为 NOT-RUN，
  理由写“P1 baseline 未建”；R1 已建 P1 baseline，该理由已过时，R1 段仅写“范围同 R0”，
  未重述当前理由。NOT-RUN 事实仍成立，未见把未跑项写成通过。
- **残余风险（非本包 FAIL）**：baseline approval 绑定 `gate_result_sha256`，但 `diff`
  放行路径不重新核对当前 gate 配置哈希；审批后若改阈值，需另行治理。另 P1 baseline 仅
  b0 live，badcase/regression/holdout live NOT-RUN（主人方案 A 已授权并披露）。

## 证据与约束

- `docs/reports/OBS-EVAL/P1/evidence/verify/T112/01-gate-approval-and-calibration.md`
- `docs/reports/OBS-EVAL/P1/evidence/verify/T112/02-baseline-live-and-guard.md`
- `docs/reports/OBS-EVAL/P1/evidence/verify/T112/03-tests-commits-and-scope.md`

未重跑 live、零真实模型/embedding/rerank/OCR 调用；未改交付物；未 commit/push/切分支；
除上述 3 份证据与本 review 外，仅在 `.claude/handoffs/_scratch/T112v/` 写临时探针、
在 `backend/.pytest-tmp/` 写 pytest 临时产物。
