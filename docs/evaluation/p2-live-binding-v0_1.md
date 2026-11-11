# P2 真实准入绑定契约 v0.1（T206-PRE）

> 状态：**已实现并离线验证**（Mock dry-run，真实调用 0）。适用包：T203 运行器 / T205 评分与门禁。
> 本文件只规定「绑定与失败语义」，不改任何已冻结的分母、阈值、gate 版本与业务 API。

## 0. 为什么需要这份契约

T205 review §3 的两条限制（trace 无评测身份、产物无检索证据 id）与 R2 的 8 条非阻断发现
（①失败无产物 ②错误码只靠消息前缀 ③run_id 缺失可放行 ⑤probe 复跑写仓库）在**真实准入前**
必须补齐。本契约把「身份 / 证据 / 配置摘要 / 失败产物 / 错误码 / run_id」的绑定口径固定下来，
使 ``trace_integrity`` 能在 Mock dry-run 真 PASS，而**缺任何一项仍然 fail closed**。

## 1. 评测身份绑进 trace（trace identity）

六个字段（与冻结 ``TraceRecord`` 同名字段，不新增字段）：

| 字段 | 取值来源（P2） | gate 侧期望值 |
|---|---|---|
| `run_id` | `run_p2` 生成本次 run id（或调用方显式传入） | `run_manifest.run_id` |
| `dataset_version` | `P2RunDataset.identity.dataset_version`（H2 manifest 权威） | 同左 |
| `manifest_sha256` | `P2RunDataset.identity.manifest_sha256` | `run_manifest.corpus_manifest_sha256` |
| `pipeline_version` | `observability.versioning.pipeline_version()`（qa/rag/tokenizer 同一口径） | `run_manifest.pipeline_version` |
| `index_revision` | 灌库/发布完成后的产品 revision（`adapter.product_revision()`） | `run_manifest.index_revision` |
| `config_hash` | 本契约 §3 的**绑定摘要** | `run_manifest.config_hash` |

实现（additive，业务代码零改动）：

- `observability.tracer.trace_identity(**fields)`：在请求上下文的 contextvar 里绑定身份；
  只接受上述六个字段名，值 `str/int` 且非空，未知字段/空值 → `ValueError`；
- `start_trace` 在**创建时快照**该身份；组装 `TraceRecord` 时先落身份、再让业务 `annotate`
  覆盖（业务埋点优先，身份不能伪造未被埋点声明的字段）；
- `ProductEvalAdapter` 在 `create_app` 之后追加一个最外层 HTTP middleware，把绑定好的身份
  放进 contextvar —— 产品路由、业务服务、`main.py` 均未修改；
- **要么全绑、要么不绑**：`bind_trace_identity` 要求六字段齐全，缺一项整体拒绝；运行器在
  gate 身份缺失时**不绑**（记 `binding.missing`），trace 因此仍会 `version_binding` 失败。

证据（Mock dry-run 实测）：`test_mock_dry_run_binds_identity_and_passes_trace_integrity`
把真实 run 产物接进 `build_gate_run` + `evaluate_p2_hard_gates(require_trace=True)`，
`gate_status["trace_integrity"] == "pass"`；未绑身份时同一路径仍然 fail（见 §8）。

## 2. 引用证据 id（citation evidence）

产品响应里的 `sources[].source_id` 就是**来源单元 id**（unit 级）；评测侧在**产品返回之后**
用只读 SQL 把它解析成稳定证据身份，写入该轮的 `product.evidence`：

| 字段 | 含义 |
|---|---|
| `unit_id` | 来源单元 UUID（`source_units.id`，与产品 `source_id` 同一值） |
| `unit_key` / `locator` | 单元业务键与定位（sheet/row/heading/page…） |
| `document_id` / `version_id` / `version_number` | 所属文档与版本身份 |
| `state` / `active` | 版本状态、是否为该文档当前有效版本 |
| `in_run` | 该文档是否属于本次 run 灌入的文档集合 |
| `verified` / `reason` | 是否满足 `locator 非空 ∧ active ∧ published ∧ number≥1 ∧ in_run` |

判定（`p2_scoring.citation_evidence_status`）：

- 只对 `kind == "answer"` 的轮次要求证据；任一轮缺证据、任一引用未 `verified`、
  或整份产物没有作答轮 → `complete = False`（unknown），**不当通过**；
- `complete = True` 才允许调用方把 `citation_evidence_complete=True` 传给
  `evaluate_p2_gate`；判定默认值仍是 `False`；
- H2 聚合路径用 `include_case_ids=False` 输出（不含 case_id，符合"只出聚合"）。

**能力边界（如实）**：上表证明的是「引用落在本轮灌入的、当前有效的来源单元上，且带稳定
unit/locator/版本身份」。**「引用 ⊆ 本轮检索候选」由 R1 的检索候选接线负责**（见 §2b），
两者互不替代：证据 id 证明引用可核对，候选集合证明引用确实检索得到。本包**不新增 API
字段**：`SourceSummary`/`SourceView` 未改，解析在产品库侧只读完成。

## 2b. 检索候选（retrieved，R1）

产品没有暴露「这一轮返回给模型的候选集合」的 API。适配器因此**用产品自己的检索代码在同一
revision / 同一查询状态下重放一次**，把候选单元写进该轮的 `product.retrieved`
（`{document_name, unit_ids, unit_key, locator}`，按文档名/unit_key/unit_id 排序）：

| 轮次路径（trace `path`） | 候选来源 |
|---|---|
| `rag` | 发送前快照的持久查询状态 + 同一 lexicon/business_date/page_size → `parse_query` → `QaEngine.candidate_unit_ids`（只读） |
| `legacy` / `legacy_with_rag_candidates` | 产品同一意图解析（`conversations.intent.parse_question`，含 `_load_context` 上下文）+ 同一检索入口 `conversations.service._retrieve`（记录型问题带 rag 候选上界） |
| 非作答轮 / 路径未知 / 任一步失败 | 空（不猜、不补） |

判定（既有 gate `citation_required`，**未放宽**）：引用 unit 必须 ⊆ 该轮候选；候选为空或缺项
→ `citation_not_in_evidence`（fail）；非作答轮不要求引用。评分侧
`normalize_product_outcome` 只用 `product.retrieved` 填 `outcome.retrieved`（显式传入的
评测夹具候选优先）。

**诚实边界（mock 链）**：这是"重放"，不是产品内部那次调用的返回值（产品无该 API）。重放比产品
内部更窄时只会 fail-closed（引用被判不在候选内），不会更宽地放过引用；因此 pilot 若出现
`citation_not_in_evidence` 而人工复核认为引用合法，应按"候选重放口径不覆盖该轮上下文"处理，
不得改成"缺候选也算通过"。

**live 链的候选来源（T206-LIVE-R1/F6，零额外付费）**：live **不重放**。适配器从产品 answer
请求的 `CompletionInput.evidence`（产品本轮**实际交给模型**的证据集合，由
`GatedChatGateway` 在发送时捕获）取 `source_id`，再经产品库只读解析成同一身份结构
（`document_name/unit_ids/unit_key/locator`）。它既不是引用（引用取模型实际回的
`source_ids`，通常更少），也不是评测器另跑一次检索：候选就是"模型拿到的证据"。

| 轮次情形（live） | `product.retrieved` |
|---|---|
| legacy 作答轮（记录型/正文型，发生过 answer chat） | 该次 chat 请求的 `evidence`（捕获） |
| rag 内核直答轮 / 零付费轮 / 未捕获到 | 空 → `citation_required` fail-closed |

**live 不做付费重放**：任何"再检索一次"的重放都会真的再发一次 embedding/rerank（占计划项
配额并计费）。要这么做必须先补 replay 计划项 + 新 GO；在那之前 `retrieval_candidates()`
在 live 下直接拒绝（结构性闸门，`RuntimeError`），不会把付费调用静默记到旧计划项上。

## 3. config_hash（确定性绑定摘要）

```text
config_hash = sha256(canonical_json({
  binding_version, dataset_version, manifest_sha256, label_version,
  pipeline_version, index_revision, provider, gate_version, gate_config_hash
}))
```

- `p2_scoring.binding_config_hash`：组件规范化（去空白、键排序、类型收紧）后 canonical JSON
  → 64 位 hex；**同配置同 hash，任一组件变化必变**；
- `provider` 只含身份字段（provider/model/实现名/传输名），**不含调用计数**（否则每跑一次都变）；
- **索引身份**由 `index_revision`（产品 revision）+ `pipeline_version` 组件里的 rag schema /
  index cache / tokenizer 版本共同确定，不另立第二份"索引版本"；
- 缺任一组件（含 `gate_version`/`gate_config_hash`）→ `binding_input_missing`，不 quietly 跳过；
- 写入位置：`run_manifest.binding` + 顶层 `config_hash`、`summary.binding`、
  `gate.json.binding`；`P2GateDecision.binding_config_hash` 记录判定所依据的摘要
  （与 `P2GateDecision.config_hash`＝gate 配置摘要语义不同，不混用）；
- 门禁核对（`evaluate_p2_gate`）：`run_manifest.config_hash` 缺失 → `config_hash_unbound`；
  scorecard 声明的 `config_hash` 与之不一致 → `config_hash_binding_mismatch`；
  **scorecard 未声明 `config_hash`（manifest 有）→ `config_hash_unbound`**（R1：缺 ≠ 跳过核对，
  否则"不声明"就能绕过同源证明）；以上均 unknown 不放行；
- 因此**打分驱动（pilot）构造 scorecard 时必须显式传 `config_hash=run_manifest["config_hash"]`**
  （`score_public_suites(..., config_hash=...)` / `aggregate_holdout(..., config_hash=...)`），
  不传即被上面的门禁阻断——不是提示，是放行前提。

## 4. 失败也写产物

runner 的产物写入改为「先校验、后落盘，校验失败也落盘」：

| 场景 | 结果 |
|---|---|
| 发送后中止（产品 error / 超时 / 取消） | 照旧写 5 件套，`failure` 带 `stage/case_id/turn/item_id/ticket` |
| 产物校验失败（网络分解对不上、缺 detail） | 写 `run_manifest/summary/run_result/gate`（+ holdout 聚合），`status=aborted`、`stop_code=<稳定码>`、`failure.stage=artifact_validation`，然后**抛出**同一稳定码 |
| 校验未通过的网络计数 | `summary.network.available=false` + `code`；`summary.providers=null`；`gate.json.real_sends_allowed=false`（不把未核对计数当实测事实） |

## 5. 稳定错误码

| 码 | 触发点 |
|---|---|
| `provider_network_detail_mismatch` | 顶层出站 ≠ detail 汇总，或 detail 分解之和 ≠ 汇总，或 detail 缺失 |
| `run_id_missing` | `run_p2(run_id=...)` 传入空/非 str；门禁侧 manifest 缺 `run_id` → `run_binding_missing` |
| `binding_input_missing` / `binding_input_invalid` | `binding_config_hash` 组件缺失/为空/类型非法 |
| `artifact_validation_failed` | 预留：产物写入层面的失败（当前校验路径用上面的具体码） |

`P2RunError(ValueError)` 带 `.code`/`.detail`，消息以码开头（既有 `pytest.raises(match=...)` 仍成立）。

## 6. run_id 必填

- `run_p2` 显式给 `run_id` 时必须是**非空 str**，否则在**建 run 目录/发送之前**抛
  `P2RunError("run_id_missing")`；
- 不给则由 runner 生成 `p2run-<16 hex>`，并写入 manifest / 每条 trace / 每条请求行；
- `evaluate_p2_gate`：manifest 缺 `run_id` → `run_binding_missing`（unknown）；
  scorecard 声明了别的 run → 仍为 `run_binding_mismatch`。

## 7. 产物字段（additive）

新增/变化（旧键全部保留，键名不变的语义也不变）：

- `run_manifest.json`：顶层 `suite/dataset_version/dataset_sha256/corpus_manifest_sha256/
  business_date/index_revision/pipeline_version/gate_version/gate_config_hash/label_version/
  created_at/case_count/config_hash/dataset_path/trace_store`（可直接喂 `build_gate_run`）、
  `business_dates`、`binding`、`pipeline.trace.identity_bound`、公开 run 额外写 `dataset.jsonl`；
- `summary.json`：`binding`、`citation_evidence`、`network.available/code`；
- `gate.json`：`binding`、`citation_evidence`、`artifact_validation`、`failure`；
- `cases.jsonl`：每轮 `product.evidence`（引用证据 id）与 `product.retrieved`
  （本轮检索候选，R1；仅公开 run，H2 不写逐题行）。

**版本策略**：不升既有 `schema_version`（`p2-run-manifest/v0.1` 等）——只是**新增键**，
旧键名与语义一律不变（additionalProperties 兼容）；依赖新键的消费方必须同时校验
`binding.binding_version`（`p2-binding/v0.1`）。绑定公式的组件集合一旦变化就**必须**升
`P2_BINDING_VERSION`，否则同 hash 会被误当成同一份身份。

## 8. Fail-closed 矩阵

| 缺失/不一致 | 结果 |
|---|---|
| 未绑 trace 身份（run 原生清单不全） | 先被 `build_gate_run` 以 `run_manifest_incomplete` 拒绝（fail-closed，构建期） |
| 清单补全但 trace 未绑（或六字段为 None） | `trace_integrity` = `version_binding` 硬失败 |
| 只绑部分身份 | 整体不绑（`bind_trace_identity` 拒绝）；效果同前两行：先 `run_manifest_incomplete`，补全清单后 `version_binding` 失败 |
| 缺 `gate_version`/`gate_config_hash` | `binding.complete=false`、`trace_identity_bound=false`，门禁 `config_hash_unbound`/`gate_config_unbound` |
| 引用无 unit/locator/未核实 | `citation_evidence_status.complete=false` → `citation_evidence_unavailable` |
| 引用不在本轮检索候选内 / 没有候选 | `citation_required` = fail（`citation_not_in_evidence`），非 unknown、不放过 |
| scorecard 未声明 `config_hash`（manifest 有） | `config_hash_unbound`（unknown），不放行 |
| manifest 缺 `run_id` | `run_binding_missing`（unknown） |
| 网络分解不一致 | `provider_network_detail_mismatch`（抛错 + 失败产物） |

## 9. 零真实调用与边界

本包全部为离线：Mock 产品应用 + Mock provider + 隔离目录；真实调用 **0**、未读 `.env`/H1/H2、
未联网、未改 `fixtures/`/`gate.py`/`p2_ingestion.py`/业务 API。真实 live 链（`P2Gate` 预留与结算）
仍归 T206 正式 pilot，不在本契约范围内。

## 10. T206-LIVE 增补：live 装配的绑定与失败语义（additive）

本节只新增；§1–§9 的字段/公式/阈值不变。

### 10.0 显式模式

- `ProductEvalAdapter(mode="live", live_wiring=...)` 才构造真实 provider/真实 OCR 传输；
  **默认 `mode="mock"`**（T203 行为零变化：`is_mock=True`、离线替身、`_NoOcrGateway`）。
- `mode="live"` 缺 `live_wiring` 或 `mode="mock"` 带 wiring 都在构造期拒绝（配置期 fail closed）。

### 10.1 真实供应商身份（绑定摘要的 provider 段）

live 的 `binding_components().provider` 只放**身份**（不含凭据/计数）：

| 段 | 取值 |
|---|---|
| chat | `provider=deepseek / model=MKTKB_MODEL_NAME（必须等于已核 deepseek-flash）/ transport=<真实传输类名>` |
| embedding | `impl=GatedEmbeddingProvider / provider=bailian / model=text-embedding-v4` |
| rerank | `impl=GatedRerankProvider / provider=bailian / model=gte-rerank-v2` |
| ocr | `tencent:GeneralAccurateOCR（真实传输）` |

因此 live run 的 `config_hash` 与任何 Mock run 必然不同（provider 段不同），不会把两种链路
当成同一份身份。

### 10.2 环境变量（只列名字；值不进产物/日志/异常）

`MKTKB_MODEL_API_KEY`、`MKTKB_MODEL_BASE_URL`、`MKTKB_MODEL_NAME`、
`DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`（可选）、
`MKTKB_OCR_SECRET_ID`、`MKTKB_OCR_SECRET_KEY`、`MKTKB_OCR_REGION`（可选）、
`MKTKB_OCR_DISABLED`（必须不是 1）、`MKTKB_PROJECT_TOTAL_LIMIT_CNY`（门要求）。

缺任一项：`live_env_missing:<NAME>`（只给变量名）；`MKTKB_OCR_DISABLED=1`：`live_ocr_disabled`；
非白名单 chat 模型：`live_chat_model_not_authorized`。**不读 `.env`**：live 只认进程环境。

### 10.3 逐次尝试的身份绑定

每次底层发送（embedding/rerank/OCR/query_expansion）的 `UsageEvidence.request_sha256` 必须是
**预留时的** `request_sha256`（计划项身份 `_request_sha(item, run_id)`）；provider 自己的
payload 摘要另存进回执 `provider_request_sha256` 供审计。理由：资金身份是计划项，
payload 摘要不能替代它，也不能让同一计划项的不同 payload 互相顶账。

### 10.4 缺证据的失败语义

| 场景 | 结果 |
|---|---|
| chat 200 + usage 齐全 + 输出三判据成立 | `settle_success`（J1 重算；未用预留释放） |
| chat 200 + usage 齐全，但输出判据不成立（非 stop / 内容空 / 解析结构缺失） | J1 拒绝（`finish_reason_not_stop` / `content_incomplete` / `content_not_parsed`）→ 该笔按上界保守占用并**停止** |
| chat 200，但 usage 缺字段/缺 cache 拆分/超 cap | `usage_evidence_missing`（runner 停；该笔按上界保守占用，写 failed result） |
| 产品零付费结局（拒答/澄清/未找到/知识变更） | `close_unused`（保守占用、**不**停止；不是失败） |
| 从属尝试门拒绝 | `P2_PRE_SEND_REFUSED:<code>`（全额占用、门停止、HTTP=0） |
| 计划项配额用尽 | `attempt_quota_exhausted`（**发送前**拒绝；不新增预留） |
| 回执/中心/账本计数对不上 | `attempt_accounting_mismatch`（产物照写，状态 aborted） |

### 10.5 两条旧限制的现状（R1 更新，如实）

1. **不做付费的检索候选重放**：live 的 `retrieved` 改为从产品 answer 请求的 `evidence`
   捕获（§2b，零额外调用/零额外付费）。rag 内核直答轮、零付费轮次或捕获失败时仍为
   `retrieved=()`，gate 的 `citation_required` 照旧 fail-closed；要重放必须
   **新计划 + 新 GO**（补 replay 计划项），不得把"缺候选"改成"通过"。
2. **`query_expansion` 现在有独立资金身份（不再是"上界声明"）**：产品在
   `evidence.kind=="none"` 且有问题词项时**真实**调用模型（`conversations.service`）。
   live 把它接到计划项 `expand-*`（`operation=query_expansion`、
   `cost_center=answer_retrieval`、kind=chat）：
   `begin_attempt -> confirm_before_send -> 真实 POST -> settle_success(usage)`，
   预留/结算/成本中心/回执都按该项；同一轮只允许 1 次 answer chat，`answer-*` 不再被
   expansion 顶账。计划缺 `expand-*` 时该轮在发送前失败（不借用 answer 的钱）。

### 10.6 `output_valid` / `paid_attempt`（T207-FIX-B/C，additive）

`chat_usage_evidence(...)` 的 `output_valid` **不再是 dataclass 默认值**，而是由
`p2_live.chat_output_validity(output, purpose=...)` 用**这一份真实输出**算出的三判据：

| 判据 | 取值方式 | 不成立时 |
|---|---|---|
| `finish_reason == "stop"` | 输出对象自带该字段则按其值；不带时以客户端已受理为准（`DeepSeekClient._parse` 在返回前拒绝非 stop，`providers/deepseek.py:228`） | `finish_reason_not_stop` |
| 内容非空 | `output.text` 非空 | `content_incomplete` |
| JSON 解析成功 | purpose 对应的解析结构存在：answer=`source_ids`（字符串元组）、expansion=`query_terms`（字符串元组）——客户端解析 JSON 对象成功后才会构造它们（`providers/deepseek.py:240-273`） | `content_not_parsed` |

- 三条全成立才 `output_valid=True`；缺任一条件 → `False`，且 `chat_usage_evidence` 把同一判据写进
  `content_complete`/`content_parse_ok`，因此"输出不完整"不会按 usage 入账，而是保守留账并停止；
- 调用方必须显式传判据（`make_settle_evidence` 从 `TurnContext` 取、`query_expansion` 从输出取）；
  **缺省 = 无效**（fail closed），不存在"恒置 True 换结算"的路径；
- `paid_attempt=False` 是**轮次结局标签**（零付费：合法拒答/澄清/未找到/知识变更），**不是**输出无效，
  它对应 `close_unused`（`P2_NO_PAID_ATTEMPT:*`、全额保守留账、不停止）；
- 口径影响（如实）：chat 结算的**金额**本来就由 `finish/content/cache/usage` 决定（J1 的 chat 校验
  不读 `output_valid`，只有 embedding/rerank 的 `_validate_total_evidence` 读它），因此合法 usage 轮
  的金额在修复前后相同；本次修复消除的是"内容标志被硬编码成有效"的记账缺口 —— 无效输出从
  "按 usage 入账"改为"保守上界 + 停止"。

### 10.7 环境注入：`tools/p2_live_execute.py --env-file`（T207-FIX-A additive）

真实凭据只允许经**显式** `--env-file` 进入本次执行：

- 包装器自己读文件（模式 `KEY=VALUE`，支持 `#` 注释），只认白名单：
  `MKTKB_MODEL_API_KEY` / `MKTKB_MODEL_BASE_URL` / `MKTKB_MODEL_NAME` / `DASHSCOPE_API_KEY` /
  `DASHSCOPE_BASE_URL` / `MKTKB_OCR_SECRET_ID` / `MKTKB_OCR_SECRET_KEY` / `MKTKB_OCR_REGION` /
  `MKTKB_OCR_DISABLED` / `MKTKB_PROJECT_TOTAL_LIMIT_CNY` / `MKTKB_P2_HOLDOUT_ROOT` / `MKTKB_P2_HOLDOUT_KEY_FILE`；
- 未知变量名、重复名、空值 → fail closed（`env_name_not_allowed` / `env_name_duplicated` / `env_value_empty`），
  缺必需变量 → `env_required_missing`，**只报变量名**；
- 拒绝把名为 `.env`（或 `.env.*`）的文件当输入（`env_file_forbidden`）：不允许"顺手从工作区 .env 取凭据"；
- 注入只发生在**子进程**环境（父进程环境不变，且子进程环境先剔除同名旧值再写入），
  同时设 `MKTKB_NO_DOTENV=1`、并把 `backend/src` 放进子进程 `PYTHONPATH`；
- 输出只有变量名清单 + `values_printed=false` + 子进程退出码；任何路径都不打印/记录值
  （`EnvLoading.__repr__` 也把值标 `<redacted>`）。
