# T303 开发交接提示词（运营总览与可视化入口）

> 使用方法：把本文件全文复制粘贴给开发窗口的开发助手，作为唯一任务指令。本文件自包含。
> 派单人：项目经理。派单日期：2026-11-22。前置：T301、T302 均已验收 PASS（`T301-acceptance.md`、`T302-acceptance.md`）。

---

## 0. 你的角色与铁律

你是开发执行者，本次**只做 T303：前端运营总览页 + 管理员入口 + ECharts 图表 + 下钻参数**。不做 T304 问答诊断列表/详情，不做 T305 资产列表/详情（本任务只建占位页验证参数），**不改任何后端代码**。

铁律（违反任何一条即验收 FAIL）：

1. 工作目录 `D:\GPT项目\市场部AI知识库`。Windows + PowerShell 7（pwsh），Bash 不可用。
2. 前端命令在 `frontend\` 下用 `npm.cmd` / `npx.cmd`；后端只读参照，Python 用仓库根 `.venv\Scripts\python.exe`。
3. 禁止付费调用：不调真实模型/OCR/Ragas。e2e 只走登录与只读页面，**绝不发送问答 POST**（后端未配替身时问答会报 MODEL_NOT_CONFIGURED，也不要为了造数据去调真实模型）。
4. 禁止写 `var\`。e2e 后端的数据目录必须指向隔离目录（见 §6）。
5. 禁止 git 写操作（add/commit/checkout/reset/stash/clean 全禁），git 只读命令可用。
6. 工作区在途改动与未跟踪 P2/P3 证据全部原样保留。T301、T302 的全部交付物（含 `backend\src\mktkb\operations\`、`backend\tests\operations\`、`schema.d.ts`、OpenAPI 产物）**只读不改**。
7. 发现 T302 接口缺字段/口径问题：**停下写上报事项**，不得自己改后端或改冻结口径。
8. `原型设计\P3原型\overview.html` 仅作布局参考（§3.3 已逐项对齐）：「开始评测/重试」按钮、固定四阶段耗时条、环比副注、今日按小时分段、「需澄清未确认」待处理项均为演示效果，**不实现**；不引入 Tailwind/iconify/CDN 脚本。
9. 交付只认「变更清单 + 验证证据（命令、退出码、通过/失败/跳过数）+ 已知限制」。
10. 数字用阿拉伯数字，文档用 Markdown。

## 1. 开工前必读（按顺序）

路径相对仓库根：

1. `docs\superpowers\plans\2026-11-21-mktkb-p3-operations-taskbook.md` —— T303 小节、§2、§4（唯一验收依据）。
2. `docs\reports\OBS-EVAL\P3\T301-data-audit.md` §3（指标口径）、§6（API 约定）；`T302-evidence\T302-delivery.md` §4（18 项接口契约登记，前端必须按此消费）。
3. `docs\reports\OBS-EVAL\P3\T302-evidence\api\openapi.json` —— 6 个运营接口的权威契约；`frontend\src\api\schema.d.ts` 已含全部响应类型（`OverviewResponse`、`RequestsPage`、`DocumentsPage` 等），**直接 import type，不要手写重复类型，不要重新生成 schema**。
4. `原型设计\P3原型\overview.html` —— 总览页布局参考（页头/页签/筛选条/四卡/3:2 图表行/待处理表的层级与文案基调）；`qa-diagnosis.html`、`knowledge-assets.html` 属 T304/T305 参考，本任务不做。
4. 前端源码（实核过的现状）：
   - `frontend\src\app\App.tsx` —— 路由表（45 行，Routes 嵌套 RequireAuth → AppShell）。
   - `frontend\src\app\AppShell.tsx` —— 侧栏导航：125-134 行是 `role === 'admin'` 才显示「资料管理」NavLink 的现成写法；507 行 topbar 标题按 `isDocuments` 切换；移动端抽屉复用同一 `SidebarContent`。
   - `frontend\src\app\RequireAuth.tsx` —— 登录门禁（角色门禁不在这里）。
   - `frontend\src\features\documents\DocumentsPage.tsx` —— 78 行 `isAdmin = user?.role === 'admin'`，228 行非管理员渲染 `notice notice-error` 的页面级门禁写法，照此模式。
   - `frontend\src\api\client.ts` —— 121 行 `request<T>(path, options)` 通用请求器（含 CSRF/错误信封/401 处理），185 行 `export const api = {...}` 方法集；类型从 `./schema` import。
   - `frontend\src\styles\tokens.css`、`global.css` —— 颜色变量（`--amber-*` 橙、`--rose-*` 红、`--emerald-*` 绿、`--slate-*` 灰）；断点只有 2 个：`@media (max-width: 1024px)` 和 `(max-width: 520px)`（global.css:2714/2782）。
   - `frontend\src\components\Icon.tsx` —— 只用其中已有的图标名，不改该文件。
   - `frontend\vite.config.ts` —— `/api` 代理目标由环境变量 `T08_BACKEND_ORIGIN` 覆盖（默认 8077），dev 和 preview 都生效。
   - `frontend\playwright.acceptance.config.ts` —— 现有 Playwright 配置参照（workers=1、retries=0、forbidOnly、timezone Asia/Shanghai、json reporter）。
5. 后端只读参照（造种子数据用）：`backend\tests\operations\helpers.py`（受控样本构造）、`backend\src\mktkb\config.py`（Settings：env 前缀 `MKTKB_`，必填 `admin_password`/`employee_password`/`csrf_secret`(≥16 字符)，`trusted_origins` 为 JSON 数组、禁通配）。

## 2. 交付物与文件边界

### 2.1 允许新增

| 位置 | 内容 |
| --- | --- |
| `frontend\src\features\operations\` | `OverviewPage.tsx`、`RequestsPlaceholderPage.tsx`、`DocumentsPlaceholderPage.tsx`、`filters.ts`（共享筛选逻辑）、`charts.ts`（ECharts 封装）、`operations.css`、小组件若干 |
| `frontend\e2e\operations-*.spec.ts` | 本任务 Playwright 用例 |
| `frontend\playwright.operations.config.ts` | 只选中 operations 用例的专用配置 |
| `frontend\e2e\operations-seed.py`（或放 T303-evidence\） | 隔离库种子脚本 |
| `docs\reports\OBS-EVAL\P3\T303-evidence\` | 全部命令日志、Playwright 报告、交付说明 `T303-delivery.md` |

### 2.2 允许修改的现有文件（仅此 5 个，改法受限）

1. `frontend\src\app\App.tsx` —— 只在 AppShell 子路由内加 3 条：`operations`（总览）、`operations/requests`（占位）、`operations/documents`（占位）+ 对应 import。其余不动。
2. `frontend\src\app\AppShell.tsx` —— 只加：侧栏 admin 段「知识运营」NavLink（照 125-134 行资料管理写法，用已有 Icon）；topbar 标题对 `/operations` 前缀显示「知识运营」。既有逻辑一行不改。
3. `frontend\src\api\client.ts` —— 只追加：运营类型别名（从 `Schema` 取 `OverviewResponse`/`RequestsPage`/`DocumentsPage`）+ `api` 对象内 3 个方法 `operationsOverview` / `operationsRequests` / `operationsDocuments`（GET，查询串拼接，复用 `request<T>`）。既有方法不改。
4. `frontend\package.json` + `frontend\package-lock.json` —— **只允许通过 `npm.cmd install echarts --save-exact` 产生**（本任务负责 echarts 安装，全项目只装这一次），不得手改、不得装其他包。

### 2.3 禁止

- 改 `backend\` 任何文件、`schema.d.ts`、`global.css`/`tokens.css` 既有规则（新样式全部放 `operations.css`，复用现有变量与 class）、`Icon.tsx`、`vite.config.ts`、其余现有 Playwright 配置与 e2e 用例。
- 实现 T304/T305 的完整列表/详情 UI；实现「开始评测/重试」按钮；虚构阶段耗时条。
- 写 `var\`、git 写操作、真实外部调用。

## 3. 页面与交互契约

### 3.1 路由与门禁

- `/operations` 总览；`/operations/requests`、`/operations/documents` 占位页。3 条路由都挂在 AppShell 下（沿用 RequireAuth 登录门禁）。
- 页面级 admin 门禁照 DocumentsPage 模式：非 admin 渲染无权限提示（`notice notice-error`），不发运营请求；侧栏入口只对 admin 显示。后端 403 是兜底，前端不能只靠后端。
- 员工问答/资料路径不受影响：不改 chat、documents 任何行为。

### 3.2 共享筛选逻辑（filters.ts，全页唯一实现）

- 筛选状态**全部存 URL search params**：`window=today|7d|30d|custom`、`since`、`until`、`kind`、`document_id`、`version_id`、`state`。刷新、浏览器返回后筛选原样恢复（这是验收硬条件）。
- 默认 `window=7d`。日期切换器提供 今日 / 近 7 天 / 近 30 天 / 自定义（自定义给起止日期输入，超 90 天前端直接提示不发请求；后端 422 兜底显示错误态）。
- **图表点击、键盘等价入口、日期切换器全部调用同一个更新函数**，禁止各写一套。
- 点击趋势图某天（或该天的键盘等价按钮）→ 写 `window=custom&since=该日&until=该日` 并跳转 `/operations/requests`；点击结果分布某类 → 携带当前窗口 + `kind=该类` 跳转 `/operations/requests`；点击待处理问答项 → 携带该项 `drilldown` 的日期与 kind；点击待处理导入项 → 跳转 `/operations/documents` 携带 `document_id`（有 version_id 则带上）与 `state`。**下钻参数一律取 T302 响应里的 `drilldown` 字段，不要前端自拼口径。**

### 3.3 总览页布局（对齐 `原型设计\P3原型\overview.html`，已实核；布局照原型，数据与颜色照现有系统）

原型是 Tailwind + CDN ECharts 的静态演示，**只取布局与信息层级，不引入 Tailwind/iconify/CDN 脚本**，实现用现有 React + tokens.css 变量 + 本地 echarts。自上而下：

0. 页头：标题「知识运营」+「只读工作台」徽章 + 一句说明（查看问答效果、异常分布与知识资产状态；资料处理请前往资料管理）+ 右侧「前往资料管理」链接（跳现有 `/documents`）。
1. 页签条：运营总览 / 问答诊断 / 知识资产 3 个页签（对应 `/operations`、`/operations/requests`、`/operations/documents`，后两个本任务是占位页，页签仍可点）。
2. 日期筛选条：按钮组 今日 / 近 7 天 / 近 30 天 / 自定义 + 右侧当前窗口起止文字（如「2026-11-16 至 2026-11-22」）+ 口径说明「按问答结束时间归属 · Asia/Shanghai」。
3. 四张指标卡（一行 4 列，移动端折行）：
   - 已完成问答（`metrics.completed_requests`），副注只写窗口说明；**原型的「较上一个 7 天 +12.4%」是演示数据，T302 无环比字段，不实现环比**。
   - 未找到（`metrics.not_found`），副注可写「占全部问答 x%」（分母为 0 显示「无样本」，不显示 0.0%），可点击下钻。
   - 资料冲突（`metrics.conflict`），数字与图标用橙色系，副注「需管理员核实」，可点击下钻。
   - 当前待审核版本（`metrics.review_required_versions`），卡面带「当前」小徽章 + 副注「与日期筛选无关」，下钻 `/operations/documents?state=review_required`。
4. 图表行（桌面 3:2 两栏，移动端上下堆叠）：
   - 左：问答趋势折线（ECharts LineChart，平滑 + 面积渐变，参照原型 trendChart 配置），标题「问答趋势」+ 提示「点击任一天节点 → 该日问答明细」+「单位：次」角标；`trend` 数组，横轴日历日；空数组渲染空态。**原型「今日」按小时分段是演示效果，T302 trend 按日粒度，今日就是单点，不做小时分段**。图下提供键盘可用的日期按钮列表（与点击同函数）。
   - 右：结果分布**横向条形图**（BarChart，yAxis category inverse，参照原型 distChart），6 类固定顺序与中文标签：已回答(answer)/需澄清(clarification)/未找到(not_found)/资料冲突(conflict)/服务异常(service_error)/知识已变更(knowledge_changed)；条右侧显示数值；conflict 用现有橙色系（`--amber-*`）且带文字标签，不只靠颜色；标题下提示「近 7 天共 N 条，已回答占 x%」（该占比是结果分布参考，**不得标为业务正确率**）。图下提供 6 个键盘可用按钮。
5. 待处理事项表（参照原型表格）：表头 时间 / 异常类型 / 相关问题或文件 / 查看；类型徽章沿用现有橙色系（资料冲突、版本待审核橙；服务异常、导入失败可用现有红色系徽章，均带文字）。**数据只取 T302 `pending` 数组（service_error/conflict/not_found + 导入 failed/blocked）；原型里的「需澄清未确认」待处理项是演示效果，T302 无此口径，不实现**。问答项显示 kind 中文标签 + 完成时间 + error_code（有才显示），导入项显示状态 + error_code；空列表用空态文案。
6. 辅助信息：`interrupted`（中断单列，不入六类）、`active_documents`（标「当前」）、`trace_coverage`（按 status 显示：recorded/partial 显示「覆盖 x/y」，disabled 显示「Trace 已关闭」，unavailable 显示「Trace 暂不可用」，not_recorded 显示「未记录」；**任何占比不得标为业务正确率**）。
7. 页脚说明：数据环境标注（隔离/示例数据时明示）+「本页为只读运营工作台」。

### 3.4 状态覆盖

- 加载：骨架或 spinner（沿用现有 `spinner` class）。
- 错误：错误文案 + 重试按钮（重新请求，不是发起评测）；403 显示无权限；422 显示参数错误。
- 空数据：卡片计 0、图表空态、列表空态；不补零伪造趋势、不显示假百分比。
- 响应式：桌面 1440 与移动 390 宽都要能完成筛选与下钻（用现有 1024/520 断点，样式放 operations.css）。

### 3.5 占位页（本任务只验参数，不做完整 UI）

- 读 URL 筛选 → 调 `operationsRequests` / `operationsDocuments`（同一 filters.ts 序列化）→ 页面显示：已应用筛选的逐项回显 + 接口返回的总数字段 + 提示「完整列表将在后续任务接入」。
- 目的：证明下钻携带的日期、结果、状态与总览卡片口径一致（总数相等，e2e 断言）。

### 3.6 ECharts 使用规范

- 按需引入：`echarts/core` + `LineChart`/`BarChart` + `GridComponent`/`TooltipComponent`/`LegendComponent` + `CanvasRenderer`，不全量 import。
- 组件卸载 dispose；容器尺寸变化 resize；`prefers-reduced-motion` 时关动画。
- 颜色取 tokens.css 现有变量值；tooltip 中文。

## 4. 实现步骤（每步 build 通过再进下一步）

1. `npm.cmd install echarts --save-exact`，记录版本；`npm.cmd run build` 确认基线不破。
2. `filters.ts` + client.ts 3 个方法 + 类型别名；build。
3. 路由 + 侧栏入口 + 页面门禁 + 占位页骨架；build。
4. 总览页静态布局（卡片/列表/状态覆盖，先用真实接口渲染）；build。
5. ECharts 两图 + 点击/键盘等价入口 + 下钻跳转；build。
6. 种子脚本 + Playwright 配置 + 用例 P1-P11；跑通。
7. 证据归档 + `T303-delivery.md` + git 快照对比。

## 5. Playwright 用例清单（每条一个 test，缺一条验收 FAIL）

配置 `playwright.operations.config.ts`：`testMatch: /operations-.*\.spec\.ts/`、`workers: 1`、`retries: 0`、`forbidOnly: true`、`timezoneId: 'Asia/Shanghai'`、baseURL `http://127.0.0.1:5299`、json reporter 输出到 T303-evidence；两个 project：desktop 1440x900、mobile 390x844。webServer 见 §6。

| # | 用例 | 断言要点 |
| --- | --- | --- |
| P1 | admin 登录 → 侧栏见「知识运营」→ 进入总览 | 4 卡、两图、待处理列表渲染；数字与种子预期一致 |
| P2 | employee 登录 | 侧栏无「知识运营」；直达 `/operations` 显示无权限提示；用 page.request 直调运营接口断言 403 |
| P3 | 日期切换 today/7d/30d/自定义 | 每次切换趋势与分布**同时**更新（断言发出的请求参数一致 + 卡片数字变化正确） |
| P4 | 点击趋势某天 | URL `since=until=该日`；占位页总数 == 总览该日完成量 |
| P5 | 键盘等价入口 | 只用 Tab/Enter 完成一次日期下钻与一次类别下钻，结果与鼠标点击一致 |
| P6 | 点击分布 conflict 类 | URL 带 `kind=conflict` 与当前窗口；占位页总数 == 分布 conflict 计数 |
| P7 | 点击待处理导入失败项 | 跳 documents 占位页，URL 带 document_id/state；总数与口径一致 |
| P8 | 刷新与浏览器返回 | 已应用筛选原样保留（URL 与页面显示一致） |
| P9 | 空窗口（选一段无数据的自定义窗口） | 计 0、图表与列表空态、无假百分比 |
| P10 | mobile project | 390 宽下完成日期切换 + 一次下钻 |
| P11 | 错误态 | 用 page.route 拦截运营接口返回 500/断网，页面显示错误与重试；恢复后重试成功 |

种子数据最低要求（`operations-seed.py`，只写隔离库，**标注受控样本**；构造方式参照 `backend\tests\operations\helpers.py`）：admin/employee 账号（用 create_app 的 bootstrap 或 helpers 方式）、≥2 个自然日的已完成问答（含 answer 带引用、not_found、conflict 带 result_json.conflicts、service_error）、1 个 review_required 版本、1 个 failed 导入任务（error_code=PARSE_INCOMPLETE）、若干中断请求；另留一段确定无数据的日期窗口供 P9。种子脚本打印各口径预期计数，e2e 断言直接引用这些数值。

## 6. 验证命令（照抄执行，逐条留证据到 T303-evidence\）

```powershell
# 0. 开工/收工快照
git -C 'D:\GPT项目\市场部AI知识库' status --short | Out-File -Encoding utf8 'D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P3\T303-evidence\git-status-start.txt'

# 1. 安装 echarts（frontend\ 下，唯一允许的依赖变更）
Set-Location 'D:\GPT项目\市场部AI知识库\frontend'
npm.cmd install echarts --save-exact 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T303-evidence\npm-install-echarts.txt'
$LASTEXITCODE

# 2. 构建（含 tsc）
npm.cmd run build 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T303-evidence\frontend-build.txt'
$LASTEXITCODE

# 3. 种子（仓库根下；隔离目录例：docs\reports\OBS-EVAL\P3\T303-evidence\isolated-var）
Set-Location 'D:\GPT项目\市场部AI知识库'
.\.venv\Scripts\python.exe -B frontend\e2e\operations-seed.py --data-dir 'docs\reports\OBS-EVAL\P3\T303-evidence\isolated-var' 2>&1 | Tee-Object -FilePath 'docs\reports\OBS-EVAL\P3\T303-evidence\seed-output.txt'
$LASTEXITCODE

# 4. Playwright（frontend\ 下）
Set-Location 'D:\GPT项目\市场部AI知识库\frontend'
npx.cmd playwright test --config=playwright.operations.config.ts 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T303-evidence\playwright-operations.txt'
$LASTEXITCODE
```

webServer 配置要点（写进 playwright.operations.config.ts，两个 server）：

1. 后端：`command: '..\\.venv\\Scripts\\python.exe -B -m uvicorn mktkb.main:create_app --factory --host 127.0.0.1 --port 8288'`，`cwd` 指到 `backend\`，`url: 'http://127.0.0.1:8288/api/v1/healthz'`，env：
   - `MKTKB_DATA_DIR`＝隔离目录绝对路径（与种子一致）
   - `MKTKB_ADMIN_PASSWORD` / `MKTKB_EMPLOYEE_PASSWORD`＝测试固定值（与种子、e2e 登录一致）
   - `MKTKB_CSRF_SECRET`＝≥16 字符测试固定值
   - `MKTKB_TRUSTED_ORIGINS`＝`["http://127.0.0.1:5299"]`（JSON 数组字符串，禁通配）
   - `MKTKB_TRACE_ENABLED`＝`false`、`MKTKB_RAG_QA_ENABLED`＝`false`
   - 环境变量优先级高于仓库 `.env`；e2e 全程不发问答 POST，不会触发模型调用。
2. 前端：`command: 'npm.cmd run preview -- --port 5299 --strictPort'`，`cwd` frontend\，`url: 'http://127.0.0.1:5299'`，env `T08_BACKEND_ORIGIN: 'http://127.0.0.1:8288'`（vite.config.ts 现成覆盖口）。**先 build 再跑 Playwright**。

若 Playwright 浏览器未安装，允许执行 1 次 `npx.cmd playwright install chromium` 并记录；此外不得动依赖。

## 7. 验收完成条件（项目经理逐项核对）

1. 命令 2 build 退出码 0；命令 4 Playwright P1-P11 在 desktop 与 mobile 两个 project 全部通过（用例数×project 数如实记录），退出码 0。
2. 时间筛选同时更新趋势与分布；下钻 URL 参数与卡片口径一致（P3-P7 断言）。
3. 员工无入口、直达被页面门禁拦、接口 403（P2）。
4. 刷新/返回保留筛选（P8）；空态、错误态、加载态齐备（P9/P11）；conflict 橙色系 + 文字标签。
5. 未实现「开始评测/重试」与固定阶段耗时条；占位页不越界做 T304/T305 完整 UI。
6. 边界：git 终态对比开工快照，改动仅限 §2 清单；`backend\`、`schema.d.ts`、`var\` 零改动；echarts 只装 1 次且 --save-exact。
7. `T303-delivery.md` 齐备（变更清单、证据表含退出码与用例数、种子预期值表、实现决定登记、已知限制、上报事项、边界自查）。

## 8. 红线速查（做完逐条自检）

- [ ] 全部筛选走 filters.ts 唯一实现，存 URL，刷新/返回可恢复
- [ ] 下钻参数取 T302 `drilldown` 字段，不自拼口径
- [ ] 库存指标标「当前」；中断单列不入六类；空分母不显示假百分比；任何占比不标「业务正确率」
- [ ] Trace 覆盖率按 status 独立展示（disabled/unavailable/not_recorded/partial）
- [ ] conflict 橙色系 + 文字标签；待处理沿用现有橙色系
- [ ] 页面级 admin 门禁 + 侧栏仅 admin 可见；员工路径零影响
- [ ] 不改后端、不改 schema.d.ts、不改既有 CSS 规则/Icon/vite.config
- [ ] echarts 按需引入、dispose/resize、reduced-motion
- [ ] 无付费调用、var\ 未写、git 无写操作、T301/T302 交付物未动
- [ ] 原型演示效果未实现：「开始评测/重试」、固定四阶段耗时条、环比副注、今日小时分段、「需澄清未确认」待处理项
- [ ] 布局对齐原型 overview.html（页头/页签/四卡/3:2 图表行/待处理表），颜色用现有 tokens，未引入 Tailwind/CDN