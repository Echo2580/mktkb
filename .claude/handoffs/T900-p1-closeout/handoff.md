# T900 交接单：P1 独立总验收与收口（P1 最终包）

> 基线：分支 `p1/fix-retrieval`（自 `main@083eaef`）；前置 **T100–T114 全部 G6 收口**（含 T112 R0 `7f46121` + R1 `4c2b7ba` 审批落盘、`gate_v0_2` approved、P1 release baseline `bc6f6f906db1`）。HEAD 以 `git log -1` 为准（最后一个代码 commit 之后的 PM 簿记 commit 只改 `.claude/handoffs/**`）。
> 执行者：独立验收 subagent（全新上下文，`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）；**不是**开发者、不是 PM；证伪导向，不引用开发 `report.md` 作 PASS 证据。本包不做新功能、不改代码。
> 主人 2026-11-09 22:4x 指令「继续推进任务」→ 本包为 P1 最后一步：验收后 PM 开 **1 个 PR 交主人（不合并）**，主人决策前不合并、不进下一阶段。

## 1. 目标（一句话）

对 P1 全部交付做独立总验收：按 `.claude/handoffs/2026-11-04-p1-design.md` §9 七条 + 各包验收标准复跑关键项，产出 `docs/reports/OBS-EVAL/P1/{p1-report.md, review.md}` 与 `evidence/T900/`，给出可交主人的总判定（PASS / 有保留 PASS / FAIL）与未覆盖清单。

## 2. 交付物（只准写这些路径）

- `docs/reports/OBS-EVAL/P1/review.md`（**总验收报告**：七条逐条 PASS/FAIL/BLOCKED/NOT-RUN + 命令与 `文件:行`；逐包抽查表；越界审计；未覆盖/NOT-RUN；≤150 行）
- `docs/reports/OBS-EVAL/P1/p1-report.md`（**P1 收口报告**：范围与逐包 commit 表、七条结果、真实调用与账本成本（保守口径）、残余 #51–#59、发布建议；≤150 行；不含答案原文/凭据/Holdout 明细）
- `docs/reports/OBS-EVAL/P1/evidence/T900/`（≤4 份复跑证据：命令+关键输出摘要）
- **不写** `.claude/handoffs/**`（PM 负责 `_index.md` 与交接）；不 commit/push。

## 3. 输入（只看这些）

1. `.claude/handoffs/2026-11-04-p1-design.md` §9（P1 七条验收）、§5–§8（设计口径）。
2. `.claude/handoffs/_index.md`（唯一事实源：逐包状态、PM 裁定、残余 #30–#59）与 `2026-11-06-p1-pause-handoff.md` §15/§16。
3. 各包 `.claude/handoffs/T1{00,01,02,03,04,05,06,07,08,09,10,11,12,13,14}-*/` 的 `handoff.md` §3 与 `review*.md`（复核结论是否仍成立；关键项必须自己跑）。
4. `docs/reports/OBS-EVAL/P1/evidence/`（开发证据）与 `evidence/verify/`（各包验收证据）；`docs/reports/OBS-EVAL/P0/`（P0 baseline 只读锚）。
5. `docs/evaluation/gate_v0_2.json`、`var/eval/baselines/bc6f6f906db1/{baseline,approval}.json`、T112 的 live run 目录、T111 pilot run 目录（`var/eval/runs/`，只读）。

## 4. 允许 / 禁止

**允许**：§2 三份产物 + 证据目录；只读整个仓库；`%TEMP%` 与 `backend\.pytest-tmp` 临时产物。

**禁止**：
- 不改任何代码/测试/配置/fixtures/`docs/evidence/**`/`var/**`/账本/GO；不 commit/push；不切分支。
- **零真实模型/embedding/rerank/OCR 调用（本包不重跑 live）**；不读 `.env`；不读 `P1-HOLDOUT` 逐题内容（只核 T108 聚合证据与导出 sha）。
- 不改 `gate_v0_2.json` 的 `status`/阈值，不改 baseline 审批文件（审批是主人+R1 已落盘的事实，只能核对）。
- 不把已知非阻断残余（`_index` #51–#59）当新失败重复返工；只在 review 中判断"是否仍存在/是否超范围"。

## 5. 验收标准（逐条可判定）

1. **P1 §9 第 1 条（7 项修复转正）**：regression 7 条用例 RED→PASS 证据仍成立（复跑 `regression` local + gate 或核对 fixtures/证据）；b0 40 题中对应场景 local 下不再复现；无硬门禁失败。
2. **第 2 条（行为变化受控）**：b0 + badcase + regression 的 gate 结果/diff/退出码对 P0 有记录；错误码/文案取值变化清单（T104/T106）存在且字段结构未变（抽查 `AskResult`/`MessageView`/响应字面）。
3. **第 3 条（Holdout 30 冻结可用）**：`fixtures/evaluation/holdout-questions.jsonl` 无答案导出 sha/30 行/13 键；`label_version` 固定；T108 真实 holdout 30/30、error=0、分母 30 证据复算；防污染（默认聚合、`--allow-holdout-details` 默认拒绝、audit 无题干）仍成立。
4. **第 4 条（真实检索评测跑通）**：T111 pilot + T112 b0 全量 live 的 run 产物、manifest 六要素、指标、零 chat、账本计数可只读复核；**badcase/regression/holdout 的 live 为 NOT-RUN（主人方案 A 请求上限），如实登记，不得写成通过**；账本花费 ≤ 阶段额度（核 `BudgetLedger.summary()` 只读：**505/1000 预留**、P1-RETRIEVAL **0.0142293/3.0 元**、总 accounted ≈15.07/20、`provider_billed_cny=null`）。
5. **第 5 条（门禁与 baseline 升级）**：`gate_v0_2.json` `status=approved` 且阈值=主人批准值（`min_sample=8`；R/M/nDCG `absolute_min=0.855`；hard_filter `absolute_max=0.02`；empty_recall `absolute_max=0.145`；`max_regression_pp=2.0`；answer/refusal/runtime 仍 null）；P1 release baseline `bc6f6f906db1`（b0/live/retrieval_only）`approval.json` 齐全（approver=主人、gate_exit_code=0、quality=pass、六要素=manifest）、与 P0 baseline 跨版本比较只分析不放行（`require_release_baseline` fail closed 抽查）。
6. **第 6 条（监控 API 只读可用）**：4 端点 admin 200/employee 403/匿名 401；不返回原文、Holdout 明细不可达；OpenAPI 快照与接口文档 §8 一致（T114 证据复核 + 轻量本地探针，零真实调用）。
7. **第 7 条（回归与边界）**：`pytest backend/tests` **全量只跑 1 次**，0 failed/0 error（当前会话 `danger-full-access`，内存 ≥2GB；既有 flake 命中只隔离复跑该用例 1 次并记录，**不得重跑整套**）；前端 typecheck/build（若可）或记录 NOT-RUN；`git log --oneline main..p1/fix-retrieval` 全量 commit 路径审计（是否越界、是否改业务 API Body/schema/依赖清单）；`pyproject.toml`/`uv.lock` 无 P1 期间新生产依赖。
8. **产物自洽**：`review.md`/`p1-report.md` 数字（测试数、请求数、金额、sha）与实测/证据一致；未覆盖与 NOT-RUN 完整；≤10 行给主人摘要。

## 6. 必须实际运行的检查（输出摘要存证据）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
git status --short; git log --oneline -12
git log --oneline main..p1/fix-retrieval
git diff --stat main..p1/fix-retrieval
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t900-full
# local 三套 + gate（t900-b0/badcase/regression）
# holdout：只读核对 T108 证据 + fixtures 导出 sha；如需跑，用 T108 聚合模式（零真实调用、不写逐题到仓库）
# gate_v0_2 / baseline 审批文件只读核对；P0 跨版本比较只分析
```

## 7. 已知边界（必须遵守）

- **不重跑 live**：T111/T112 的真实调用已发生且账本硬绑定；用 run 产物 + 账本只读核算，不得产生新的真实请求。
- 已知非阻断残余（写报告时逐条判断"是否仍存在"）：T105 P2 政策词+字段词倾倒等（#51）；T106 `not_found` 徽标/INVALID_QUERY e2e NOT-RUN（#52）；T108 report 167 行、3 拒答题 fail（#53）；T109 report 140 行（#54）；T110 nDCG 保守下界/empty_recall（#55）；T111 GO 计划计数口径差/pilot 指标平凡（#56）；T113 OpenAPI securitySchemes/父提交笔误（#57）；T114 holdout 标志措辞/`trace_unavailable`/`partial_data` 未专项测试（#58）；T112 R1 重写 run `gate.json`（exit 3→0，已披露）、审批后 config_hash 变化（已披露）、R0 §5 跨版本 NOT-RUN 理由过时、diff 放行路径不重新核对 gate 配置哈希（#59）。
- **外部未跟踪文件**：`docs/面试/市场部AI知识库-最终版面试知识库.md`（2026-11-09 21:40 由主人侧产生，未跟踪、非 P1 交付）。不得修改/提交它；越界审计时把它作为"非 P1 工作树外部文件"单独说明。
- **T112 方案 A 的后果**：P1 §9 第 4 条只覆盖 b0 live；badcase/regression/holdout live 属 NOT-RUN（主人 2026-11-09 决策）。总判定允许"有保留 PASS"并逐项列明；不得擅自改需求或补跑 live。
- 审批类事项只核对不代批：`gate_v0_2` 偏差/阈值若与提案不符，按事实记录。

## 8. 提交

**不 commit、不 push、不切分支**。交付物由 PM 在收口 commit 中统一入库（`.claude/handoffs/**` 之外的文件由 PM 提交）。

## 9. review.md / p1-report.md 格式

- `review.md`：总判定（PASS / 有保留 PASS / FAIL）+ 七条逐条表 + 逐包抽查表（T100–T114：结论/自己复跑的命令或 `文件:行`/与各包 review 的差异）+ 全量回归 + 越界审计 + 未覆盖/NOT-RUN + ≤10 行给主人摘要。
- `p1-report.md`：P1 范围与逐包 commit 表（含 T111 pilot、T112 b0 baseline）+ 七条结果 + 真实调用/成本（保守口径）+ 残余与 NOT-RUN + 发布建议（含"是否建议合并 main"——由主人决定）。
