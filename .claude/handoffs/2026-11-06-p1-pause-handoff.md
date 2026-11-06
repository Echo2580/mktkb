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
| T105 D6 指代/字段错配（ERR-06） | 收口流程中：前序 dev 中断（04:19），已按 §S 恢复；接续轮完成/待验收/待簿记——**暂停前必须走完** |
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

## 7. 暂停时状态（待 T105 收口后由 PM 更新）

- 暂停 HEAD：`<待 T105 收口后填写>`
- T105 收口 commit：`<待填写>`
- 全量基线：`<待填写>`
- 工作树：`<待填>`

## 8. 2026-11-06 11:1x 状态更新（暂停前最后一次核对）

- **T105 开发已完成并提交**：`2306aaa`「p1/T105 anaphora field inheritance + no-field clarification」（父 `17c0e63`）；工作树 clean；全量 1693 passed、b0/badcase `case_diffs=0`、RG006 fail→pass、regression gate hard 变 `[]`。
- **T105 独立验收未完成**：验收子会话（2ccfc42f）**静默失败**——无 `review.md`、无 `docs/reports/OBS-EVAL/P1/evidence/verify/T105/`、08:55 后无 pytest 活动、无 python 进程、无通知。**这是暂停前唯一未收口动作**。
- 暂停 HEAD 记为 `2306aaa`；`_index` 中 T105 状态为"G4 验收待重派"（#47）。
- 续跑第一步 = 按本文件/交接提示词重派 T105 验收（PASS 后 PM 簿记收口，再按主人 A 指令暂停）。
