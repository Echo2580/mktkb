# T207 第一步 A-R2：实际执行证据采集契约 v0.2（T207-CAPTURE-CONTRACT-R2）

- 版本：`p2-hard-evidence-capture/v0.3`（local_mock）、`p2-hard-evidence-capture/v0.3-live`（live_h2）。
  旧 `.../v0.1`、`.../v0.2-live` 只读保持，**不升版本、不补字段、不改绑定**。
- 范围：在 v0.1/R1 语义之上增加**当次运行快照**（产品响应切片、trace 白名单、检索/使用来源），
  并把“采集完整 / 四轴可判 / 质量评分输入可重建”三者显式区分。
- 不授权：真实 H2、真实模型/产品发送、新计划/GO/ledger、四轴真实结论或任何质量通过声明。
  本契约只描述采集、保真与完整性；四轴规则见 `p2-hard-evidence-classification-v0_2.md`。

## 1. 版本与读写分发

| 对象 | 旧（只读） | 新（本包提供，显式选择） |
|---|---|---|
| local_mock envelope/manifest | `p2-hard-evidence-capture/v0.1` | `p2-hard-evidence-capture/v0.3` |
| live_h2 envelope/manifest | `p2-hard-evidence-capture/v0.2-live` | `p2-hard-evidence-capture/v0.3-live` |
| capture 事件块 | `mktkb.eval-capture/v0.1` | 同左（事件协议不变） |
| db_projection | `p2-hard-evidence-capture-db/v0.1` | 同左（投影字段不变） |
| runtime_snapshot | 不存在 | `p2-runtime-snapshot/v0.1` |

- **版本选择必须显式**：`EvidenceCaptureConfig.capture_schema_version=None`（旧调用）逐值保持旧默认
  （local_mock v0.1 / live_h2 v0.2-live，不写 `runtime_snapshot`）；只有显式选择 v0.3/v0.3-live
  才启用新契约。不允许静默升级旧调用，也不允许把 v0.3 字段集合放宽给 v0.1。
- `validate_turn_evidence(payload, *, expected_bindings=None, phase='any')` 与
  `read_encrypted_evidence(path, *, key, expected_bindings=...)` **签名不变**；按顶层
  `schema_version` 先分发，再用该版本自己的严格键集校验。旧版缺少新键**不是**新版的完整；
  新版缺少 `runtime_snapshot` 固定拒绝（`runtime_snapshot_required`）。任何版本都不接受
  “把 v0.3 键集当成 v0.1 放宽”或反向升级。
- v0.3/v0.3-live 顶层键 = v0.1/v0.2-live 顶层键 + `runtime_snapshot`（必填）。v0.3-live 仍必须带
  `run_binding`（9 键，语义与 v0.2-live §8.2 逐值一致）。v0.3 local_mock 出现 `run_binding`
  仍按 `run_binding_not_allowed` 拒绝。
- 磁盘密文恒为 `phase="pre_write"`（无 `sealed`）；写后回执只在会话内存对象上。writer 写前
  用 `pre_write`，读回用 `pre_write`，内存回执对象用 `post_write`。

## 2. 逐字段对账（任务 0 交付物）

`version_number` / `pagination` / `trace` / `retrieved` 在链路各层的已有情况：

| 层 | version_number | pagination | trace | retrieved |
|---|---|---|---|---|
| 产品响应 JSON | `sources[].version_number`（有） | `pagination`（枚举/分页回答才出现；可为 absent） | 响应头 `X-Trace-ID`（有） | 无“候选集合”字段；模型证据只在请求侧 |
| 观察事件 | 不单独记录 | 不记录 | 不记录 | `retrieval_observed.unit_ids`（实际检索轮次）；`model_input.evidence`（实际发送）；`direct_rag_answer.facts/cited_unit_ids`；`entity_inheritance` |
| 同实例 DB 投影 | `units.version_number/version_id/active_version_id`（有） | 无（分页是响应语义，不是 DB 行） | 无（trace 在独立库） | `units` + `message_sources`（引用身份，不是候选） |
| ProductTurn | `sources[].version_number` 在 `sources` dict 内（有） | **丢弃**（`as_dict` 无该键；`p2_scoring` 读到 `{}`） | `trace_id/path/outcome/status/spans`（有） | mock 路径为**事后重放** `retrieval_candidates()`；live 为实际模型证据 |
| 密文 envelope（旧） | 只在 DB 投影里（有） | **无** | **无** | 只在事件里（有） |
| 严格 reader（旧） | 有 | 无 | 无 | 有 |
| 重算输入（旧） | 有（投影） | **缺** | **缺** | 有（事件） |

结论（本包必须闭合的缺口）：

1. **G1 产品返回版本 vs DB 投影版本**：旧 envelope 只有投影侧的 `version_number`，无法证明
   “产品当时返回的是哪一版”。新 `runtime_snapshot.product_response.sources[]` 保全产品原值，
   完整性逐 source 与投影 `units` 交叉核对（不一致 → incomplete）。
2. **G2 分页**：产品响应/`AskResult` 有 `pagination`，旧链路全程丢弃。新快照按产品原值
   保全 `page/page_size/total/returned/has_more/next_page`，或显式 `absent`（真实未发生），
   不填空对象。
3. **G3 trace**：产品有 trace 身份与 span，旧 envelope 完全没有。新快照只保全白名单字段
   （trace_id/path/outcome/status/span 名/model_failure_reason），或显式 `absent`（配置未开启）。
4. **G4 候选/使用分层**：旧链路把 mock 的 `retrieval_candidates()` 重放当候选。新链路
   **不再重放**：候选只来自当次 `retrieval_observed` / 实际检索边界事件；发送证据来自
   `model_input.evidence`/`direct_rag_answer`；引用来自 `answer_result/commit_observed` 与
   `message_sources`；继承来自 `entity_inheritance`。四层分开，层名固定。

## 3. runtime_snapshot（唯一权威来源与跨层对应）

`runtime_snapshot` 是**当次回合结束时**对三类事实的封存切片，不是事后重建。每块有固定
`availability`/`reason`；顶层有 request/conversation/revision 绑定。

```text
runtime_snapshot = {
  schema_version: "p2-runtime-snapshot/v0.1",
  captured_utc: str,
  binding: {
    client_request_id: str, conversation_id: str,
    pre_revision: int|null, post_revision: int|null, capture_revision: int|null
  },
  product_response: {
    availability: "available"|"absent"|"unavailable",
    reason: str|null,                     # available 时必须 null
    request_id: str|null, message_id: str|null, kind: str|null, revision: int|null,
    http_status: int|null, timed_out: bool,
    sources: [ {source_id, document_name, version_number:int, status, locator:obj,
                published_at:str|null} ],           # 产品原序；不按 DB 重排
    pagination: {page, page_size, total, returned, has_more, next_page} | null,  # 原值或 null
    missing_fields: [str], error_code: str|null, retryable: bool
  },
  trace: {
    availability: "available"|"absent"|"unavailable",
    reason: str|null,                     # trace_disabled / trace_record_missing
    trace_id: str|null, path: str|null, outcome: str|null, status: str|null,
    spans: [str],                         # 只记录 span 名，按原序
    model_failure_reason: str|null        # 产品既有固定安全子因；无则 null
  },
  retrieval_use: {
    availability: "complete"|"partial"|"unavailable",
    reason: str|null,
    candidate_observation: {availability: "observed"|"not_observed", reason: str|null},
    candidates: [ {scope:str, candidate:bool, unit_ids:[str], truncated:bool,
                   empty:bool, seq:int} ],
    model_evidence: [ {purpose:str, unit_ids:[str], seq:int} ],
    direct_rag_facts: [ {entity_key:str, source_unit_id:str, doc_id:str,
                         version_id:str, revision:int} ],
    direct_rag_citations: [str], final_citations: [str],
    inheritance: [ {entity_type:str, entity_key:str, source_unit_id:str,
                    source_message_id:str|null, source:str} ]
  }
}
```

### 3.1 唯一权威来源

- `product_response`：唯一权威 = 该次产品 HTTP 响应体（adapter 在**同一次传输**后解析）。
  禁止用 DB 事后反查、禁止第二次请求、禁止从 `db_projection` 反填。`kind/text` 等已由
  `answer_result/commit_observed` 记录，快照只补充“产品返回了什么来源/分页/版本”。
- `trace`：唯一权威 = 产品 trace 存储中 `X-Trace-ID` 对应记录（同进程只读一次）。
  只允许上表字段；不得 dump 全部 span attributes、headers、cookies、token、provider repr 或原文。
- `retrieval_use`：唯一权威 = 当次 sink 事件（`retrieval_observed/model_input/direct_rag_answer/
  answer_result/commit_observed/entity_inheritance`）。快照是这些事件的**派生索引**；完整性逐项
  核对快照与事件相等，任一侧被改都固定 incomplete。层名固定：
  `candidate`（检索候选，不是使用）、`model_evidence`、`direct_rag_fact`、
  `direct_rag_citation`、`final_citation`、`inheritance`。

### 3.2 availability 语义（不得把“没观察到”当“空集”）

- `product_response.available`：已收到、可解析为对象、且带齐 `request_id/message_id/kind/revision`
  的响应（含 4xx/5xx 的产品 JSON）。`absent`：请求未发生或超时（同时 `timed_out=true`/
  http_status=null）。`unavailable`：响应体不可解析（非 JSON/非对象/空 body →
  `product_response_unparsable`）或阶段不可证。`available` 时 `reason` 必须为 null；
  `absent/unavailable` 必须有固定 reason。
- `trace.available`：取得 trace 记录。`absent`：产品未返回 `X-Trace-ID`（trace 未开启，
  合法如实记录）。`unavailable`：有 trace_id 但记录缺失/读取失败。
- `retrieval_use.complete`：回合正常完成（响应已收到、未超时、sink 非 failed），观察窗口覆盖
  全程；每个层的空列表因此表示“确实没有该层使用”。`partial`：超时/中止/写入前失败，但已发生的
  事件保留。`unavailable`：replay，或观察未建立。**partial/unavailable 不因列表为空而变成空集证据。**
- `retrieval_use.candidate_observation`：`observed` 当且仅当本回合有 `retrieval_observed`
  事件；否则 `not_observed` 并给固定 reason（RAG 内部检索不可观察为
  `candidate_layer_not_observed`，其它为 `no_retrieval_observed`，replay 为 `replay`）。
  `not_observed` 的 `candidates=[]` **不是**“空候选”证据。

### 3.3 身份与时点约束

- `binding` 与本轮 `turn.client_request_id/conversation_id/pre_revision/post_revision` 逐值相等。
- `product_response.available` 时，`request_id/message_id/kind/revision` **必须非空**，并与
  `claim_observed/commit_observed/answer_result` 的对应值逐值一致；缺失记
  `runtime_product_response_incomplete`，不一致记 `runtime_product_response_inconsistent`。
  不允许“缺字段就跳过比较”。
- `sources` 必须是响应里存在的 list（缺键或 null → `product_sources_invalid`），不得静默映射为
  `[]`。每个 `sources[]` 必须在 `db_projection.units` 解析到同一 `unit_id`，且
  `version_number/document_name` 与产品返回逐值相等；解析不到 → `unresolved_unit_ids`
  按既有规则保留，但产品来源未解析固定 incomplete。
- `pagination` 出现时 `page/page_size/total/returned` 为 int、`has_more` 为 bool、
  `next_page` 为 int|null；且 `page>=1`、`page_size>=1`、`0<=returned<=total`、
  `has_more` 与 `next_page` 互斥一致。产品未返回分页 → `null`（真实 absent），不得填 0/空对象。
- 修订变化：快照只描述该次响应时点；若 `post_revision != capture_revision` 或
  `revision` 回退，按既有 `revision_snapshot_mismatch/revision_unstable` incomplete。
  禁止用稍后“当前版本”回填来源版本。

## 4. 完整性（evaluate_completeness 增补，v0.3）

在 v0.1/R1 全部检查不变的前提下新增（任一不成立 → incomplete，固定错误码）：

- `runtime_snapshot_missing` / `runtime_snapshot_schema_invalid`（键/类型/版本）。
- `runtime_snapshot_binding_mismatch`（binding 与 turn 不一致）。
- `runtime_product_response_missing`：回合正常结束却无 available 产品响应；
  `runtime_product_response_incomplete`：available 但缺 `request_id/message_id/kind/revision`；
  `runtime_product_response_inconsistent`：身份/来源/分页与事件或投影不一致。
- `runtime_source_unresolved` / `runtime_projection_version_mismatch` / `runtime_pagination_invalid`
  （含 `page/page_size>=1`、`0<=returned<=total`、`has_more` 与 `next_page` 一致）。
  语义非法的分页由 builder 记 `unavailable/runtime_pagination_invalid`（保留真实阶段、仍可落盘），
  完整性固定 incomplete；不得让严格 writer 把整条证据拒掉而丢失现场。
- 已提交的最终引用（`commit_observed.source_ids`）必须被产品返回的 `sources` 覆盖；
  两份来源集合矛盾 → `runtime_product_response_inconsistent`，不能“都算真”。
- `runtime_trace_unresolved`：有 trace_id 却 unavailable；`absent` 不判 incomplete，但记入
  `scoring_readiness`。
- `runtime_usage_inconsistent`：快照派生索引与事件不逐值相等；`runtime_usage_partial`：
  `retrieval_use.partial`（超时/中止的真实阶段保留，不冒充空集或成功）；
  `runtime_candidate_observation_inconsistent`：候选观察标记与事件不一致。

`completeness` 新增只读块：

```text
scoring_readiness = {
  four_axis: bool,                 # status=complete 且观察覆盖完整
  quality_rescore: bool,           # four_axis 且 product_response available 且 trace != unavailable
  reasons: [str]                   # 固定码；quality_rescore=false 时非空
}
```

- `four_axis=false` 时仍可能“协议合法”（例如 trace 未开启但四轴证据齐全）——两者分开。
- `quality_rescore=true` **不**声明真实质量通过、不声明 production_ready；只表示该回合的原始
  评分输入可重建。真实质量重评分属任务 C；本包不执行评分。

## 5. 采集时点与防止重放（A5/R11 边界）

- `finish_turn` 仍在同一请求返回后、trace/业务库封存或下一轮推进**之前**执行：事件快照 →
  同实例只读 DB 投影 → runtime_snapshot（产品响应/trace/派生索引）→ 完整性 → 加密写盘 →
  读回校验。
- 采集链**禁止**再调用产品检索、模型或任何搜索来补证据；`runtime_snapshot` 只消费该次
  响应、该次事件、该次 trace 记录。
- 评测器的 `retrieval_candidates()` 重放在**采集启用时不再参与**该轮评估候选：候选只取该轮
  `retrieval_use.candidates`（实际观察）。关闭采集时旧行为逐值不变（loose compatibility）。
- 产品不可观察的内部 RAG 检索候选（引擎内部 search）不伪造：该轮
  `candidate_observation.availability="not_observed"`、`reason="candidate_layer_not_observed"`，
  `candidates=[]` 不得被当成“空候选”通过；B/验收按 NOT-RUN 记录（见 §8）。

## 6. 秘密边界

- 原文（题面/答案/来源正文/trace 属性/provider 对象）只允许出现在**认证密文**与进程内。
- `runtime_snapshot` 不含 headers/cookies/token/连接串/repr/整库 dump；trace 只允许 §3 白名单。
- 公开摘要 `public_capture_summary` 只增固定计数：`runtime_product_response_present`、
  `runtime_trace_status`（available/absent/unavailable）、`runtime_usage_status`
  （complete/partial/unavailable）、`scoring_quality_rescore`（bool）。不含题面/答案/ID/hash。
- repr/异常/日志只含固定码与字段名，不回显值。

## 7. 兼容矩阵

| 产物 | 写入版本 | 旧 reader | 新 reader | 备注 |
|---|---|---|---|---|
| v0.1 local_mock | 旧调用默认 | 支持 | 支持（原语义） | 不补字段/不升级 |
| v0.2-live | 旧调用默认（live） | 支持 | 支持（原语义） | 同上 |
| v0.3 local_mock | 显式选择 | 固定拒绝 `envelope_schema_version_invalid` | 支持 | 必须含 runtime_snapshot |
| v0.3-live | 显式选择 | 固定拒绝 | 支持 | 仍必须含 run_binding |
| manifest 同上 | 同 envelope | 同上 | 同上 | summary 不含正文 |

- CLI 读取：`p2-hard-evidence-recompute` 通过 `read_encrypted_evidence` 自动分发；
  旧 `tools/p2_h2_historical_audit.py` 只放行 v0.1/v0.2-live，遇 v0.3* 固定
  `unsupported_evidence_schema`（不静默降级、不忽略新键）。
- 旧产物不得被追加字段、改版本或重绑；新协议不声明旧 run 的评分 readiness。
- **v0.3 版本内说明**：`candidate_observation` 属于本包最终接收 schema 的一部分；A-I 首轮
  开发对象未在仓外保留任何 v0.3 密文（开发/验收均为临时目录、已清理），故不存在需要
  “事后补字段”的旧 v0.3 产物；首轮对象按 superseded 记录，不作为兼容对象。

## 8. 已知未覆盖（NOT-RUN / NOT-VERIFIED）

- 真实 H2/真实 GO/ledger/预算/凭据/preflight 全部未执行；本包零真实外连。
- 真实产品 RAG 引擎内部检索候选不可观察：新版本把该层标为
  `candidate_layer_not_observed`，不以重放补；相关正式路径验收 NOT-RUN。
- trace 的评分必要性取决于未来目标评分定义；本包只区分 `quality_rescore` readiness，
  不实现真实质量重评分。
- live_h2 正式格式链路由任务 C 用合成传输验证；A 包只验证构造与读写分发。
