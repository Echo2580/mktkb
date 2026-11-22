# T305 开发交接提示词（知识资产与导入状态）

> 全文复制给另一个开发窗口，与 T304 **并行开发**。文件归属见 §2，越界即验收 FAIL。
> 派单人：项目经理。日期：2026-11-22。前置：T301/T302/T303 均验收 PASS。

## 0. 角色与铁律

你是开发执行者，只做 T305：把 `/operations/documents` 占位页升级为知识资产页（资产列表 + 资产抽屉 + 总览下钻同口径详情）。**不改任何后端代码**；上传/重试/审核/发布/删除一律跳现有资料管理页，本页只读。

1. 工作目录 `D:\GPT项目\市场部AI知识库`；Windows + PowerShell 7，Bash 不可用；前端命令用 `npm.cmd`/`npx.cmd`。
2. 禁止付费调用；e2e 只走登录与只读页面，**绝不发问答 POST、绝不上传/发布/删除**；禁写 `var\`；git 无写操作。
3. T301/T302/T303 交付物只读；工作区在途改动原样保留。
4. 接口缺口径：**停下写上报事项**，不改后端、不改冻结口径、不编造数据。
5. 原型 `原型设计\P3原型\knowledge-assets.html` 是布局参考（已实读，契约见 §3）；演示数字与文案不照抄；不引入 Tailwind/iconify/CDN。
6. 交付只认变更清单 + 验证证据 + 已知限制。数字用阿拉伯数字。

## 1. 必读（按顺序）

1. 任务书 T305 小节、§2、§4；`T301-data-audit.md` §3（计数口径）、§6（API 约定）。
2. `T302-evidence\T302-delivery.md` §4 契约（重点：documents 列表**没有** document_id/version_id 过滤参数；pending 导入项为当前库存口径）；`T302-evidence\api\openapi.json`；`schema.d.ts` 已有 `DocumentsPage`/`DocumentDetailResponse` 类型，直接 import type，不重新生成。
3. `T303-acceptance.md` §三裁决 ②：总览下钻到具体文档用 `GET /api/v1/operations/documents/{document_id}` 详情端点（列表无该过滤参数）。
4. 原型 `原型设计\P3原型\knowledge-assets.html` 全文。
5. 现有代码：`features\operations\`（filters.ts 的 state 映射、DocumentsPlaceholderPage.tsx、operations.css、门禁写法）、`api\client.ts`（`request<T>`、`api.operationsDocuments`）、`e2e\operations-overview.spec.ts`（兼容契约 §2.3）、`playwright.operations.config.ts`、`e2e\operations-seed.py`（种子参照）、现有资料管理页路由（「前往资料管理」跳转目标，读 App.tsx 确认路径）。

## 2. 文件归属（与 T304 并行的硬边界）

### 2.1 T305 独占（新增或改写）

| 路径 | 说明 |
| --- | --- |
| `frontend\src\features\operations\DocumentsPlaceholderPage.tsx` | **改写为完整知识资产页**（文件名与导出名不变，App.tsx 无需改） |
| `frontend\src\features\operations\assets\`（新目录） | AssetDrawer.tsx、VersionList.tsx、ImportStatusBlock.tsx、assetsApi.ts（封装文档详情 GET）、assets.css 等 |
| `frontend\e2e\operations-assets-*.spec.ts`、`frontend\e2e\operations-assets-seed.py` | 本任务用例与种子 |
| `frontend\playwright.operations-assets.config.ts` | 专用配置（§6） |
| `docs\reports\OBS-EVAL\P3\T305-evidence\` | 全部证据 + `T305-delivery.md` |

### 2.2 冻结（两任务都只读）

`backend\**`、`schema.d.ts`、`App.tsx`、`AppShell.tsx`、`client.ts`、`filters.ts`、`operations.css`、`OperationsOverviewPage.tsx`、`charts.ts`、`EChart.tsx`、`operations-overview.spec.ts`、`playwright.operations.config.ts`、`package.json`/`package-lock.json`（不装任何新依赖）、T301/T302/T303 全部交付物。新样式放 `assets\assets.css`。新 URL 参数在自己页面内读取，不改 filters.ts。

### 2.3 兼容契约（保住 T303 的 13 条用例，不改共享 spec）

`operations-overview.spec.ts` 的 P7/P8/P10/P11 断言 documents 页上的 `data-testid="ops-placeholder-ready"`、`ops-placeholder-total`（筛选下总数，纯数字文本）、`ops-placeholder-document`（document_id 原文）、`ops-placeholder-state`（含 state 原文）。你的完整页面**必须保留这 4 个 testid 与语义**（放列表上方筛选摘要条；总数用游标累计，上限 20 页并标注）。完成后 T303 回归（§6 命令 3）必须全绿。

## 3. 页面契约（对齐原型 knowledge-assets.html，数据按 T302 实际字段）

### 3.1 页面骨架

页头（「知识运营」+「只读工作台」徽章 + 描述「查看每份资料的生效版本、导入状态与被引用情况；处理失败版本请前往资料管理。」+ 右侧蓝色「前往资料管理」按钮跳现有资料管理路由）、3 页签条（知识资产高亮）。admin 门禁照 T303 模式。

### 3.2 资产列表

- 筛选条（照原型）：资料名称搜索框（接口无名称参数，**对已加载页做客户端过滤**并标注该限制）+ 文件类型下拉（全部/Excel/Word/PDF/图片 → file_type）+ 处理状态下拉（全部/生效中/待审核/导入失败 → 按 filters.ts 的 state 映射转 version_state/processing_state）+ 重置 + 右侧「共 N 份资料」（游标累计总数，放 `ops-placeholder-total`）。
- 引用计数窗口：默认近 7 天，提供今日/近 7 天/近 30 天切换（URL window 参数，复用 filters.ts），表脚注明「引用次数为所选窗口内最终引用」。
- 表格列（照原型 7 列）：资料名称（含文件类型图标色块，用现有 Icon/字符方案）/ 类型 / 当前生效版本（current_version：「V{n} 生效」绿徽章；无生效版本显示「暂无生效版本」灰徽章，**不得把最新版当生效版展示**）/ 新版处理状态（latest_import：无新版灰字「无新版」、待审核琥珀「V{n} 待审核」、导入失败红「V{n} 导入失败」、处理中相应文案）/ 引用次数（final_citations，右对齐）/ 最近发布时间（生效版本 published_at）/ 查看（详情）。
- 游标分页「加载更多」；空态照原型（「没有符合筛选条件的资料」+ 清除筛选）。
- 行点击/键盘 Enter 打开抽屉，URL 写 `document_id=...`（直链、刷新保留、关闭移除）。

### 3.3 总览下钻（同口径，重点验收）

- `?state=review_required`：琥珀横幅「已按『当前待审核版本』筛选：N 份资料存在待审核新版，发布前旧版本继续生效。」（N=当前筛选总数）+ 列表已按待审核过滤；用户改动任一筛选后横幅消失（照原型 hideBanner）。
- `?document_id=...&state=failed`：调 `GET /api/v1/operations/documents/{document_id}` 直接打开该文档抽屉，列表同时按 state 过滤；摘要条保留 document_id/state testid。**不用列表接口做 document_id 过滤（它没有该参数）。**

### 3.4 资产抽屉（右侧 520px，Esc/遮罩关闭）

调文档详情端点，自上而下：

1. 头部：资料名 + 元信息「{类型} · {n} 个版本 · 当前生效 V{n} · 只读」。
2. **版本列表**：逐版本行（版本号、状态徽章：生效绿/待审核琥珀/导入失败红/已替换灰/已删除浅灰、上传/发布时间、导入进度或 error_code 若接口返回）；**旧版本行不得展示新版本内容**。
3. **导入状态块**（照原型三态）：失败红块「V{n} 导入失败，V{m} 继续生效」+ 失败环节/error_code/可展示原因 + 「可前往资料管理重新上传」；待审核琥珀块「新版已提取，等待管理员检查发布…在此之前问答继续引用旧版本」；正常绿块「导入完成，已发布生效」。接口未返回的字段（如逐阶段时间线）不编造，只渲染实际返回。
4. **引用卡**：「{窗口} 被引用 N 次」+「查看关联问答」链接 → `/operations/requests?document_id=...&window=...`（T304 并行开发中，本任务只断言跳转 URL 参数正确，不断言对方页面内容）；版本级引用可附「按版本查看」链接带 version_id。
5. 底部：「前往资料管理」+ 关闭。表脚说明「导入失败的版本不会参与问答，也不会替换当前生效版本」。

### 3.5 口径红线

- 引用数 = T301 最终引用口径（排除 kind='conflict'）；文档被冲突问答关联时 related_requests_count 含冲突，抽屉/列表如有展示需单独标注「含冲突关联」，不得混入最终引用数。
- 待审核/生效资料卡为当前库存口径，不随窗口回溯（T302 契约 metrics.basis="current"）。
- 处理动作零实现：本页无任何上传/重试/审核/发布/删除按钮，只有跳转链接。

## 4. 实现步骤

1. assetsApi.ts + 页面骨架（页签/筛选/门禁/跳转），build 过。
2. 列表 + 窗口切换 + 游标分页 + 兼容 testid，build 过；跑 T303 回归确认 P7/P8/P10/P11 绿。
3. 抽屉（版本列表/导入状态/引用卡），build 过。
4. 下钻两链路（state 横幅 / document_id 直开抽屉），build 过。
5. 种子 + 专用配置 + 用例 A1-A10；全过。
6. T303 回归 + 证据归档 + 交付说明 + git 快照对比。

## 5. Playwright 用例（A1-A10，desktop + mobile 双 project）

种子（operations-assets-seed.py，只写自己的隔离目录）最低覆盖任务书 4 场景：①同一文档被多条问答引用（含一条问答内同文档多行，最终引用去重后计数正确）；②旧版被新版替换（superseded 版本有历史引用，列表当前生效显示新版）；③待审核新版（旧版继续生效，state=review_required 可筛出）；④导入失败新版（PARSE_INCOMPLETE 类 error_code，旧版继续生效，state=failed 可筛出）；另含无生效版本文档、已删除版本、冲突关联文档（验证「含冲突关联」标注）、>1 页文档量。种子打印预期值 JSON。

| # | 用例 | 断言要点 |
| --- | --- | --- |
| A1 | 列表渲染 | 各列与种子一致；生效版本徽章正确；无生效版本文档不显示最新版为生效 |
| A2 | 筛选 | 类型/状态/名称搜索组合正确；state 映射走 filters.ts；重置恢复 |
| A3 | 窗口切换 | 今日/7 天/30 天引用数与种子预期一致；URL window 正确 |
| A4 | 多引用去重 | 场景① 文档引用数 = 去重后预期；关联问答数 ≥ 引用数且口径标注在位 |
| A5 | 换版场景 | 场景② 列表显示新版生效；抽屉旧版标「已替换」；旧版行无新版内容 |
| A6 | 待审核下钻 | `?state=review_required` 横幅 + 过滤 + 总数一致；抽屉琥珀块；改筛选横幅消失 |
| A7 | 失败下钻 | `?document_id&state=failed` 直开抽屉；失败块含 error_code；「V{n} 失败，V{m} 继续生效」；列表 state 过滤一致 |
| A8 | 抽屉直链与跳转 | 点行 URL 带 document_id、刷新保留、Esc 关闭移除；「查看关联问答」URL 含 document_id+window；「前往资料管理」到现有路由 |
| A9 | 员工与状态 | employee 门禁 + 直调 403；空态；接口 500 错误态 + 重试 |
| A10 | 移动端 | 390 宽完成筛选 + 打开抽屉 + 关闭；无处理类按钮 |

## 6. 验证命令（证据存 T305-evidence\）

```powershell
# 0. 开工快照
git -C 'D:\GPT项目\市场部AI知识库' status --short | Out-File -Encoding utf8 'D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P3\T305-evidence\git-status-start.txt'
# 1. 构建
Set-Location 'D:\GPT项目\市场部AI知识库\frontend'
npm.cmd run build 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T305-evidence\frontend-build.txt'; $LASTEXITCODE
# 2. 本任务用例（专用配置：testMatch /operations-assets-.*\.spec\.ts/，后端 8290、preview 5301，MKTKB_TRUSTED_ORIGINS=["http://127.0.0.1:5301"]，数据目录 T305-evidence\isolated-var，reporter 输出全部指向 T305-evidence；其余照 playwright.operations.config.ts 模式）
npx.cmd playwright test --config=playwright.operations-assets.config.ts 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T305-evidence\playwright-assets.txt'; $LASTEXITCODE
# 3. T303 回归（复用 T303 配置与隔离数据；--reporter=list 避免覆盖 T303 报告）
npx.cmd playwright test --config=playwright.operations.config.ts operations-overview --reporter=list 2>&1 | Tee-Object -FilePath '..\docs\reports\OBS-EVAL\P3\T305-evidence\playwright-t303-regression.txt'; $LASTEXITCODE
```

**并行注意**：命令 3 占用 8288/5299，T304 窗口也跑同一回归；端口被占用就等 1-2 分钟重试，不改 T303 配置。命令 2 用你自己的 8290/5301，与 T304（8289/5300）互不冲突。

## 7. 验收完成条件

1. build 退出码 0；A1-A10 双 project 全过；T303 回归 26 条全绿。
2. 任务书 4 场景（多引用/换版/待审核/导入失败）全部可核对；计数与问答明细口径一致；旧版不得当新版内容展示。
3. 总览待审核卡与导入失败项下钻到同口径详情（A6/A7）。
4. 全页只读：零处理按钮，处理走现有资料管理页。
5. 边界：改动仅限 §2.1；冻结文件零改动；var\ 未写；无新依赖。
6. `T305-delivery.md`：变更清单、证据表、实现决定与偏差登记（含名称搜索为客户端过滤的限制）、已知限制、上报事项、边界自查。

## 8. 红线速查

- [ ] 列表接口无 document_id 过滤 → 下钻用详情端点；不私改后端
- [ ] 当前生效 ≠ 最新版本；旧版不展示新版内容；失败/待审核旧版继续生效
- [ ] 引用数排除 conflict；冲突关联单独标注；库存口径不回溯
- [ ] 零处理按钮；「查看关联问答」只断言 URL 参数（T304 并行）
- [ ] 兼容 testid 保留，T303 回归全绿；冻结文件未动；不装依赖
- [ ] 无付费调用、无上传/发布/删除、var\ 未写、git 无写操作