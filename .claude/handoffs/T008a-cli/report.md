# T008a CLI 与 P0 全流程 run（P0 第 13 包）开发报告

> 基线：`p0/obs-eval` @ `09ea77b`（纯簿记；代码基线 `08536ed` T007 R1）。本包单 commit `p0/T008a eval cli`（sha 见交付回执/`git log -1`），未 push。
> 真实 P0 baseline 未建立：`gate_v0_1.json` 仍 `unapproved`，T009 主人审批阈值后才建立；本包不自动批、不复制。

## 1. 完成内容

- `backend/src/mktkb/evaluation/cli.py`（515 行）：argparse 子命令 `dataset build|validate`、`run`、`gate [--calibrate]`、`baseline approve|list`、`diff`、`export`；退出码透传；无 `--allow-holdout-details`。
- `tools/rag_eval.py`（24 行）：薄包装，仅补 `backend/src` 到 `sys.path` 后转调 `cli.main()`。
- `backend/tests/evaluation/test_cli.py`（812 行 / 35 项）：子命令面、未知参数不抛栈、退出码 0/1/2/3/4 透传、calibrate 只写提案、approve 现场重算/拒绝、diff 必传 gate 并调 `require_release_baseline`、baseline 缺失 fail closed、render 返回值原样落盘。
- 证据 4 份：`docs/reports/OBS-EVAL/P0/evidence/T008a/01..04`。

## 2. §5 逐条自证（≤2 行/条）

1. **子命令齐全**：`cli.py:427` 注册 6 个命令；`test_cli.py::test_help_exits_zero_and_lists_every_subcommand`、`::test_allow_holdout_details_is_not_a_p0_option` 通过；未知子命令/参数走 argparse→`main` 捕获（`cli.py:491`），实测非 0 且无 Traceback。
2. **退出码透传**：`gate` 返回 `gate.exit_code`（`cli.py:222`）、`diff`（`cli.py:371`）、`baseline approve` 拒绝返回门禁码（`cli.py:262`）；`test_gate_exit_code_is_passed_through[0/1/2/3/4]`、`test_run_diff_export_exit_codes_cover_zero_one_three` 覆盖 0/1/3（4 另由参数化透传；真实 live 未跑，P0 禁止）。
3. **全流程真实跑通**：b0/badcase local + b0 replay 三件套齐全（01 证据 05–07）；默认配置 gate 三者均 exit 3、`hard_failures=[]`、`quality=unknown`、`config_status=unapproved`；`--calibrate` 写 45 行 `gate_proposal.json`（status unapproved）且 `gate_v0_1.json` 字节未变；%TEMP% 已审批演示配置下干净集 exit 0（01 证据 11）。
4. **敏感注入 → exit 1**：%TEMP% run 副本 + 临时数据集给 Q01 注入 `forbidden_values`；`gate` exit 1、`hard_failures=['security_leak']`、failure `Q01/forbidden_value`（03 证据一）。
5. **baseline 审批纪律**：缺 `--gate`/`--approver`/`--reason` 均 exit 2；声明 exit 0 的 gate JSON 被现场重算 exit 3 拒绝、`approval.json` 计数 0（03 证据二）；真实 baseline 缺失时 `diff` exit 3 + “baseline 未建立，待 T009”，未创建目录/未调 `save_baseline`（03 证据三）。
6. **测试与回归（策略 A）**：`test_cli.py` 35 passed；`backend/tests/evaluation` 313 passed；全量 `backend/tests` 1586 passed / 0 failed / 0 error（T007 基线 1551 + 35）；无新依赖、未读 `.env`、零真实调用。

## 3. 实际运行结果

```text
python -B tools\rag_eval.py --help                                                   -> 0
... dataset validate --suite b0 --path fixtures\evaluation\b0.jsonl                 -> 0  (cases=40)
... dataset build --b0 ... --badcase ... --out %TEMP%\t008a\dataset-build            -> 0  (40+13，只写 %TEMP%)
... run --suite b0 --mode local --out var\eval\runs\p0-b0                           -> 0
... run --suite badcase --mode local --out var\eval\runs\p0-badcase                  -> 0
... run --suite b0 --mode replay --from-run var\eval\runs\p0-b0 --out ...\p0-b0-replay -> 0
... gate --run ...\p0-b0 --config docs\evaluation\gate_v0_1.json --calibrate          -> 3
... gate --run ...\p0-badcase --config docs\evaluation\gate_v0_1.json                -> 3
... gate --run ...\p0-b0-replay --config docs\evaluation\gate_v0_1.json              -> 3
... gate --run ...\p0-b0 --config %TEMP%\t008a\gate-approved-fixture.json            -> 0  (仅演示，非审批)
... baseline approve （缺 --gate / --approver / --reason）                           -> 2 / 2 / 2
... baseline approve --gate <声明 exit 0>                                            -> 3（现场重算拒绝，无 approval.json）
... diff --run ...\p0-b0 （无 baseline）                                              -> 3（baseline 未建立，待 T009）
... diff --baseline c0ce2856938f --root %TEMP%\t008a\baselines                       -> 3（release_allowed=False）
... export --baseline c0ce2856938f --root %TEMP%\t008a\baselines                     -> 0（报告字节与 diff 一致）
pytest backend/tests/evaluation/test_cli.py                                          -> 35 passed (0.38s)
pytest backend/tests/evaluation                                                      -> 313 passed (9.70s)
pytest backend/tests                                                                 -> 1586 passed (341.83s / 0:05:41)
```

- 三件套路径：`var/eval/runs/p0-b0`、`p0-badcase`、`p0-b0-replay`；`run_id` 与产物 sha256 见 02 证据。
- proposal：`gate_proposal.json` status=unapproved、45 行、`gate_config_hash=eeb70a6c2d3b7c32fd6153194a8b93beb28464f9752ccd851192a7b0e0aac293`；未改 `gate_v0_1.json`。
- 报告：`report.md` 16106 B / `report.html` 23292 B，UTF-8 无 BOM；diff 与 export 逐字节相同；exit 3、`thresholds_unapproved`、cost 0 分母 unknown、p95 无 SLA unknown 原样呈现（04 证据）。
- commit stat：`git show --stat --oneline HEAD` 可复现；本 commit 只含 cli.py / rag_eval.py / test_cli.py + 4 证据 + 本报告。

## 4. 偏离与未做

- `export` 是报告层，成功落盘返回 0（即使当前 gate=3）；门禁是否放行由 `diff`/`gate` 的退出码表达，报告不参与门禁。若验收要求 `export` 也透传 gate 码，可一行改为 `return gate.exit_code`。
- 干净集 exit 0 用 `%TEMP%` 已审批演示配置（由 proposal 实测值派生、12 指标、不写仓库）；真实阈值审批仍属 T009，未伪造 `approval.json`、未建立真实 baseline。
- 未跑 live（P0 禁止）；退出码 4 只做了 CLI 透传参数化测试，真实 live 由 `evaluate_gate` 内部拒绝；退出码 2 的真实质量回退由 T006b 既有测试覆盖，本包未重复。
- 未做 T008b 的七条验收与 p0-report；未改既有 evaluation 模块/观测/业务代码/既有测试断言；未新增依赖、未 push。

## 5. 风险与遗留

- 报告中的 p95 受机器负载影响（本机 15/15/14ms）；T009 若把 p95 写成绝对阈值需稳定环境或 SLA。
- `cost_per_case_cny` 离线 local 零样本，持续 unknown；报告不补零，接入真实成本前不能作为放行指标。
- 真实 baseline 必须由 T009 审批阈值后，用同一 `approve_baseline`/CLI 路径建立；当前默认配置必然 exit 3 且被拒。
- 全量耗时 5:41；已知 flake `test_g08_short_budget_cancels_inflight_model_call` 本轮未命中。

## 交接摘要（≤10 行）

- 交付：`cli.py` / `rag_eval.py` / `test_cli.py`（35 项）+ 4 份证据 + 本报告；单 commit `p0/T008a eval cli`，未 push。
- 全流程：b0/badcase local + b0 replay 均 exit 0；默认 gate 三者 exit 3（硬门禁全过、质量 unknown）；calibrate 只写 proposal。
- 敏感注入 exit 1（security_leak）；approve 缺参数 exit 2、声明 exit 0 仍被现场重算 exit 3 拒绝且无 approval.json。
- 无 baseline 时 diff exit 3“baseline 未建立，待 T009”；未自动建/复制；真实 baseline 待 T009。
- 测试：35 + 313 + 1586（0 failed/0 error）；无新依赖、零真实调用、未读 `.env`。
