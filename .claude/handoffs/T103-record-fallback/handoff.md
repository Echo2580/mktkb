# T103 交接单：D4 记录路回落语义检索（ERR-04，P1 第 5 包）

> 基线：分支 `p1/fix-retrieval`（自 `main@083eaef`；T100/T107/T101/T102 已收口）。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 目标（一句话）
修"记录过多 → 直接给零候选无解澄清"的死路：overshoot 时回落语义/正文检索并给出可解释结果（候选或命中量与缩小方式），澄清必须说清真实原因；回落路径留 trace 降级标记；前端不再把"本轮无候选"说成"历史未保存"。

## 2. 背景（ERR-04，依据 `错误记录-20261104.md` §ERR-20261104-04 与 §三 40Q 矩阵）
- 现象：问「物料领用通知图片要求先填写什么」→「〔需要确认〕符合条件的记录过多，请缩小查询条件后重试。」+「该历史消息未保存候选明细」；既不说哪份资料命中多少条，又没有任何候选，还把"没给候选"误归因成"历史未保存"。
- 根因：`backend/src/mktkb/conversations/service.py` 的 `limit=20 → 100` 双阈值分支；当前代码位置约 `:2009-2017`（`if evidence.truncated: … return clarification("符合条件的记录过多…")`，零 candidates），以及 query expansion 后的 `:2050-2051` 同类截断。宽泛词面「物料领用」必然命中 `corpus/enterprise-20261101/excel/E05_领用核销台账_1200行.xlsx`，20/100 双阈值注定 overshoot。
- 40Q 矩阵实测未过的 8 题 Q25/Q26/Q29/Q30/Q34/Q35/Q37/Q38 全部映射本缺陷（`错误记录` §三）；Q36 属 ERR-07（T104）。
- 前端：`frontend/src/features/chat/MessageCard.tsx` 在"clarification + 候选为空"时渲染「该历史消息未保存候选明细；请重新提问以获取可选项。」（约 `:120-138`），对**本轮**响应也这样显示 → 误归因。

## 3. 输入（先读这些）
1. `.claude\handoffs\2026-11-04-p1-design.md` §3（T103 行）、任务拆解 T103 段。
2. `错误记录-20261104.md` §ERR-20261104-04（:200-241）、§三 40Q 矩阵（:420-433）。
3. `backend/src/mktkb/conversations/service.py`：`_evidence`/`truncated` 分支（约 `:2002-2060`）、`_Result`/`_candidate_view`、`_retrieve`、`_no_record_text` 相关；观察 `evidence.truncated` 的语义（超过 limit 即 truncated）。
4. `frontend/src/features/chat/MessageCard.tsx:40-145`（`liveCandidates`/`candidates`/零候选文案）。
5. 既有测试：`backend/tests/integration/test_chat.py`（clarification/候选/记录过多相关）、`backend/tests/unit/test_conversations.py`、`backend/tests/observability/test_paths_e2e.py`（trace annotate 写法）。
6. `fixtures/evaluation/regression.jsonl` RG004（本包要收口转 PASS）；`backend/tests/evaluation/test_regression_suite.py` 参考。
7. b0 目标题：Q25/Q26/Q29/Q30（text）、Q34/Q35/Q37/Q38（ocr）——见 `fixtures/evaluation/b0.jsonl`；`Q31` 是既有 local fail，不要顺手改。

## 4. 交付物（只准写这些路径）
1. `backend/src/mktkb/conversations/service.py`（主改）：overshoot 时**回落**（例如改用 document/语义检索计划、或从 evidence 构造候选、或给命中条数+缩小建议再澄清）；澄清文本必须含真实原因/命中量/缩小方式；空候选必须诚实。
   - trace 降级标记：用既有 trace annotate 机制写**数据字段**（如 `annotate_trace(record_overshoot_fallback=True)` 或 span annotate 计数），**不得**改 trace schema 结构/必需 span 表/outcome 枚举。
2. `frontend/src/features/chat/MessageCard.tsx`：**仅**修"本轮响应零候选"被显示为"历史未保存"这一处（用已有 `live`/`message` 区分；不得顺手重构、不得改 API 契约/字段）。
3. 本包测试：`backend/tests/`（unit + integration；必须覆盖"truncated 强制触发 → 回落/诚实澄清 + trace 标记"）；前端 `npm run typecheck`（必要时 `npm run build`）。
4. `fixtures/evaluation/regression.jsonl`：**仅**收口 RG004（按实现口径更新 `expected_kind`/`expected_values`/`notes`，须能 local 复现；不得删 `forbidden_values`），可追加 T103 种子；**禁止动 RG001/RG002/RG003/RG005–RG007**。
5. `docs/reports/OBS-EVAL/P1/evidence/T103/`（≤4 份证据）
6. `.claude/handoffs/T103-record-fallback/report.md`（五段，≤80 行）
7. 1 个 commit（见 §7）
**不要写**：其他后端模块/API schema/响应字段结构、b0/badcase、gate 配置、其他前端文件、`.claude/handoffs` 其他文件。

## 5. 允许 / 禁止
- 允许：service.py 回落逻辑 + trace annotate；MessageCard 零候选误归因的最小修正；本包测试；RG004 口径收口；只读读语料/测试。
- 禁止：改业务 API 字段结构（新增响应字段也算）、改其他包文件、改检索/embedding 取数语义（可复用既有 `_retrieve`/plan，不重写）、改 b0/badcase、放宽/删除既有断言、`skip`/`xfail`、真实模型调用、读 `.env`/Holdout、切分支/push、新增生产依赖。

## 6. 验收标准（逐条可判定）
1. **无解澄清消失**：对 Q25/Q26/Q29/Q30/Q34/Q35/Q37/Q38 场景（local/offline 可执行范围内）验证不再返回"零候选 + 符合条件的记录过多"这一无解澄清；每个问题给出 before/after 行为表（kind/text 关键措辞/候选数/是否回落），不得用"跳过"过关。OCR 题若 local 本就 skipped_requires_ocr，须如实标注并只断言非 OCR 分支可验证部分。
2. **回落路径可证明**：用**强制 truncated 的测试**（monkeypatch 或合成 evidence）证明 overshoot → 回落/诚实澄清分支被触发；该路径 trace 里能看到降级标记（数据字段），且不破坏 trace_integrity/必需 span（跑 `backend/tests/observability` 全绿）。
3. **文案诚实**：候选为空时文本不再声称"历史未保存"；前端对"本轮零候选"与"历史加载无候选"显示不同且真实的原因（`npm run typecheck` 通过；`npm run build` 若可用须通过，否则 NOT-RUN 说明）。
4. **RG004 收口**：按实现口径更新并 local **PASS**（或如 local 不可达，如实记录依赖原因并给最强可验证断言）；RG001–RG003/RG005–RG007 状态不变（RG001–RG003 仍 PASS、RG005–RG007 仍 RED 且失败集不变）。
5. **回归**：本包测试 + 受影响目录（`backend/tests/integration`、`backend/tests/unit`）+ 全量 `backend/tests` 0 failed/0 error（§11A 各 1 次；内存当前 2.44GB，全量前看 `FreePhysicalMemory`；既有 flake 隔离复跑 1 次）；b0/badcase local run + gate 与修复前对照：`hard_failures` 无新增，case 级变化仅限记录路目标题并逐条解释。
6. 证据 ≤4 份、report 五段、1 commit、只改允许文件、无 skip/xfail/删断言。

## 7. 提交要求
- 分支 `p1/fix-retrieval`；**1 个 commit**，消息：`p1/T103 record-path fallback + honest clarification`；不 push/不 amend 历史。
- 提交前 `git status --short` 只含允许路径；report 记录 commit 信息（sha 写交付回复即可）。

## 8. 报告格式（五段，≤80 行）
1) 完成内容；2) 验收标准自证（每条 ≤2 行，带命令/`文件:行`）；3) 实际运行结果（本包/目录/全量 + b0/badcase/regression 前后对照 + 前端 typecheck/build + commit sha + stat）；4) 偏离或未做（含 RG004 口径理由、前端改动范围、OCR 题处理）；5) 风险（一句话）。

## 9. PM 裁定记录（2026-11-06 02:4x，T103 完成后）

**裁定：接受 RG004 口径收口（有条件）**。
- 事实：本地评测语料 `corpus/enterprise-20261101` 未收录 D09；local RAG 实测输出诚实 `no_answer`（修复前为"记录过多"无解澄清）。`expected_kind` clarification→no_answer、`should_refuse=true` 并补 `refusal_reason`，`forbidden_values` 原样保留。属"本地可达性口径"，非放宽断言。
- 条件（验收必须逐条证明）：① local 文本诚实，不得出现"该历史消息未保存/符合条件的记录过多请缩小"等错误归因；② 产品 legacy 回落必须由强制 truncated 用例证明（document 与 record 两分支 + `filter_decisions_json` 降级标记 + 必需 span 不破）；③ RG001–RG003 仍 PASS、RG005–RG007 状态/失败集不变；④ gate 不得出现新的 hard failure 名称；⑤ 若发现"本应 answer 却被收口为 refuse"属口径伪装 → 退回返工。
- 前端 5 行最小改动（仅 live 零候选分叉）接受；全量文案统一仍归 T106。
