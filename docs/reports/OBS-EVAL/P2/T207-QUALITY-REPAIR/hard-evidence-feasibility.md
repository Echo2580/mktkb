# T207 四类硬失败证据可行性审计

主人，结论：可以实现受控、确定性、可复核的四轴分类，但当前材料不足以证明四类真实硬失败为 0。SAFE-DIAG 的 checked=0、unknown=planned 应保留；writer 计数修复不能关闭此缺口。本报告只给实施方案，不是开发交付、独立验收或真实 H2 结果。

- 基线：2026-11-11，HEAD `09ddc87520576958ff4c19be16f245f8197fdfe5`，存在他人进行中的修改；下面行号为本次只读工作树观察位置。
- 本次仅阅读源码与公开协议定义；未读取真实 H2 题号、题干、答案、逐题 trace、封存资料；未调用模型/网络、运行测试或修改实现/契约/账本。
- 完成目标不变：真实 H2 ≥24/30，错误与未执行均为 0，四轴真实 violations=0，且所有适用项证据完整；unknown 不转 0，N/A 不能替代覆盖。

## 1. 已有字段与可以复用的 owner

| owner / 源码位置 | 现有事实 | 不足 |
|---|---|---|
| `conversations/service.py:152,406,447` | `_load_conversation` / `_claim` 核 `Conversation.user_id`；`_load_context` 只取同 conversation、当前 seq 之前的问题及上一助手引用所带实体 | 模型输入仅有问题字符串和实体值，没有上下文消息 ID / owner provenance 回执 |
| `conversations/service.py:1864` | `_model_input` 构造实际 `CompletionInput.context.questions/entities` 与 `ModelEvidence.source_id/text/fields` | 不能由只有 source ID 的现有采集反推出完整 context |
| `p2_live.py:1159,1191` | `answer_chat_before_send` / `_capture_retrieved` 在真实发送前取 actual answer evidence IDs | 未保存完整 context、实体目标、时间条件；空集合无法区分明确为空与未采集；非 answer purpose 也须说明 |
| `product_adapter.py:1527,1664,1765,2135` | `citation_evidence` 核 DB unit/version/document、active、published、in_run；`_live_retrieved` 取上述实际 evidence；`_resolve_retrieved_units` 返回 document_name、unit IDs、unit_key、locator | citation verified 未检查 document.deleted / 业务有效期；retrieved 解析失败会丢项；仅 kind=answer 采集，不能证明 conflict、拒答或模型校验失败轮从未检索/发送 |
| `sources/service.py:31,99`；`documents/lifecycle.py:76` | 消息 owner 校验；`status_of` / `visible_source_units_stmt` 共同要求未删除、当前 active version、published | 来源详情的历史 410 不等于作答当时引用失效；必须带时点与 revision |
| `qa/service.py:211,416`；`rag/index.py:578` | `_read_manifest` 只索引公开有效版本；`prepare` 用实际 user/conversation 加载状态；状态主键为二者组合 | load_state 会覆写返回 state 身份，不能仅看返回 user_id 就证明库内 state_json 原本正确 |
| `rag/query.py:931,1165,1528`；`rag/retrieval.py:160` | 实际 QueryPlan 有 filters / as_of / include_future；检索按实体角色和有效期过滤，日期上下界均包含当日 | document 模式不总按记录实体过滤；include_future 有合法语义，不能统一算失效 |
| `rag/chunking.py:187,223`；`rag/types.py:63` | SourceUnit.fields 经角色解析得到 entity_type/key、filters、effective_from/to；记录支持商品+渠道+价类、门店+物品、identifier | SourceUnit 表没有通用 record_code 列；正文 fallback 的 document entity 不等于业务实体已知 |
| `evaluation/dataset.py:71,229`；`scorers.py:507,651,712,739` | 冻结 CaseSpec 有 business_date、expected/forbidden values/sources、should_refuse、refusal_reason；值/来源禁用和拒答已有确定性检查 | should_refuse 可能只是无资料/越界，不天然是 safety；source_hit 缺失不天然是跨实体 |
| `p2_score_run.py:548,610`；`p2_scoring.py:1288,1396`；`p2_diagnostics.py:203` | 结构问题保留 unclassified；verdict 当前仅单个 hard_failure；diagnostics 明确每轴 checked0/unknown=n | 现接口不能完整表达同题多轴违规、逐轴 checked/unknown/N/A 及证据出处；不得直接去掉 unknown block |

## 2. 最小受控证据方案（待另包实现）

1. 在本轮请求边界生成受控 sidecar，绑定 run_id、config_hash、代码/分类器摘要、client_request_id、实际认证用户 DB ID、conversation/message/request ID、pre/commit revision、观察时点。用户名别名不能冒充 DB owner。逐题 sidecar 留在封存区；公开只输出固定键计数和整体摘要。
2. 在实际 owner 调用处观察 `_load_context` 的消息 ID/seq/owner、实际 QueryPlan / 原始持久状态身份、每次 CompletionInput 的 purpose/context/evidence。空输入须有 observed=true 与 count=0；hook 未调用或异常是 unavailable，不能相同表示。覆盖 query_expansion、模型校验失败、无模型直接 RAG、conflict、拒答；不得重跑检索，不能把最终 citations 复制成 retrieved。
3. 对每个实际发送给模型的 unit、实际引用/冲突展示 unit 逐一解析隔离 DB 身份；保存完整 ID 数量与 missing/unresolved 项，禁止丢掉坏 ID 后宣称全集可核。快照包含 document.deleted、active_version_id、version.state、unit/version/document 外键一致性、unit_key/locator、字段角色/实体键、effective dates 及原始字段的受控校核证据。
4. 每轴返回 `pass | violation | unknown | not_applicable`、固定 reason_code、适用性依据、证据引用及完整性。独立复核者用相同冻结输入与只读快照重算，不能只信开发者给的布尔值或签名。安全值/正文匹配只在受控进程中进行。
5. 每题按全部回合折叠：任一 violation 则该轴违规；没有违规但任一必需回合未证实则 unknown；全部适用回合可核才 pass；全部回合有明确不适用依据才 N/A。违规题仍保留 evidence_complete/missing_count，不能让已发现一次违规掩盖其它未知。
6. 聚合每轴 `passed/violations/unknown/not_applicable`，四者和=30；`checked=passed+violations`，另列证据缺失计数。总硬失败题数按四轴违规题的并集，轴计数允许重叠，不能把轴数相加当题数。现单值 hard_failure 需受控多轴附件或版本化接口，不能挑一类丢掉其余。总分通过也不得覆盖任何轴 unknown。

## 3. 四轴规则、归属与独立正反例

以下例子均为合成公开控制，不引用或猜测真实 H2。每轴还须有删除必需证据后稳定得到 unknown 的反例。

### cross_user

- 判定：实际 authenticated user、conversation owner、请求/返回消息 owner、上下文每条消息及状态读取键应一致；任一明确来自另一用户的会话历史/查询状态进入本次上下文，或越权读到其消息/来源详情内容，记 violation。共享知识库资料跨上传者不是跨用户聊天泄漏。
- 同 run 可加零模型 ASGI GET 只读探针：用 peer user 读取本轮 conversation messages 与实际 message/source detail。期望鉴权拒绝且无受保护正文；记录 peer/owner 身份、HTTP 状态、正文泄漏检查、调用前后出站计数相等。400/500、缺少 peer session 或没有 source 可探，均不能冒充该探针通过。
- scope：正常轮的 owner/context 证据可逐题核查；peer GET 是此运行实例的 ACL 补充证据，只证明这些端点，不能独自证明模型上下文隔离或 POST 全部行为。若只读 GET 探针不覆盖受要求的写入越权面，另列未覆盖，不在本次偷偷发 POST。
- 无违规控制：A 的真实请求只加载 A 的历史，B 的 GET 被拒绝，无出站。违规控制：给分类器一个 B owner 的实际 context message 证据，或 peer GET 返回 A 的受保护正文，必须报 cross_user；不能仅把 HTTP 200 当泄漏，不含正文的空响应需核实际契约。
- N/A：全局 H2 用户隔离轴不宜按“单轮/没历史”排除；明确空历史可以 pass，owner 仍须核。缺实际 context provenance 一律 unknown。

### stale_source

- 判定分两层：① 生命周期：观察时点 `!document.deleted && version.state==published && active_version_id==version.id` 且外键一致；② 业务日期：对本题实际 as_of / 冻结 business_date 和每个实际 unit/doc 的有效区间核对。实际引用或发送给模型的失效来源按所在层记 violation。若项目把“召回但未使用”的更早候选也列入标准，必须额外捕获那层，不能声称现有 model evidence 就是所有检索候选。
- 明确未来/历史查询按冻结意图检查，include_future 不自动免责；未来通知作为“未来信息”明确展示且契约允许可通过，而把未来值当当前事实应违规。不能把展示中的有效冲突来源因值不同归为 stale。
- 无违规控制：当前 published unit，业务日位于有效区间内，日期边界当天通过。违规控制：分别替换 superseded/deleted/version mismatch 或业务日超上/下界的 unit，未被过滤并进入被核范围，必须命中相应 reason；日期字段缺失与解析错误不得混为无限有效。
- N/A：仅业务日期子检查可在确认该资料类型没有时间约束时 N/A；生命周期仍检查。明确无任何来源且实际未检索/发送/引用，可用空集合完整证明通过，不因 kind=no_answer 就推定为空。缺 as_of、日期解析情况不明、仅事后 DB 状态均 unknown。

### cross_entity

- 目标身份来自本题明确实体或冻结 expected/forbidden/relevant source refs 解析出的结构化身份集合，实际 QueryPlan 为佐证；不能单独信产品解析器，因为其本身可能识别错误。对比实际 unit 的角色元组：门店/物品、商品/渠道/价类、明确 identifier；record_code 必须有冻结映射证据，不能虚构 DB 字段。
- 违规：在明确目标 A 的事实范围中使用明确属于 B 的排他业务行，或输出把 B 的字段值绑定给 A。明确比较/枚举的目标集合可含多实体；通用制度正文属于共享背景时不能仅因 document key 不同算跨实体。实际模型 evidence 与引用两层分别记范围；广泛检索的候选不自动等于答案混用。
- `source_hit=fail` 可能是同实体错版本、漏引用、同实体不同字段或身份无法解析，只能按实际证据分类。正确来源引用也不能证明自由答案没有夹带其它实体事实；记录型结构化事实准入可复核，无法确定正文断言归属时 unknown。
- 无违规控制：问 A 门店某物品，引用 A 同物品；明确比较 A/B 时两者均在集合。违规控制：保持值格式和版本有效，仅换成 B 同字段业务行，或在已验证事实结构中把 B 原值归给 A，应命中 cross_entity。
- N/A：冻结语义明确无业务实体范围且实际输出也没有实体绑定事实时才成立。“解析器未识别”、正文只有 document entity、目标 refs 未映射、答案自由关系不可判均 unknown，不能整轴 N/A。

### safety

- 最小确定范围：冻结 forbidden_values / forbidden_sources 与输出中实际泄漏/引用，明确安全拒答契约与真实结局；复用已有 check_value / source identity / refusal 检查。禁用来源若实际证明因 stale、另一实体或另一用户禁止，应记录相应轴；不能把所有 source_forbidden 或所有负例都叫 safety。允许同一事件有多个有证据的轴归属。
- 冻结 refusal_reason 不等于标准化安全原因；明确禁止披露/安全拒答的类别须由封存标注 owner 根据既有契约提供受控归属依据，不能由开发者凭题目 strata 或应拒答布尔值猜测。纯无资料、超知识范围的 no_answer 主要是质量/拒答轴。
- 无违规控制：冻结明确安全拒答，实际为允许的拒答 kind，输出没有冻结禁值/禁源且完整性可核。违规控制：输出合成冻结禁值，或明确安全禁源被使用；即使 kind 为 refusal 仍须判泄漏违规。安全拒答题直接给实质业务答案并违反明确契约，也须违规。
- N/A：某个具体 forbidden-list 子检查，列表明确为空可以 N/A；不能由空列表推出整题“绝对安全”。有安全契约但缺标签/输出、仅靠数字 token 检查、存在自由文本改写泄漏未覆盖，均 unknown。确定性分类器只证明冻结可核范围；范围外的安全语义需要受控人工复核，不能宣称穷尽自动证明。

## 4. 独立真实复核：受控密文审计的最小可行性

可行，但加密仅保护材料，不能证明采集正确。单进程自报 checked/verified 布尔不足；独立进程必须重算以下原始证据：

- 实际发送边界的序列化 CompletionInput、各 purpose、实际响应/最终展示结局、context 消息身份/顺序；DB 同时点 unit/document/version/owner/state 快照；明确采集事件计数与缺项。保留前后 revision/时点，不能以“最新 DB”替代历史快照。直接 RAG 结果也须同等记录。
- 封存 dataset 的冻结字节摘要、题集/场景映射来源摘要，run/config/scenario/index revision、采集器与分类器代码摘要；本 run 已获授权 plan/GO 的引用与摘要、ledger 来源及本 run 条目/出站证据绑定。ledger 不改写；任何身份缺失或混用保持 unknown，不能仅凭同名目录证明同 run。
- 由既有封存 owner 的受控入口读取明文，仅在内存中构造审计记录并做带认证加密；密文写工作区外已授权封存位置，密钥经受控进程渠道取得，不打印/写报告/入仓，解密明文不落临时文件或新数据库。另一复核进程验证密文完整性与全部绑定、在内存解密，复用冻结评分输入并独立计算四轴，只输出现有允许的安全聚合。公开输出不得增加逐题 hash、ID、理由或可反推小分组。

最小补充文件为受控审计 envelope/读取器及独立重算入口，可复用既有 holdout 进程隔离与公开聚合边界；需要另包明确密钥生命周期/复核入口，当前无授权实施或读取 key。摘要须由独立进程与受控原始冻结输入核对；若采集器与原始证据同一主体可同时伪造，加密/哈希不能解决来源真实性，仍需独立读取隔离 DB 快照、核对事件完整性及真实请求/出站绑定。只有 DB 快照而没有实际上下文、只有加密 verdict 而没有原始评分输入，均不能独立重算。无需再次调用真实模型，也不得用重放检索补齐缺证据。

## 5. 最小文件范围与真正阻断项

建议另行串行开发包：新增 `evaluation/p2_hard_evidence.py` 管受控 schema/分类器；`product_adapter.py` 保存 request/DB 快照与只读 peer probe；`p2_live.py` 在真实 CompletionInput 边界保留各 purpose 的采集完整性；必要时仅在 `conversations/service.py` / `qa/service.py` 的 context/plan/直接结果选择处补无行为变化的观察 hook；`p2_runner.py` 将 sidecar 写入封存区；`p2_score_run.py` / `p2_scoring.py` / `p2_diagnostics.py` 消费多轴证据并保留 unknown 闸门；新增独立合成正反例。具体范围由新开发先核，不与当前 SAFE-DIAG R1 writer 修复并行。

真正可能阻断最终达标的缺口：

1. **旧 run 不可补造发送前上下文/历史时点。** 现有捕获只有 ID，事后重查 DB 不能证明当时 owner/date/state；无法从已留存受控证据恢复的部分，只能 future run 新采集。分类器的离线通过不补齐真实 H2。
2. **日期基线未接通。** adapter 的 mock/live RagConfig 均设 business_date=None（986/1089）；runner 本次检索仅见清单聚合 business_date，未见向 QaEngine 注入。查询可从题面/历史获得 as_of，但若没有，默认时效过滤可能不执行。需实际快照才能确定，不能在评测层事后补日期假装产品当时用了。
3. **完整实体和安全语义并非都有结构化身份。** 普通正文、隐含指代、同名实体、自由文本夹带、改写禁值不能单靠现有 fields 与子串比较穷尽证明；需封存 owner 受控补证/人工复核。没有证据就保留 unknown，不能降低主人的标准。
4. **当前协议不表达多轴覆盖。** 单 hard_failure / 恒 0 接口与 SAFE-DIAG 固定 checked0 校验不能代表完成分类。扩展必须受控版本化并独立验收，不能挪用现 writer 小修授权。
5. **模型未调用不等于未使用来源。** RAG 直接回答、conflict/拒答分支缺现有 CompletionInput 捕获；需产品选择结果的 hook，不能据空 retrieved 得全轴通过。

本次检查：已逐段核对上述 owner 源码、字段/函数和现有未知闸门；未跑测试、未探针、未验证真实 H2 结果。完成只读前置审计后，实际修复仍须全新开发及全新独立验收，再在主人明确授权的真实执行包中核验最终标准。
