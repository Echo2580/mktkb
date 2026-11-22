# T305 交付说明：知识运营 · 知识资产页

> 结论：`/operations/documents` 已由占位页升级为知识资产页（列表/筛选/窗口/横幅/抽屉/下钻），全页只读。构建退出码 0，A1-A10 双 project 20/20 通过，T303 回归 26/26 通过。改动仅落在派单 §2.1 文件内，冻结文件零改动。

## 1. 变更清单（仅 §2.1）

| 路径 | 类型 | 内容 |
| --- | --- | --- |
| `frontend\src\features\operations\DocumentsPlaceholderPage.tsx` | 改写 | 文件名与导出名不变；页头、3 页签、筛选条、表格、分页、横幅、兼容 testid、抽屉挂载 |
| `frontend\src\features\operations\assets\assetsApi.ts` | 新增 | 只读封装：`loadAllDocuments`（page_size 20、游标累计、上限 20 页）、`loadDocumentDetail`、`loadDocumentDetails`（并发 6 + 缓存） |
| `frontend\src\features\operations\assets\assetModel.ts` | 新增 | 展示口径：类型映射、版本/导入徽章、生效版本判定、`needsDetail`、失败环节文案、时间格式化 |
| `frontend\src\features\operations\assets\AssetDrawer.tsx` | 新增 | 520px 抽屉：头部元信息、版本列表、导入三态块、引用卡与关联问答下钻、底部跳转/关闭；Esc 与遮罩可关 |
| `frontend\src\features\operations\assets\VersionList.tsx` | 新增 | 逐版本行（`data-version-number` / `data-version-state`），旧版本行不展示新版本内容 |
| `frontend\src\features\operations\assets\ImportStatusBlock.tsx` | 新增 | 三态导入块（`data-tone=failed/review/published`） |
| `frontend\src\features\operations\assets\assets.css` | 新增 | T305 全部样式，未改 `operations.css` |
| `frontend\e2e\operations-assets-page.spec.ts` | 新增 | A1-A10，desktop + mobile 双 project |
| `frontend\e2e\operations-assets-seed.py` | 新增 | 受控种子，只写 `--data-dir`（25 份资料、7 个核心场景、18 份批量、请求/冲突、导入任务） |
| `frontend\playwright.operations-assets.config.ts` | 新增 | 专用配置：5301/8290、`testMatch /operations-assets-.*\.spec\.ts/`、数据目录 `T305-evidence\isolated-var` |
| `docs\reports\OBS-EVAL\P3\T305-evidence\` | 新增 | 本说明与全部证据 |

## 2. 页面能力对照 §3

- 页头：标题「知识运营」+「只读工作台」徽章 + 描述文案 + 右侧「前往资料管理」跳现有资料管理路由。
- 页签：运营总览 / 问答诊断 / 知识资产（高亮），与 T303 的 P12 断言一致。
- 筛选条：名称搜索（客户端，已标注限制）+ 文件类型 + 处理状态 + 重置 + 右侧「共 N 份资料」（游标累计，置于 `ops-placeholder-total`）。
- 引用窗口：今日 / 近 7 天 / 近 30 天，URL 参数 `window`，默认近 7 天，复用 `filters.ts` 的常量与映射。
- 表格 7 列：名称（类型色块）/ 类型 / 当前生效版本（`V{n} 生效` 绿徽章或「暂无生效版本」灰徽章）/ 新版处理状态 / 引用次数（`final_citations`，右对齐）/ 最近发布时间 / 查看。
- 分页：「加载更多」按游标翻页，最多 20 页（400 条），页脚注明上限。
- 待审核横幅：`?state=review_required` 时显示「已按『当前待审核版本』筛选：N 份资料存在待审核新版，发布前旧版本继续生效。」，N 取当前总数；用户改动任一筛选后横幅消失。
- 直链下钻：`?document_id=...`（可带 `state`）直接打开抽屉，列表同时按 `state` 过滤，不按 `document_id` 过滤。
- 兼容 testid 保留：`ops-placeholder-ready`、`ops-placeholder-total`、`ops-placeholder-document`、`ops-placeholder-state`。
- 只读：整页零上传/重试/审核/发布/删除按钮（A10 显式断言），处理动作全部跳资料管理页。

## 3. 验证证据

| 项 | 命令 / 数据 | 结果 | 证据文件 |
| --- | --- | --- | --- |
| 构建 | `npm.cmd run build` | exit 0，`✓ built in 407ms` | `frontend-build.txt` |
| A1-A10（主证据） | `npx.cmd playwright test --config=playwright.operations-assets.config.ts`（手动起 8290/5301 后 `MKTKB_REUSE_SERVER=1` 复用） | `20 passed (26.1s)`，exit 0 | `playwright-assets.txt` |
| A1-A10（派单原命令复跑） | 同上配置、不设复用环境变量 | 测试 20 条全 `ok`，`20 passed (6.3m)` | `playwright-assets-official.txt` |
| T303 回归 | `npx.cmd playwright test --config=playwright.operations.config.ts operations-overview --reporter=list` | `26 passed (59.3s)`，exit 0 | `playwright-t303-regression.txt` |
| 种子期望 | `operations-assets-seed.py` | 25 份 / 2 页 / review 2 / failed 1 | `isolated-var\seed-summary.json`、`seed-run.txt` |
| 开工快照 | 派单 §6 步骤 0 | — | `git-status-start.txt` |

### 3.1 运行环境偏差（重要，供复跑参考）

本机 Windows 上 Playwright 1.64 的 `webServer` 收尾会挂起：20 条/26 条测试已全部 `ok`，但 CLI 不打印汇总、不退出，直到把 8290/5301（或 8288/5299）的监听进程释放后才输出 `passed` 汇总。已验证与用例无关（同一份代码手动起服务复用后 26.1s 干净退出，exit 0）。

复跑处理：若命令 2/3 在全部 `ok` 后长时间无汇总，按下面方式释放监听进程即可收尾（仅结束本次 Playwright 拉起的服务，不影响其他窗口）：

```powershell
foreach($port in 8290,5301,8288,5299){
  $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if($c){ Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
}
```

本任务的专用配置为此加了 `gracefulShutdown`、`stdout/stderr: ignore` 与 `reuseExistingServer: process.env.MKTKB_REUSE_SERVER === '1'`，preview 改为直接启动 `node node_modules/vite/bin/vite.js preview`（避免 `npm.cmd` 子进程残留）。T303 配置冻结，未做任何改动。

## 4. 实现决定与偏差登记

1. **生效版本判定**：只认 `current_version.state === 'published'`；其余一律「暂无生效版本」，不把最新版当生效版（对应 §3.2 红线）。
2. **列表缺口径的补齐**：列表契约没有「最新版本状态/版本号」，需要时调只读详情端点 `GET /operations/documents/{document_id}` 补齐。
3. **详情请求节流**：`needsDetail()` 仅在「无生效版本」或「`latest_import !== null`」时请求；已发布且无导入线索的行按「无新版」保守展示。整页详情请求从每页 25 次降到约 3 次，是本机低内存环境下稳定通过的前提。
4. **名称搜索为客户端过滤**：列表接口无名称参数，只对已加载页过滤，UI 已标注该限制（验收口径 §7.6 要求登记）。
5. **文件类型**：docx/pdf/xlsx 走接口 `file_type`；「图片」在调用前不过滤，加载后按 png/jpg/jpeg 客户端筛选。
6. **状态映射**：复用 `filters.ts` 的 `mapDocumentState`，URL 里保留 `state` 原文；列表仅按 `state` 过滤。
7. **引用口径**：列表「引用次数」取 `final_citations`；抽屉「关联问答」取 `related_requests_count`；当 `related > final` 时标注「含冲突关联，不计入最终引用」，不混入最终引用数。
8. **document_id 下钻**：依 T303 §三裁决 ②，不用列表接口做 `document_id/version_id` 过滤，改为打开抽屉并调详情端点；列表不同时按 `document_id` 过滤。
9. **抽屉关闭**：移除 `document_id`（保留 `window`），支持 Esc 与遮罩关闭；标题旁标注「只读」。
10. **版本列表**：只渲染该版本自身字段，`superseded` 行不展示新版本内容；失败版本展示 `error_code/message`，不编造时间线。
11. **关联问答链接**：指向 `/operations/requests?document_id=...&window=...`（版本级附 `version_id`），本任务只断言 URL 参数，页面内容属 T304。

## 5. 已知限制

- 名称搜索只覆盖已加载页（当前 25 份资料 2 页全量加载后等价全量；超过 400 条时只搜已加载范围）。
- 「新版处理状态」在「已生效且 `latest_import` 为空」的行显示「无新版」，属保守判定；若后端后续在列表补 `latest_version/latest_import` 字段可移除该保守分支。
- 图片类型筛选在接口返回后于客户端完成，跨页时仅对已加载页生效。
- 列表最多累计 20 页（400 条），页脚已标注；超出部分不加载。
- 引用数与关联问答数均来自 T302 列表/详情端点，本页不重新计算、不回溯窗口。
- 抽屉不展示导入逐阶段时间线（接口未返回），只展示 `stage/error_code/message/attempts` 等实际字段。

## 6. 上报事项

1. **列表接口建议补充字段**：`latest_version`（number/state）与 `name` 搜索参数。当前「新版处理状态」需按需调详情、名称搜索退化为客户端过滤，都是接口缺口导致的降级实现。
2. **Playwright 收尾挂起**：本机 Playwright 1.64 + Windows 下 `webServer` 停止阶段不退出（见 §3.1），T303 冻结配置复跑同样会挂；建议后续由维护方在 T303/T304 配置统一加 `gracefulShutdown` 或改直启进程，本次未越界修改。
3. **T304 依赖**：抽屉「查看关联问答」只保证 URL 参数正确，`/operations/requests` 的接收与展示由 T304 交付，联调时需复核参数名 `document_id/version_id/window`。

## 7. 边界自查

- 改动文件：§1 所列 11 项，全部位于 §2.1 白名单。
- 冻结文件：`client.ts`、`schema.d.ts`、`App.tsx`、`AppShell.tsx`、`filters.ts`、`operations.css`、`OperationsOverviewPage.tsx`、`charts.ts`、`EChart.tsx`、`operations-overview.spec.ts`、`playwright.operations.config.ts`、`package.json`、`package-lock.json` 修改时间均 ≤ 11-22 02:58，早于本任务开工（03:35），零改动。
- 后端：未改 `backend\**`；本机不存在 `backend\var`，未写 `var\`。
- 依赖：未安装任何新依赖（`package.json`/`package-lock.json` 时间未变）。
- 数据面：e2e 只走登录与只读 GET，未发问答 POST，未上传/发布/删除；种子只写 `T305-evidence\isolated-var`。
- 交付物：未改 T301/T302/T303 任何文件。
- git：本机 PATH 中无 git 可执行文件，无法在收尾时再取 `git status`；开工快照 `git-status-start.txt` 为派单 §6 步骤 0 的原样产物，边界以上面的文件清单 + 修改时间核对。

## 8. 红线速查

- [x] 列表接口无 `document_id` 过滤 → 下钻走详情端点，未改后端
- [x] 当前生效 ≠ 最新版本；旧版不展示新版内容；失败/待审核时旧版继续生效
- [x] 引用数排除 conflict；冲突关联单独标注；库存口径不回溯
- [x] 零处理按钮；关联问答只断言 URL 参数
- [x] 兼容 testid 保留，T303 回归 26/26 全绿；冻结文件未动；未装依赖
- [x] 无付费调用、无上传/发布/删除、`var\` 未写、git 无写操作
