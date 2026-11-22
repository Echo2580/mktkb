# T303 返工交付：运营总览对齐原型

日期：2026-11-22
工作目录：`D:\GPT项目\市场部AI知识库`
规格：`docs\reports\OBS-EVAL\P3\T303-rework-dispatch.md`（G1-G14）
验收依据：`docs\superpowers\plans\2026-11-21-mktkb-p3-operations-taskbook.md` T303 小节与 §2

## 结论

返工完成。`/operations` 总览已按 G1-G14 对齐原型布局与文案，数据流、URL 筛选、下钻参数、API 调用与 admin 门禁未改。`npm.cmd run build` 退出码 0；Playwright P1-P13 桌面 + 移动共 26 条全部通过（26 passed / 0 failed / 0 skipped）。本轮未改后端、`schema.d.ts`、App.tsx/AppShell.tsx/client.ts、package.json/lock，未写 `var\`，git 无写操作。

## G1-G14 逐项核验

| 项 | 要求 | 结果 | 实现位置 |
|---|---|---|---|
| G1 | 页头下 3 页签，下划线、当前高亮；两个占位页同页签条 | ☑ | `OperationsOverviewPage.tsx:270`；`RequestsPlaceholderPage.tsx:120`；`DocumentsPlaceholderPage.tsx:121`；样式 `operations.css:28`；P12 桌面/移动通过 |
| G2 | 徽章「只读工作台」、右侧「前往资料管理」、描述按原型 | ☑ | `OperationsOverviewPage.tsx:259`（描述）、`:262`（资料管理入口）、`:265`（徽章）；P12 断言通过 |
| G3 | 筛选条右侧「按问答结束时间归属 · Asia/Shanghai」 | ☑ | `OperationsOverviewPage.tsx:331`；样式 `operations.css:52` |
| G4 | 未找到卡副注「占全部问答 x%」，分母 `completed_requests`，0 显示「无样本」，仍可下钻 | ☑ | `OperationsOverviewPage.tsx:70`（`shareText`）、`:396`（副注 testid）；卡片点击逻辑未改；P13 断言百分比与卡片数字一致，空窗口「无样本」 |
| G5 | 冲突卡副注「需管理员核实」，数字保持橙色 | ☑ | `OperationsOverviewPage.tsx:410`；橙色沿用 `.ops-metric-amber`；P13 通过 |
| G6 | 待审核卡副注「与日期筛选无关」，保留「当前」徽章 | ☑ | `OperationsOverviewPage.tsx:429`（当前徽章）、`:434`（副注）；P13 通过 |
| G7 | 趋势标题「问答趋势」、节点提示、右上「单位：次」 | ☑ | `OperationsOverviewPage.tsx:467`（标题）、`:468`（单位）、`:473`（提示） |
| G8 | 趋势 `smooth:true`、`symbolSize:6`、自上而下蓝色渐变面积 0.16→0.01 | ☑ | `charts.ts:64`（smooth）、`:67`（symbolSize）、`:79`（colorStops 0.16→0.01）；P4/P10 图表点击通过 |
| G9 | 分布改横向条形：`yAxis category + inverse:true`、`barWidth:12`、条右数值、6 类语义配色 | ☑ | `charts.ts:9`（配色映射）、`:114`（inverse）、`:123`（bar）、`:124`（barWidth）、`:131`（右侧 label）；`EChart.tsx:38`/`:59` 支持 y 轴索引；P6/P10 通过 |
| G10 | 分布提示「近 X 天共 N 条，已回答占 x%」，0 为「无样本」，删除「（橙色）」 | ☑ | `OperationsOverviewPage.tsx:130`（窗口天数）、`:518`（提示 testid `ops-dist-hint`）；`:535` 起键盘按钮无颜色后缀；P9 无假百分比 |
| G11 | 图表行比例 3:2（1.5fr:1fr），移动端上下堆叠 | ☑ | `operations.css:225`（1.5fr:1fr）、`:389`（≤1024 单列） |
| G12 | 待处理 4 列表格：时间/异常类型/相关问题或文件/查看；徽章文字与颜色；第 3 列只用实际字段；动作复用原下钻 | ☑ | `OperationsOverviewPage.tsx:573`（表格）至 `:642`；样式 `operations.css:284` 起；P7 导入下钻、P1 数量通过；移动端 4 列均在视口内 |
| G13 | Trace 映射 `recorded/partial/disabled/unavailable/not_recorded`，删 `ok`，未知「状态未知」，不回显英文 | ☑ | `OperationsOverviewPage.tsx:33`（映射）、`:43`（拼接 x/y）、`:70` 前 `traceStatusText`；P1/P13 断言无英文状态；P13 拦截 `recorded · 3/7` 通过 |
| G14 | 页脚只读说明；隔离/演示环境标注 | ☑ | `OperationsOverviewPage.tsx:659`；样式 `operations.css:358`；本地 `127.0.0.1/localhost` 显示「演示环境 · 受控样本数据」 |

红线条目：

- ☑ 只改布局/文案/图表配置，数据流与下钻口径零变化
- ☑ 未引入 Tailwind/CDN/新依赖，颜色取自现有样式与 tokens
- ☑ 未出现「业务正确率」；分母 0 显示「无样本」
- ☑ 未编造文档名、问题原文、环比、小时分段
- ☑ 未实现「开始评测/重试」、固定阶段耗时条、「需澄清未确认」待处理项
- ☑ build 与 P1-P13 全过；`var\` 未写；git 无写操作

## 验证证据表

| 命令 | 退出码 | 结果 | 证据文件 |
|---|---|---|---|
| `npm.cmd run build`（`frontend\`） | 0 | `tsc --noEmit` 通过；vite 构建成功；仅 chunk >500 kB 提示 | `rework\frontend-build.txt` |
| `npx.cmd playwright test --config=playwright.operations.config.ts` | 0 | 26 passed / 0 failed / 0 skipped / 0 flaky；desktop 13 + mobile 13；耗时 51.9s | `rework\playwright-operations.txt`、`rework\playwright-operations.json` |
| `git status --porcelain` 开工/收工对比 | 0 | SHA256 一致，改动仅限允许清单 | `rework\git-status-start.txt`、`rework\git-status-end.txt` |
| 截图归档（隔离种子 + preview） | 0 | 桌面 1440×1400、移动 390×2300 整页 | `rework\screenshots\overview-desktop.png`、`overview-mobile.png` |

用例覆盖：P1-P11 全量重跑；P12 页签存在/切换/高亮/往返筛选保留；P13 未找到副注百分比、空窗口「无样本」、Trace 中文映射且无英文回显。desktop 与 mobile 两个 project 全部通过。

## 断言调整说明

| 用例 | 调整 | 原因 | 是否放松口径 |
|---|---|---|---|
| P1 | Trace 断言由「未启用」改为「Trace 已关闭」 | G13 规范文案 | 否，仍校验 Trace 状态存在且为中文 |
| P9 | 保留原空态与 0 计数断言；仍断言页面无 `NaN`、无百分比 | G4 空窗口改「无样本」 | 否，反而明确禁止假百分比 |
| P12（新增） | 3 页签、`aria-current`、切到两个占位页再回总览，`window=30d` 与指标值保留 | 覆盖 G1/G2 与筛选不丢失 | 否，沿用原 URL 与指标口径 |
| P13（新增） | 未找到百分比 = `not_found / completed_requests`；空窗口「无样本」；Trace 状态无英文回显；拦截响应验证 `已记录 · 3/7` | 覆盖 G4/G13 | 否，分母仍为 `completed_requests`，未改 T301/T302 口径 |

总数、URL 参数、403 门禁、筛选保留等原有断言均未放松。

## 已知限制

1. T302 `pending` 未返回文档名与问题原文，表格第 3 列只显示问答 kind 中文 + `error_code`，导入项显示「资料导入 · {error_code}」+ document_id 短标识，不编造缺失字段。
2. T302 当前无「版本待审核」「需澄清未确认」待处理类型，原型中的这两类徽章未实现；待审核以库存卡独立展示。
3. 分布提示中「近 X 天」按当前窗口天数计算；自定义单日窗口显示「近 1 天」，今日窗口显示「今日」。
4. 演示环境标注以 `localhost/127.0.0.1` 判定，仅用于本地隔离预览；生产环境不显示该标注，也不推断生产状态。
5. 移动端待处理表在 390px 下压缩字号与内边距以容纳 4 列，长错误码会换行，未改为横向滚动。

## 上报事项

1. **首轮 Playwright JSON/HTML 报告被覆盖（需项目经理知悉）**：`playwright.operations.config.ts` 的 reporter 输出路径固定指向 `T303-evidence\` 根目录，返工按规格「沿用首轮配置」全量重跑时，覆盖了首轮 `playwright-operations.json` 与 `playwright-report\`。首轮 `playwright-operations.txt`（22 passed）与 `T303-delivery.md` 未被改动，仍可作首轮依据；返工 JSON 已另存 `rework\playwright-operations.json`。未改配置以避免超出 §0 允许文件清单，后续如需长期保留两轮 JSON，建议另立返工专用 reporter 路径。
2. 无规格与接口新增冲突；原型中 T302 不存在的两类待处理项已按返工单明确不实现。

## 改动文件

- `frontend\src\features\operations\OperationsOverviewPage.tsx`
- `frontend\src\features\operations\charts.ts`
- `frontend\src\features\operations\EChart.tsx`（仅增加 `categoryAxis` 与 y 轴索引换算）
- `frontend\src\features\operations\operations.css`
- `frontend\src\features\operations\RequestsPlaceholderPage.tsx`（仅页签条与返回链接保留筛选）
- `frontend\src\features\operations\DocumentsPlaceholderPage.tsx`（仅页签条与返回链接保留筛选）
- `frontend\e2e\operations-overview.spec.ts`（P1 文案断言、P9 保留、新增 P12/P13）
- `docs\reports\OBS-EVAL\P3\T303-evidence\rework\`（本轮证据与截图）

未改：`backend\`、`frontend\src\api\schema.d.ts`、`frontend\src\app\App.tsx`、`AppShell.tsx`、`frontend\src\api\client.ts`、`package.json`、`package-lock.json`、`var\`。
