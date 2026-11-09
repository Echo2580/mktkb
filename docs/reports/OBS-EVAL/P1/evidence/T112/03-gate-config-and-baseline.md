# T112 证据 03：gate v0.2 配置契约与 live 授权边界

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. `docs/evaluation/gate_v0_2.json`（status=unapproved）

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
