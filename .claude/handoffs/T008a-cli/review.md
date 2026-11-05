# T008a 独立验收（对象 f2c0209）

- 验收者：全新上下文，未使用开发会话历史；不采信 report.md 的自述，全部关键结论由本人执行 CLI 复现。
- 环境：Windows PowerShell；分支 `p0/obs-eval`；HEAD `f2c0209`（父 `9abe92a`）；Python `.\.venv\Scripts\python.exe -B`；
  `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；零真实调用；串行执行。
- 隔离：run/gate/proposal/报告全部写到 `%TEMP%\t008a-verify`；仓库只新增本 review 与 `evidence/verify/T008a/` 3 份证据。

## 总判定

**PASS**。§5.1–§5.6 全部满足；无 FAIL。存在 1 个覆盖缺口（真实 exit 4 不可经 CLI 到达，NOT-RUN）和 1 个 LOW 文档偏差（proposal “45 行”表述），均不阻断本包。

## §5 逐条判定

| 条目 | 判定 | 独立证据 |
|---|---|---|
| 5.1 子命令齐全 | **PASS** | `--help` 列出 6 组命令 exit 0；未知子命令/参数/`--allow-holdout-details` 均 exit 2 且无 Traceback；`dataset validate/build`、`baseline list` 实跑通过。01 [V01–V08] |
| 5.2 退出码透传 | **PASS（4 NOT-RUN）** | 0：run 三条 + `%TEMP%` 已审批演示配置 gate；1：敏感注入 gate 与 diff；3：默认 gate/无 baseline diff/审批拒绝；2：approve 缺参。真实 4 未达成：CLI 对 live manifest 在 `RunManifest.from_dict` 即 exit 3，`evaluate_gate` 的 live→4 未触达；`run --mode live` 被 argparse 拒绝（exit 2）。01 [V09–V17]、02 [V19–V21]、[V30] |
| 5.3 全流程真实跑通 | **PASS** | b0/badcase local + b0 replay 三件套齐全、均 exit 0；默认 gate 三者 exit 3、`hard_failures=[]`、quality unknown、config_status unapproved；`--calibrate` 只写 proposal（status unapproved），`gate_v0_1.json` blob 与父提交完全相同；`%TEMP%` 已审批演示配置下 gate exit 0（仅演示，非审批）。01 [V09–V15]、[配置不可变] |
| 5.4 敏感注入 exit 1 | **PASS** | `%TEMP%` run 副本 + 临时数据集给 Q01 注入 `forbidden_values`：gate exit 1、`hard_failures=['security_leak']`、failure `Q01/forbidden_value`；未改 fixtures。02 [V18] |
| 5.5 baseline 审批纪律 | **PASS** | 缺 `--gate`/`--approver`/`--reason` 均 exit 2；自称 exit 0 的 gate JSON 被现场重算 exit 3 拒绝，`approval.json` 计数 0、baselines 目录未创建；无 baseline 时 diff exit 3 且明确“baseline 未建立，待 T009”，未自动建/复制；未审批 baseline 下 diff `release_allowed=False`，blocked 分别为 `current_gate_exit_3` 与 `baseline_unapproved`，且 `require_release_baseline` 的“放行阻断”实际打印。02 [V19–V26] |
| 5.6 测试与回归 | **PASS** | `test_cli.py` 35 passed；`backend/tests/evaluation` 313 passed；全量 `backend/tests` 1586 passed / 0 failed / 0 error（433.43s，仅此一次）；无新依赖；local 强制 `provider_mode="offline"`，未读 `.env`。03 [T01–T03] |

## 失败项 / 偏差

- **FAIL：无。**
- **GAP-1（NOT-RUN，非阻断）**：真实 `mode=live → exit 4` 没有可用的 CLI 入口。`run --mode live` 是 argparse exit 2；手工把 run_manifest 改成 live 后，`gate` 在 `load_run_result` 阶段被 `RunManifest.from_dict` 以 exit 3 拒绝（`ValueError: run_manifest.mode 非法: 'live'`），`gate.py` 的 live→4 分支不可达。交付测试只用参数化 mock 覆盖 4，不是端到端。证据：01 [V16–V17]，`backend/src/mktkb/evaluation/gate.py:3123`、`cli.py:202`。
- **LOW-1（文档偏差）**：report.md 第 17/46 行称 `gate_proposal.json` “45 行”；实际 887 行、45 条 metric 行。结论（status=unapproved、未改配置）不受影响。证据：01 [三]、03 [D01]。
- **OBS-1（语义提醒）**：gate=0 且 baseline 未审批时 `diff` 进程 exit 0，但 `release_allowed=False`、`blocked=baseline_unapproved`，guard 已打印；`export` 成功即 exit 0（即使 gate=3）。发布判定必须读 `release_allowed`/`release_blocked_reason`，不能只看退出码。02 [V26–V27]。
- **OBS-2（环境）**：验收期间工作树出现未跟踪的 `.claude/handoffs/prompts/T008b-dev.md`（非本次创建）；跟踪文件相对 f2c0209 无改动，代码基线未漂移。

## 未覆盖

- `baseline approve` 的成功路径（未在 `%TEMP%` 生成 `approval.json`，避免伪造 baseline 审批）；仅核对代码与单测，未实跑。
- 真实 live/exit 4、真实质量阈值审批与真实 baseline（均属 T009 人工门）。
- `diff --comparison cross_version` 等组合未逐一复测（T007 已验收，本包未改 report/baseline 逻辑）。
- “零真实调用”未做网络抓包；依据 runner 的 offline 硬校验、CLI 无 `.env` 读取与既有 spy/socket guard 全量通过。

## 对 T008b 的输入约束

1. 可直接用 CLI 命令做 p0-report：`dataset validate/build`、`run`（local/replay）、`gate [--calibrate]`、`baseline approve/list`、`diff`、`export`；参数面与退出码已实测（证据 01）。
2. 报告口径：默认配置 `gate=3`、`thresholds_unapproved`、cost `unknown`/分母 0、p95 有观测但质量 unknown；**不得写“质量通过”**，不得补零。真实 baseline 未建立，`diff` 必须写“baseline 未建立，待 T009”，不得自动建/复制/审批。
3. 不得声称“live→4 已端到端覆盖”：要么标 NOT-RUN，要么直接用 `evaluate_gate` 构造 live RunResult 并注明绕过 CLI manifest 校验。
4. `diff` 的退出码只等于当前 gate 码；发布是否放行必须读 `release_allowed` / `release_blocked_reason`（并确认 `require_release_baseline` 被调用）。`export` exit 0 不代表放行。
5. 证据位置：`docs/reports/OBS-EVAL/P0/evidence/verify/T008a/01-commands-exit-codes.txt`、`02-baseline-diff-export.txt`、`03-tests-boundaries.txt`；对象提交 `f2c0209`，8 文件均在 handoff §2 允许路径内，`var/eval/**` 未入库。
