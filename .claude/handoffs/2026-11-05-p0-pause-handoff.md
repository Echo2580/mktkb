# P0 暂停交接（2026-11-05 10:20，主人指令：T004 完成即停）

> 用途：给主人或「回头用别的智能体验证」的交接说明。分支 `p0/obs-eval`，基线 `main` @ `8e44158`；未 push、未开 PR。
> 当前 HEAD：`f126598 p0/T004b scorer`；全量 `backend/tests` 最近一次：**1377 passed / 0 failed / 0 error**（386.82s）。

## 1. 提交链（p0/obs-eval）

| # | commit | 内容 | 状态 |
|---|---|---|---|
| 1 | `7b02f40` | T001 Trace 契约与版本绑定 | ✅ 独立验收 PASS |
| 2 | `2ac976f` | T002 SQLite Trace 仓储 | ✅ PASS |
| 3 | `dea4d5d` | T003a tracer 内核 | ✅ PASS |
| 4 | `d41d19f` | T003b 配置 + 中间件（X-Trace-ID） | ✅ PASS |
| 5 | `776497f` | T003c RAG 路径埋点 | ✅ 有条件通过（§5.4 契约缺口移交 T003d） |
| 6 | `b811f9f` | T003d QA/legacy 埋点 + 契约修订 | 首轮 FAIL（1 项窄缺陷） |
| 7 | `574e288` | T004a 评测数据集 + gold + fixtures | 开发完成（未独立验收，按主人指令） |
| 8 | `71756f5` | T003d R1 reason-aware 契约修复 | ✅ 定向复验 PASS |
| 9 | `f126598` | T004b scorer（值/来源/kind/分页/拒答/检索） | 开发完成（未独立验收） |

## 2. 已验证/未验证

- **已独立验收**：T001、T002、T003a、T003b（PASS）；T003c（有条件通过，其 §5.4 已由 T003d 关闭）；T003d（R1 定向复验 PASS）。
- **仅开发完成、未验收**：T004a、T004b（主人指令：留待其他 AI 验证）。
- **未开工**：T005（Replay/Local Runner）、T006a/b（双层门禁）、T007（Baseline/Diff/报告）、T008a/b（CLI、P0 七条验收）、T009（P0 收口）；P1 全部（设计/拆解已定稿、Holdout 30 已交付）。

## 3. 证据位置

- 开发证据：`docs/reports/OBS-EVAL/P0/evidence/T001…T004b/`
- 验收证据：`docs/reports/OBS-EVAL/P0/evidence/verify/T001…T003d/`（**未入库**，约 50+ 文件，需要时统一提交）
- 流程材料：`.claude/handoffs/T<NNN>-*/{handoff.md,report.md,review*.md}`；任务索引 `.claude/handoffs/_index.md`；四段提示词 `.claude/handoffs/prompts/`
- P1：`.claude/handoffs/2026-11-04-p1-{design,task-breakdown}.md`；Holdout：`docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/`（本地、gitignore，开发禁用）

## 4. 给验证方的建议命令

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git log --oneline -10
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation backend/tests/observability -q -p no:cacheprovider --basetemp backend\.pytest-tmp\verify2
```

逐包验收标准：`.claude/handoffs/T<NNN>-*/handoff.md` §5；开发自证：同目录 `report.md`；已有验收结论：`review.md` / `review-R1.md`。

## 5. 已知遗留（非阻塞，详见 `_index.md` 遗留项 1–27）

1. 验收证据 `evidence/verify/**` 未入库；PM 交接/提示词/review 未入库（工作树有未跟踪文件，未 commit）。
2. T006a 门禁实现时必须：用 `required_spans(..., reason=record.reason)`；对 `status=replayed` 跳过 path/outcome 校验；对 `*_json` 非法 JSON 做合法性校验；不依赖内核拒绝 `mode=live`。
3. T004a 偏离：locator 按范围型、`expected_pagination=null`（N05 min_total 在 notes）、N11 turns 留空、Q37–Q40 OCR locator 归一 page=1。
4. T004b 风险：`EvalCitation.unit_ids`/`EvalRetrieved.unit_ids` 需 runner 填充（replay 需持久化，否则 unit 级指标 fail closed）；`value_no_fabricated` 偏严（建议门禁按软指标）；拒答口径（no_answer/not_found/refusal）需与 gate 文档对齐；`EvalOutcome` 在计划字段外增加 `retrieved`。
5. T003d 为两个 commit（`b811f9f` + `71756f5`），未 amend；`_executed_span_names` 读 `TraceContext._spans`（与既有 `_trace_is_legacy` 同口径）。
6. T003c 冻结边界：`citation_refs_json.locator.cells[].display` 隐私口径未重议；证据 05/08 为 amend 前快照。
7. 团队 8 席位已满，后续改用全新上下文 subagent（一包一新助手）。
8. 提速策略 A/C/D 已写入 project-manager 技能 §11（默认启用）。

## 6. 下一步选项（等主人指令）

- **A**：继续 P0 剩余包（T005→T009），按 A/C/D 提速；完成后 T009 独立收口。
- **B**：先由主人/其他 AI 复验 T004a/T004b 与既有验收证据，再决定是否继续。
- **C**：直接进入 P1（需先签 GO/预算：`P1-RETRIEVAL` 3.0 元从 S2-DEV 划转、总上限 20 不变）。
