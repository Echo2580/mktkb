# 协调区索引（_index.md）

> 唯一事实源；状态一律用门编号（G0–G6）。「待审」列有且最多一个「是」。
> 当前阶段：v0.1 已冻结（main @ `85dfbe0`，tag `v0.1-local-20261104`），P0 任务单**待主人审阅**，未派发。

| ID | 任务 | 状态 | 轮次 | 待审 | 阻塞 |
|---|---|---|---|---|---|
| T001 | Trace 数据契约与版本绑定 | G0 待审 | 0 | 否 | — |
| T002 | SQLite Trace 仓储 | G0 待审 | 0 | 否 | T001 |
| T003 | 最小侵入埋点 + 中间件 | G0 待审 | 0 | 否 | T002 |
| T004 | 评测数据集 + gold + scorer | G0 待审 | 0 | 否 | T001 |
| T005 | Replay / Local Runner | G0 待审 | 0 | 否 | T004 |
| T006 | 双层发布门禁 | G0 待审 | 0 | 否 | T005 |
| T007 | Baseline / Diff / 报告 | G0 待审 | 0 | 否 | T006 |
| T008 | CLI 与 P0 七条验收 | G0 待审 | 0 | 否 | T007 |
| T009 | 独立验收与 P0 收口 | G0 待审 | 0 | 否 | T001–T008 |

- 任务拆解与验收口径：`2026-11-04-p0-task-breakdown.md`
- **PM 交接提示词（新窗口用，长版）**：`prompts/p0-pm-handoff-20261104.md`
- **PM 交接提示词（简版，直接复制）**：`prompts/p0-pm-handoff-short-20261104.md`
- 方案：`docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md`、`docs/superpowers/plans/2026-11-04-mktkb-observability-evaluation-p0.md`
- 冻结基线证据：`docs/evidence/LOCAL-R1-20261101/TEST-20261104/`（本地，不入库）
