# P0 可观测性与自动化评测（obs-eval）

本 PR 完成 MKTKB 项目 P0 阶段：Trace 采集/存储/埋点、确定性离线评测器（Local + Replay）、双层发布门禁、Baseline/Diff/报告、CLI 与 P0 七条验收测试。

- 基线：`main` @ `8e44158`；分支 `p0/obs-eval`
- 交付 commit：18 个（另有簿记/返工提交），最新交付 `2f7b174`（T008b）；收口 `aa45bd4`（T009 产物）
- 全量测试：**1593 passed / 0 failed / 0 error**（`pytest backend/tests`，约 7 分钟）
- 独立验收：每个包一份全新上下文验收（`review.md` / `review-R1.md`），P0 总验收见 `docs/reports/OBS-EVAL/P0/review.md`（**有保留 PASS**，无阻断缺陷）

## 交付包

| 包 | 内容 | commit |
|---|---|---|
| T001 | Trace 契约与版本绑定 | `7b02f40` |
| T002 | SQLite Trace 仓储 | `2ac976f` |
| T003a | tracer 内核 | `dea4d5d` |
| T003b | 配置 + 中间件（X-Trace-ID） | `d41d19f` |
| T003c | RAG 路径埋点 | `776497f` |
| T003d | QA/legacy 埋点 + reason-aware 契约（含 R1） | `b811f9f` + `71756f5` |
| T004a | 评测数据集 + gold 解析 + fixtures | `574e288` |
| T004b | scorer（值/来源/kind/分页/拒答/检索） | `f126598` |
| T005 | Replay / Local Runner + 运行清单 | `80fd092` |
| T006a | 门禁硬层 8 项 + 退出码（含 R1） | `f6bb3c4` + `90d7133` |
| T006b | 门禁质量层 + 校准 + 豁免 | `5a4c054` |
| T007 | Baseline + Diff + 报告（含 R1） | `6447b85` + `08536ed` |
| T008a | CLI + P0 全流程 | `f2c0209` |
| T008b | P0 七条验收测试 + p0-report | `2f7b174` |
| T009 | 独立总验收 + anchors | `aa45bd4` |

## 验收与证据

- P0 七条（设计 §11）逐条复跑：业务行为不变（golden + 345 integration）、`trace_id` 端到端、B0 40 / BadCase 13 独立回归、版本绑定、baseline+diff+JSON 报告、8 项硬门禁 exit 1、零真实模型调用。
- 证据：`docs/reports/OBS-EVAL/P0/evidence/{T001..T008b,verify/T001..T008b,T009}/`；开发/验收报告 `.claude/handoffs/T*/`；索引 `.claude/handoffs/_index.md`。
- 锚：`docs/reports/OBS-EVAL/P0/anchors.json`（dataset/corpus sha256、pipeline/gate 版本、38 commit、测试数）。

## NOT-RUN（不得视为通过）

`mode=live → exit 4` 端到端（参数层 exit 2 / 手改 manifest exit 3，仅单测覆盖 4）；真实 baseline 与阈值审批；真实 OCR/embedding/rerank/LLM；P1/P2 真实回答质量；HTML 渲染效果；`cross_entity`/`stale_bypass` 真实 case 类；`pagination_contract` 真实期望值。

## 合并前需主人决策（G5）

1. **质量阈值审批**：`docs/evaluation/gate_v0_1.json` 仍 `status=unapproved`、阈值全空；按 `T006b` 的 `gate_proposal.json` 审批后 `gate quality=True` 才能从 exit 3 变 0。建议值见 proposal（b0 Recall/MRR/nDCG min 0.9487/0.8498/0.8755，badcase 0.7479/0.6967/0.6651）。
2. **真实 baseline 建立**：审批阈值后执行 `baseline approve`（当前无 approved baseline，放行路径全部 fail closed）。
3. **设计 §7.2 口径回写**：`locator` 范围型（unit_key 身份型 / locator 范围型）需正式写入设计文档（PM 已追认，实现与测试按此执行）。

## 硬约束核对

- 零真实模型/OCR/embedding/rerank 调用；未读 `.env`；未新增生产依赖。
- 不改业务 API 请求/响应 Body 与业务库/索引库 schema（OpenAPI 快照与 T003b 验收一致）。
- 未改 `docs/evidence/**`、`var/**`、账本/GO、冻结 fixtures。
