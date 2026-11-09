# T112 证据 03：gate v0.2 配置契约与 live 授权边界

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. `docs/evaluation/gate_v0_2.json`（R0 快照：status=unapproved；R1 审批变更见 §E）

```text
schema_version=mktkb.gate.config.v0.2  gate_version=mktkb.gate.v0.2  status=unapproved
hard_gates=8 项（与 v0.1 逐项相同）
hard_gate_min_sample={b0:32, badcase:13, regression:7}
suites=[b0, badcase, regression]
metrics=15（retrieval 5 / answer 5 / refusal 3 / runtime 2），
  每条显式含 min_sample / absolute_min / absolute_max / max_regression_pp（当前 null）
sha256(gate_v0_2.json)=2A86D922394AA34671D54AA1E59C0D3F1AEDB74B1A23A9FC953FEA4B531F3C10
```

解析/校验（`gate.py:381` `load_gate_config`）：schema 与 gate_version 必须成对；
v0.2 必须声明 `suites` 且含 `regression`（`:404`）、metrics 必须覆盖 design §8.2
检索 5 指标且方向正确、四个阈值字段不得缺省；非法一律 `ValueError`（fail closed）。
v0.1 配置仍按原路径加载（`suites=()`，15 指标），P0 行为不变。

## B. live + retrieval_only 判定（v0.2 才放行）

- `evaluate_gate`：`mode=live` 只有 `scope=retrieval_only` **且** config
  `gate_version=mktkb.gate.v0.2` 才进入判定（`gate.py:3255`）；否则维持 P0
  `exit_code=4`（`gate.py:3270`），既有测试 `test_live_mode_exits_four` 全绿。
- retrieval_only 下不生成答案：`conflict_not_rejected` / `exact_value_contract` /
  `pagination_contract` / `citation_required` 显式 `not_applicable` 并写 warning
  （`gate.py:3465`）；`security_leak` / `cross_entity` / `stale_bypass` 按检索证据评估。
- `trace_integrity`：retrieval_only 只要求核心检索 Span `{recall, fuse}`（不要求
  `parse/answer/commit`，`gate.py:1907`），版本绑定/条件 Span 校验不变。
- 质量层：retrieval_only 只评估 retrieval 组（`gate.py:2771`），答案/拒答/运行指标
  不参与、不伪造观测；未审批 → 每条 `thresholds_unapproved` unknown。

## C. 全量 live 授权守卫（默认关闭，原行为不变）

- `live.py:677` `validate_full_live_dataset`：仅 `suite=b0` + 数据集与冻结
  `fixtures/evaluation/b0.jsonl` **字节级 sha256 一致** + 恰好 40 题；三者任一不符
  `LiveConfigError`（不建索引、不预留、不发请求）。
- CLI `--allow-full-live`（`live.py:802`）默认 false；与 `--pilot` 互斥。默认关闭时
  40 题数据集仍在 GO/凭据检查前被拒（exit 3，`test_live_cli_without_allow_full_live_refuses_before_go`）。
- `runner.py:1052` 只在开关打开时调用守卫；manifest `gate_version=mktkb.gate.v0.2`
  （`:1154`，仅 live 分支；local/replay 仍 `mktkb.gate.v0.1`）。

## D. P1 release baseline 身份/审批边界

- `baseline.py:150`：`mode=live` 只允许绑定 `gate_version=mktkb.gate.v0.2`；
  P0 gate v0.1 的 live manifest 仍拒绝建立 baseline（既有 `test_baseline.py` 不变）。
- `baseline_id` 仍是六字段 `dataset_version+pipeline_version+mode+scope+gate_version+
  corpus_sha256` 的 sha256[:12]；无 copy/rename API；跨版本只分析。
- `baseline approve` 现场重算门禁；`status=unapproved` / `exit_code≠0` / 缺
  approver/reason 一律拒绝且不写 `approval.json`。R0 **未**执行 approve（前置条件
  未满足：gate exit 3 + config unapproved）。
- 测试用临时 approved 副本覆盖“接受路径”：`approve_baseline` 写入
  `baseline.json` + `approval.json`，`load_baseline(expected=...)` 往返通过
  （`test_baseline_approve_accepts_approved_live_gate`）。仓库配置未改。

## E. R1 审批落盘（2026-11-09 20:00 +08:00，主人书面批准）

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

依据：`prompts/T112-dev-R1.md` + `handoff.md §7`（主人 2026-11-09 19:54 +08:00 批准，审批人=主人）。只落盘批准值；R0 校准证据 02 未改（`gate_proposal.json` 仍 `0E7D641F…`）。

### E1. 配置（只改 status/阈值/审批元数据）

```text
docs/evaluation/gate_v0_2.json
status: unapproved -> approved（仅检索层；answer/refusal/runtime 10 指标阈值保持 null）
sha256: 2A86D922394AA34671D54AA1E59C0D3F1AEDB74B1A23A9FC953FEA4B531F3C10 (R0)
     -> 02012B048A32BC04F61A8454A69FBFA7C6F40C2F0B333688CE0B87DD0FF39A70 (R1)
loader config_hash: 5362de3c3a8f258adfaa779e6b237bd1fb22d03d4eb74c36c93bd9808a6af482 (R0)
                  -> b5bfdb49e5dff249d05185d7dfc3edced346037a7df20ec787758a4b3ce24481 (R1)
```

- 检索 5 指标：`min_sample=8`；Recall/MRR/nDCG `absolute_min=0.855`、`absolute_max=null`；
  hard_filter `absolute_max=0.02`；empty_recall `absolute_max=0.145`；三项均 `max_regression_pp=2.0`。
- 顶层 `approval`（审计/溯源，`load_gate_config` 不读取该对象）：`approver=主人`、
  `approved_at=2026-11-09T19:54:00+08:00`、`scope=retrieval_only`、reason 见批准记录。
- 8 项硬门禁、`suites`、15 metrics 骨架未变；`quality_layer.status=approved` +
  `approval_scope=retrieval_only（answer/refusal/runtime 未批准）`。
- **哈希口径**：loader 的 `config_hash` 覆盖整份 JSON，审批后必然变化；R0 proposal/主人
  批准记录里的 `5362de3c…` 是审批前字节，不参与 baseline 六要素身份；`approval.json`
  绑定的是门禁结果 `gate_result_sha256`，不是配置哈希。

### E2. gate exit 0（approved 配置 × R0 live run）

```text
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate ^
  --run var\eval\runs\b0-live-20261109T111828086143Z-0efd058b ^
  --config docs\evaluation\gate_v0_2.json
gate exit_code=0 run_id=b0-live-20261109T111828086143Z-0efd058b suite=b0 mode=live
  scored=32/32 hard_failures=[] quality=pass config_status=approved
```

- 质量层 15 条（5 指标 × all/exact/text）全 `pass`；`min_sample` 全 pass（8/32、8/24、8/8）、
  `absolute_*` 全 pass、`max_regression_pp=skipped`（首次 baseline 无对照）；
  0 quality failures / 0 unknowns。
- 硬门禁：`trace_integrity=pass`，其余 7 项 `not_applicable`（retrieval_only），`hard_failures=[]`。
- `gate.json` sha256 `DA208E34EB15CB98CC38BC4CEEA9558C4D7875CE7B3E1A118F7EADAECE36C1E7`
  （R0 为 exit 3 的 `89DDCE23…`；仅该派生产物被 gate 重写，见 E3 产物摘要）。

### E3. baseline approve

```text
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline approve ^
  --run var\eval\runs\b0-live-20261109T111828086143Z-0efd058b ^
  --gate var\eval\runs\b0-live-20261109T111828086143Z-0efd058b\gate.json ^
  --config docs\evaluation\gate_v0_2.json --approver "主人" ^
  --reason "P1 首次 release baseline（b0 live 40 题）；绝对阈值按 T112 校准提案批准；首次建立不做回退检测"
现场重算 gate exit_code=0（--gate 声明 exit_code=0；仅审计，不作为审批依据）
baseline approved baseline_id=bc6f6f906db1 run_id=b0-live-20261109T111828086143Z-0efd058b approver=主人
```

- `baseline_id=bc6f6f906db1`；六要素 = `b0:b0-2026-11-04:bd4f0f7ccc6e` / `08166b113481` /
  `live` / `retrieval_only` / `mktkb.gate.v0.2` / `68899152…`。
- 审批文件：`var/eval/baselines/bc6f6f906db1/approval.json`，sha256
  `80113647D0B640D37B3F6C86C6B67758DE7E907F51E3A6FF47DC42B1AF9AAD43`；
  `gate_exit_code=0`、`quality_status=pass`、`gate_result_sha256=c9fcbb…`、approver=主人。
- `baseline.json` sha256 `1924FAF86FAD52D4495F07C64E2DB1A9262A1299A2B0817FE9D604DE3AD6B07A`；
  `artifact_sha256` 与 run 的 manifest/cases/summary 逐一相等。
- `baseline list`：`baseline_id=bc6f6f906db1 run_id=… suite=b0 pipeline_version=08166b113481 approved=yes`（exit 0）。
- P0 baseline：审批前 `var/eval/baselines` 不存在（本 workspace 无 P0 baseline 产物）；
  审批后仅 `bc6f6f906db1` 一条 → 未创建/未 copy/未影响 P0 baseline。
- live 产物未动：`run_manifest.json` `010E6CC0…`、`cases.jsonl` `0A4BA7FB…`、`summary.json`
  `F8542E66…` 与 R0 一致；`gate_proposal.json` 未改写（`0E7D641F…`）。

### E4. 测试与合规

```text
pytest backend/tests/evaluation/test_t112_gate_baseline.py -> 13 passed
pytest backend/tests/evaluation                            -> 433 passed（211.85s）
pytest backend/tests                                       -> 1933 passed, 1 warning（571.04s；0 failed/0 error）
```

- R0 的 3 处测试因仓库配置转 approved 而更新：契约测试断言批准值与审批元数据；
  原「unapproved → unknown/exit 3」「unapproved 拒绝审批」改用临时未审批副本，
  覆盖未删、无 skip/xfail/删断言。
- 零真实模型/embedding/rerank/OCR；未写账本/GO；未改业务代码/API/fixtures/P0 gate/baseline；
  未读 `.env`/Holdout；未 push/amend。