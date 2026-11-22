# T304 交付说明（问答诊断页）

- 任务：`T304-dispatch.md` §1-§8，市场部 AI 知识库 P3 运营工作台「问答诊断」页
- 执行人：开发执行窗口（与 T305 知识资产页并行）
- 完成时间：2026-11-22
- 代码基线：分支 `codex/p2-e2e`，HEAD `0d6ba61d0c6253550adf26888dab935ffe4310b1`（`T304-evidence/git-head-start.txt`、`git-sha-start.txt`）
- 证据目录：`docs/reports/OBS-EVAL/P3/T304-evidence/`

## 1. 变更清单（仅 §2.1 独占文件）

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `frontend/src/features/operations/RequestsPlaceholderPage.tsx` | 改写（导出名与文件名不变） | 问答诊断页整页：头部+只读徽章+示例数据徽章、三页签 `ops-tabs`、次级 `qa-seg`（问答记录/固定评测，`tab=eval` 入 URL）、窗口/结果/资料筛选、游标分页列表、加载更多、错误与重试 |
| `frontend/src/features/operations/qa/qaApi.ts` | 新增 | 封装 3 个只读 GET：`/operations/requests/{id}`、`/operations/evaluation-runs`、`/observability/runs/{run_id}`；类型全部取自 `schema.d.ts` |
| `frontend/src/features/operations/qa/spanLabels.ts` | 新增 | T301 冻结 Span→中文映射（rag 8 个 / legacy 6 个 / 子 Span 7 个），`legacy_with_rag_candidates` 归 legacy |
| `frontend/src/features/operations/qa/qaMeta.ts` | 新增 | 六类结果标签与说明、上海时区时间、引用状态（active/superseded）、locator 扁平化、评测状态派生、degraded 文案 |
| `frontend/src/features/operations/qa/StageBars.tsx` | 新增 | 阶段条：只渲染实际记录的 Span，宽度按已记录占比，未记录显示「时长未记录」且不计入合计，错误 Span 标红带错误码，子 Span 折叠 `<details>`，重放 attempt 标注 |
| `frontend/src/features/operations/qa/DiagnosisDrawer.tsx` | 新增 | 520px 诊断抽屉：Esc/遮罩关闭与焦点管理、原问题与完成时间、结果卡、引用卡、冲突两列卡、执行阶段区、只读声明；无「打开会话记录」入口 |
| `frontend/src/features/operations/qa/EvalRunsPanel.tsx` | 新增 | 固定评测页签：批次表（批次/样本数/评测状态/创建时间/查看摘要）、holdout 徽章、无开始/重试/下载入口；单批次抽屉复用 `/observability/runs/{id}`，只展示白名单字段与 holdout 聚合 |
| `frontend/src/features/operations/qa/qa.css` | 新增 | T304 全部样式（徽章六色、抽屉、冲突两列、阶段条、评测表、720/390 断点），未改 `operations.css`/global |
| `frontend/e2e/operations-qa-seed.py` | 新增 | 受控种子：24 条 7d + 25 条 30d 问答、Trace 记录（含重放/无 Trace）、3 个评测批次 + 1 个空目录，输出 `seed-summary.json` |
| `frontend/e2e/operations-qa.spec.ts` | 新增 | Q1-Q10（Q10 只在 mobile project 执行），期望值全部读 `seed-summary.json` |
| `frontend/playwright.operations-qa.config.ts` | 新增 | 专用配置：`testMatch /operations-qa.*\.spec\.ts/`、隔离数据目录、4 个 webServer（双栈）、desktop/mobile 双 project、串行无重试 |
| `docs/reports/OBS-EVAL/P3/T304-delivery.md`、`T304-evidence/` | 新增 | 本文件与全部证据 |

冻结文件零改动：`operations.css`、`filters.ts`、`client.ts`、`schema.d.ts`、`App.tsx`、`AppShell.tsx`、`OperationsOverviewPage.tsx`、`charts.ts`、`EChart.tsx`、`operations-overview.spec.ts`、`playwright.operations.config.ts`、`backend/**`、T301/T302/T303 既有交付物。未装任何新依赖。

## 2. 证据表

| # | 命令 | 结果 | 证据文件 |
| --- | --- | --- | --- |
| 1 | `npm run typecheck` | 退出码 0 | `T304-evidence/frontend-typecheck.txt` |
| 2 | `npm run build` | 退出码 0（dist 生成成功） | `T304-evidence/frontend-build.txt` |
| 3 | `npx playwright test --config=playwright.operations-qa.config.ts` | **19 passed / 1 skipped / 0 failed**（51.7s，skipped 是 desktop project 的 Q10，按设计只跑 mobile） | `T304-evidence/playwright-qa.txt`、`playwright-qa.json`（`expected=19 skipped=1 unexpected=0 flaky=0`）、`playwright-report/index.html` |
| 4 | `npx playwright test --config=playwright.operations.config.ts operations-overview --reporter=list` | **26 passed / 0 failed**（46.3s，T303 P1-P13 双 project 全绿） | `T304-evidence/playwright-t303-regression.txt` |

种子与期望值：`T304-evidence/isolated-var/seed-summary.json`（只写隔离目录，`backend/var/` 未写入）。关键期望值：today=16、week7d=24、month30d=25、empty=0、conflict_week=1、page_size=20、首页 20 行、共 2 页。

用例覆盖（每个用例都断言了页面真实渲染值，不是只断 URL）：

| 用例 | 覆盖点 | desktop | mobile |
| --- | --- | --- | --- |
| Q1 | 窗口（today/7d/30d/自定义）切换、结果筛选、kind 原文、总数与行数一致、重置 | 通过 | 通过 |
| Q2 | 游标分页首页 20 条、加载更多累计到 24、无重复、总数一致 | 通过 | 通过 |
| Q3 | 直链 `request_id` 打开抽屉、Esc 关闭后筛选保留、Tab/Enter 键盘可开 | 通过 | 通过 |
| Q4 | active 引用显示 V2 与 locator（`sheet Sheet1,row 1`）、superseded 引用灰显仅元信息、revision 展示 | 通过 | 通过 |
| Q5 | 冲突两方（门店服务手册 V1「3 个工作日」/ 市场活动补充通知 V1「5 个工作日」）两列展示、不显示引用卡 | 通过 | 通过 |
| Q6 | 阶段条仅渲染映射内实际 Span（rag 7 阶段 / legacy 5 阶段）、未记录不补 0ms、重放 attempt2 标注重放且 0 Span、service_error 标红 `MODEL_TIMEOUT` | 通过 | 通过 |
| Q7 | Trace 关闭态栈：业务内容与引用照常可读、阶段区显示「Trace 已关闭」且无阶段条 | 通过 | 通过 |
| Q8 | 固定评测页签：3 个批次分母（20/20/12）与状态（已完成/评测失败/已完成）一致、holdout 扣留徽章、无「开始评测」入口、刷新保留 `tab=eval` | 通过 | 通过 |
| Q9 | 员工账号 403 门禁文案、详情 403、空窗口空态、500 失败重试恢复 | 通过 | 通过 |
| Q10 | 390×844：筛选可用、抽屉宽度不超视口、关闭正常 | 按设计 skip | 通过 |

## 3. 偏差与实现决定登记

1. **Trace 关闭态用第二套真实栈**（实现决定，非偏差）：派单只给了 8289/5300 主栈，但 Q7 需要「后端 Trace 关闭」的真实环境。实现为：主栈 8289 + preview 5300（`MKTKB_TRACE_ENABLED=true`），关闭态栈 8292 + preview 5302（`false`，同一隔离数据目录，`MKTKB_TRUSTED_ORIGINS` 分别指向 5300 / 5302）。端口 8290/5301 留给 T305，未占用。
2. **数据目录命名按派单 `T304-evidence\isolated-var`**（早期用过 `isolated-qa`，已改名并对齐，代码里只有两处引用）。
3. **完成时间来自列表行**：`RequestDetailResponse` 不返回 `finished_at`，抽屉的完成时间由列表行 `finishedAt` 传入；若直链打开且该行不在当前列表页，显示「未记录」，不编造。
4. **引用卡锚点用 `document_id`**：`data-citation` 绑文档 id（另存 `data-source-id`），这样同文档两条引用（active/superseded）能分别定位。
5. **T303 回归必须带 `operations-overview` 过滤**：T303 配置的 `testMatch` 是 `/operations-.*\.spec\.ts/`，会同时选中 T305 的 `operations-assets-page.spec.ts` 和本任务的 `operations-qa.spec.ts`，在 T303 的数据目录下必然失败（不是回归失败）。按派单 §6 命令 3 的写法（带 `operations-overview`）跑才是 26 条。
6. **环境适配开关（默认关闭影响）**：`playwright.operations-qa.config.ts` 增加 `T304_STACK=main|traceoff|both`（默认 both，一次跑完整套；内存紧张时可拆栈跑）、Chromium 启动参数（`--renderer-process-limit=1`、`--js-flags=--max-old-space-size=384` 等）与 `OPENBLAS/OMP/MKL_NUM_THREADS=1`。这些只影响测试进程资源，不改变被测逻辑。
7. **移动端断言容差**：`deviceScaleFactor=2` 下抽屉宽度出现 390.0000048px 的亚像素误差，断言容差放到 0.5px（不是放宽语义）。

## 4. 已知限制

- 本机物理内存 16GB、系统提交额度（48.4GB）在全套并行时会打满：Chromium 会报 `VirtualAlloc failed`、uvicorn 导入期 `MemoryError`、PowerShell 自身 OOM 崩掉，还出现过整机掉线。上述最终结果是在释放重负载进程后跑出的（`FreeVirt ≈ 5GB`）。**建议验收在空闲机器上执行，运行期间不要并行其它 Playwright 套件。**
- 评测页签为只读视图，只能看批次聚合与 holdout 扣留，逐题明细不可见（T301/T302 契约如此，页面不请求逐题）。
- 抽屉的「完成时间」在直链且行不在当前页时显示「未记录」（见 §3.3）。

## 5. 上报事项

- **T303 的 `playwright.operations.config.ts` 的 `testMatch` 建议收窄**（例如 `/operations-overview.*\.spec\.ts/`），否则任何新增的 `operations-*.spec.ts` 都会污染 T303 回归。该文件属 T303 冻结文件，本窗口未改，请项目经理裁决。
- T305 的 `operations-assets-page.spec.ts` 同样会被上述宽 pattern 选中，两个窗口的回归结果都受影响，建议一并处理。

## 6. 边界自查

| 检查项 | 结论 | 证据 |
| --- | --- | --- |
| 改动仅限 §2.1 | 是。`git status -uall` 中本任务新增/改写只有：`RequestsPlaceholderPage.tsx`、`qa/` 7 个新文件、`e2e/operations-qa-seed.py`、`e2e/operations-qa.spec.ts`、`playwright.operations-qa.config.ts`、本交付文档与证据目录 | `T304-evidence/git-status-uall-end.txt` |
| 冻结文件零改动 | 是。开工/收工 `git status` 的已修改（`M`）集合完全一致（`client.ts`、`schema.d.ts`、`App.tsx`、`AppShell.tsx`、`package.json` 等均为开工前已存在的改动，非本窗口产生） | `git-status-start.txt` 与 `git-status-end.txt` 的 `Compare-Object` 差异只有 6 个新增 `??` 条目（本任务 3 个 + T305 3 个） |
| `backend/var/` 未写 | 是。所有后端进程都用 `MKTKB_DATA_DIR=T304-evidence\isolated-var` | `playwright.operations-qa.config.ts`（`BACKEND_ENV`） |
| 未装新依赖 | 是。未改 `package.json`/`package-lock.json`，未执行任何 install | `git-status-*` |
| 无付费调用 | 是。种子与用例只走本地只读接口 | `operations-qa-seed.py`、`qaApi.ts` |
| 无 git 写操作 | 是。只做了 `git status/diff/rev-parse` 读取 | `git-head-start.txt`、`git-sha-start.txt` |
| 无「打开会话记录」入口 | 是。抽屉与列表都不提供会话跳转 | `DiagnosisDrawer.tsx` |

## 7. 复现命令

```powershell
# 重建受控种子（会先清理自己上次的目录）
Set-Location 'D:\GPT项目\市场部AI知识库'
.\.venv\Scripts\python.exe -B frontend\e2e\operations-qa-seed.py --data-dir 'docs\reports\OBS-EVAL\P3\T304-evidence\isolated-var'

# 本任务全套（双栈，一次跑完 desktop + mobile）
Set-Location 'D:\GPT项目\市场部AI知识库\frontend'
npx.cmd playwright test --config=playwright.operations-qa.config.ts

# 内存紧张时拆栈（可选）
$env:T304_STACK='main';     npx.cmd playwright test --config=playwright.operations-qa.config.ts --project=desktop --grep-invert 'Q7'
$env:T304_STACK='traceoff'; npx.cmd playwright test --config=playwright.operations-qa.config.ts --project=desktop --grep 'Q7'
Remove-Item Env:T304_STACK

# T303 回归（必须是 26 条）
npx.cmd playwright test --config=playwright.operations.config.ts operations-overview --reporter=list
```
