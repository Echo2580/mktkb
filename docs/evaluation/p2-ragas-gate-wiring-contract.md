# E3 / T208 Gate 接线离线契约 v0.1

本包只补真实 `P2Gate` 方法与既有 Ragas 0.4.4 的离线装配。默认关闭；不是完整 T208、真实裁判校准、H2 验证或发布批准。E1 模块及其原契约保持字节不变。

```python
await score_ragas_with_p2_gate(
    run, plan=plan, gate=gate, judge=synthetic_transport,
    authorization=ragas_authorization,
    item_ids_by_case={case_id: six_unique_judge_item_ids},
    enabled=True, clock=clock,
)
```

- 一次只允许 **1 个**既有 `synthetic/public_fixture` case，明确拒绝多 case（`p2_single_case_required`）及 H2/holdout 来源。没有批次调度、产品答案生成或真实传输实现。
- 该 case 显式绑定 6 个唯一计划项；每项 `requests=1`、`operation=judge`、`cost_center=judge`、case/model 一致。拒答仍要求六项计划绑定，但不发送。
- 顺序固定为 Statement→NLI→Claim→NLI→Claim→NLI；第七次、并发/重入或序列不符在预留前停止。
- 同时校验 RagasAuthorization 的 run/plan/hash、judge 身份/版本，P2Gate authorization、实际 owning plan/ledger/run 与两个 Gate ledger guard 的归属；不能用旁置 DTO 冒充实际 Gate 绑定。
- Gate 必须尚未使用。账本必须在测试进程系统临时目录内，不能是软链或 evidence 路径；其实际账本/预算必须仍匹配 P2Gate 原固定路径常量。产品代码不修改任何路径常量，不提供绕过路径参数；只有测试 monkeypatch 原固定常量。

每个结构化调用执行现有 `P2Gate.begin(item_id)` → `confirm_before_send(ticket)` → synthetic `complete(prompt, response_model, ticket=ticket)` → `settle_success(ticket, evidence=UsageEvidence)`。每笔 item/request/reservation 唯一，结算沿用 `usage-conservative-v1`，不复制 Gate/账本会计。

传输声明 `execution_mode='synthetic'`、judge_id、judge_version、model，返回带 `content`（对应 response_model 实例）与 `evidence`（真实 UsageEvidence 类型）的对象。传输异常、缺用量、非法用量或结算拒绝均停止，自动重试 0；不伪造 usage 或释放保守预留。发送前授权失效不发送，原 Gate 保守落账。版本化结算已写 unknown 时不追加第二次 result。E1 外层次数/金额顶或框架失败造成评分未完成且已有调用时，也停止原 Gate。

结果 schema=`p2-ragas-gate-result/v0.1`，包含 E1 版本化 `score`、逐调用摘要 `calls`、`p2_cost`、固定原因码与 `retry_count=0`。`p2_cost` 是本次 Gate 合成调用的预留与保守结算；`score.cost` 是 E1 自身临时合成网关账，两者不相加、不代表真实供应商费用。摘要保留 run/plan/hash/item/request/reservation/model/judge_version/prompt摘要，不保存 prompt/答案/上下文/参考原文或自由异常文本。

默认关闭/前置拒绝/缺 Ragas 返回 blocked；调用中异常返回 unknown。除 E1 固定码外，接线码为 `wiring_disabled`、`p2_gate_missing`、`p2_binding_invalid`、`p2_binding_mismatch`、`p2_single_case_required`、`p2_synthetic_ledger_required`、`p2_gate_binding_mismatch`、`p2_gate_already_used`、`p2_item_binding_invalid`、`p2_gate_refused`、`nested_call_ceiling_exceeded`、`nested_sequence_invalid`、`usage_evidence_missing`、`usage_settlement_refused`、`wiring_internal_error`。发送后序列化失败也保留已有调用及保守资金摘要，不返回空审计。

`auxiliary_only=True`、`quality_decision=None`、`production_ready=False`；无 passed/release_ready 字段。高软分不清除 hard_failure，不抬升质量门。

验证只运行新定向文件，标准 asyncio.run、真实框架及真实 Gate、socket/DNS/httpx guard。真实 judge、真实价格/费用/GO、真实批次校准、H2 辅助评分、正式 T208 均 NOT-RUN。证据见 `docs/reports/OBS-EVAL/P2/T208-GATE-WIRING-OFFLINE/`；独立验收由另一上下文执行。
