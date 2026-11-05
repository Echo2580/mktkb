# P0 收口交接（2026-11-05，给新窗口）

> 用途：新开 PM 会话接续 P1 时的唯一事实源入口。先读本文件，再读 `_index.md`（遗留项 1–38）与 P1 设计/拆解稿。
> 主人 2026-11-05 决策：**P0 通过**（G5 → G6 收口）。

## 1. 交付状态

| 项 | 值 |
|---|---|
| 分支 | `p0/obs-eval`（基于 `main` @ `8e44158`） |
| 最新交付 commit | `2f7b174`（T008b）；收口提交见 `git log --oneline -3` |
| PR | **#1** https://github.com/Echo2580/mktkb/pull/1 ，OPEN，**未合并**（等主人） |
| 全量测试 | **1593 passed / 0 failed / 0 error**（`pytest backend/tests`） |
| 独立验收 | 每包一份全新上下文验收（`T*/review.md`、`review-R1.md`）；总验收 `docs/reports/OBS-EVAL/P0/review.md` = 有保留 PASS，无阻断缺陷 |
| 工作树 | 干净 |

## 2. P0 做了什么（一句话）

Trace 采集/SQLite 存储/最小侵入埋点（`X-Trace-ID`）、确定性离线评测器（Local + Replay）、双层发布门禁（8 项硬门禁 + 质量层/校准/豁免）、Baseline/Diff/Markdown+HTML 报告、CLI、P0 七条验收测试。

## 3. 主人未执行的可选项（不要擅自动）

1. 阈值审批：`docs/evaluation/gate_v0_1.json` 仍 `status=unapproved`、阈值空；提案在 `docs/reports/OBS-EVAL/P0/evidence/T006b/{gate,badcase}-proposal.json`。
2. 真实 baseline：未建立（审批阈值后才可 `baseline approve`）。
3. 设计 §7.2 `locator` 范围型口径未回写（PM 已追认，实现/测试按此执行）。
4. PR #1 未合并。

## 4. P1 开工门（新窗口第一件事）

P1 设计与拆解已定稿：`.claude/handoffs/2026-11-04-p1-design.md`、`2026-11-04-p1-task-breakdown.md`（15 包：T107 → T101–T106 → T108 → T109 → T110 → T111 → T112 → T113 → T114 → T900）。

- **PRE-2（阻塞 T111 与一切 live）**：预算划转 `P1-RETRIEVAL` 3.0 元（自 S2-DEV 划转，总上限仍 20）+ GO 改版，需**主人签** `budget.json` / `S2-LIVE-GO.json`；PM 只出清单、不碰原件。
- **PRE-4**：D-3 兼容授权（允许错误码/文案取值变化、字段结构不变），需主人书面确认，T104/T106 需要。
- **PRE-3**：P0 遗留复核（PM 自己，读 `_index.md` 遗留项 1–38）。
- 未签 GO 前：只做只读准备与 P1-PRE-3；**不得**派开发包、不得调用真实模型/embedding/rerank。

## 5. 交接材料位置

- 任务索引：`.claude/handoffs/_index.md`
- P0 流程与验收：`.claude/handoffs/T*/`；P0 收口产物：`docs/reports/OBS-EVAL/P0/`
- P1 提示词：`.claude/handoffs/prompts/p1-pm-resume.md`（新窗口用）
- P1 Holdout（本地、不入库、开发禁用）：`docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/`
