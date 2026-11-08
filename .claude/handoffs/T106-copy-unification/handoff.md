# T106 交接单：D3 文案统一（ERR-05，P1 第 8 包）

> 基线：分支 `p1/fix-retrieval`（T100/T107/T101/T102/T103/T104/T105 已 G6 收口；HEAD `87ea720`）。本包依赖前面所有 reason 已稳定（T104 七类服务错误文案已定稿，T105 指代文案已定稿）。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。
> D-3 授权（主人 2026-11-05 书面确认）：允许错误码/文案**取值**变化；**API 请求参数与响应 Body 字段结构不变**。

## 1. 目标（一句话）
把用户可见的 outcome/reason 文案统一成**唯一、诚实、可自救**的映射（说清原因/可否重试/是否与资料无关），并让前端徽标与提示文案与真实原因一致——「无候选」不得再说成「历史未保存」；**不改 API 字段结构、不改 kind/error_code 语义、不改意图词表**。

## 2. 背景（ERR-05，`错误记录-20261104.md:243-270`）
- 现象：5 条错误里徽标全指向资料侧（"无匹配资料/需要确认/基于已发布资料"），真实原因在系统侧（上轮实体顶替、识别成另一查询、词表误判、检索过宽未给候选）；用户会按错误方向自救。
- 模板：ERR-07 已定稿的服务错误文案（`conversations/service.py` `_service_error` 一带）——"这是服务调用失败，不是资料中没有答案。…可稍后重新提问"是**正确模板**，本包沿用其"三要素"风格。
- 前端现状：`frontend/src/features/chat/MessageCard.tsx:135-139` 对 clarification 的 history 分支一律写"该历史消息未保存候选明细"（无候选时误导）；徽标 `RESULT_KIND_LABELS`（`frontend/src/utils/format.ts`）只按 kind 显示。
- 已知约束：`MessageView` **没有 reason 字段且不得新增**（D-3 字段结构不变）；历史消息的 candidates 未持久化（`conversations/models.py` 只存 kind/error_code）→ 前端无法知道历史澄清是否曾有候选，文案必须**不武断**。

## 3. 输入（先读这些）
1. `.claude\handoffs\2026-11-04-p1-design.md` T106 行；`2026-11-04-p1-task-breakdown.md` §T106；`错误记录-20261104.md` §ERR-05（:243-270）。
2. 后端文案现状：`backend\src\mktkb\conversations\service.py`（legacy `_Result(kind,text,reason)`：`UNKNOWN_IDENTIFIER`/`IDENTIFIER_NOT_RETRIEVABLE`/`NO_INTENT`/`UNRECORDED_FIELD`/`CONFLICTING_VALUES` 等；`_service_error` 七类；`_rag_turn_result`）、`backend\src\mktkb\rag\answer.py`（`_no_answer` 各 reason 文案、`_document_fallback`、`_effective_no_answer`、POLICY_FOLLOWUP 文案）、`backend\src\mktkb\rag\query.py`（clarification 文案）、`intent.py`（legacy 澄清文案，**只读，禁改**）。
3. 前端：`frontend\src\features\chat\MessageCard.tsx`（clarification/not_found/service_error 区块）、`frontend\src\utils\format.ts` `RESULT_KIND_LABELS`/`resultKindTone`、`frontend\src\api\client.ts`（AskResult/MessageView 字段）。
4. 既有测试：`backend\tests\unit\test_conversations.py`、`backend\tests\integration\test_chat.py`、`backend\tests\unit|integration\test_p1_t10{1,3}*`、前端 `frontend\e2e\02-chat.spec.ts`、`frontend\e2e\acceptance-02-kinds.spec.ts`（徽标/文案断言）。
5. `fixtures/evaluation/regression.jsonl`：RG007（defect-t106）**不要改**——其失败集是意图词表问题（与 RG005 同类，`_index` #46 已登记），本包只保证不新增失败。

## 4. 交付物（只准写这些路径）
1. **新增** `backend/src/mktkb/copy.py`：用户可见 reason→文案的**唯一映射** + 文案函数（支持动态字段名/实体名占位）；覆盖后端实际会返回给用户的 reason（至少含：legacy 5 个 + rag 的 `DOCUMENT_NOT_FOUND`/`UNKNOWN_STORE`/`RECORD_ONLY`/`MULTIPLE_ENTITIES`/`*_AMBIGUOUS`/`CLARIFICATION_REQUIRED`/`NO_EVIDENCE`/`NO_SUPPORTING_SENTENCE`/`NOT_YET_EFFECTIVE`/`EFFECTIVE_WINDOW_*`/`ANAPHORA_NO_ENTITY`/`ANAPHORA_NO_FIELD`/`ANAPHORA_NEW_CONTENT`/`POLICY_FOLLOWUP`/`NO_RECORD_FOR_ENTITY`/`NO_ENUMERABLE_RECORD`/`PAGE_OUT_OF_RANGE`/`FIELD_NOT_RECORDED`/`NO_INTENT`/`UNRECORDED_FIELD`/`INDEX_NOT_READY`/`KNOWLEDGE_CHANGED`/`EMPTY_QUERY`/`UNKNOWN_REGION`/`MISSING_SLOT`）。**T104 七类服务错误文案保持等价（不得回退三要素）。**
2. `backend/src/mktkb/conversations/service.py`、`backend/src/mktkb/rag/answer.py`、`backend/src/mktkb/rag/query.py`：**仅文案来源改为映射**（最小改动；kind/字段结构/error_code 取值/状态机与检索路径不变；report §4 单列每文件改动理由）。
3. `frontend/src/features/chat/MessageCard.tsx`（必要时 `frontend/src/utils/format.ts`）：clarification 无候选/历史消息文案改为**不武断且可自救**（不得声称"未保存/资料缺失"）；徽标与真实原因一致（无候选澄清不得显示成"基于已发布资料"；有候选仍"需要确认"；如需改标签须同步 e2e）。
4. `backend/tests/` 本包测试：映射唯一性/三要素/主要 reason 覆盖；必要时同步既有文案断言（**只改取值、不改结构/强度**，report 列清单）。
5. `frontend/e2e/`（如文案断言确需变更，最小同步；不得放宽断言语义）。
6. `docs/reports/OBS-EVAL/P1/evidence/T106/`（≤4 份）、`.claude/handoffs/T106-copy-unification/report.md`（五段 ≤80 行）、1 个 commit。
**不要写**：`intent.py`、b0/badcase 数据、gate 配置、其他包文件、`.claude/handoffs` 其他文件、`conversations/schemas.py`（字段结构）、`var/`、账本/GO。

## 5. 边界与硬约束
- 不改业务 API 请求参数/响应 Body **字段结构**（`AskResult` 12 字段、`MessageView` 字段集逐字不变；可加内部常量/函数）。
- 不改 `ResultKind` 枚举集合/顺序、`error_code` 语义与七类码；不改意图词表（RG005/RG007 残余不属本包）；不新增生产依赖。
- 零真实模型/embedding/rerank/OCR 调用；不读 `.env`/Holdout；不改 `docs/evidence/**`、`var/**`、账本/GO；不 push/amend 历史；无 skip/xfail/删断言/放宽断言。
- 文案不得编造原因：前端无法精确知道 reason 时用**中性**文案（例如"该回答未提供可选项"），不得断言"历史未保存/资料没有"。

## 6. 验收标准（逐条可判定）
1. **映射唯一/完整**：`copy.py` 覆盖 §4-1 清单中全部**用户可见** reason；单测枚举断言「每 reason 唯一文案、无重复串」（语义相同的可显式白名单）；文案含适用三要素（原因/可否重试/是否与资料无关）。
2. **行为不变**：`AskResult` 12 字段、`MessageView` 字段集与父提交逐字相同；`kind`/`error_code` 取值集合与父提交相同；T101–T105 行为（b0/badcase/regression + 各包测试）不变；服务错误七类文案三要素保持。
3. **前端修正**：clarification 无候选（live）与历史消息均不再出现"该历史消息未保存候选明细"式**武断断言**（改为中性可自救文案）；徽标与真实原因一致（无候选澄清不显示"基于已发布资料"；有候选仍"需要确认"）；`npm run typecheck` + `npm run build` 通过；受影响 e2e（`02-chat`、`acceptance-02-kinds`）通过（环境不允许则记录实际尝试 + NOT-RUN，不得声称通过）。
4. **回归**：本包测试 + `backend/tests/unit` + `backend/tests/integration` + `backend/tests/observability` + 全量 `backend/tests` 0 failed/0 error（§11A 各 1 次；全量前内存 <2GB 轮询，仍不足才 NOT-RUN）；b0/badcase local run+gate 对 P0 基线（`hard_failures` 无新增；允许**仅文案相关 check** 的 case 级差异，但 kind/status 不得变，逐例列在 report；若出现新 hard 或 kind 变化 → 回退对应文案）；regression RG001–RG006 状态不变（RG006 PASS）、RG007 失败集不变、gate 无新增 hard 名。
5. **合规/形式**：证据 ≤4、report 五段 ≤80 行、1 commit、只改允许文件、无 skip/xfail/删断言/新依赖/真实调用；前端改动有 build 证据。

## 7. 提交与报告
- 分支 `p1/fix-retrieval`；**1 个 commit**，消息：`p1/T106 unify reason copy + honest frontend badges`；不 push/不 amend。
- 提交前 `git status --short` 只含允许路径。
- report 五段（≤80 行）：完成内容 / 验收标准自证（每条 ≤2 行，带命令或 `文件:行`）/ 实际运行结果（本包/unit/integration/observability/全量 + b0/badcase/regression 前后对照 + 前端 build/e2e + commit sha + stat）/ 偏离或未做（含文案取值变化清单、前端 e2e 是否 NOT-RUN 及原因）/ 风险。

## 8. 坑（务必避）
- `MessageView` 无 reason 且不能加字段 → 前端不得"猜原因"；只能按可用字段（kind/error_code/candidates/live/retryable）给中性文案。
- b0/badcase 的检查含文本敏感项（如 forbidden values/精确值）：改文案后必须前后对照，出现新 hard 或 kind/status 变化即回退该文案。
- `RESULT_KIND_LABELS` 键名被 e2e 断言（`需要确认`/`无匹配资料`/`基于已发布资料`）：改标签须同步 e2e 且不得放宽语义。
- 既有测试对文案有逐字断言（`test_chat.py`、`test_conversations.py`、T101/T103 测试）：只允许按"文案取值变化"最小同步，report 列清单，禁止改结构/强度。
- 前端 e2e 依赖后端服务与浏览器：若环境不具备，明确 NOT-RUN + 实际尝试记录；至少 typecheck/build 必须通过。
