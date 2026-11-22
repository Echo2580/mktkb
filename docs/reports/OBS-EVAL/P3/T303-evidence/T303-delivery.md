# T303 交付说明：运营总览与可视化入口

- 任务：T303 前端只读运营总览、管理员入口与页面门禁、ECharts 趋势/分布、下钻占位页。
- 工作目录：`D:\GPT项目\市场部AI知识库`（Windows，PowerShell 7，前端命令用 `npm.cmd` / `npx.cmd`）。
- 验收依据：`docs\superpowers\plans\2026-11-21-mktkb-p3-operations-taskbook.md` 的 T303 小节与 §2；`docs\reports\OBS-EVAL\P3\T303-dispatch.md` 全文。
- 任务边界：仅前端；未改后端、`schema.d.ts`、既有 CSS/Icon/vite 配置；未实现 T304/T305 完整 UI；未做「开始评测/重试」与阶段耗时条；全程离线，未发问答 POST。

## 1. 变更清单

### 1.1 新增文件

| 路径 | 内容 |
| --- | --- |
| `frontend\src\features\operations\filters.ts` | 筛选唯一实现：URL 读写、窗口换算、90 天校验、下钻参数、接口参数序列化、`state` 映射 |
| `frontend\src\features\operations\charts.ts` | 趋势折线与结果分布 ECharts option；conflict 橙色、中文标签 |
| `frontend\src\features\operations\EChart.tsx` | ECharts 按需注册、初始化/`dispose`、`ResizeObserver`、图表点击换算 |
| `frontend\src\features\operations\OperationsOverviewPage.tsx` | `/operations` 总览：日期筛选、四指标卡、库存/Trace 状态、两图、待处理列表 |
| `frontend\src\features\operations\RequestsPlaceholderPage.tsx` | 问答诊断占位页：回显筛选、游标累计总数、后续任务提示 |
| `frontend\src\features\operations\DocumentsPlaceholderPage.tsx` | 资产与导入占位页：回显筛选、状态映射、游标累计总数 |
| `frontend\src\features\operations\operations.css` | 运营页新增样式（仅本文件；未改 global/tokens） |
| `frontend\e2e\operations-overview.spec.ts` | P1-P11 Playwright 用例 |
| `frontend\e2e\operations-seed.py` | 隔离库受控种子与预期值汇总 `seed-summary.json` |
| `frontend\playwright.operations.config.ts` | T303 专用 Playwright 配置（desktop/mobile 双 project、隔离 webServer） |
| `docs\reports\OBS-EVAL\P3\T303-evidence\` | 命令日志、Playwright 报告、种子、边界核验与本文件 |

### 1.2 修改现有文件（仅允许清单）

| 文件 | 变更 | 行数（新增/删除） |
| --- | --- | --- |
| `frontend\src\app\App.tsx` | 3 条路由 + 3 个 import | 6 / 0 |
| `frontend\src\app\AppShell.tsx` | admin 侧栏「知识运营」入口；topbar 标题「知识运营」 | 16 / 1 |
| `frontend\src\api\client.ts` | 运营类型别名 + 3 个 GET 方法 + 窗口查询串辅助 | 52 / 0 |
| `frontend\package.json` | `echarts: "6.1.0"`（仅 `npm.cmd install echarts --save-exact` 产生） | 1 / 0 |
| `frontend\package-lock.json` | 同上，npm 自动生成 | 26 / 30 |

未修改：`backend\` 任何文件、`frontend\src\api\schema.d.ts`、`global.css`、`tokens.css`、`Icon.tsx`、`vite.config.ts`、既有 Playwright 配置与既有 e2e。

### 1.3 路由与入口

- `/operations`：运营总览。
- `/operations/requests`：问答诊断占位页（只验下钻参数）。
- `/operations/documents`：资产与导入占位页（只验下钻参数）。
- 三条路由都挂在 `RequireAuth → AppShell` 下；非 admin 页面级门禁渲染 `notice notice-error`，不发运营请求；侧栏入口仅 admin 可见。

## 2. 验证证据

| # | 命令（摘要） | 证据文件 | 退出码 | 结果 |
| --- | --- | --- | --- | --- |
| 0 | `git status --short` 开工快照 | `git-status-start.txt` | 0 | 记录开工在途改动 |
| 1 | `npm.cmd install echarts --save-exact` | `npm-install-echarts.txt` / `-exit.txt` | 0 | `added 3 packages`；`echarts=6.1.0`（`echarts-version.txt`） |
| 2 | `npm.cmd run build` | `frontend-build.txt` / `-exit.txt` | 0 | `tsc --noEmit` 通过，`vite build` 成功；仅有 >500 kB chunk 提示 |
| 3 | `.\.venv\Scripts\python.exe -B frontend\e2e\operations-seed.py --data-dir …\isolated-var` | `seed-output.txt` / `seed-exit.txt` | 0 | `SEED_OK`；写入隔离目录与 `seed-summary.json` |
| 4 | `npx.cmd playwright test --config=playwright.operations.config.ts` | `playwright-operations.txt` / `-exit.txt` / `.json` / `playwright-report\` | 0 | **22 passed / 0 failed / 0 skipped / 0 flaky**（desktop 11 + mobile 11） |
| 5 | 后端边界对比开工快照 | `backend-status-start.txt` / `backend-status-end.txt` / `backend-untouched-end.txt` | — | `BACKEND_UNCHANGED_VS_START` |
| 6 | `var\`、T301、T302 写入检查 | `var-status-end.txt` | — | `backend/var` 不存在；T301/T302 证据目录开工后修改文件数均为 0 |
| 7 | schema 与只读交付物状态对比 | `readonly-check-end.txt` | — | `schema.d.ts` 开工/收工状态一致（均为 T302 造成的 `M`） |
| 8 | 收工快照与允许文件 diff | `git-status-end.txt` / `diff-stat-end.txt` / `diff-numstat-allowed.txt` | — | 仅 §1.2 允许文件出现 T303 变更 |

Playwright 统计（取自 `playwright-operations.json`）：

```json
{"expected":22,"skipped":0,"unexpected":0,"flaky":0}
```

效果截图（隔离种子、真实接口）：`screenshots\overview-desktop.png`、`overview-desktop-bottom.png`、`overview-mobile.png`、`overview-mobile-bottom.png`、`requests-desktop.png`、`documents-desktop.png`、`employee-gate-desktop.png`，另有 mobile 版 requests/documents。

### 2.1 用例矩阵

| 用例 | desktop 1440×900 | mobile 390×844 |
| --- | --- | --- |
| P1 admin 入口/四卡/两图/待处理 | 通过 | 通过 |
| P2 employee 无入口/门禁/直调 403 | 通过 | 通过 |
| P3 today/7d/30d/自定义 + 请求参数 + 两图同步 | 通过 | 通过 |
| P4 趋势图点击某天 → 占位页总数一致 | 通过 | 通过 |
| P5 仅 Tab/Enter 日期与类别下钻 | 通过 | 通过 |
| P6 分布 conflict → kind + 窗口 + 总数一致 | 通过 | 通过 |
| P7 待处理导入 → document_id/state + 总数一致 | 通过 | 通过 |
| P8 刷新和浏览器返回保留筛选 | 通过 | 通过 |
| P9 空窗口：计 0、图表空态、无假百分比 | 通过 | 通过 |
| P10 移动端 390 日期切换 + 下钻 | 通过（桌面同流程回归） | 通过（390 断言） |
| P11 接口 500 → 错误态 + 重试恢复 | 通过 | 通过 |

说明：P10 在 mobile project 断言视口为 390×844；desktop 同一条用例以 1440×900 复跑同一流程，因此两个 project 均为 22/22 通过。

## 3. 种子预期值（受控样本）

种子日期锚定运行当天（Asia/Shanghai），本次为 `today=2026-11-22`、`yesterday=2026-11-21`、`ten_days_ago=2026-11-12`；空窗口 `2020-01-01` 至 `2020-01-02`。

| 指标 | today | 7d | 30d | yesterday | 空窗口 |
| --- | --- | --- | --- | --- | --- |
| 已完成问答 | 5 | 7 | 8 | 2 | 0 |
| 未找到 | 1 | 1 | 1 | 0 | 0 |
| 资料冲突 | 1 | 1 | 1 | 0 | 0 |
| 待审核版本（当前） | 1 | 1 | 1 | 1 | 1 |
| 中断请求 | 1 | 2 | 2 | 1 | 0 |
| 生效资料（当前） | 2 | 2 | 2 | 2 | 2 |
| 待处理项 | 4 | 4 | 4 | 1 | 1 |
| 趋势天数 | 1 | 2 | 3 | 1 | 0 |

| 分布（7d） | answer | clarification | not_found | conflict | service_error | knowledge_changed |
| --- | --- | --- | --- | --- | --- | --- |
| 计数 | 3 | 1 | 1 | 1 | 1 | 0 |

| 下钻总数 | 值 |
| --- | --- |
| 7d 问答列表（无 kind） | 7 |
| today 问答列表 | 5 |
| yesterday 问答列表 | 2 |
| 7d conflict 列表 | 1 |
| review_required 资料 | 1 |
| failed 导入（指定 document_id） | 1 |

种子构造：4 个资料（A/B 已发布、C 待审核、D 导入失败 `PARSE_INCOMPLETE`）；8 个已完成问答分布在 3 个自然日；2 个中断（running/expired）；1 个失败导入。种子文件位于 `T303-evidence\isolated-var\seed-summary.json`，e2e 直接读取，不硬编码业务数值。

## 4. 实现决定登记

| 编号 | 决定 | 理由/影响 |
| --- | --- | --- |
| D303-01 | `filters.ts` 为筛选唯一实现：URL 读写、窗口换算、下钻参数、接口序列化都从这里出 | 日期切换、图表点击、键盘按钮共用同一更新函数；刷新/返回可恢复 |
| D303-02 | 筛选全部存 URL：`window`、`since`、`until`、`kind`、`document_id`、`version_id`、`state` | 满足 P8；刷新后页面状态与 URL 一致 |
| D303-03 | ECharts 按 `echarts/core` + `LineChart`/`BarChart` + `Grid`/`Tooltip`/`Legend` + `CanvasRenderer` 按需注册 | 符合 §3.6；未全量 `import 'echarts'` |
| D303-04 | 图表点击用 `convertFromPixel` 求分类索引，失败时按绘图区比例兜底 | 点击某天/某类与键盘按钮回调同一个 `goDay` / `goKind` |
| D303-05 | ECharts 组件卸载 `dispose`、`ResizeObserver` + window resize、`prefers-reduced-motion` 关闭动画 | 符合 §3.6 |
| D303-06 | 颜色取 `tokens.css` 值：conflict `#d97706`（`--amber-600`），主色 `#2563eb`（`--blue-600`），灰 `#94a3b8`（`--slate-400`） | 不用 CSS 变量进 canvas；conflict 同时带文字标签 |
| D303-07 | 趋势/分布空数据渲染 `empty-state`，不构造 0 值假点 | P9；分布全 0 也走空态 |
| D303-08 | 库存类指标（待审核版本、生效资料）标「当前」，不随窗口回溯 | 与 T302 口径一致 |
| D303-09 | Trace 覆盖按 `status` 独立展示（未启用/不可用/未记录/部分记录/完整），仅在有 covered/total 时显示 `x/y`，不算百分比 | 避免把 Trace 覆盖误读为业务正确率 |
| D303-10 | 待处理问答项下钻取响应的 `drilldown.date` / `drilldown.kind`；导入项取 `drilldown.document_id` / `version_id` / `state` | 遵守「下钻参数取 T302 响应，不自拼口径」 |
| D303-11 | 占位页总数由 `next_cursor` 循环累加（每页 100，最多 20 页），并标注「接口分页未提供 total 字段」 | 见 §5 上报事项 1；不编造 `total` |
| D303-12 | `document_id` / `version_id` 下钻在 documents 列表返回项上做前端精确匹配 | 见 §5 上报事项 2；不改后端 |
| D303-13 | URL 单一 `state` 按值映射：版本态 → `version_state`，`failed`/`blocked`/`succeeded` → `processing_state` | 见 §5 上报事项 3 |
| D303-14 | 占位页只做筛选回显、总数与「完整列表将在后续任务接入」 | 不越界实现 T304/T305 |
| D303-15 | 页面加载/错误/空态齐备；错误提供「重试」；非 admin 不发请求 | P2/P11；后端 403 仅兜底 |

## 5. 上报事项（规格与 T302 接口差异，未擅自改后端或口径）

1. **分页响应没有 `total` 字段。** T302 `RequestsPage` / `DocumentsPage` 只有 `items`、`next_cursor`、`page_size`、`window`。§3.5 要求占位页显示「接口返回的总数字段」，实际无此字段。处理：占位页按 `next_cursor` 累计并明确标注「按 next_cursor 累计 N 页；接口分页未提供 total 字段」；P4/P6/P7 的「总数相等」仍成立。建议后续任务在 T302 契约中补 `total`，或提供专用 count 接口。
2. **documents 列表没有 `document_id` / `version_id` 查询参数。** §3.3/§3.4 要求待处理导入下钻 `/operations/documents?document_id=…&state=…` 并断言总数一致。处理：保留 URL 参数；请求只带 T302 支持的状态过滤，再对返回项按 `document_id` / `current_version.version_id` 精确匹配。种子数据量小，P7 通过；大数据量下效率不足，建议后续任务补后端过滤参数。
3. **单一 `state` 与 T302 双状态参数不一致。** T302 用 `version_state` 与 `processing_state`；URL 只约定一个 `state`。处理：`review_required` 等版本态映射到 `version_state`，`failed`/`blocked`/`succeeded` 映射到 `processing_state`，`state` 原文回显。若后续新增状态，需要维护映射表。
4. **待处理导入项不随窗口回溯，导致空窗口 P9 的「待处理列表空态」不成立。** T302 的 `pending` 中导入失败项是库存口径；空窗口下仍返回 1 个失败导入。处理：P9 断言趋势/分布空态、请求类待处理为空、导入项数量与接口一致（本次为 1），并保留「当前」口径说明；不前端丢弃该导入项。

以上 4 项均未改动后端、未改 T301/T302 口径；如验收要求与字面完全一致，需要产品/后端任务另行裁决。

## 6. 已知限制

- 占位页总数最多累计 20 页（2000 条）；超过后可能截断。种子与验收数据远低于该上限。T304/T305 接入完整列表时应改用服务端分页/总数。
- 占位页不展示明细列表、不做排序/分页控件（本任务刻意不越界）。
- ECharts 打包后主 chunk 约 915 kB，构建仅提示 >500 kB，不阻塞；未做路由级 code split（不在本任务范围）。
- 图表点击在绘图区外使用比例兜底映射，极端窄屏下点击边缘可能落到相邻分类；键盘按钮路径始终精确。
- 移动端侧栏入口需先打开抽屉才能看到，页面直达不受影响；P1/P2 已覆盖。
- `prefers-reduced-motion` 仅关闭图表动画，页面切换动画沿用既有全局样式。

## 7. 边界自查

- [x] 只新增 `frontend\src\features\operations\`、operations e2e、`playwright.operations.config.ts`、T303-evidence。
- [x] 现有文件仅改 `App.tsx`（3 路由）、`AppShell.tsx`（入口+标题）、`client.ts`（类型+3 方法）、`package.json`/`package-lock.json`（仅 npm 安装 echarts）。
- [x] `backend\` 相对开工快照零改动（`BACKEND_UNCHANGED_VS_START`）。
- [x] `schema.d.ts` 未重新生成、未手写，开工/收工状态一致。
- [x] 未写 `backend\var\`（目录不存在）；隔离数据全部在 `T303-evidence\isolated-var`。
- [x] T301/T302 交付物未被写入（开工后修改文件数 0）。
- [x] 无 git 写操作；仅使用只读 `git status` / `git diff`。
- [x] echarts 仅安装 1 次，`--save-exact`，版本 6.1.0。
- [x] 全程离线；未发问答 POST、未调真实模型/OCR、无付费调用。
- [x] 未实现「开始评测/重试」、固定阶段耗时条、T304/T305 完整 UI。
- [x] 22 个 Playwright 用例全部通过，退出码 0。
