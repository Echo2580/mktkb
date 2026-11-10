# T111 证据 02：pilot 成本（保守口径）

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

运行：`b0-live-20261108T194053896474Z-b224f9fb`（b0 前 10 题；`mode=live`、
`scope=retrieval_only`）。本文件只写估算与账本记录，**不写供应商实际账单**。

## A. 运行前预检（超限即拒绝）

```text
estimated_cny=0.2427765
  embedding_index_cny=0.0026115（6 文件 / 27 chunk / 7 个 batch）
  query_embedding_cny=0.0001650（10 题 × 1 次）
  rerank_cny=0.2400000（10 题 × 单请求预留上界 0.024）
total_requests=27（7 + 10 + 10）
max_single_reserve_cny=0.04096 ≤ GO max_request_cny=0.05
stage_remaining_cny=3.0；request_remaining=619
accepted=true；reasons=[]
```

估算口径：chunk 文本 UTF-8 字节数作 token 上界；embedding 按 0.5 元/百万 token、
rerank 按 0.8 元/百万 token；超过 settlement cap 的批次按整笔预留计。**是保守估算，
不是账单。**

## B. 共享账本（stage=P1-RETRIEVAL）

| 项 | before | after | delta |
| --- | ---: | ---: | ---: |
| stage_accounted_cny | 0.0 | 0.0026345 | **+0.0026345** |
| stage_remaining_cny | 3.0 | 2.9973655 | -0.0026345 |
| accounted_cny（全项目） | 15.0566296 | 15.0592641 | +0.0026345 |
| remaining_cny（全项目） | 4.9433704 | 4.9407359 | -0.0026345 |
| reservation_count | 381 | 408 | **+27** |
| result_count | 381 | 408 | +27 |

- 账本 delta 按 `run_id` 归属：`reserved` = embedding 17 / rerank 10 / chat 0；
  `result` = embedding 17 / rerank 10 / chat 0；27 笔结果全部 `succeeded`。
- 保守结算拆分：embedding 0.0010345 + rerank 0.0016 = **0.0026345 元**。
- 单笔最大预留 0.04096 元（embedding），≤ GO 单请求上限 0.05 元。
- `provider_billed_cny` 恒为 `null`（J1 约定）；供应商实账未知，报告不声称“实际账单”。

## C. 与预检的关系

预检 0.2427765 元是**最坏情况估算**（rerank 每题按 0.024 预留上界计）；
账本实际保守记录 0.0026345 元。两者相差主要因为 rerank 实际 usage 远低于请求预留上界，
embedding 实际 usage 也低于按字节数估算的上界。报告采用账本记录作为保守成本，
并保留预检作为“运行前拒绝超限”的闸门证据。

## D. 请求量级

```text
provider_requests.attempts = {"embedding": 17, "rerank": 10}
provider_requests.outcomes = {"embedding": {"response": 17}, "rerank": {"response": 10}}
```

17 = 索引 7 个 embedding batch + 10 题 query embedding；10 = 10 题 rerank；
chat=0。符合“索引 chunk 批次 + 10 题 × (1 query embed + 1 rerank)”量级，零重试
（每类 attempts == outcomes.response）。
