# P2-T207-FIX-CONFLICT 修复报告（N08 / C05 / C06）

范围：离线 Mock 复现 → 产品根因 → 最小修复 → 影响面差分 → 回归。零真实调用；未改 `evaluation/**`、fixtures、账本/GO；未 commit。

## 1. 结论
三例都已离线复现失败并在**产品既有路径**上修复：C05/C06 的冲突识别不再依赖 rag 候选排序窗口；N08 图片/实物识别类问题按范围外拒答（not_found）。
54 例公开 case 修复前后逐题差分：**只有 N08 变化**（clarification→not_found，strict fail→pass），其余 0 变化。

## 2. 复现与前后证据（`evidence/repro-before-after.json`）
运行形状：与 R2/R3 相同的灌库计划（V03→D01 同槽、V04 不发布、V01/V02 发布），产品走同一 HTTP 入口，mock provider。

| 例 | 修复前（复现 live：每轮只 1 次 query embedding） | 修复后 |
| --- | --- | --- |
| C05 | `answer`，仅 D01 一个来源，1 次模型调用（与 R2 实测一致） | `conflict`，B区1号货架第二层 + D区暂存柜，来源 D01/V01，0 次模型调用 |
| C06 | `answer`，仅 D02 一个来源，1 次模型调用 | `conflict`，010-00000001 + 010-00000099，来源 D02/V02，0 次模型调用 |
| N08 | `clarification`「请补充要查询的门店或物品。」 | `not_found`「…该问题属于首版范围外，无法据此判断物品的位置。」 |

对照组：同一 C05/C06 在不限 embedding 的离线口径下**修复前就是 conflict** —— 缺陷在候选窗口，不在冲突比较本身。

## 3. 根因（行号按 HEAD）
C05/C06（四段链路，全部有实测旁证）：
1. `qa/service.py:452-495`：记录型问题做**两次** rag 召回（record 面 + document 面）。
2. `rag/chunking.py:467-472`：正文块固定 `fields={}/filters={}`，record 面 `_passes_filters`（`rag/retrieval.py:407-438`）必然过滤掉它，通知只能靠 document 面召回。
3. live 计划每轮只给 1 个 query_embedding/rerank（`PM/T207-plan-v0_1.json`；R2 run_manifest query_embedding=55、answer=55）；`evaluation/p2_live.py:1018-1026` 两路共用同一计划项，第 2 次在 `AttemptBudget.take`（`p2_live.py:297`）**发送前**被拒。
4. 该异常被 `rag/retrieval.py:307-309` 吞成 vector 面降级 → document 面候选为空（live trace 第 2 个 recall 有 embedding_query、无 rerank；该轮只结算 1 次 embedding+1 次 rerank）。
5. 产品把 rag 候选当记录型证据上界（`retrieval/service.py:305-315`），通知段被裁掉；冲突只在"恰好 1 个实体组"时比较（`retrieval/service.py:391-397`），于是按表格行作答。

复核（用 live R2/R3 数据库副本，只读）：同一意图去掉候选上界 → C05/C06 都返回 conflict（两值两来源）；按实测单行候选 → 返回 answer。即产品冲突逻辑正确，缺的是"同实体另一有效来源"。

N08：`conversations/intent.py:466-542`（HEAD）只命中字段词「位置」、无门店/物品 → 直接给澄清「请补充要查询的门店或物品。」，从未识别"以照片为事实来源"。

## 4. 改动清单（+122 行，纯新增，不改既有分支）
- `conversations/intent.py` +42（`76123b492ae7c294`）：`image_source_question`（来源介词+图片名词、"照片里/图片中"、"看图…"）+ `IntentPlan.image_not_supported`；命中时仍执行一次正文检索（保留 retrieve 的真实执行事实与 Span 契约）。
- `conversations/service.py` +68（`51f481062e40f416`）：① 检索后按 `IMAGE_NOT_SUPPORTED` 返回 not_found（不调模型、不编造）；② 单实体记录命中时用"同实体（门店／门店+物品）全部可见记录"复核冲突（`_same_entity_evidence`：产品检索索引 SQL 只读、无供应商调用、不受 `candidate_ids` 限制），**只有**复核返回 conflict 才采用。
- `copy.py` +12（`cfabcc3a3a4ff258`）：`IMAGE_NOT_SUPPORTED` 文案（含"范围外/无法"，不含"照片中/已定位"）。
- 测试新增 `tests/integration/test_t207_fix_conflict.py`（`f858cd1a30bef651`）：窄候选下 C05/C06 仍 conflict、图片题拒答、资料名+图片不误判。

## 5. 影响面差分（`evidence/impact-before-after.json`，54 例，Mock 前后对照）
- Q01–Q40（40）、N01–N07（7）、C01–C04（4）：kind／文本／来源／冲突／候选／判分**全部一致，0 变化**。
- N08：clarification → not_found（唯一变化）；C05/C06 离线仍 conflict（原本就通过）。
- 为何 B0 不变：同实体复核只纳入同一门店+物品（或同一门店）的记录；D10 盘点通知的"盘点地点"不在 `HEADER_ROLES.location`，位置题被 `_units_with_roles` 排除，Q39/Q40 仍 answer。

## 6. 回归（backend/，`.venv/Scripts/python.exe -m pytest`）
- `tests/unit` + `tests/integration` + `tests/acceptance` + `tests/evaluation/test_p0_acceptance.py`：**856 passed / 1 failed**。
- 该 1 例（`test_s2h_r3_official_profile::...worst_case_is_2103552`）是**既有环境漂移**：共享预算文件 `limit_cny=40`（live 提额）与代码常量 10.0 不符；用 HEAD 源码同样失败；预算/账本属禁止改动面。
- 关键套件复跑：`test_t09_b0_baseline`、`test_t09_mutation`、`test_p2_public_controls`、`test_p0_acceptance`、`test_t09_d2_text_facts`、`test_chat`、`test_p1_t106_copy` + 新增测试：**54 passed**。
- 新增测试在 HEAD 源码上 4 项全部失败（证明它确实锁定本次修复）。
- `tests/observability` + `tests/rag` + `tests/evaluation/test_p2_public_cases.py`/`test_p2_score_run.py`：720 passed / 2 failed，两例也都是既有环境问题：`test_s4_stage_limit` 共享预算 40≠20（同上，账本禁止改动）；`test_p2_public_cases::test_repo_run_inputs_are_consistent` 只在 cwd=repo 根时通过（从 backend/ 跑时相对路径 `fixtures/…` 解析失败），在仓库根复跑通过。
- 零真实出站：全部 mock/受控替身；repro 输出 `provider_posts` 为空，修复后冲突轮 0 次模型调用。

## 7. 限制
- 按要求未做真实调用复测；"live 形状"用"每轮 1 次 query embedding"门控仿真复现，另以 live R2/R3 索引内容与账本回执旁证根因。
- 修复改变了"记录型证据只来自 rag 候选"的**边界**：冲突披露可以读取同实体、候选窗口之外的可见正文来源；不产生任何字段值，来源仍需通过 commit 事务的有效性/可见性复核。若发布方要求冲突也必须严格受候选窗口约束，需另做设计（例如把 document 面召回并入同一计划项）。
- N08 按"以图片为事实来源"的句式判定；对已发布图片资料的提问（"物料领用通知图片要求…"）不受影响（已逐条锁定）。
