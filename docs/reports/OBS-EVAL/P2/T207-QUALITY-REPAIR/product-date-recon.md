# T207-04 前置：产品业务日期/as_of 只读侦察（结论）

- 现场：分支 codex/p2-e2e，HEAD `97b00666`，工作树含未提交 A/R1 改动；本文件行号均为当前工作树。本包只读：零产品/模型/网络/脚本执行，未读 .env/冻结 H2 原文/私有密文/保管会话。

## 1. 产品是否已有业务日期/as_of 配置或输入路径（有，但仅进程级配置，无请求/界面入参）

- Settings 字段：`rag_business_date: str | None = None`（backend/src/mktkb/config.py:109；env 前缀 MKTKB_ :24-32；格式校验 :259-264）。
- 真实产品装配：main.py:84-98 把 `settings.rag_business_date`（main.py:90）传给 `resolve_rag_config(business_date=...)`（backend/src/mktkb/qa/service.py:612-631）→ `RagConfig.business_date`（backend/src/mktkb/rag/config.py:88；from_env 形参 :233、赋值 :296）→ QaEngine（qa/service.py:152-165）→ `prepare` 用 `business_date=self.config.business_date` 调 parse_query（qa/service.py:417-427，:425）。
- 直答路径：QaEngine.answer → RagIndex.ask → answer_question 用 `index.config.business_date` 重解析（rag/answer.py:64-82，:80）。
- QueryPlan.as_of 来源：`_as_of(question, previous.as_of, business_date)`，优先题面显式日期，其次“现在/当前/今天”用 business_date 或上一轮，否则 previous.as_of 或 business_date（rag/query.py:931-947、:1165；QueryPlan.as_of 属性 rag/types.py:232-234）。`include_future` 仅由题面未来词表决定（query.py:110、:1166；types.py:226）。
- 检索是否用时点：仅 `plan.as_of and not include_future` 才启用 effective_from/to 过滤（rag/retrieval.py:205-210；facts.py:79-82）；as_of 为空则完全不按有效期过滤。
- 持久化：RagDocument.business_date 列存在且写入（rag/models.py:53；rag/index.py:298-313，:311），但产品清单构造固定 business_date=None（qa/service.py:212-257，:239），且检索不读该列（retrieval.py 只用 effective_from/to）；QueryState.as_of 随会话持久化（rag/models.py:163-168；rag/index.py:579-624）。
- API：提问 schema 仅 client_request_id+question（backend/src/mktkb/conversations/schemas.py:46-49；路由 conversations/routes.py:98-114），无 as_of/business_date；observability 的 business_date 只是 run manifest 只读摘要（observability/routes.py:174-195、:211-229）。legacy 意图路径无日期概念（conversations/intent.py:453-459；conversations/service.py:656-673、:2336-2344；retrieval/service.py:432-456 无日期过滤）。

## 2. RagConfig(business_date=None) 的定性

- RagConfig 定义在 rag/config.py:88（不在 product_adapter）。
- P2 适配器 mock/live 都硬编码 None：mock `RagConfig(..., business_date=None)`（backend/src/mktkb/evaluation/product_adapter.py:1003-1011，:1006）→ QaEngine(:1012-1018)；live 同（:1107-1129，:1110）→ QaEngine(:1191-1197)。
- 两处 Settings 也未给 rag_business_date（:970-990、:1074-1097）；且适配器自注入 qa_engine，main.py 中产品自己的 resolve_rag_config/QaEngine 分支（main.py:84-98）被跳过。
- 结论：不是产品能力缺失，也不是产品本无此配置；是 P2 评测装配复制产品装配时丢弃了已有配置（评测层未接线，且自持 QaEngine 使产品工厂路径失效）。

## 3. 已有配置但适配器未传：最小修复点候选（≥2，含风险）

- C1（推荐，最小）：在 mock/live 两处 Settings 显式接收 `rag_business_date`（默认 None，显式参数优先、避免宿主 env 泄漏），并用它替换 `RagConfig(..., business_date=None)` 的 :1006/:1110，等价 main.py:85-91 的转发。值来源=运行级显式声明（建议冻结 H2 公开 manifest 的 business_date=2026-10-28，docs/evaluation/p2-holdout-v2.manifest.json:14；P2RunDataset 当前丢弃该字段，product_adapter.py:258-279），由 05 入口/06 计划传入。风险：默认保持 None 则公开 57/默认 binding 差分不变；启用后 rag 路径 as_of 变化会改变 57 与 H2 Mock E2E 结果，须新基线并独立验收；Settings 仍读宿主 env（_env_file=None 只关文件），必须显式参数优先。
- C2：mock 路径改走产品工厂 `resolve_rag_config(business_date=settings.rag_business_date, ...)`（qa/service.py:612-631）；live 因产品 GO/账本 env 检查（qa/service.py:643-678）与 P2Gate 冲突，仍须 C1 式转发，形成两条路径。风险：provider/binding 身份与测试面变大。
- C3（不建议）：新增产品 per-request as_of：AskRequest（conversations/schemas.py:46-49）→ qa.prepare/answer（qa/service.py:417、:432）→ 适配器 payload（product_adapter.py:2220-2228）。风险：改产品 API/schema/契约；单数据集唯一日期（evaluation/live.py:709-713 同口径）并无 per-request 需求；违反“不扩功能/不改 schema”，除非先证产品缺陷。
- C4（禁止）：用 dataset.cases 日期或事后填值，或把 run manifest 的 business_date 当“产品实际使用”（该值由 CaseSpec 聚合，p2_runner.py:2306-2313）；任务书 §5 明确禁止隐藏 CaseSpec 注入/事后填值假装当时用了。
- 防“假装用了”的硬条件：值须在 start()/ensure_ready() 前进入 RagConfig（:1003/:1107 早于 :1012/:1191、:1034/:1211）；实际值必须由 A 采集输出（§6）；分类器只信实际快照，不信 manifest/报告字段。

## 4. 若“产品没有配置”（本侦察为否）

- 本侦察确认产品有配置（§1），无需新增产品能力即可让 rag 路径用业务日期；但“运行级取值从哪来”是未决项：P2 plan/contracts 无 business_date 字段（p2_contracts.py、p2_holdout_plan.py 均无），可用声明值只有冻结 H2 manifest 的 2026-10-28（p2-holdout-v2.manifest.json:14）与 CaseSpec.business_date（evaluation/dataset.py:237）。
- 若要求界面/请求级日期，则必须新增产品能力（C3，成本见 §3），由主人决定范围；T207 单日期运行不需要。

## 5. CaseSpec.business_date 在数据集与评分中的角色

- 契约定位：评测数据集“业务日期”，用于 effective_from/to 与 include_future 判定（docs/evaluation/eval_data_v0_1.md:53；格式 docs/evaluation/p2-dataset-v0_1.md:60）；CaseSpec 字段/序列化/校验（evaluation/dataset.py:237、:268、:331、:364）。
- 产品“应使用”基准：v0.2 保管契约明确“可用已有 CaseSpec.business_date 作为产品应使用的基准，但不能把历史意图缺明确日期臆造为该日期，也不能声称产品实际上用了它”（docs/evaluation/p2-h2-custody-annotations-v0_2.md:26）。
- 评分现状：CaseSpec.business_date 只进数字白名单（scorers.py:415-422）；P2 run manifest 由 cases 聚合出 business_date（p2_runner.py:2306-2313、:2339），gate 要求该 manifest 字段（p2_scoring.py:2225-2241）；无 scorer 用它做 stale 判定（gate.py:57-60、:3446-3449 明说 v0.1 数据集无 as_of/effective 字段）。
- 历史意图缺日期 vs 产品实际日期：冻结标注 stale_source 轴含 as_of(ISO|null)+temporal_intent（p2-h2-custody-annotations-v0_1.md:11、:22；校验 p2_holdout_scenarios.py:33-40、:115-127）；2 处日期锚点保留 required+as_of=null、不臆造（T207-CUSTODY-V2/review.md:13；annotation-report.md:30）；实际日期只能来自运行期快照（v0_1.md:34），缺失/冲突按 unknown 或 violation，不得互相替代（T207 step1 任务书 B1 第105行）。

## 6. 与四轴 stale_source 的接口：A 采集已实现与缺口

- 已实现：回合 DB 投影含 rag_business_date（backend/src/mktkb/evaluation/p2_evidence_capture.py:269-285、:457-483，:483 读 qa.config.business_date）；产品侧 plan_observed 事件含 as_of/include_future/state_as_of（observability/evaluation_capture.py:139-153；发出点 conversations/service.py:2290-2307），与投影一起进 turn envelope（p2_evidence_capture.py:810-869，:863-864）；契约把 rag_business_date 列为固定投影字段（docs/evaluation/p2-hard-evidence-capture-v0_1.md:55），plan_observed 为必需事件（:59；p2_evidence_capture.py:48-54）。
- 缺口：① 实际值当前必为 None（§2），修复后才有“产品实际 as_of”；② 分类器未实现（p2_hard_evidence.py 不存在），A 只核完整性、不核 as_of 与冻结意图（p2_evidence_capture.py:568-577 只核 plan 条数/路径）；③ 运行绑定/摘要不含业务日期：adapter binding_components 无该字段（product_adapter.py:1483-1556），config_hash 组成固定无日期（p2_runner.py:720-730），产品 safe_config_summary 亦无 business_date（rag/config.py:380-408）→ 不同日期可同 config_hash；④ path=legacy 的 plan_observed.as_of 只是 prepare 计划，legacy 检索实际不做日期过滤（§1），分类器不能当作实际过滤日期；⑤ completeness 不要求 as_of 非空或与冻结 manifest 一致（同 :568-577）。

## 7. 结论：04 走“确认缺陷→最小修复+独立验收”

- 依据：产品能力端到端存在（§1）；缺失是 P2 适配器丢弃已存在配置且自注入 QaEngine 使产品工厂路径失效（product_adapter.py:1006/:1110；main.py:84-98）。这是可离线复现、可最小修复的接线缺陷（C1），不是分类器能补的日期。
- 不修的代价：H2 rag 路径 as_of 恒 None、检索不做时效过滤，stale_source 日期子检查只能 unknown；legacy 轮完全无日期概念 → 无法达成 unknown0。
- 随修证明链：实际 as_of/rag_business_date 必须进 A 证据并进运行绑定（§6 ③④）；分类器按“实际快照 vs 冻结意图”判，禁止用 CaseSpec/manifest 回填（§3 C4）。
- 未决项：① H2 运行级日期取值与声明位置（建议公开 manifest 的 2026-10-28，经 06 计划/GO 显式传入产品配置，而非 adapter 自动取）；② 2 处日期锚点 as_of=null 仍 unknown（保管语义未决，不因产品修复消除）；③ 界面/请求级日期属新增能力（C3），需另决；④ 本侦察未读冻结 H2 原文/附件/凭据，未运行任何代码。
