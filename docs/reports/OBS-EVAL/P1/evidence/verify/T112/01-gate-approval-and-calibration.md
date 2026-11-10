# T112 独立验收证据 01：审批阈值与 gate 复跑

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 配置逐项核对（只读 `docs/evaluation/gate_v0_2.json`）

```text
status=approved  schema_version=mktkb.gate.config.v0.2  gate_version=mktkb.gate.v0.2
hard_gates 8 项与 gate_v0_1.json 逐项相同（Python 比较 == True）
suites=[b0,badcase,regression]（含 regression）
metrics=15（retrieval 5 / answer 5 / refusal 3 / runtime 2）
Recall@10 / MRR@10 / nDCG@10: min_sample=8, absolute_min=0.855, absolute_max=null, max_regression_pp=2.0
hard_filter_violation_rate: min_sample=8, absolute_min=null, absolute_max=0.02, max_regression_pp=2.0
empty_recall_rate: min_sample=8, absolute_min=null, absolute_max=0.145, max_regression_pp=2.0
answer/refusal/runtime 10 指标四字段全部 null（Python all(...)==True）
approval.approver=主人；approved_at=2026-11-09T19:54:00+08:00；scope/ reason 与 handoff §7 一致
sha256(gate_v0_2.json) R0 2A86D922… → R1 02012B04…；loader config_hash 5362de3c… → b5bfdb49…
```

## B. approved 配置 × R0 live run 现场重算（在 scratch 副本执行，避免改写交付 run）

```text
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate ^
  --run .claude\handoffs\_scratch\T112v\run --config docs\evaluation\gate_v0_2.json
gate exit_code=0 run_id=b0-live-20261109T111828086143Z-0efd058b suite=b0 mode=live
  scored=32/32 hard_failures=[] quality=pass config_status=approved
```

- `gate.json`：15 条质量结果全 `pass`；`min_sample` 8/32、8/24、8/8；`absolute_*` 全 pass；
  `max_regression_pp=skipped`（`no_baseline`）；`unknowns=0`；7 个不适用硬门禁显式
  `not_applicable`，`trace_integrity=pass`。
- 观测值：Recall/MRR/nDCG all=0.96875、exact=1.0、text=0.875；
  hard_filter all/exact/text=0；empty_recall all=0.03125、exact=0、text=0.125。
- 规范摘要 `sha256(canonical gate.json)=c9fcbbb67aa896f1024199fc4c61e931ae36b2df3038fe095897e37d4721742b`
  = `approval.json.gate_result_sha256`。

## C. 未审批副本负例（证明未审批 ≠ 通过）

用 `git show 7f46121:docs/evaluation/gate_v0_2.json` 的逐字节 R0 未审批配置
（sha `2A86D922…`）对同一 run 重算：

```text
gate exit_code=3 ... scored=32/32 hard_failures=[] quality=unknown config_status=unapproved
```

- 质量层逐条 `thresholds_unapproved` unknown，不伪造 pass；exit 3 不是 0。
- 未修改 R1 配置；负例只在 scratch 副本上执行。

## D. 校准可复现（未审批 R0 配置，连续两次）

```text
proposal1=0E7D641F2C12EDFF2C5EB5E342B4FA4D7324D14FA67BF8A45BEC4BAE441EC9BD
proposal2=0E7D641F2C12EDFF2C5EB5E342B4FA4D7324D14FA67BF8A45BEC4BAE441EC9BD
same=True
config_before=2A86D922... config_after=2A86D922... same=True
orig_proposal=0E7D641F... match=True
```

- proposal 与 R0 落盘 `gate_proposal.json` 逐字节一致；配置未被改写；
  `gate.py:3181` 的 `write_gate_proposal` 同时拒绝覆盖 v0.1/v0.2 配置。
- proposal 含 `run_id=b0-live-20261109T111828086143Z-0efd058b`、
  `gate_config_hash=5362de3c…`、strata=all/exact/text。
