# T207 第一步 A 包：实际执行证据采集契约 v0.1

- 版本：A 包离线契约，**默认关闭**；启用后才产生内存事件与仓外密文。
- 范围：产品边界观察（A1）、同实例独立 DB 投影（A2）、仓外认证密文与严格校验（A3）。
- **不授权**真实 H2、真实模型/产品发送、新计划/GO、四轴分类结论或任何质量通过声明。
- 本契约只描述采集与完整性；四轴逐题结论属 B 包，另行版本化。

## 1. A1 产品边界观察

模块：backend/src/mktkb/observability/evaluation_capture.py。

- capture_scope(sink) 是 contextvars 实现的可嵌套上下文管理器；退出必恢复上一层，异常路径同样恢复。
- emit_capture_event(kind, **payload) 在无活动 sink 时为 no-op；观察器自身错误不向产品抛错，只在 sink 上记固定 capture_error 并使 sink 失败。
- 固定事件种类（未知 kind/字段/类型/超限一律拒绝并令 sink 失败）：
  claim_observed、context_observed、context_message、entity_inheritance、query_state_observed、
  query_state_saved、query_state_cleared、plan_observed、retrieval_observed、model_input、
  model_output、answer_result、direct_rag_answer、commit_observed、capture_error。
- 事件只含白名单字段；不采认证头、token、cookie、网关对象 repr。
- R1 起固定事件携带完整原值：model_output 增加 provider_request_id/usage（完整
  CompletionOutput，raw_usage 依供应商契约不落盘）；direct_rag_answer 增加 facts（完整
  事实列表，不只 fact_count）；query_state_observed/saved/cleared 增加 state_json（原始
  持久状态键值，不只 state_keys）。
- sink 上限 MAX_EVENTS=4096；溢出记 capture_event_overflow 并失败，不静默丢弃后宣称成功。
- R1 起 CaptureSink/TurnCapture/EvidenceCaptureSession/EvidenceCaptureConfig/EvidenceWriter
  的 repr 采用严格白名单（只给状态/计数），不回显事件正文、题面/答案、Fernet key 或绑定字典。
- 产品 hook 仅最小修改：conversations/service.py（_load_context、_claim、_model_input 边界、
  _call_model、_answer 检索/计划事实、ask 结果、_commit_result_impl）、qa/service.py
  （answer 直接 RAG、候选层）、rag/index.py（QueryState 原始持久行身份/读写键）。

## 2. A2 同实例独立 DB 投影

模块：backend/src/mktkb/evaluation/p2_evidence_capture.py。

- EvidenceCaptureConfig(root_dir, bindings, fixture_kind, strict=True, writer=None)；
  fixture_kind 仅允许 local_mock（本包不伪造真实 GO/ledger）。
- 必须绑定键（缺一即配置失败）：run_id、plan_id、plan_sha256、dataset_version、
  manifest_sha256、label_version、suite、scenario_id、scenario_contract_sha256、
  assignment_sha256、custody_sha256、config_sha256、pipeline_version、index_revision、
  code_version、fixture_kind。
- EvidenceCaptureSession.bind(adapter_bindings) 在首个回合合并 adapter 的
  dataset/pipeline/index 实际身份；run/scenario/plan/custody/config 由调用方显式给出。
- 逐回合 TurnCapture：turn_index、client_request_id、conversation_id、
  authenticated_user_id（产品库真实用户 ID，不采用户名别名）、question_sha256、
  pre_revision、sink、started_utc。
- finish_turn 构造原始证据：capture 事件快照 + db_projection（同一隔离实例只读 session
  重新查询，不复制 hook payload）+ completeness。
- db_projection 固定字段：schema_version、snapshot_utc、pre_revision、capture_revision、
  conversation(owner/deleted/时间)、request(id/owner/status/attempt/client_request_id 摘要/
  user_message_id/result_message_id/error)、messages(owner/role/seq/kind/revision/text)、
  message_sources、units(unit_key/locator/text/raw_fields/date_fields/**entity_type/
  entity_key/entity_filters**/document_id/document_name/document_deleted/version_id/
  version_number/version_state/active_version_id/active/published_at)、
  unresolved_unit_ids(保留坏 ID 与 not_found)、query_states
  (原始 stored_user_id/stored_conversation_id/state_json/keys)、query_states_available、
  rag_business_date、**truncations**（显式截断码）、errors。
- R1 起 messages 只保留最近 60 条（长会话当前回合在末尾）；任何被裁剪/截断（messages_limit、
  message_text、units_limit、unit_text）都写入 truncations 并令完整性 incomplete，不得静默裁剪。
- 完整性：事件 seq 连续；claim 恰一条；非 replay 回合要求 claim_observed、context_observed、
  plan_observed、answer_result、commit_observed；model_input/model_output 按 purpose 配对；
  plan.path=rag 时要求 direct_rag_answer；请求/会话缺行、QueryState 不可读、revision 回退、
  超时均记 incomplete 固定错误码。replay 只要求 claim_observed(replay=true)。
- R1 起完整性还核对（任一不成立即 incomplete，不得继续发送）：
  - sink 失败状态/错误码（capture_sink_failed / capture_error:<code>）与投影截断；
  - context_observed 的 count/empty 与 context_message 条数一致，且 context_message 的
    owner/role/seq/text 与独立 DB 投影逐值一致、顺序递增、条数与历史用户消息尾部一致；
  - claim_observed 的 request/conversation/owner/authenticated user/user_message 与 DB 投影一致；
  - commit_observed 的 request/message id/seq/kind/text 与 DB 投影一致；
  - revision 同时点：pre/capture/post 三类 revision 必须齐全且 capture==post、
    claim.initial==pre、commit.revision_before/after==pre/post，无法取得即 revision_unavailable；
  - 直接 RAG：facts 完整、fact_count==len(facts)、fact.source_unit_id 必须 resolved/unresolved；
  - 实体继承：source_unit 的 entity_filters 与 entity_type/entity_key 一致，来源消息为前序 assistant；
  - model_input.context_questions 与实际上下文文本一致。
- strict=True 时任何非 complete 回合立即 blocked=True 并抛 EvidenceCaptureIncomplete；
  后续 turn 抛 EvidenceCaptureBlocked，不再发给产品。默认 capture 不启用时产品行为逐值不变。
- 公开摘要 public_capture_summary 只含固定计数/状态；不含题面、答案、题号、逐题 hash。

## 3. A3 仓外认证密文

模块：backend/src/mktkb/evaluation/p2_evidence_io.py。

- EvidenceWriter(root_dir, key, bindings, fixture_kind, max_envelope_bytes, run_name)：
  先严格校验 -> 规范化 JSON -> Fernet 加密 -> 仓外原子写 -> 立即读回校验；失败置 failed，
  清理临时文件并抛固定 EvidenceIOError。
- 目录规则：root 必须是仓外新目录；拒绝仓库内与旧封存根 D:/mktkb-p2-holdout；写入目标
  解析后必须仍在 root 下（防符号链接/junction 逃逸）；明文只留内存。
- turn envelope 顶层固定键：schema_version、fixture_kind、bindings、adapter_components、
  turn、capture、db_projection、completeness、sealed(写后回执)。
- manifest 顶层固定键：schema_version、fixture_kind、started_utc、bindings、
  adapter_components、summary、turns(公开摘要列表)、sealed。
- 校验拒绝：未知键、重复 JSON 键、非 UTF-8、NaN/Infinity、bool 冒充计数、坏 Fernet/
  截断密文、非连续/重复事件 seq、未知事件字段、跨 run/scenario 绑定不匹配、超过
  max_envelope_bytes、sealed 回执结构不符。
- R1 起严格按 schema 区分必需/可选字段：投影行缺 owner/FK/生命周期/原值等必需字段、
  嵌套坏类型（如 conversation.deleted 非 bool、usage 值非 int）一律拒绝；合法 null 必须
  以键存在 + null 值表达，缺字段与 null 明确区分；manifest 的 summary/公开 turns 行同样校验。
- sealed 阶段显式定义：`phase="pre_write"` 为 writer 入参/磁盘 envelope，禁止出现 sealed；
  `phase="post_write"` 为 writer 回执已附加的内存对象，必须带 sealed；读取器校验磁盘密文按
  pre_write（磁盘上没有回执，回执由会话侧内存附加）。
- read_encrypted_evidence(path, key, expected_bindings) 先解密验签，再校验 schema 与
  全部期望绑定，最后返回内存对象。
- verify_db_alignment(evidence) 是纯函数：只报原始一致性检查/固定 findings（owner、
  request/会话归属、上下文 owner、result message、unit 生命周期投影、QueryState 会话、
  revision 未回退），不产生任何四轴 verdict。
- 失败语义：任何回合写入/读回/完整性失败 -> session.blocked=True、保留已构造证据与
  固定失败状态、阻止后续发送；adapter.close 在 purge/封存前尝试写 manifest，失败仍
  执行清理并随后抛错（不为保全证据关闭 purge）。

## 4. 接线与默认不变

- ProductEvalAdapter 新增 evidence_capture 参数（默认 None）；start 时创建 session，
  首个回合绑定；ask_turn 内以 capture_scope 包住产品 HTTP 调用，结束后构造证据；
  默认关闭时无额外 session/事件/文件。
- p2_runner.run_p2 新增 evidence_capture 参数（默认 None），发送前调用
  adapter.enable_evidence_capture(config)；p2_live.build_live_adapter / run_live_p2
  透传；不允许在已有回合后启用。
- 不新增 CLI/常驻服务；不改真实 ledger/budget/旧 GO、冻结 schema/scenario/12 source。

## 5. 已知未覆盖（如实 NOT-VERIFIED）

- 本包不执行真实 H2、不读真实题面/标签/私有密文、不发真实模型/产品请求；不产生四轴
  真实结论；T207/P2 质量仍 BLOCKED。
- E2E 使用合成公开 fixtures 与 MockChatBackend；conflict 来自公开变体资料，intent
  query_expansion 分支以显式注入空检索合成触发；不冒称真实运行覆盖。
- holdout 封存/真实 GO/ledger 绑定未在本包验证；envelope 中 GO/ledger 均为 local_mock
  显式占位，不得当真实授权。
- real-mode 路径（p2_live 真实传输）未执行；仅验证参数接线与构造。

## 6. R1 修订（2026-11-12，T207 EVIDENCE-CAPTURE R1）

本版为 A 包 R1 最小修订（v0.1 契约内同步；B 包仍须按最终接收版读取）：

- 观察协议：新增字段 kind（opt_dict_int/json_obj/facts）如上；新增事件字段 model_output.
  provider_request_id/usage、direct_rag_answer.facts、query_state_observed/saved/cleared.
  state_json；全部仍属固定白名单，未知键/坏类型继续拒绝。
- 投影：新增 db_projection.truncations 与 units.entity_type/entity_key/entity_filters；
  messages 改为最近 60 条窗口并显式记录截断。
- 完整性签名：evaluate_completeness(events, projection, timed_out, capture_status=None,
  capture_errors=None, post_revision=None, authenticated_user_id=None)；build_turn_evidence
  自动传入 sink 状态/错误、post_revision 与 turn 身份。旧调用缺少这些参数时按 unavailable
  记 incomplete（不会静默 complete）。
- IO：validate_turn_evidence/validate_manifest 新增 phase 参数（pre_write/post_write/any，
  默认 any）；EvidenceWriter 写前用 pre_write，read_encrypted_evidence 对磁盘密文用 pre_write；
  内存回执对象用 post_write。schema 严格区分必需/可选/null。
- 秘密边界：异常消息只含固定码/字段名；EvidenceWriter 等 repr 不回显 key/正文。
- 边界不变：仍不授权真实 H2、真实模型/产品发送、新计划/GO、四轴结论。

## 7. R1-1 修订（2026-11-12，独立验收 3 项 FAIL 处置）

- 实体继承来源：entity_inheritance.source_message_id 必须是**同 conversation、同 owner、
  seq 早于本轮用户消息**的 assistant；缺失/非 assistant/非前序/跨会话/owner 不符均记固定
  incomplete 码。replay 回合用同一请求的 DB 投影 user_message 定位本轮边界；replay 本身不产生
  继承事件。
- fixture_kind：envelope/manifest 顶层 fixture_kind 必须存在、属于本包枚举（v0.1 仅
  local_mock）且与 bindings.fixture_kind 一致；live/未知值/混用一律拒绝（live 属 05 范围，
  本包不实现）。
- replay 语义：当且仅当唯一事件为 claim_observed(replay=true) 时 status="replayed"，不要求
  plan/context/answer/commit，strict 不阻断；被 replay 的请求在 DB 必须 succeeded；缺 claim
  或附带其它事件（伪造 replay）一律 incomplete。非 replay 严格性不变。
- writer 绑定一致性：EvidenceCaptureSession.finish_turn/finalize 在写盘前核验 writer 的
  首回合前已知绑定（run/scenario/plan/assignment/custody/config/code 等）必须与 session 一致，
  不一致固定失败并阻断，**不再静默覆盖**；仅 bind() 声明可合并的 adapter 身份键
  （dataset_version/manifest_sha256/label_version/suite/pipeline_version/index_revision）
  在同步时允许更新。



## 8. 05 live versioned 扩展（2026-11-13；fixture_kind=live_h2）

本节是 **追加**（v0.1 local_mock 语义/默认路径逐值不变），只服务受控真实入口
`tools/p2_h2_controlled_execute.py`；真实 H2 发送由 07 执行、独立复核由 08 执行。

### 8.1 枚举与 schema（强区分）

- `FIXTURE_KINDS=(local_mock, live_h2)`；live envelope/manifest 的 schema_version 固定
  `p2-hard-evidence-capture/v0.2-live`，local_mock 仍固定 `.../v0.1`，互不通用。
- live 在 v0.1 顶层键集上**只增加** `run_binding`（必填）；local_mock 出现该键即拒绝
  （unknown key），live 缺该键即拒绝（missing required）。
- bindings 仍是固定 16 键。live 配置期 `index_revision` 可为占位
  `pending_post_ingest`；`EvidenceCaptureSession.bind()` 必须用适配器实际 revision 覆盖，
  磁盘 envelope/manifest 的 index_revision 只允许十进制数字，否则 `live_index_revision_pending`。
  live 的 `finalize()` 在未绑定（无实际产品身份）时拒绝写 manifest。

### 8.2 run_binding（9 键，可独立复算）

`plan_sha256 / run_id / scenario_id / go_sha256 / ledger_sha256 / business_date /
code_version / config_sha256 / attempt_scope_sha256`。

- 除 business_date（YYYY-MM-DD）与 run_id/scenario_id（token）外均为 64 位小写 hex；
- 与 16 键 bindings 的 run_id/plan_sha256/scenario_id/code_version/config_sha256 **逐值一致**；
- `attempt_scope_sha256 = sha256(canonical{run_id, plan_sha256, scenario_id, go_sha256,
  ledger_sha256})`；08/复核方可用同 5 值复算，因此不能由调用方任意填写；
- 新增固定拒绝码：unsupported_fixture_kind / fixture_kind_mismatch / run_binding_required /
  run_binding_not_allowed / run_binding_unknown_keys / run_binding_missing /
  run_binding_hash_invalid / run_binding_token_invalid / run_binding_business_date_invalid /
  run_binding_mismatch / run_binding_scope_mismatch / live_index_revision_pending /
  envelope_schema_version_invalid / manifest_schema_version_invalid。

### 8.3 绑定来源与时点（不信任调用方字符串）

- `plan-private` 产出仓外私有 run-binding：holdout manifest/cases/source-map/annotation/
  review/addendum/scenario 的摘要 + config 摘要 + code 摘要 + business_date，以及四 run 的
  plan_id/run_id/plan_sha/scenario_binding/16 键绑定（index_revision 占位）。
- `run` 在 `open_live_gate` **之后**才填入 go_sha256/ledger_sha256/attempt_scope_sha256；
  `run_p2` 在 ingest/首个发送之前把 run binding 与本次 run_id、plan_sha、真实 gate 的
  GO/账本摘要、产品**实际** `rag_business_date`、code/config 逐值核对；不一致即
  `live_evidence_binding_mismatch`（零发送）。
- 证据 writer 在 `adapter.start()` 之后构造（factory），因此 index_revision/
  pipeline_version/business_date 取实际值；writer 首回合前已知绑定与 session 不一致仍固定
  拒绝（沿用 A-R1，不静默覆盖）。

### 8.4 落盘与封存时点

- 每回合 envelope 在回合结束即加密写入仓外证据根并读回校验；manifest 在 `adapter.close()`
  的 evidence_finalize 写出——早于 trace 删除与含题干业务库封存（purge 前封存）。
- 受控入口在 close 之后重新解密全部 turn + manifest，核对 turn_index/run_binding/状态计数，
  再对整 out_dir + 证据根做仓外只读归档（逐文件 sha256 + 树摘要 + seal manifest）。

### 8.5 边界（不授权）

live_h2 只表示"本 run 由受控真实入口产生并绑定了实际 GO/账本/代码/配置"，**不**表示已执行、
不产生四轴真实结论、不授权质量放行；真实 H2/真实 GO/ledger/供应商发送仍由 06/07 执行，
08 独立复核。

### 8.6 R1 修复（2026-11-13；A–E，additive，不改 §8.1–§8.5 语义）

本节只记录 05 R1 对**受控入口**的边界修订；不改 B 值、scenario contract、plan 公式、
冻结件、真 GO/账本/预算，也不改变 live_h2 envelope 的 16 键/9 键 schema。

**A. 凭据 / 运行环境分离（硬边界）**

- 授权 .env 只提供 6 个凭据键（MODEL_API_KEY/BASE_URL/NAME、DASHSCOPE_API_KEY、
  OCR_SECRET_ID/KEY）；产品自有的 CSRF/管理员密码/员工密码/可信来源/Cookie 键按真实
  .env 形状**忽略**（不进入内存映射）；未知键仍固定拒绝。
- holdout 根、holdout key 文件、项目总上限（40）只能由显式 CLI 参数
  `--holdout-root/--holdout-key-file/--project-total-limit-cny` 提供；同名键即便出现在
  .env 也会被剥离。进程内校验：根存在且在仓外、key 存在/仓外/44 位 Fernet、总上限=40；
  拒绝码 holdout_root_missing/invalid/inside_repo、holdout_key_file_missing/
  unreadable/invalid/inside_repo、project_total_limit_missing/mismatch。
- `--env-file` 对 plan-private 可选（不发送、不用凭据）；对 preflight/run/recompute 仍必需。
  DASHSCOPE_BASE_URL/OCR_REGION 不在必需集，缺省用产品默认（并与冻结 config 校验）。
- 旧 `tools/p2_live_execute.py` 默认拒绝 .env 的行为不变；不启用普通库 dotenv。

**B. chat 模型钉住**

- `applied_env` 把 MKTKB_MODEL_NAME 钉住为计划/契约 CHAT_MODEL=deepseek-flash；真实 .env
  的旧默认模型不生效；plan/preflight/run-receipt 的安全聚合记录 chat_model/model_pinned。
- 冻结 config 显式声明冲突模型时仍由 `_verify_env_against_config` 以
  env_chat_model_mismatch 拒绝；`load_live_env` 的 live_chat_model_not_authorized 保留为
  第二道固定码防线。

**C. 封存前清除明文派生物**

- run 结束、adapter.close 之后、seal 之前，受控入口删除本 run out_dir 内的
  data/（index DB 及 -wal/-shm/-journal、storage 上传原文件、observability）与 p2-run/
  （含 case_id/ingest 文档名的逐题元数据）；只保留 controlled/case-plan.json 这一安全回执。
- run receipt 记录 removed_paths（相对路径 + 删除前 sha256 + bytes）、removed_count/bytes、
  data_dir_removed/run_dir_removed、plaintext_scan（针数/文件数/命中路径，不回显文本）与
  plaintext_clean；任一步失败或最终扫描命中 -> plaintext_clean=false，不 seal。
- 封存目录只允许密文/安全聚合/索引哈希，不允许明文业务库；需要保留的含明文派生物必须
  加密进仓外证据根，不得明文留在封存目录。

**D. capture 失败归因**

- case plan 的 turn 状态固定为 executed / error / not_started：有加密回执的是 executed；
  已开始（含已发送）但没有回执的是 error（error 为固定码，如 evidence_capture_incomplete/
  adapter_error）；只有尚未开始的是 not_started。
- run receipt 记录 case_plan_started_turns/case_plan_failed_turn_code，ledger/回执仍可追；
  汇总 status 沿用 runner 的 aborted/blocked，不伪装成 succeeded。

**E. B 值来源与 06 前置**

- 四 run 的 index_embedding requests 只来自冻结 scenario contract（scenario_ingest_sha256
  绑定）；plan-private 显式输出每 run 的 index_embedding_allocation（item_id/requests/
  batches/source=frozen_scenario_contract/source_sha256），不从合成 corpus 重新推断。
- B=8/9/11/13 是真实 public fixtures 的四状态 embedding 请求实测（CUSTODY 的
  public_snapshot_preflight.py：sum(ceil(n/5))；public-snapshot-refined-preflight.json），
  不是合成 corpus 的 chunk 分布；06 必须用真实 public fixtures 复测四状态并确认
  <= 计划 B，否则停。该复测属 06，05 标 NOT-RUN。
