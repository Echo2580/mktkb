# T304 独立验收记录（问答诊断与固定评测摘要）

- 验收人：项目经理（MainAgent）
- 日期：2026-11-22
- 对象：开发窗口交回的 T304（交付说明 `T304-delivery.md`，证据 `T304-evidence\`）
- 依据：`T304-dispatch.md` §7 完成条件、§8 红线；T301 冻结口径；T303 兼容契约

## 一、结论

**正式 PASS（2026-11-22 C1 复核关闭，见 §八）**

初验为有条件通过，唯一必改项 C1（「24 小时内回溯」虚构文案）已由开发窗口修复并经验收人复核关闭。两项上报裁决见 §四。

## 二、独立复跑证据（验收人本机执行，非采信自报）

| # | 命令 | 退出码 | 结果 | 验收日志 |
| --- | --- | --- | --- | --- |
| 1 | `npm.cmd run build`（含 tsc --noEmit） | 0 | 646 modules，dist 构建成功 | `T304-acceptance-rerun-build.txt` |
| 2 | `npx.cmd playwright test --config=playwright.operations-qa.config.ts` | 0 | **19 passed / 1 skipped / 0 failed**（53.8s；skip 为 desktop Q10，按设计只跑 mobile） | `T304-acceptance-rerun-qa.txt` |
| 3 | `npx.cmd playwright test --config=playwright.operations.config.ts operations-overview --reporter=list` | 0 | **26 passed / 0 failed**（49.0s，P1-P13 双 project） | `T304-acceptance-rerun-t303.txt` |

- 命令 3 首次执行时 8288 被 T305 窗口的同名回归占用（reuseExistingServer:false 报错退出 1），按并行约定等待端口释放后重试成功；未杀任何他窗口进程。
- 开发方 `playwright-qa.json` stats 复核：expected=19 / skipped=1 / unexpected=0 / flaky=0，与自报一致。
- 验收期间空闲提交额度约 15GB，未复现内存问题；验收后 8288/8289/8292/5299/5300/5302 无残留监听。

## 三、红线逐条核对（代码实读 + 用例断言双重确认）

| 红线 | 结论 | 依据 |
| --- | --- | --- |
| 冲突两方取 conflicts 块、不计引用数 | 符合 | DiagnosisDrawer.tsx：conflict 时隐藏引用区（Q5 断言 qa-citations 计数 0）；两列卡片值/名称/版本与种子逐项相等；来源不足 2 方时明示不补造 |
| 旧版仅元信息、active 才带定位 | 符合 | superseded 卡片无「定位：」（Q4 断言），文案「该版本已失效，仅展示元信息」；locatorText 兜底剔除 cells |
| revision 展示 | 符合 | qa-revision testid，Q4 断言 answer=5 / superseded=3 |
| 阶段条只渲染 T301 冻结映射内实际 Span | 符合 | spanLabels.ts 与 T301 §4 逐项一致（rag 8 / legacy 6 / 子 Span 7，legacy_with_rag_candidates 归 legacy）；Q6 断言 rag 7 阶段、legacy 5 阶段、不出现另一路径标签 |
| 未记录不补 0ms、不虚构总耗时 | 符合 | durationOf 缺失返回 null→「时长未记录」；合计只统计已记录主阶段并标注未记录个数；Q6 断言无「0 ms」 |
| 重放标注 | 符合 | attempt2 data-replayed=true + 「重放」徽章 + 0 Span 说明（Q6） |
| Trace 三态独立文案、业务可读 | 符合 | disabled/unavailable/not_recorded 三套标题+说明；Q7 在真实 Trace 关闭栈断言业务内容与引用照常可读、无阶段条 |
| 评测只读、无发起/重试/下载入口 | 符合 | EvalRunsPanel 无此类按钮（Q8 断言计数 0）；单批次只调 GET /observability/runs/{id} |
| holdout 只聚合、分母保留 | 符合 | 扣留徽章 + 抽屉 withheld 提示 + 不渲染逐题（Q8 断言 leak-into-ui 不出现）；样本数取 manifest.case_count 原始分母（20/20/12） |
| 不标业务正确率/通过率 | 符合 | 全目录检索无此措辞；指标标注「仅代表该批次受控执行结果」 |
| 兼容 testid 语义不变 | 符合 | ops-placeholder-ready/total/kind 在筛选摘要条，total=游标累计（20 页上限标注）、kind 含原文；T303 回归 26 条全绿实证 |
| 无「打开会话记录」入口 | 符合 | 抽屉/列表均无会话跳转，全目录检索无 session 链接 |

样本核对（Q5/Q6/Q7 与 seed-summary.json 逐项一致）：conflict=b570ae0f…708f、service_error=f69bdfee…ce89（MODEL_TIMEOUT 标红）、replayed=9abcfa20…ed77（attempt2 重放 0 Span）、no_trace=1dd2ec0f…a370（not_recorded）。

## 四、上报事项裁决

1. **T303 配置 testMatch 收窄建议：接受，移交 T306 执行。** 并行期间 `playwright.operations.config.ts` 保持冻结（T305 仍在用），两窗口回归一律带 `operations-overview` 文件过滤（本次验收已按此执行并 26 条全绿）。T306 收口时把 testMatch 收窄为 `/operations-overview.*\.spec\.ts/` 并按轮次分 reporter 目录，一并消除污染风险。
2. **Trace 关闭态第二套栈 8292/5302：接受。** 真实 `MKTKB_TRACE_ENABLED=false` 环境比 Mock 更符合验收口径；与主栈共用隔离目录（接口只读）、trusted origins 各自正确、端口与 T305（8290/5301）不冲突。配套 `T304_STACK` 拆栈开关与 Chromium/线程数资源参数只影响测试进程，接受。

## 五、边界实核

- git：开工/收工/当前已修改集合三方一致（9 个文件，均为 T302/T303 既有改动）；HEAD 仍 0d6ba61；验收复跑后 M 集合不变。
- 冻结文件时间戳核对：全部早于 T304 开工快照（03:33:07）；唯一晚于开工的 DocumentsPlaceholderPage.tsx（04:14）为 T305 独占文件的并行改动，非 T304 越界。
- `var\mktkb.sqlite3`/WAL 仍 2026-11-21 16:42:50，`var\observability\qa-traces.sqlite3` 仍 2026-11-05 20:52:22，验收前后均未写。
- 种子脚本只写隔离目录（rmtree 有「非本任务种子目录拒绝覆盖」护栏）；唯一 POST 为登录；无付费调用、无新依赖、无 git 写操作。

## 六、接受的实现决定与已知限制（登记，不阻塞）

1. 列表列按 API 实际字段适配（请求标识/引用数替代原型的问题摘要/资料名列），派单 §3.2 预授权，接受。
2. 抽屉完成时间取自列表行；直链且行不在已加载页时显示「未记录」，不编造，接受。
3. 引用卡锚点 data-citation=document_id + data-source-id 区分同文档多引用，接受。
4. 移动端抽屉宽度断言 0.5px 亚像素容差，接受。
5. 边缘情形备忘（T306 留意，非必改）：trace.status=partial 且 attempts 为空时阶段区不渲染状态框（当前后端 partial 必有 attempts，未触发）；「24 小时」文案见 C1。

## 七、转正式 PASS 的条件（已关闭）

- C1：删除/替换 RequestsPlaceholderPage.tsx:277 的「24 小时内回溯」文案；复跑 build 与 T304 全套。→ **已关闭，见 §八。**

## 八、C1 复核关闭记录（2026-11-22）

验收人独立复核 3 项，全部通过：

1. **改动行实读**：RequestsPlaceholderPage.tsx:277 现为「异常与冲突记录可逐条回溯到资料与执行过程」，事实表述，无保留策略/时限暗示；`frontend\src` 全目录检索「24 小时」0 命中；文件总行数不变（543 行），与单行替换一致。
2. **复跑证据核对**：`T304-C1-rerun-build.txt` 构建成功（✓ built in 506ms，退出码 0）；`T304-C1-rerun-qa.txt` 19 passed / 1 skipped / 0 failed（49.9s，skip 为 desktop Q10）；`playwright-qa.json` 已刷新（startTime 2026-11-22T05:50Z，expected=19 / skipped=1 / unexpected=0 / flaky=0），与自报一致。
3. **边界复核**：git 已修改集合与开工/收工一致（9 个文件），HEAD 仍 0d6ba61；`var\` 三库时间戳仍为基线值（2026-11-21 16:42:50 / 2026-11-05 20:52:22），未写。

开发方说明的两次环境性失败（外部中断、8289 残留 uvicorn 端口占用）不涉及代码/配置改动，第三次复跑通过，接受。

**T304 正式 PASS。** 遗留移交 T306：T303 配置 testMatch 收窄 + reporter 按轮次分目录（§四裁决 1）；partial 且 attempts 为空的边缘情形备忘（§六.5）。