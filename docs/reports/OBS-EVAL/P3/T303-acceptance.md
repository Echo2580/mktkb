# T303・运营总览与可视化入口 — 项目经理验收记录（含返工）

- 验收依据：任务书 T303 小节、§2、§4；派单 `T303-dispatch.md`（修订版，布局对齐原型）；返工单 `T303-rework-dispatch.md`（G1-G14）
- 验收日期：2026-11-22
- 交付方：开发窗口（首轮 + 返工各 1 轮）；交付说明 `T303-evidence/T303-delivery.md`、`T303-evidence/rework/T303-rework-delivery.md`
- **T303 总结论：PASS**（开发自测 PASS；独立验收 PASS；真实环境验证 NOT-RUN——离线 + 隔离种子，属后续单独授权事项）

## 一、逐项对账（派单 §7 完成条件 + 返工 G1-G14）

| # | 完成条件 | 开发自测 | 独立验收 | 真实环境验证 | 证据 |
|---|----------|----------|----------|--------------|------|
| 1 | build 退出码 0；Playwright 全过 | PASS（首轮 22/22；返工 26/26，P1-P13 × desktop/mobile） | PASS（PM 复跑 build 退出码 0；Playwright 26 通过/0 失败/0 跳过，56.0s，webServer 自启隔离后端 8288 + preview 5299） | NOT-RUN | `T303-acceptance-rerun-build.txt`、`T303-acceptance-rerun-playwright.txt` |
| 2 | 时间筛选同时更新趋势与分布；下钻参数与卡片口径一致 | PASS（P3-P7） | PASS（复跑含 P4/P6/P7 总数相等断言；下钻取 T302 drilldown 字段，代码抽查属实） | NOT-RUN | spec + filters.ts |
| 3 | 员工无入口、页面门禁、接口 403 | PASS（P2） | PASS（复跑通过；侧栏 admin 条件渲染与 DocumentsPage 模式一致） | NOT-RUN | AppShell.tsx、页面门禁 |
| 4 | 刷新/返回保留筛选；空/错误/加载态；conflict 橙 + 文字 | PASS（P8/P9/P11） | PASS（复跑通过；截图核视觉） | NOT-RUN | spec、截图 |
| 5 | 原型演示效果未实现；占位页不越界 | PASS | PASS（无开始评测/重试、无固定耗时条、无环比/小时分段/需澄清待处理项；占位页仅回显 + 累计总数） | NOT-RUN | 代码抽查 |
| 6 | 边界 | PASS（自查齐备） | PASS（PM 实核：已跟踪改动累计仅 main.py+2（T302）、App.tsx+6、AppShell.tsx+17/-1、client.ts+52、package.json+1（echarts 6.1.0 --save-exact）、lock、schema.d.ts（T302 生成物）；var\ 主库与 WAL 时间戳早于 T303 开工未被写；T301/T302 交付物未动） | NOT-RUN | PM git/时间戳实核 |
| 7 | 交付说明齐备 | PASS（两轮均含变更、证据表、实现决定、限制、上报） | PASS | — | 两份 delivery |

**返工 G1-G14 独立核验**：PM 实读 `charts.ts`（G8 平滑 + 渐变 0.16→0.01、G9 横向条形 inverse/barWidth 12/右侧数值/6 类语义配色与原型一致）、页面代码（G1 页签、G2 只读工作台 + 前往资料管理、G3 口径说明、G4 shareText 分母 0 无样本、G5/G6 副注、G13 recorded 映射 + 状态未知兜底）、桌面整页截图（页签/四卡/3:2 图表行/4 列待处理表/页脚演示环境标注均与原型布局吻合）。14 项全部落实。

## 二、独立验收执行记录（PM 实测）

| 动作 | 命令 | 工作目录 | 退出码 | 结果 | 证据（P3/ 下） |
|------|------|----------|--------|------|----------------|
| 复跑构建 | `npm.cmd run build` | frontend\ | 0 | tsc + vite 通过（仅 chunk 体积提示） | `T303-acceptance-rerun-build.txt` |
| 复跑全量 e2e | `npx.cmd playwright test --config=playwright.operations.config.ts` | frontend\ | 0 | 26 通过/0 失败/0 跳过（desktop 13 + mobile 13，56.0s） | `T303-acceptance-rerun-playwright.txt` |
| 视觉核验 | 读返工桌面整页截图对照原型 overview.html | — | — | 布局逐项吻合 | `rework/screenshots/overview-desktop.png` |
| 边界实核 | git diff --stat、var\ 时间戳 | 仓库根 | 0 | 仅允许文件；var\ 未写 | 本记录 |
| 代码抽查 | charts.ts 全文、页面关键行 grep | — | — | G 项与红线落实；无「业务正确率」字样 | 本记录 |

注：PM 复跑的 reporter 按现有配置写入 `T303-evidence\playwright-operations.json`（覆盖返工 JSON，返工 JSON 已另存 `rework\` 不受影响）；PM 复跑 txt 独立命名保留。

## 三、首轮上报事项裁决（4 项，均不阻塞 T303）

| # | 事项 | 裁决 |
|---|------|------|
| 1 | T302 分页响应无 `total` 字段，占位页按 next_cursor 累计（上限 20 页） | **接受**。任务书 T302 契约本就未要求 total，属派单 §3.5 措辞超出契约（PM 责任）。T304/T305 列表用游标分页，计数对账以 overview 统计为准；若 T306 实测数据量导致累计截断影响对账，再立 T302 补充单加 total/count，不现在扩范围 |
| 2 | documents 列表无 document_id/version_id 过滤参数，前端对返回项精确匹配 | **接受（占位页范围内）**。T305 资产/导入下钻应改用现有 `GET /operations/documents/{document_id}` 详情端点（任务书契约已有），不依赖列表过滤；T305 派单将写明 |
| 3 | URL 单一 state 与 T302 version_state/processing_state 双参数映射 | **接受**。映射表集中在 filters.ts，T305 沿用；新增状态时同步维护 |
| 4 | 导入失败待处理项为库存口径，空窗口仍显示 | **接受**。与 T302 契约登记一致（pending 导入项当前口径）；P9 断言按此调整且未放松其余口径。页面保留「当前」口径说明即可 |

返工上报事项（首轮 Playwright JSON/HTML 被固定 reporter 路径覆盖）：**知悉并接受**，首轮 txt 与交付说明未受影响；T306 集成验收时 reporter 输出按轮次分目录，已记入 T306 待办。

## 四、已知限制（随候选进入 T306）

1. 占位页累计总数上限 2000 条；T304/T305 接完整列表时改服务端游标分页。
2. ECharts 主 chunk 约 915 kB（构建提示不阻塞）；路由级 code split 不在 P3 范围，T306 性能测量时一并评估。
3. 图表点击绘图区外比例兜底，极端窄屏可能落相邻分类；键盘路径始终精确。
4. 待处理表第 3 列无文档名/问题原文（T302 pending 未返回），不编造；T305 详情页可补文档名展示。
5. 演示环境标注按 localhost 判定，仅本地隔离预览；种子为受控样本（已标注），Span/性能不代表线上。
6. 真实环境验证 NOT-RUN；三条端到端路径 T306 复验。

## 五、结论与下一步

- 开发自测：**PASS**；独立验收：**PASS**；真实环境验证：**NOT-RUN**。
- **T303 总结论：PASS**。T304、T305 解除阻塞，可并行派单（文件边界分开：T304 问答诊断方向、T305 知识资产方向，共享文件仅 client.ts/filters.ts 需声明归属）。