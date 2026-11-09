# P1 暂停交接（2026-11-06，给新窗口续跑）

> 主人指令（2026-11-06 08:3x）：**A —— T105 收口后即暂停 P1**，不再派 T106…T114/T900；分支与簿记保留，等主人指令再续。
> 用法：新 PM 会话先读本文件 → `.claude/handoffs/_index.md`（唯一事实源）→ `2026-11-05-p1-kickoff-gate.md`（开工门与决策）→ 再按下文"续跑步骤"恢复。
> **续跑提示词**：`prompts/p1-resume-20261106.md`（2026-11-06 已补全：PM 项目要求、子智能体模型 `wb/cn:deepseek-v4.1-flash/max`、硬约束、预算与 GO、测试/证据预算、剩余包要点、已接受裁定）。**新窗口复制该提示词即可接管。**

## 1. 项目与分支状态

| 项 | 值 |
|---|---|
| 分支 | `p1/fix-retrieval`（自 `main@083eaef` = P0 已合并 merge commit） |
| HEAD（暂停时） | 见 `git log --oneline -3`；PM 簿记与 8 个交付 commit 均已入库，未 push（远端无 p1 分支） |
| PR | P1 尚未开 PR（按设计 T900 后才开）；PR #1（P0）已合并 |
| 工作树 | 暂停时应为 clean；若有未提交，见 §5 |
| 全量测试基线 | T104 收口时 `1678 passed / 0 failed / 0 error`（T105 收口后以新数字为准） |

## 2. P1 包进度（16 开发包 + T900）

| 包 | 状态 |
|---|---|
| T100 基线测试耦合修复（P1 前置） | ✅ G6 收口（dev `b35ae72`；验收 PASS） |
| T107 regression suite + 数据集契约扩展 | ✅ G6 收口（dev `36fe095`；验收 PASS） |
| T101 ERR-03 词表语境与法规优先 | ✅ G6 收口（dev `a7282b3`；验收 PASS；PM 裁定 A 两处窄改） |
| T102 组 A 状态继承（ERR-01/02/D5） | ✅ G6 收口（dev `85d9ffc`；验收 PASS；残余 R1–R3 见 _index #44） |
| T103 D4 记录路回落（ERR-04） | ✅ G6 收口（dev `43b7976`；验收 PASS；RG004 口径经 PM 裁定；残余 #45） |
| T104 D1 异常原因透传（ERR-07 产品侧） | ✅ G6 收口（dev `e7ee804`；验收 PASS；残余 #46） |
| T105 D6 指代/字段错配（ERR-06） | ✅ **G6 已收口**（dev `2306aaa`+R1 `fc60c57`+R2 `b37ad21`；R3 独立验收 **PASS**：`review-R3.md`、探针 133/133、全量 1718 passed；P2 残余见 `_index` #51） |
| T106 D3 文案统一（后端+前端） | ⏸ 未开始（handoff 未写） |
| T108 Holdout 支持与防污染 | ⏸ 未开始（handoff 未写） |
| T109 多轮 turns runner | ⏸ 未开始（T102/T105 的 RG002/RG003/RG006 多轮复现依赖它） |
| T110 检索金标与检索指标 | ⏸ 未开始（T110 handoff 必须写 §7.2 追认口径：unit_key 严格唯一 / locator 范围型返回 unit 集合） |
| T111 live 检索运行器（需 PRE-2 GO，已签；只跑 retrieval_only） | ⏸ 未开始；**主人已定 pilot 10 题后停一次给主人过目**；GO 绑定 f4710b18…、有效至 2026-11-30；运行需 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0` |
| T112 门禁阈值校准与 P1 baseline | ⏸ 未开始（gate_v0_2；refusal_recall 零样本展示/per-stratum 校准口径见 _index #35） |
| T113 监控 API（只读聚合） | ⏸ 未开始（可提前，但按主人暂停指令不动） |
| T114 监控 API 权限/负例/文档 | ⏸ 未开始 |
| T900 独立验收与 P1 收口 | ⏸ 未开始（全部完成后 1 个 PR 交主人，不合并） |

## 3. 已定决策与红线（勿丢）

- 子智能体模型：开发/验收均 `wb / cn:deepseek-v4.1-flash`，**推理档统一 `max`**（kickoff §12）。
- 每包：1 个开发 subagent（全新上下文）+ 1 个验收 subagent（全新上下文、证伪导向）；每包 **1 个交付 commit** + PM 簿记 commit；证据 `docs/reports/OBS-EVAL/P1/evidence/T<NNN>/`，验收证据 `.../evidence/verify/T<NNN>/`。
- T111 外**零真实调用**；不读 `.env`、不打印凭据；不改业务 API 字段结构、不改业务库/索引库 schema、不新增生产依赖；不动 `docs/evidence`/`var`/账本/GO/冻结 fixtures；不 commit 账本/GO；不杀外部服务。
- P0 三项可选项（阈值/baseline/§7.2 回写）继续冻结；PR #1 已合并，P1 完成后开新 PR、不擅自合并。
- 验收/开发预算见 PM 技能 §11（A 测试预算 / C 证据 ≤4 / D 内存门槛：全量前 `FreePhysicalMemory ≥2GB`，否则轮询等待，仍不足才 NOT-RUN 并如实记录）。
- 既有 flake 清单：`test_g08_short_budget_cancels_inflight_model_call`、`test_lifecycle.py::test_concurrent_publish_and_global_revision_cas[v05]`（隔离复跑 1 次即过；不据此返工）。

## 4. 暂停前还剩的动作（T105 收口）

1. T105 接续轮开发完成 → PM G2 核验（单 commit、只改允许文件、report 五段、b0/badcase 对照、全量）。
2. 派独立验收 subagent（全新上下文、max）→ PASS 后 PM 簿记 commit（review + verify 证据 + `_index` 更新）。
3. 若验收 FAIL → 出返工单（同一开发上下文继续，轮次+1）；若中断再次发生 → 按 §S 恢复。
4. T105 收口完成后：写/更新本文件"暂停时 HEAD 与全量基线"，**停止派单**。

> **2026-11-06 11:2x 更新**：第 2 步（重派独立验收）被 **wb 路线故障**阻塞（2 次验收 subagent + 3 次探测均静默失败，默认账号路线正常）；主人裁决**先保持暂停、不偏离模型策略**。T105 记 `G4 验收 BLOCKED`、**未收口**，续跑第一步见 §9 与 `_index` #48。

## 5. 续跑步骤（新窗口，主人说继续时）

1. `git status --short` / `git log --oneline -5` 核对现场；确认在 `p1/fix-retrieval`；按 §11D 看内存。
2. 读 `_index.md` 与各包 handoff（`.claude/handoffs/T<NNN>-*/handoff.md`）；下一包是 **T106**（D3 文案统一，前后端；依赖 T105 已收口）。
3. PM 流程：写 T106 handoff + prompts → commit 簿记 → 派开发 subagent → G2 → 派验收 → 簿记收口；之后 T108 → T109 → T110 → T111（pilot 停）→ T112 → T113 → T114 → T900。
4. 关键提醒：T109 让多轮 `turns` 真正执行后，RG002/RG003/RG006 的多轮形态可复跑；T110 必须携带 §7.2 追认口径；T111 只能 `live + retrieval_only` 且 pilot 后停一次给主人过目。

## 6. 关键文件索引

- 索引/决策：`.claude/handoffs/_index.md`、`2026-11-05-p1-kickoff-gate.md`
- P1 设计与拆解：`.claude/handoffs/2026-11-04-p1-design.md`、`2026-11-04-p1-task-breakdown.md`
- 各包：`.claude/handoffs/T100-baseline-config/`、`T107-regression-suite/`、`T101-vocab-context/`、`T102-state-inheritance/`、`T103-record-fallback/`、`T104-error-classification/`、`T105-anaphora-field/`（handoff/report/review 各三份）
- 证据：`docs/reports/OBS-EVAL/P1/evidence/{T*,verify/*}`；P0 证据 `docs/reports/OBS-EVAL/P0/`
- 配置/账本（只读，勿改）：`docs/evidence/LOCAL-R1-20261101/PM/S2-LIVE-GO.json`（P1 版，备份 `S2-LIVE-GO-20261104.json`）、`.../budget/budget.json`、`.../budget/live-ledger.jsonl`
- Holdout（开发禁用、不入库）：`docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/`

## 7. 暂停时状态（2026-11-07 02:4x；T105 已 G6 收口，P1 按指令 A 暂停）

- 暂停 HEAD：本次 PM 收口簿记 commit（`git log --oneline -1`）；T105 交付 = `2306aaa`（初版）+`fc60c57`（R1）+`b37ad21`（R2）三个 dev commit，均未 push/未 amend。
- T105 状态：**G6 已收口**（R3 独立验收 PASS：`review-R3.md`；验收证据 `docs/reports/OBS-EVAL/P1/evidence/verify/T105-R3/`；P2 残余见 `_index` #51）。
- 全量基线：验收方独立复跑 **1718 passed / 0 failed / 0 error**（T105 R3 实测；b0/badcase `case_diffs=0`、gate hard `[]`；regression 仅 RG006 fail→pass）。
- 工作树：clean（`_scratch/T105/` 为 gitignored 探针+WIP patch，按 kickoff §7 保留待主人确认后清理）。
- P1 状态：**暂停中**——按主人 2026-11-06 指令 A，T105 收口后不再派 T106…T114/T900；续跑第一包 = **T106**（D3 文案统一，前后端），等主人指令。

## 8. 2026-11-06 11:1x 状态更新（暂停前最后一次核对）

- **T105 开发已完成并提交**：`2306aaa`「p1/T105 anaphora field inheritance + no-field clarification」（父 `17c0e63`）；工作树 clean；全量 1693 passed、b0/badcase `case_diffs=0`、RG006 fail→pass、regression gate hard 变 `[]`。
- **T105 独立验收未完成**：验收子会话（2ccfc42f）**静默失败**——无 `review.md`、无 `docs/reports/OBS-EVAL/P1/evidence/verify/T105/`、08:55 后无 pytest 活动、无 python 进程、无通知。**这是暂停前唯一未收口动作**。
- 暂停 HEAD 记为 `2306aaa`；`_index` 中 T105 状态为"G4 验收待重派"（#47）。
- 续跑第一步 = 按本文件/交接提示词重派 T105 验收（PASS 后 PM 簿记收口，再按主人 A 指令暂停）。

## 9. 2026-11-06 11:2x 状态更新（重派验收被 wb 路线故障阻塞；主人裁决保持暂停）

- **T105 第 2 次验收重派失败（非任务问题）**：PM 已写 `prompts/T105-verify-R1.md`（含 §6 全部复跑项、b0/badcase/regression 口径、HTTP 产品路径探针、接续完整性核对、证据 ≤4/不改交付物/不 commit 约束）并派全新上下文验收 subagent（`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`）→ 约 15s **静默失败**，无 `review.md`、无 `verify/T105`、无 pytest 活动、工作树无改动（第 2 次；前序 `2ccfc42f` 见 #47）。
- **路线诊断**：随后 3 次最小探测（同路线 ×2、`wb/cn:glm-5.3-flash` ×1）全部 ~15s 静默失败（`lastTurnCompleted=false`）；同一时刻默认账号路线 `deepseek-account/deepseek-flash` 探测成功 → **wb 路线整体不可用**。
- **主人裁决（2026-11-06 11:2x）**：**先保持暂停、不偏离 wb 模型策略**；T105 记为 **G4 验收 BLOCKED**（`_index` #48），不产出任何伪 review/证据，不声称收口。
- **续跑第一步（wb 修复后或主人说继续）**：直接按 `prompts/T105-verify-R1.md` 重派全新上下文验收（先查内存 ≥2GB；证据/报告预算与命令口径已固化）→ PASS 后 PM 簿记收口并更新 §7；FAIL 则出返工单给原开发上下文（轮次 +1，3 轮上限）。
- **现场**：分支 `p1/fix-retrieval`，工作树 clean，交付 `2306aaa` 与 4 份开发证据、report、2 个测试文件均保全；`_scratch/T105/`（gitignored 探针）保留。

## 10. 2026-11-06 11:1x–12:0x 状态更新（wb 恢复→验收 FAIL→R1 返工）

- **wb 路线恢复**（11:19 探测 OK）后，PM 重派全新上下文验收 subagent（`wb/cn:deepseek-v4.1-flash/max`，提示词 `prompts/T105-verify-R1.md`），完成全项复跑。
- **验收结论：FAIL（2 阻断）**——**B1**「枚举后 那个海报的第2页」被 T105 指代分支劫持（clarification/无分页），相对 `17c0e63` 基线是**行为回退**；**B2** 带新内容指代追问（打印材质/陈列要求/规格型号，无标识上下文）仍 8 条×8 字段整条倾倒（基线已有，但违反「任何路径不得整条渲染」且 report §5 声明不实）。其余复跑全 PASS：本包 15、rag 335、observability 255、integration 367+1 既有 flake（隔离复跑过）、全量 1693 passed；b0/badcase `case_diffs=0`、gate hard `[]`；regression 仅 RG006 fail→pass、其余失败集不变；T101/T102 定向 37 passed。
- **PM 处置**：接受 FAIL（证据充分、非放水），验收产物 `review.md` + `verify/T105/`（4 份）已随簿记 commit 入库；出返工单 `T105-anaphora-field/rework-R1.md` + `prompts/T105-dev-R1.md`，R1（轮次 1/3）= 1 个新 commit，仅改 `query.py`/`answer.py`+本包测试，B1 对齐基线分页、B2 不整条倾倒且不抢正文，禁止改 `conversations/`/`intent.py`/fixtures。
- **下一步（续跑）**：R1 开发完成后 PM G2 核验 → 全新上下文验收 **R2**（定向复验 B1/B2 + 受影响测试 + 全量 1 次，其余条款沿用上轮 PASS）→ PASS 后簿记收口并回到主人指令 A（暂停）；FAIL 则轮次 +1（上限 3）。

## 11. 2026-11-06 12:3x 主人「暂停任务」：R1 停手现场与续跑须知

- **处置**：R1 开发 subagent 收到暂停后停手、**未 commit**；PM 未丢弃任何已完成工作（按 §S）。工作树保留 4 文件改动（`git diff --stat` = +209/−4；无 untracked；均在允许路径）。
- **WIP 备份**：`git diff --binary` 已备份到 `.claude/handoffs/_scratch/T105/R1-wip-20261106-123035.patch`（25712 B，sha256 `890eba3e94a759a045806657ee1d1b898f95a41cbc7c7103129a18530fdf5c23`，gitignored、不入库）；如需恢复：`git apply <patch>`（当前工作树已含同内容，勿重复应用）。
- **开发自报的 R1 初修结果（未经独立验收，不得当 PASS）**：
  - B1：枚举后「那个海报的第2页」恢复 `page=2`（验收方探针 70/70，原 64/70）；已补 unit + HTTP「第N页」用例；单独「第2页」行为不变。
  - B2：带记录字段追问（规格/价格/数量/位置）只答该字段（规格 29 字）；打印材质/陈列要求改为 `not_found`（`reason=ANAPHORA_NEW_CONTENT`，文案「资料中未记录这项信息…」），不再 8 条×8 字段倾倒（S15/S16 泄露 0）。
  - 运行自报：本包 23、rag 339、observability 255、integration 372、**全量 1701 passed/0 failed**、T101/T102 定向 44 passed；b0/badcase 对 P0 `case_diffs=0`、gate hard `[]`；regression 对 `17c0e63` 仅 RG006 fail→pass、RG005/RG007 失败集不变、无新增 hard 名。
- **未完成（暂停所致）**：`report.md` R1 段与 §5 更正、证据 `03-test-runs.md`/`04-scope-and-limitations.md` R1 段、1 个完成 commit（消息 `p1/T105 R1 fix anaphora pagination regression + new-content dump`）。
- **待 PM/主人复核口径（续跑先裁定）**：B2 的非字段新内容（打印材质/陈列要求）最终收窄为 **not_found** 而非走正文检索。需确认：①是否满足「不得整条倾倒且不抢正文」；②是否会把本可由正文回答的问题误判为查无（当前 b0/badcase/regression/T101/T102 未显示误伤，R2 验收须专门探针核验该边界）。若不可接受 → 退回 R1 开发调整（轮次仍 1，未超限）。

- **2026-11-07 00:5x 续跑裁定**：PM 复核 R1 未提交实现后**接受 B2 收窄方向**（记录字段追问→单字段作答；非字段新内容→`not_found`/`reason=ANAPHORA_NEW_CONTENT`，不倾倒、未改 `conversations/`），附三条约束：report 须如实披露「不先走正文/legacy」的保守化风险并记 P2 残余；不得扩大拦截范围（政策/法规/正文/纯指代/分页行为维持上轮 PASS）；R2 若用探针证明「基线本可从正文回答的问题」被压成 `not_found`（行为回退）则 B2 未收口、R1 内再调整。裁定全文见 `T105-anaphora-field/rework-R1.md` §5。已恢复 R1 开发补完收尾。

## 12. 2026-11-07 00:5x–01:3x：R1 收尾入库 + R2 验收 FAIL + R2 返工

- **R1 收尾**：接续上下文补完 `report.md` §6（70 行，含 B2 收窄披露/P2 残余/接续说明）与证据 03 §D/04 §E，**commit `fc60c57`**（7 文件，代码/测试 4 文件 +209/−4；不 push/不 amend；PM 已 G2 核验：允许路径、无 skip/xfail、无越界、证据仍 4 份）。补跑本包 23 passed、验收方旧探针 70/70（注明旧探针未覆盖政策/法规组合）。
- **R2 独立验收（`review-R2.md`）：FAIL**——B1 **PASS**（枚举后第2页 page=2/266 字，与基线一致）；B2 点名项 PASS（规格 29 字单字段；打印材质/陈列要求 not_found 35 字 0 泄露）；**但 R1 新分支对政策/法规追问排除不完整**：上文问位置/规格后「那个海报的价格欺诈规定是什么/相关规定/适用的价格欺诈规定」返回继承字段答案 27/29 字；`那个海报的档期物料…`（C3）/`审批流程`（C6）被压 not_found，而单独问可答 21 天/流程；C4/C7 文案「未找到记录」不实（P2）→ 违反 PM 裁定 §5-2「不得扩大拦截」。证据：三树对照（`17c0e63`/`2306aaa`/`fc60c57`）+ 谓词实测（`is_policy_question`/`is_regulation_question`/`is_anaphora_field_followup`）+ 代码行 `query.py:1336-1352`。其余复跑全 PASS：本包 23、rag 339、observability 255、integration 372、全量 **1701 passed/0 failed**、T101/T102 窄集 37/全集 44；b0/badcase `case_diffs=0`、gate hard `[]`；regression 仅 RG006 fail→pass、无新 hard。
- **PM 处置**：接受 FAIL（证据充分、非放水；R2 探针另证明`report:66`/证据 04:37 把该组合记为「观察（不阻塞）」已被证伪）；产物 `review-R2.md` + `verify/T105-R2/`（4 份）随簿记入库；出 `rework-R2.md` + `prompts/T105-dev-R2.md`：R2 返工 = 1 个新 commit（不 amend `fc60c57`），只改 `query.py`/`answer.py` + 本包测试，修政策/法规排除并补「实体+指代+政策/法规」HTTP 用例。
- **下一步**：R2 开发完成 → PM G2 → 全新上下文验收 **R3**（B2 组合定向 + 全量 1 次；其余条款沿用前轮 PASS）→ PASS 后簿记收口并回主人指令 A（暂停）；**轮次口径**：R3 是对第 2 次返工的复验，若 FAIL 仍可做第 3 轮返工，**仅当第 3 轮复验仍 FAIL 才达 3 轮上限**，届时停止返工并报主人三选一（改需求/换方案/接受现状）。

## 13. 2026-11-07 02:0x：R2 返工完成（`b37ad21`）→ PM G2 通过 → R3 验收已派

- **R2 交付**：commit `b37ad21`（父 `cbbb241`；7 文件 +452/−7：`query.py` +49、`answer.py` +68、本包 2 测试、`report.md` §7、证据 03/04 R2 段）；未改 `conversations/`、`intent.py`、fixtures/b0/badcase/gate；无 skip/xfail/删断言；工作树 clean。
- **实现要点**：`query.py` 新增 `is_policy_followup`（排除「要求/规则」防 B2 回退）+ `POLICY_FOLLOWUP` 分支（指代+政策/法规+显式实体：清继承字段、保留实体、置 enumerate+reason）；`answer.py` 新增 `_policy_document_plan` 换回正文 document 计划、法规题不拿标题/截断半句作答、C7 按记录块判「记录存在缺字段」。
- **开发自报（未独立验收）**：验收探针 62/62；C3 20 字含 21 天、C4 136 字含 2022-07-01+两项废止、C5 系列 58/140/156/58 字法规条文（0 继承字段）、C6 37 字、C7 22 字「未记录日期（记录存在，但缺少该字段）」；B1/B2 点名项/C1/C2/C8 不变；本包 40、rag 347、integration 381、observability 255、全量 **1718 passed/0 failed**、T101/T102 37/44；b0/badcase `case_diffs=0`、gate hard `[]`；regression 仅 RG006 fail→pass、无新 hard。
- **PM G2**：通过（单 dev commit、允许路径、无越界/无 skip；report 99 行 > 80 行预算 → 记非阻塞偏差，由 R3/收口披露）。已派全新上下文验收 **R3**（`prompts/T105-verify-R3.md`：定向 C3–C7 + 必须保持项 + 新启发式证伪 + 全量 1 次 + b0/badcase/regression）。
- **若 R3 PASS**：PM 簿记收口（review-R3 + verify/T105-R3 证据 + `_index` T105→G6 + §7 回填 + 清 `_scratch/T105`）并按主人指令 A 暂停；**若 R3 FAIL**：第 3 轮返工（最后一轮），其复验仍 FAIL 则停止并报主人三选一。

## 14. 2026-11-07 02:4x：T105 R3 验收 PASS → G6 收口 → P1 暂停

- **R3 独立验收（全新上下文，`review-R3.md` 78 行）：PASS，无阻断**。P2 残余 3 项：①「政策词+台账字段词」组合（`标准规格/价格标准/提交数量`）576 字 8×8 倾倒（等于基线 `17c0e63`、相对 R1 回退；按「不得比基线更差」判非阻断，建议下一包 `elif` 守卫加 `bool(field_roles)`）；②`报销规则` 词面漏判 → 22 字记录式；③文档/法规答案 `sources=[]`。观察：`report.md` 99 行 > 80 行预算（返工追加所致，记非阻塞偏差）。
- **R2 交付 `b37ad21` 通过**：C3/C4/C5 系列/C6/C7 全部按目标（C5 58/140/156/58 字条文、C3 20 字含 21 天、C4 136 字含 2022-07-01、C6 37 字、C7 22 字准确文案）；B1/B2 点名项与控制组保持；独立探针 **133/133**；全量 **1718 passed / 0 failed / 0 error**；b0/badcase `case_diffs=0`+hard `[]`；regression 仅 RG006 fail→pass。
- **PM 已簿记收口**：`_index` T105→**G6**（P2 残余 #51）、`review-R3.md`+`verify/T105-R3/`（4 份）入库、本文件 §2/§7 回填；`_scratch/T105/` 按 kickoff §7 保留待主人确认后清理。
- **P1 暂停**：按主人 2026-11-06 指令 A，T105 收口后**不派 T106…T114/T900**；等主人指令再续。续跑顺序 `T106→T108→T109→T110→T111（pilot 停）→T112→T113→T114→T900`；执行要求见 `prompts/p1-resume-20261106.md`。

## 15. 2026-11-09 09:18 主人「暂停任务」：当前进度与续跑须知

- **暂停 HEAD**：`fcc3434`（T113 handoff 簿记）；分支 `p1/fix-retrieval`。
- **已收口（本次持续推进段）**：T106 G6（文案统一，R2 PASS，全量 1733）；T108 G6（Holdout 防污染，R2 PASS，真实 holdout 30/30、error=0）；T109 G6（多轮 runner，R2 PASS，全量 1795，RG006 按多轮口径更新一行）；T110 G6（检索金标/同 chunk 同排名，技术 PASS，全量 1812）；T111 G6（live 检索 pilot：真实 b0 前 10 全 pass、R/MRR/nDCG=1.0、chat=0、零重试；验收方 ≤10 复跑后账本 **435/1000 请求、P1-RETRIEVAL 0.005269 元**；主人已「放行全量」，但 **T112 请求上限策略等主人指定**）。
- **在飞（暂停时未完成）**：T113（监控 API）开发 subagent 于 09:14 前后派出，暂停时已写 `backend/src/mktkb/observability/routes.py`（新）、`main.py`、`observability/store.py`（只读聚合 helper）、`tests/observability/test_routes.py`，**尚未 commit**；子会话可能仍在跑。**恢复第一步**：`git status --short` + `git log --oneline -3` 核实；若已提交 → PM G2 → 独立验收；若未提交 → 按 §S 保留、等待/接续（禁止丢弃）。
- **T112（门禁阈值校准 + P1 baseline）暂缓**：等主人指定请求上限方案。事实：账本 435/1000，剩余 565 请求；regression live 索引 49 docs/5066 chunks、batch=5 约需 1014+ 次 embedding，超出剩余。候选方案：缩语料/提高 embedding batch（provider 上限 10）/缩减 suite/重签 GO+放宽代码 `MAX_GO_REQUESTS`。阶段金额剩 **2.994731 元**（P1-RETRIEVAL 3.0 已用 0.005269）。
- **账本/GO 现场**：`docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`（已 435 预留；`provider_billed_cny=null`；GO 前缀 sha `f4710b18…` 不变）；**未 commit 账本/GO**。
- **续跑顺序**：① 核实并收口 T113（→独立验收）→ ② T114（监控 API 权限/负例/文档；handoff 草稿在 `_scratch/T114/handoff-draft.md`，需落正式文件+提示词）→ ③ T112（等主人方案）→ ④ T900（P1 七条 + 1 PR 不合并）。T113/T114 零 live，可先做；T112/T111 全量 live 需主人放行。
- **2026-11-09 09:20 追加：主人「113 也暂停」**——T113 开发子会话在飞（已写 routes/main/store helper/测试，未 commit），PM 侧无法直接中断（非 teammate）；已停止一切派单/验收/后续动作。恢复时先 git status --short + git log --oneline -3 核实其最终落点：若已自提交 → 按 G2 核验；若未提交 → 按 §S 保留接续；禁止丢弃。T114 亦暂停（草稿留存 _scratch/T114/handoff-draft.md）。
- **工作树**：非 clean（T113 在飞改动，见上；恢复时先核实归属）。`.claude/handoffs/_scratch/` 保留 T108/T109/T110/T111/T114 草稿（gitignored）。
- **风险/残余（累计，详见 `_index` #51–#56）**：T105 P2（政策词+字段词 576 倾倒等）；T106 `not_found` 徽标/INVALID_QUERY e2e NOT-RUN；T108 report 167 行、3 拒答题 fail（质量留 T110/T112）；T109 report 140 行；T110 nDCG 保守下界/empty_recall 口径/真实 relevant_units 未覆盖；T111 GO 计划计数 7/4 vs 实际 17/10、pilot 指标平凡、请求上限阻塞 T112。
- **2026-11-09 09:33 更正：T113 已在暂停后自行收尾并提交 `9edc003`**（父 `10bb42b`，未 push/amend；工作树 clean；9 文件均在允许路径、report 80 行、证据 4 份；无业务代码/API/intent/fixtures/账本/GO 改动）。按暂停指令**未做 G2 与独立验收**。恢复顺序：PM G2 核验（4 端点/降级/holdout 聚合/store 只读 helper 必要性/OpenAPI）→ 派独立验收 → 收口。**工作树当前 clean**（本条之前的“非 clean（T113 在飞）”已过时）。T114 仍暂停（草稿 `_scratch/T114/handoff-draft.md`）。

## 16. 2026-11-09 18:0x 续跑（新窗口接管）：T113 收口，T114 启动

- **T113 G6 已收口**：PM G2 通过（单 dev commit `9edc003`、9 文件全在允许路径、4 个 GET + `require_role("admin")`、trace 关闭降级、holdout 只聚合、`store.list_window` 纯 SELECT、OpenAPI 注册）。独立验收（全新上下文 `wb/cn:deepseek-v4.1-flash/max`）判 **PASS**：6/7 项（`review.md` 72 行 + `verify/T113/` 4 份），全量 0 failed 在验收沙箱因 `docs/evidence` 只读 **BLOCKED**（46 项环境性 PermissionError，两次总数均 1858）。
- **环境恢复**：主人将本会话文件策略切为 `danger-full-access`；PM 在未改交付物的工作树上原样复跑全量 → **1858 passed / 0 failed / 0 error（474.19s）**，记录 `T113-observability-api/pm-full-suite-check.md`。第 7 项环境缺口解除（验收方 BLOCKED 事实保留在 review §3/§5）。
- **残余 #57（PM 裁定，非阻塞）**：OpenAPI 无 `securitySchemes`（LOW-1 → T114 文档如实写明 cookie-session/401/403，不新增全局 scheme）；report/证据父提交笔误（LOW-2，不返工）；只读测试未覆盖业务库（INFO，验收方已补）。
- **清理**：验收方遗留在仓库根的 `_scratch/`（970MB、未被 gitignore）已删；关键脚本/日志保留在 `.claude/handoffs/_scratch/T113v/`（gitignored）；pm 全量日志 `.claude/handoffs/_scratch/pm-full-pytest-20261109.log`。
- **下一包 = T114（监控 API 权限/负例/文档）**：正式 handoff `T114-observability-auth-docs/handoff.md` + `prompts/T114-{dev,verify}.md` 已落盘，按「派开发 → G2 → 独立验收 → 收口」执行。**T112 方案已由主人于 2026-11-09 18:2x 定为 A（缩到 b0 live baseline）**：复用 T111 已建真实索引（6 docs/27 chunks），只跑 b0 40 题 live（约 80–90 请求），badcase/regression 用绝对阈值、不上 live baseline（设计 §8.2 首次 baseline 用绝对阈值）；待 T114 收口后派 T112。T900 未开始。
