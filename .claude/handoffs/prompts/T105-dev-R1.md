角色：开发助手（返工轮 R1），不是验收者。任务 **T105（D6 指代/字段错配，ERR-06）返工**。
模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（report R1 段首注明）。
工作目录：`D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；上一轮交付 `2306aaa`，当前 HEAD 含 PM 簿记 commit（只动 `.claude/handoffs/**`）。

## 第一步（按序读，只读理解）
1. `.claude\handoffs\T105-anaphora-field\rework-R1.md`（**本轮返工单：B1/B2 判据、期望、边界、必跑项**）
2. 同目录 `handoff.md`（§4 允许文件、§5 RG006 口径、§10 接续须知）、`report.md`（上一轮自述）
3. 同目录 `review.md`（独立验收 FAIL，2 阻断；只当问题线索与被证伪事实，不要照抄解释）
4. `docs\reports\OBS-EVAL\P1\evidence\verify\T105\`（01-verdict 根因、03-probe-results 逐场景对照；04 命令口径）

## 第二步：实现（最小改动）
- **B1**：修 `backend/src/mktkb/rag/query.py` 中 T105 指代分支先于分页处理的问题，使显式「列出来/全部/第 N 页」保持枚举分页（对齐 `17c0e63` 基线 page=2），补 unit + HTTP「枚举后 那个海报的第2页」用例。
- **B2**：使带新内容的指代追问不得整条倾倒——含记录字段的按单字段作答（对齐带标识时 29 字行为），非记录字段新内容（打印材质/陈列要求）走正文/legacy 但收窄，或澄清且不列出未问字段值；不得抢正文（T101 法规题/政策题/档期物料类不变）。
- 只改 `query.py`、`answer.py`（仅必要、最小，report 单列理由）与 `backend/tests/` 本包测试；**禁止改 `conversations/`、`intent.py`、fixtures、b0/badcase、gate 配置**；若必须改禁止文件 → 停手报 PM。

## 第三步：验证与交付（全部实际执行）
- 按 `rework-R1.md` §3 跑：本包 2 文件 / rag / integration / observability / 全量（内存 ≥2GB，不足轮询；既有 flake 隔离复跑 1 次）/ b0+badcase 对 P0 基线 `case_diffs=0`、hard `[]` / regression 对 `17c0e63` 基线逐例（RG006 保持 pass、RG005/RG007 失败集不变、无新 hard 名）/ T101+T102 定向。
- 1 个新 commit（`p1/T105 R1 fix anaphora pagination regression + new-content dump`），不 push/不 amend；`report.md` 追加 R1 段并修正不实表述；证据 03/04 追加 R1 段（不新增文件）。
- 不读 `.env`/Holdout；零真实模型/embedding/rerank/OCR；无 skip/xfail/删断言。
- 结束时回复 ≤10 行交接摘要（commit、B1/B2 修复前后证据、测试数字、偏离、风险）；详细内容写 report。
