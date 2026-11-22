# T303 返工交接提示词（总览页对齐原型）

> 使用方法：全文复制给开发窗口。这是对已完成的 T303 的**返工单**：功能与数据逻辑已验收可用，本次只改视觉布局与文案，对齐 `原型设计\P3原型\overview.html`。
> 派单人：项目经理。日期：2026-11-22。返工依据：`T303-dispatch.md` §3.3（修订版，已逐项对齐原型）+ 本单差距清单（PM 实读现有代码后列出）。

## 0. 范围与铁律

- **只改前端运营页的布局/文案/图表配置**。数据流、filters.ts 筛选逻辑、下钻参数、API 调用、门禁逻辑已正确，**不要重写**；如需微调仅限配合布局。
- 沿用 T303 原派单全部铁律：不改 `backend\`、`schema.d.ts`、既有 CSS 规则/Icon/vite.config；不装新依赖；不写 `var\`；git 无写操作；无付费调用；不发问答 POST。
- 允许改动文件：`frontend\src\features\operations\` 内现有文件、`frontend\e2e\operations-*.spec.ts`（仅配合文案/结构变化调整断言与新增用例）、`docs\reports\OBS-EVAL\P3\T303-evidence\`（新增返工证据，不覆盖首轮证据）。App.tsx/AppShell.tsx/client.ts 本轮预计不需要动。
- 原型是 Tailwind + CDN 演示，**只取布局与文案，不引入 Tailwind/iconify/CDN**；颜色用现有 tokens.css 变量。
- 先读：`原型设计\P3原型\overview.html`（全文）、`T303-dispatch.md` §3.3、现有 `OperationsOverviewPage.tsx` / `charts.ts` / `operations.css`。

## 1. 差距清单（PM 实核，逐项改，改完逐项打勾）

| # | 现状（已实核） | 改成（对齐原型） |
| --- | --- | --- |
| G1 | 无页签条 | 页头下加 3 页签：运营总览 / 问答诊断 / 知识资产，分别链接 `/operations`、`/operations/requests`、`/operations/documents`，当前页签高亮（下划线式，参照原型 119-123 行）；两个占位页顶部也放同一页签条 |
| G2 | 页头徽章「管理员只读」，无资料管理入口 | 徽章文字改「只读工作台」；页头右侧加「前往资料管理」链接（跳现有 `/documents`）；描述文案改原型基调：「查看问答效果、异常分布与知识资产状态；资料处理请前往资料管理。」 |
| G3 | 筛选条只有窗口 label | 筛选条右侧补口径说明「按问答结束时间归属 · Asia/Shanghai」；窗口起止文字保留 |
| G4 | 未找到卡副注「点击按 kind=not_found 下钻」（暴露内部参数） | 改「占全部问答 x%」（x = not_found/completed_requests，分母 0 显示「无样本」，不显示 0.0%）；卡片仍可点击下钻 |
| G5 | 冲突卡副注「冲突引用不计入最终引用」 | 改「需管理员核实」；冲突数字保持橙色（现有 ops-metric-amber 保留） |
| G6 | 待审核卡副注「点击查看待审核资料」 | 改「与日期筛选无关」；「当前」徽章保留 |
| G7 | 趋势卡标题「完成趋势」，无操作提示 | 标题改「问答趋势」；标题下加提示「点击任一天节点 → 该日问答明细」；右上加「单位：次」小角标 |
| G8 | 趋势折线 smooth:false、纯色面积 | 改平滑曲线 + 自上而下的面积渐变（参照原型 trendChart：smooth:true、symbolSize 6、LinearGradient 蓝色 0.16→0.01，颜色值换成现有 tokens 对应色） |
| G9 | 结果分布是**纵向柱状图**，6 类全灰只有 conflict 橙 | 改**横向条形图**（yAxis type category + inverse:true，barWidth 12，条右显示数值 label，参照原型 distChart）；6 类按原型配色映射到现有 tokens：已回答蓝、需澄清灰、未找到琥珀、资料冲突橙、服务异常红（rose）、知识已变更青绿（emerald）；中文标签与顺序不变 |
| G10 | 分布卡提示是技术文案「conflict（资料冲突）使用橙色标识并附文字标签…」；键盘按钮带「（橙色）」后缀 | 提示改「近 X 天共 N 条，已回答占 x%」（X 随窗口变化，N=六类合计，分母 0 显示「无样本」；**不得标为业务正确率**）；删掉「（橙色）」后缀，颜色语义由图表颜色+文字标签承担 |
| G11 | 图表行比例 1.15fr:1fr | 改 3:2（如 1.5fr:1fr），移动端保持上下堆叠 |
| G12 | 待处理是按钮列表，导入项文案「资料导入 PARSE_INCOMPLETE」 | 改 4 列表格：时间 / 异常类型 / 相关问题或文件 / 查看（参照原型 220-261 行）。**内容只用 T302 pending 实际字段**：时间=finished_at（Shanghai 显示）；类型徽章：资料冲突/待审核橙、服务异常/导入失败红（rose），均带文字；第 3 列问答项显示 kind 中文 + error_code（有才显示），导入项显示「资料导入 · {error_code}」+ 文档标识（API 无文档名与问题原文，**不得编造**，此限制写入交付说明）；第 4 列「查看诊断 / 查看资产」链接式按钮，点击行为与现有 goRequestPending/goImportPending 完全一致；空态保留 |
| G13 | Trace 状态映射表含不存在的 `ok`，缺 `recorded`（会回显英文原文） | 修正映射：recorded→「已记录 · x/y」、partial→「部分覆盖 · x/y」、disabled→「Trace 已关闭」、unavailable→「Trace 暂不可用」、not_recorded→「未记录」；删除 ok；未知值兜底显示「状态未知」不显示英文 |
| G14 | 无页脚说明 | 页面底部加一行：「本页为只读运营工作台 · 指标、图表与明细取自同一查询条件」；隔离/演示环境时标注数据环境 |

保持不变（不要动）：filters.ts 全部逻辑、URL 参数、下钻取 drilldown 字段、admin 门禁、加载/错误/空态结构、键盘等价入口机制（按钮文案可随 G10 调整）、中断/生效资料辅助区、EChart.tsx 的 dispose/resize/reduced-motion（横向条形图的 onCategoryClick 索引映射需确认仍正确）。

## 2. 验证要求（全部重跑，证据存 T303-evidence\rework\）

```powershell
Set-Location 'D:\GPT项目\市场部AI知识库\frontend'
npm.cmd run build 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T303-evidence\rework\frontend-build.txt'
$LASTEXITCODE
npx.cmd playwright test --config=playwright.operations.config.ts 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T303-evidence\rework\playwright-operations.txt'
$LASTEXITCODE
```

- P1-P11 全部重跑通过（desktop + mobile）；因文案/结构变化调整断言时，**不得放松口径断言**（总数相等、URL 参数、403、筛选保留等必须原样保留）。
- 新增 P12：页签条存在且 3 页签可切换、当前页签高亮、切到占位页再切回总览筛选保留。
- 新增 P13：未找到卡副注百分比与卡片数字一致（分母 0 窗口显示「无样本」）；Trace 状态文案为中文映射（无英文原样回显）。
- 种子与 webServer 沿用首轮配置；若首轮隔离目录已存在直接复用，不写 `var\`。
- git 开工/收工快照对比，确认改动仅限 §0 允许清单。

## 3. 交付

`T303-evidence\rework\T303-rework-delivery.md`：G1-G14 逐项打勾与改动文件行号、验证证据表（命令/退出码/用例数）、断言调整说明（改了哪些、为何不放松口径）、已知限制（含第 3 列无文档名/问题原文的数据限制）、上报事项（无则写无）。

## 4. 红线速查

- [ ] 只改布局/文案/图表配置，数据流与下钻口径零变化
- [ ] 不引入 Tailwind/CDN，颜色用现有 tokens；conflict 橙 + 文字标签
- [ ] 任何占比不标「业务正确率」；分母 0 显示「无样本」
- [ ] 不编造 API 没有的字段（文档名、问题原文、环比、小时分段）
- [ ] 原型演示效果仍不实现：开始评测/重试、固定阶段耗时条、环比、「需澄清未确认」待处理项
- [ ] build 与 Playwright 全过，口径断言未放松；var\ 未写；git 无写操作