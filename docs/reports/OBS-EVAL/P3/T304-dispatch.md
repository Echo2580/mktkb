# T304 开发交接提示词（问答诊断与固定评测摘要）

> 全文复制给开发窗口。与 T305 **并行开发**，文件归属见 §2，越界即验收 FAIL。
> 派单人：项目经理。日期：2026-11-22。前置：T301/T302/T303 均验收 PASS。

## 0. 角色与铁律

你是开发执行者，只做 T304：把 `/operations/requests` 占位页升级为问答诊断页（列表 + 诊断抽屉 + 执行阶段条 + 固定评测页签）。**不改任何后端代码**。

1. 工作目录 `D:\GPT项目\市场部AI知识库`；Windows + PowerShell 7，Bash 不可用；前端命令用 `npm.cmd`/`npx.cmd`。
2. 禁止付费调用；e2e 只走登录与只读页面，**绝不发问答 POST**；禁写 `var\`；git 无写操作（只读命令可用）。
3. T301/T302/T303 交付物只读（含隔离库、证据、报告）；工作区在途改动原样保留。
4. 发现接口缺口径：**停下写上报事项**，不改后端、不改冻结口径、不编造数据。
5. 原型 `原型设计\P3原型\qa-diagnosis.html` 是布局参考（已实读，契约见 §3）；其中「开始评测/重试」按钮、按结果类型固定的阶段耗时与百分比、总耗时秒数均为演示效果，**不实现**；不引入 Tailwind/iconify/CDN。
6. 交付只认变更清单 + 验证证据（命令、退出码、用例数）+ 已知限制。数字用阿拉伯数字。

## 1. 必读（按顺序）

1. 任务书 `docs\superpowers\plans\2026-11-21-mktkb-p3-operations-taskbook.md` T304 小节、§2、§4。
2. `T301-data-audit.md` §4（Span→阶段映射，**冻结，本单 §3.4 已摘录**）、§6.3/6.4（冲突与 Trace 状态）。
3. `T302-evidence\T302-delivery.md` §4（接口契约 18 项）；`T302-evidence\api\openapi.json`；`frontend\src\api\schema.d.ts` 已有 `RequestDetailResponse`/`RequestsPage`/`EvaluationRunsResponse` 等类型，直接 import type，**不重新生成 schema**。
4. `T303-acceptance.md`（裁决：列表用游标分页，无 total 字段；下钻取 drilldown）。
5. 原型 `原型设计\P3原型\qa-diagnosis.html` 全文。
6. 现有代码：`frontend\src\features\operations\`（filters.ts、RequestsPlaceholderPage.tsx、operations.css、OperationsOverviewPage.tsx 的门禁/状态写法）、`frontend\src\api\client.ts`（`request<T>`、`api.operationsRequests`）、`frontend\e2e\operations-overview.spec.ts`（**兼容契约见 §2.3**）、`frontend\playwright.operations.config.ts`（webServer 写法参照）、`frontend\e2e\operations-seed.py`（种子构造参照）。

## 2. 文件归属（与 T305 并行的硬边界）

### 2.1 T304 独占（新增或改写）

| 路径 | 说明 |
| --- | --- |
| `frontend\src\features\operations\RequestsPlaceholderPage.tsx` | **改写为完整问答诊断页**（文件名与导出名不变，App.tsx 无需改） |
| `frontend\src\features\operations\qa\`（新目录） | DiagnosisDrawer.tsx、StageBars.tsx、EvalRunsPanel.tsx、qaApi.ts（用 `request<T>` 封装详情/评测批次/单 run 3 个 GET）、spanLabels.ts、qa.css 等 |
| `frontend\e2e\operations-qa-*.spec.ts`、`frontend\e2e\operations-qa-seed.py` | 本任务用例与种子 |
| `frontend\playwright.operations-qa.config.ts` | 专用配置（§6） |
| `docs\reports\OBS-EVAL\P3\T304-evidence\` | 全部证据 + `T304-delivery.md` |

### 2.2 冻结（两任务都只读）

`backend\**`、`schema.d.ts`、`App.tsx`、`AppShell.tsx`、`client.ts`、`filters.ts`、`operations.css`、`OperationsOverviewPage.tsx`、`charts.ts`、`EChart.tsx`、`operations-overview.spec.ts`、`playwright.operations.config.ts`、`package.json`/`package-lock.json`（echarts 已装，**不装任何新依赖**）、T301/T302/T303 全部交付物。新样式一律放 `qa\qa.css`。需要新的 URL 参数（如 `request_id`）在自己页面内用 `useSearchParams` 读取，**不改 filters.ts**。

### 2.3 兼容契约（保住 T303 的 13 条用例，不改共享 spec）

`operations-overview.spec.ts` 的 P4/P5/P6 断言 requests 页上的 `data-testid="ops-placeholder-ready"`、`ops-placeholder-total`（当前筛选下总条数，文本为纯数字）、`ops-placeholder-kind`（含 kind 原文）。你的完整页面**必须保留这 3 个 testid 与语义**（可放在列表上方的筛选摘要条里；总数沿用 next_cursor 游标累计，上限 20 页并标注）。完成后跑 T303 回归（§6 命令 3）必须全绿。

## 3. 页面契约（对齐原型 qa-diagnosis.html，数据按 T302 实际字段）

### 3.1 页面骨架

页头（标题「知识运营」+「只读工作台」徽章 + 描述「逐条查看问答结果、引用版本与执行过程，异常记录可回溯到具体资料。」+ 右侧「返回总览」链接）、3 页签条（问答诊断高亮，复用 T303 页签样式 class）、次级页签「问答记录 / 固定评测」（按钮组，状态存 URL `tab=records|eval`，刷新保留）。admin 门禁照 T303 模式。

### 3.2 问答记录列表

- 筛选条：窗口（今日/近 7 天/近 30 天/自定义，复用 filters.ts）+ 结果下拉（全部 + 六类中文）+ 重置按钮 + 右侧摘要「当前筛选共 N 条」（N=游标累计总数，放 `ops-placeholder-total`）。
- `document_id`/`version_id` 在 URL 时显示蓝色横幅「已按资料筛选问答记录」+「清除筛选」（原型 assetBanner；资料名接口未返回时显示文档标识，不编造）。
- 表格列（原型 5 列按 API 实际字段适配，**不编造问题摘要与资料名**）：时间（finished_at，Shanghai）/ 请求标识（request_id 短形式 + conflict 橙徽章）/ 结果（六类中文徽章，配色照原型：已回答绿、需澄清/未找到琥珀、冲突橙、服务异常红、知识已变更青绿，用现有 tokens）/ 引用数（citation_count，0 显示「未引用资料」）/ 操作（查看诊断）。列偏差写入交付说明。
- 游标分页：「加载更多」按钮追加下一页（next_cursor），无重复无漏项；空态照原型（「当前筛选条件下没有问答记录」+ 清除筛选）。
- 行可点击且键盘可用（Tab 聚焦 + Enter 打开抽屉）；点击写 URL `request_id=...`（抽屉可直链、刷新后仍打开、关闭时移除该参数，其余筛选不动）。

### 3.3 诊断抽屉（右侧 520px，Esc/遮罩关闭，复用现有 Dialog/Drawer 模式或自建）

调 `GET /api/v1/operations/requests/{request_id}`（qaApi.ts 封装），自上而下：

1. **原问题**：question 原文 + 完成时间/请求标识元信息。
2. **最终结果**：kind 徽章 + 按 kind 的中文说明（照原型 TYPE_META 文案）+ 回答正文（result.text，有则显示）+ error_code（有则显示）+ **知识库 revision**。
3. **引用资料及版本**：citations 逐条卡片（document_name、version_number 徽章、published_at、status；active 才显示 locator；superseded/deleted 显示「已被替换/已删除」灰色徽章，只给元信息）；右上「资料管理 →」链接跳现有 `/documents`。无引用显示「本次回答未引用资料」。
4. **冲突分列**（kind=conflict）：橙色提示条「两份资料均为当前有效版本，记载不一致，系统未自动判定哪一份正确。」+ 两列卡片（各含 document/version/值/说明，取自 conflicts 块）+ 建议处理文案 + 前往资料管理链接。**conflicts 不计入引用数。**
5. **执行阶段**（§3.4）：按 attempt 分组；重放 attempt 显式「重放」徽章；Trace 状态独立文案（disabled「Trace 已关闭」/unavailable「Trace 暂不可用」/not_recorded「本次未记录执行过程」+ 说明「问答内容与引用资料仍可正常查看」）。
6. 底部：「记录为只读，不可编辑」+ 关闭按钮。**不做「打开会话记录」跳转**（跨用户会话归属校验不变，运营页不开放他人会话入口）。

### 3.4 执行阶段条（T301 冻结映射，只渲染实际记录的 Span）

主阶段标签映射（spanLabels.ts 按此实现，不得增删）：

| path | Span → 标签 |
| --- | --- |
| rag | parse→解析计划、recall→检索召回、fuse→融合排序、answer→答案生成、commit→状态持久化；条件 Span 实际存在才渲染：vector_recall→向量召回、rerank→重排、index_sync→索引同步 |
| legacy / legacy_with_rag_candidates | intent_parse→意图解析、retrieve→证据检索、model_answer→模型作答、answer_validate→答案校验、commit→结果提交；条件 Span：query_expansion→查询扩展 |

- 子 Span（exact_recall/lexical_recall/embedding_query/hard_filter/fact_validate/entity_conflict_check/model_failure）不进主阶段条，放「展开细节」折叠区（名称 + duration_ms + status + error_code）。
- 每阶段一行：标签 + 横条（宽度按该 attempt 内已记录主阶段 duration_ms 的相对比例）+ 毫秒数。**未记录 ≠ 0ms，不补阶段、不按结果类型虚构、不显示伪造总耗时秒数**；合计只在有记录时显示「已记录阶段合计 X ms」。
- status=error 的 Span 条用红色系并显示 error_code；不展示 attribute 原文（接口本就只回键名与计数，可显示属性个数）。

### 3.5 固定评测页签

- 说明条：「固定评测使用一组固定问法回归验证回答质量…评测结果不影响线上问答」（照原型文案，但**去掉「由管理员发起」语义，P3 只读不发起**）。
- 调 `GET /api/v1/operations/evaluation-runs`：表格列 批次（run_id + dataset/suite）/ 样本数（case_count，保留原始分母）/ 评测状态（由 scored_count/error_count/gate_status 派生：无执行记录→「未评测」灰、error_count>0 或 gate 失败→「评测失败」红并单列失败原因计数、正常完成→「已完成」绿 + 主要指标值）/ 创建时间 / 操作「查看摘要」。
- 「查看摘要」展开或抽屉显示单批次聚合：调现有 `GET /api/v1/observability/runs/{run_id}`（qaApi.ts 封装），展示 manifest/summary/gate 白名单聚合；`holdout_detected/details_withheld=true` 显示「holdout 明细已扣留，仅聚合可见」徽章，不请求逐题。
- 空列表显示「未找到可用批次」；`degraded_reason` 条目显示对应降级说明。**无「开始评测/重试/查看报告下载」按钮。**
- **任何分数不得标为业务正确率**；指标无样本显示「无样本」。

## 4. 实现步骤

1. qaApi.ts + spanLabels.ts + 页面骨架（页签/筛选/门禁），build 过。
2. 列表 + 游标分页 + 兼容 testid，build 过；跑 T303 回归确认 P4/P5/P6 绿。
3. 抽屉（问题/结果/引用/冲突/revision），build 过。
4. 阶段条 + attempts + Trace 状态，build 过。
5. 评测页签 + 单 run 摘要，build 过。
6. 种子 + 专用 Playwright 配置 + 用例 Q1-Q10；全过。
7. T303 回归 + 证据归档 + 交付说明 + git 快照对比。

## 5. Playwright 用例（Q1-Q10，desktop 1440×900 + mobile 390×844 双 project）

种子（operations-qa-seed.py，只写自己的隔离目录，标注受控样本 + Mock）最低覆盖：≥2 日问答含 answer 带引用（含同文档多行引用）、not_found、conflict（result_json.conflicts 两方）、service_error、knowledge_changed、superseded 旧版引用、重放请求、无 Trace 请求（Trace 关闭应用产生或直写无 Trace 行）、1 个受控评测 run 目录（manifest/summary/gate 三 JSON，含 1 个 holdout run 与 1 个空目录）、>1 页的请求量（验证分页）。种子打印预期值 JSON 供断言。

| # | 用例 | 断言要点 |
| --- | --- | --- |
| Q1 | 列表渲染与筛选 | 窗口 + kind 筛选后列表与摘要总数一致；URL 参数正确；重置恢复 |
| Q2 | 分页 | 加载更多后无重复 request_id；累计总数与种子预期一致 |
| Q3 | 抽屉直链 | 点行打开抽屉且 URL 带 request_id；刷新仍打开；Esc 关闭且参数移除、筛选保留 |
| Q4 | answer 详情 | 问题/回答/revision/引用名称与版本与种子一致；active 带定位、superseded 只给元信息 |
| Q5 | conflict 详情 | 两方卡片值与种子一致；引用数为 0；橙色提示与建议处理在位 |
| Q6 | 阶段条 | 有 Trace 的 attempt 只出现映射内实际 Span；重放 attempt 带「重放」；无 Trace 显示「未记录」且业务内容可读；不出现虚构阶段 |
| Q7 | Trace 关闭 | 关闭态应用下详情业务可读、阶段区显示「Trace 已关闭」 |
| Q8 | 评测页签 | 批次/样本数/状态与受控 run 一致；holdout 显示扣留徽章；空目录不出现；无「开始评测/重试」按钮；切页签刷新保留 |
| Q9 | 员工与空态 | employee 门禁 + 直调 403；空窗口空态；接口 500 错误态 + 重试 |
| Q10 | 移动端 | 390 宽完成筛选 + 打开抽屉 + 关闭 |

## 6. 验证命令（证据存 T304-evidence\）

```powershell
# 0. 开工快照
git -C 'D:\GPT项目\市场部AI知识库' status --short | Out-File -Encoding utf8 'D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P3\T304-evidence\git-status-start.txt'
# 1. 构建
Set-Location 'D:\GPT项目\市场部AI知识库\frontend'
npm.cmd run build 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T304-evidence\frontend-build.txt'; $LASTEXITCODE
# 2. 本任务用例（专用配置：testMatch /operations-qa-.*\.spec\.ts/，后端 8289、preview 5300，MKTKB_TRUSTED_ORIGINS=["http://127.0.0.1:5300"]，数据目录 T304-evidence\isolated-var，reporter 输出全部指向 T304-evidence；其余照 playwright.operations.config.ts 模式）
npx.cmd playwright test --config=playwright.operations-qa.config.ts 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T304-evidence\playwright-qa.txt'; $LASTEXITCODE
# 3. T303 回归（复用 T303 配置与隔离数据；--reporter=list 避免覆盖 T303 的 JSON/HTML 报告）
npx.cmd playwright test --config=playwright.operations.config.ts operations-overview --reporter=list 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T304-evidence\playwright-t303-regression.txt'; $LASTEXITCODE
```

**并行注意**：命令 3 占用 8288/5299 端口，T305 窗口也会跑同一回归；若端口被占用说明另一窗口正在跑，等 1-2 分钟重试，不要改 T303 配置端口。命令 2 用你自己的 8289/5300，与 T305（8290/5301）互不冲突。

## 7. 验收完成条件

1. build 退出码 0；Q1-Q10 双 project 全过；T303 回归 26 条全绿（兼容 testid 保住）。
2. 从总览下钻到 not_found/conflict，有无 Trace 两种情况都能核对实际结果（Q5/Q6/Q7 覆盖）。
3. 评测批次原始分母与状态与页面一致；holdout 扣留；无发起评测入口。
4. 阶段条只渲染 T301 映射内实际 Span；重放可辨认；未记录不补 0。
5. 边界：改动仅限 §2.1；冻结文件零改动；var\ 未写；无新依赖。
6. `T304-delivery.md`：变更清单、证据表（退出码/用例数）、列偏差与实现决定登记、已知限制、上报事项、边界自查。

## 8. 红线速查

- [ ] 冲突两方取 conflicts 块、不计引用数；旧版只给元信息；revision 展示
- [ ] 阶段标签按 §3.4 冻结映射；未记录≠0ms；不虚构总耗时；重放标注
- [ ] Trace 关闭/不可用/未记录独立文案，业务内容始终可读
- [ ] 评测只读：无开始/重试按钮；holdout 只聚合；分母保留；不标业务正确率
- [ ] 兼容 testid 保留，T303 回归全绿；冻结文件未动；不装依赖
- [ ] 无付费调用、var\ 未写、git 无写操作、不打开他人会话入口