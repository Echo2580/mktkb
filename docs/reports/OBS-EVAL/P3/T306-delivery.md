# T306 开发交付说明（集成验收与候选交付）

> 执行人：T306 开发窗口；日期：2026-11-22；基线 HEAD `0d6ba61`（工作区 P3 改动未提交）。
> 结论：开发自测 **PASS**；I1-I8 双 project **PASS**；复算、性能、启动核对完成；独立验收 **NOT-RUN**（等待项目经理）；真实环境 **NOT-RUN**（须主人单独授权）。
> 全程未改业务代码、未做 git 写操作、未写 `var\`、未安装依赖、未发生付费调用。

## 1. 变更清单

### 1.1 修改（仅 §2.1 已裁决的 3 个 Playwright 配置）

#### `frontend/playwright.operations.config.ts`

```diff
@@
- * - 只选 operations-*.spec.ts，不影响既有 acceptance/e2e 配置；
+ * - 只选 operations-overview*.spec.ts（T306 收窄，避免串跑 qa/assets），不影响既有 acceptance/e2e 配置；
@@
-  testMatch: /operations-.*\.spec\.ts/,
+  testMatch: /operations-overview.*\.spec\.ts/,
@@
 const ISOLATED_DIR = path.join(EVIDENCE_ROOT, 'isolated-var');
+/** 每次执行生成独立轮次子目录（UTC 时间戳），只新增、不覆盖既有 json/html 证据。 */
+const ROUND_DIR = path.join(EVIDENCE_ROOT, 'rounds', new Date().toISOString().replace(/[:.]/g, '-'));
@@
-    ['json', { outputFile: path.join(EVIDENCE_ROOT, 'playwright-operations.json') }],
-    ['html', { outputFolder: path.join(EVIDENCE_ROOT, 'playwright-report'), open: 'never' }],
+    ['json', { outputFile: path.join(ROUND_DIR, 'playwright-operations.json') }],
+    ['html', { outputFolder: path.join(ROUND_DIR, 'playwright-report'), open: 'never' }],
@@ webServer 后端 8288
       reuseExistingServer: false,
+      gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
+      stdout: 'ignore',
+      stderr: 'ignore',
@@ webServer 前端 5299
-      command: 'npm.cmd run preview -- --port 5299 --strictPort',
+      command: 'node node_modules/vite/bin/vite.js preview --port 5299 --strictPort',
       reuseExistingServer: false,
+      gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
+      stdout: 'ignore',
+      stderr: 'ignore',
```

端口 `8288/5299`、隔离数据目录、用例断言、projects 与超时均未动。

#### `frontend/playwright.operations-qa.config.ts`

```diff
@@
 const ISOLATED_DIR = path.join(EVIDENCE_ROOT, 'isolated-var');
+/** 每次执行生成独立轮次子目录（UTC 时间戳），只新增、不覆盖既有 json/html 证据。 */
+const ROUND_DIR = path.join(EVIDENCE_ROOT, 'rounds', new Date().toISOString().replace(/[:.]/g, '-'));
@@
-    ['json', { outputFile: path.join(EVIDENCE_ROOT, 'playwright-qa.json') }],
-    ['html', { outputFolder: path.join(EVIDENCE_ROOT, 'playwright-report'), open: 'never' }],
+    ['json', { outputFile: path.join(ROUND_DIR, 'playwright-qa.json') }],
+    ['html', { outputFolder: path.join(ROUND_DIR, 'playwright-report'), open: 'never' }],
@@ MAIN_STACK 后端 8289 / TRACE_OFF_STACK 后端 8292
       reuseExistingServer: false,
+      gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
+      stdout: 'ignore',
+      stderr: 'ignore',
@@ 前端 5300 / 5302
-      command: 'npm.cmd run preview -- --port 5300 --strictPort',
+      command: 'node node_modules/vite/bin/vite.js preview --port 5300 --strictPort',
       reuseExistingServer: false,
+      gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
+      stdout: 'ignore',
+      stderr: 'ignore',
-      command: 'npm.cmd run preview -- --port 5302 --strictPort',
+      command: 'node node_modules/vite/bin/vite.js preview --port 5302 --strictPort',
```

`testMatch`、端口 `8289/5300/8292/5302`、双栈结构、`T304_STACK` 拆栈开关均未动。

#### `frontend/playwright.operations-assets.config.ts`

```diff
@@
 const ISOLATED_DIR = path.join(EVIDENCE_ROOT, 'isolated-var');
+/** 每次执行生成独立轮次子目录（UTC 时间戳），只新增、不覆盖既有 json/html 证据。 */
+const ROUND_DIR = path.join(EVIDENCE_ROOT, 'rounds', new Date().toISOString().replace(/[:.]/g, '-'));
@@
-    ['json', { outputFile: path.join(EVIDENCE_ROOT, 'playwright-assets.json') }],
-    ['html', { outputFolder: path.join(EVIDENCE_ROOT, 'playwright-report'), open: 'never' }],
+    ['json', { outputFile: path.join(ROUND_DIR, 'playwright-assets.json') }],
+    ['html', { outputFolder: path.join(ROUND_DIR, 'playwright-report'), open: 'never' }],
```

仅 reporter，其余未动（该配置本就有 gracefulShutdown 与直启写法，未改）。

### 1.2 新增（§2.2 独占）

| 文件 | 用途 |
| --- | --- |
| `frontend/e2e/operations-integration-seed.py` | I1-I8 共用受控种子，只写 `--data-dir` |
| `frontend/e2e/operations-integration.spec.ts` | I1-I8 双 project 用例 |
| `frontend/playwright.operations-integration.config.ts` | 主栈 8291/5303、Trace 关闭栈 8293/5304、双 project |
| `docs/reports/OBS-EVAL/P3/T306-evidence/` | 日志、轮次报告、种子、复算、性能、启动核对 |
| `docs/reports/OBS-EVAL/P3/T306-delivery.md` | 本文件 |
| `docs/reports/OBS-EVAL/P3/T306-release-candidate.md` | 发布候选材料 |

证据目录内的轮次子目录（只新增，未覆盖 T303/T304/T305 既有 json/html）：

- `T303-evidence/rounds/2026-11-22T06-29-11-490Z/`
- `T304-evidence/rounds/2026-11-22T06-30-04-833Z/`
- `T305-evidence/rounds/2026-11-22T06-31-00-952Z/`
- `T306-evidence/rounds/2026-11-22T06-49-28-642Z/`（最终全过轮次；06:36/06:37 为整改迭代，06:39 为 I6 单测）

前 3 个目录的既有 `playwright-*.json` 修改时间仍为 2026-11-22 04:18/13:51/14:11，未被本轮覆盖。

## 2. 回归证据（开发自测）

| # | 命令（工作目录） | 退出码 | 通过 | 失败 | 跳过 | 日志 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `..\.venv\Scripts\python.exe -B -m pytest tests/operations -q`（`backend\`） | 0 | 69 | 0 | 0 | `logs/pytest-operations.txt` |
| 2 | `..\.venv\Scripts\python.exe -B -m pytest tests/integration/test_chat.py tests/integration/test_answer_commit.py tests/integration/test_p1_source_bridge.py tests/integration/test_auth.py tests/observability -q`（`backend\`） | 0 | 450 | 0 | 0 | `logs/pytest-p2-regression.txt` |
| 3 | `npm.cmd run build`（`frontend\`） | 0 | — | — | — | `logs/frontend-build.txt` |
| 4 | `npx.cmd playwright test --config=playwright.operations.config.ts` | 0 | 26 | 0 | 0 | `logs/playwright-operations.txt` |
| 5 | `npx.cmd playwright test --config=playwright.operations-qa.config.ts` | 0 | 19 | 0 | 1 | `logs/playwright-qa.txt` |
| 6 | `npx.cmd playwright test --config=playwright.operations-assets.config.ts` | 0 | 20 | 0 | 0 | `logs/playwright-assets.txt` |
| 7 | `npx.cmd playwright test --config=playwright.operations-integration.config.ts` | 0 | 16 | 0 | 0 | `logs/playwright-integration.txt` |

- 第 5 条跳过为 T304 既有设计：desktop project 的 Q10（移动端用例）在 desktop 下 `skip`，mobile 下执行；非新增跳过。
- 第 4 条未加 `-g`/文件名过滤，仅靠 `testMatch` 收窄即只跑 26 条 overview 用例，证明收窄生效。
- 第 2 条在 `backend\` 下按 dispatch 指定路径执行；450 条含 P2 问答、答案提交、来源桥、鉴权与 observability。
- 构建日志尾部有 chunk 体积提示（既有构建警告），非失败。

## 3. I1-I8 集成验收

种子：`frontend/e2e/operations-integration-seed.py`；数据：`T306-evidence/isolated-var`（4 份资料、8 条已完成问答、2 个自然日、1 个失败导入、1 个待审核、2 个评测 run + 1 个空目录）。
主栈 8291/5303（Trace 开），Trace 关闭栈 8293/5304；desktop 1440×900 + mobile 390×844。

| # | 用例 | 关键断言 | 结果 |
| --- | --- | --- | --- |
| I1 | 首页→趋势日期→问答明细 | 趋势末日=今日；`since/until`=今日；列表总数=6=总览今日完成量；抽屉问题/`已回答`/引用「门店产品价目表 V1 当前有效」=种子 | PASS（双 project） |
| I2 | 结果分布→冲突详情→核对版本 | `kind=conflict&window=7d`；总数 1；两方「3 个工作日/门店服务手册 V1」「5 个工作日/市场活动补充通知 V1」均 active；引用数 0；资产抽屉 V1 生效 | PASS（双 project） |
| I3 | 待处理→导入失败详情→关联问答 | `document_id+state=failed`；总数 1；「V2 导入失败，V1 继续生效」；`PARSE_INCOMPLETE`；「查看关联问答」→`document_id` 过滤生效、横幅在位、总数 2 | PASS（双 project，T304↔T305 实跑串联） |
| I4 | 员工门禁 | 三页均「知识运营仅限管理员」；overview/requests/documents/请求详情/资料详情/evaluation-runs 六接口均 403 `ROLE_REQUIRED`；导航无「知识运营」 | PASS（双 project） |
| I5 | Trace 关闭栈 | 5304 上 I1/I2 业务内容可读，阶段区「Trace 已关闭」且无阶段条；主栈 `not_recorded` 请求显示「本次未记录执行过程」 | PASS（双 project） |
| I6 | 空窗口 | 总览 4 张关键卡为 0、趋势/分布空态、无图表、无 `NaN`/假百分比；requests 空态且总数 0；assets 引用全 0 且无匹配筛选显示空态；评测空目录不出现 | PASS（双 project，口径说明见 §7） |
| I7 | 移动端 | mobile 断言 390×844；总览→失败详情→关联问答整链走通 | PASS（双 project） |
| I8 | 评测摘要 | 2 个 run；分母 20/12 与受控 run 一致；状态「已完成」；holdout 行「holdout 明细已扣留」；抽屉仅聚合可见且无 `leak-into-ui`；无发起/重试/下载入口 | PASS（双 project） |

最终轮次报告：`T306-evidence/rounds/2026-11-22T06-49-28-642Z/playwright-integration.json` 与同名 `playwright-report/`。

## 4. 指标复算

### 4.1 T301 基准（只读复算，逐项一致）

用 T301 原脚本的只读副本（`T306-evidence/scripts/t301/`，连接改为 `mode=ro`，输出改到 `recompute-t301/`），T301 冻结目录零写。

| 项目 | T301 预期 | 本次复算 | 结论 |
| --- | --- | --- | --- |
| 请求行总数 / 范围内 / 排除已删除 | — / — / 1 | 16 / 15 / 1 | 一致 |
| 已完成问答量（请求 ID） | 13 | 13 | 一致 |
| 六类分布 | 8/1/1/1/1/1 | 8/1/1/1/1/1 | 一致 |
| 中断 | 2 | 2（running/expired） | 一致 |
| 非冲突持久引用行 | 13 | 13 | 一致 |
| 文档/版本去重对 | 6/6 | 6/6 | 一致 |
| 待审核 / 生效 / 失败版本 | 1/5/1 | 1/5/1 | 一致 |
| 失败导入 | 1（PARSE_INCOMPLETE） | 1（PARSE_INCOMPLETE） | 一致 |
| 覆盖率 | 10/13 = 0.7692 partial | 10/13 = 0.7692 partial | 一致 |
| 午夜边界 | S17→11-20、S18→11-21 | 同 | 一致 |
| 冲突持久行（D5 缺口） | 口径 0 / 实测 2 | 0 / 2 | 与 T301 报告一致，口径缺口沿用 |
| 已删除会话 S10 | 排除 | 排除 | 一致 |

结果：`T306-evidence/recompute-t301/recompute-results.json`；日志 `logs/recompute-t301.txt`；退出码 0。

### 4.2 集成种子（overview == 明细复算）

只读 SQL 独立计算（`T306-evidence/scripts/t306_recompute_integration.py`），不复用应用查询代码：

| 窗口 | overview 完成量 | 明细复算 | 六类（answer/clarification/not_found/conflict/service_error/knowledge_changed） | 结论 |
| --- | --- | --- | --- | --- |
| 今日 | 6 | 6（去重 request_id 6） | 3/0/1/1/1/0 | 一致 |
| 昨日 | 2 | 2 | 1/1/0/0/0/0 | 一致 |
| 近 7 天 | 8 | 8 | 4/1/1/1/1/0 | 一致 |
| 空窗口 | 0 | 0 | 0/0/0/0/0/0 | 一致 |

- 引用：非冲突持久行 5；消息+文档去重 4；消息+版本去重 4；冲突持久行 0（种子未给 conflict 写 sources，对齐口径）。
- 库存：待审核 1、生效 published 3、失败导入 1。
- Trace：分母 8、普通 Trace 覆盖 5、untracked 3、0.625 → `partial`，与 overview 一致。
- 结果 `recompute-integration/recompute-results.json`，`consistent=true`，退出码 0；日志 `logs/recompute-integration.txt`。

## 5. 性能实测与查询计划（只读，未建索引）

脚本 `T306-evidence/scripts/perf_probe.py`；两库 × today/7d/30d × 三类查询，各 5 次取中位数/最大值；单位 ms。

| 库 | 规模（总请求行/资料/来源行；窗口内请求行） | 窗口 | overview 中位/最大 | requests 中位/最大 | documents 中位/最大 |
| --- | --- | --- | --- | --- | --- |
| 集成 | 8 / 4 / 5；6-8 | today | 0.009 / 0.095 | 0.012 / 0.044 | 0.012 / 0.097 |
| 集成 | 同上 | 7d | 0.008 / 0.012 | 0.014 / 0.018 | 0.013 / 0.017 |
| 集成 | 同上 | 30d | 0.009 / 0.158 | 0.014 / 0.016 | 0.013 / 0.016 |
| T301 | 16 / 7 / 16；13-15 | today | 0.012 / 0.094 | 0.026 / 0.071 | 0.043 / 0.105 |
| T301 | 同上 | 7d | 0.012 / 0.016 | 0.032 / 0.238 | 0.020 / 0.029 |
| T301 | 同上 | 30d | 0.012 / 0.015 | 0.028 / 0.031 | 0.019 / 0.022 |

查询计划（7d，两库一致）：

- `overview_completed`：`SEARCH r USING INDEX ix_conversation_requests_status_deadline (status=?)` + `USE TEMP B-TREE FOR count(DISTINCT)`；无全表扫描。
- `requests_page`：status 索引定位 + `USE TEMP B-TREE FOR ORDER BY`；无全表扫描。
- `documents_citations`：status 索引 + 消息主键 + 来源 `message_id` 索引，`GROUP BY`/`count(DISTINCT)`/`ORDER BY` 各用临时 B 树；无全表扫描。

评估：在受控小样本（≤16 请求行）下单查询 < 0.3 ms，瓶颈不在 SQL，而在“窗口内全量加载后内存聚合”的应用层（T302 已记录）。当前无索引必要；若真实库单窗口请求量达到万级、requests 排序或 documents 聚合成为热点，可评估 `conversation_requests(status, finished_at)` 复合索引与 `conversation_message_sources(document_id)` 覆盖索引，预计减少排序/分组临时 B 树。**本次未执行任何 CREATE INDEX**。原文见 `perf/perf-report.md`、`perf/perf-results.json`、`logs/perf-probe.txt`。

## 6. 启动与回退核对

### 6.1 静态审查

- `一键启动.cmd`：先以进程内环境覆盖 `MKTKB_RAG_PROVIDER_MODE=live` 等参数调用 `start_local.py --owner-live`；失败（如亲验 GO 用尽）才回退 `--offline`，并明示“不调用真实模型、不伪造答案”。
- `启动-真实问答.cmd`：同上，只走 live，失败 `pause`。
- `tools/start_local.py`：`--offline` 走 `Settings(_env_file=.env)`，但 `MKTKB_DATA_DIR` 环境变量优先于 .env；离线分支强制 `rag_provider_mode=offline`、清空模型三键、`ocr_disabled=True`。非 smoke 模式打印数据目录、起 Vite、起 worker，`input()`/EOF 后按 PID 树清理前端并停后端。

### 6.2 安全试跑（离线）

命令（仓库根，PowerShell）：

```powershell
$env:MKTKB_DATA_DIR='D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P3\T306-evidence\isolated-var-launcher'
$env:MKTKB_TRACE_ENABLED='0'; $env:MKTKB_RAG_QA_ENABLED='0'
& { Start-Sleep -Seconds 40; '' } | & .\.venv\Scripts\python.exe -B tools\start_local.py --offline
```

结果（日志 `logs/launcher-offline.txt`）：

- 后端 8077 `/api/v1/healthz` 返回 `{"status":"ok"}`；前端 5673 根路径 HTTP 200；启动输出 `数据目录：...\T306-evidence\isolated-var-launcher`，并打印「离线模式：使用现有账号和资料，真实模型及 OCR 已关闭」。
- 40 秒后回车触发清理，退出码 0，`正在停止本次服务……`；8077/5673 均无残留监听。
- `var\` 15071 个文件的路径/大小/修改时间快照前后完全一致（`VAR_UNCHANGED`，快照 `logs/var-before.json`、`logs/var-after.json`）。
- 隔离目录新建 `mktkb.sqlite3` 与前端日志，证明写入落在隔离目录。
- 未走 live 分支、未触发真实模型/OCR/付费调用。

### 6.3 回退（只写文档，未执行）

- P2 发布参照：候选 `7556efd`、发布记录 `cb74457`；当前 HEAD `0d6ba61`。
- P3 候选 = HEAD `0d6ba61` + 工作区未提交 P3 改动；回退方式二选一，均须主人批准后执行：
  1. 若已按建议拆分提交：对每个 P3 提交执行 `git revert <sha>`（保留历史）。
  2. 若尚未提交：丢弃工作区 P3 改动（精确清单见 `T306-release-candidate.md` §1），保留 `.claude/handoffs`、P2 在途证据等非 P3 改动。
- 本窗口未执行任何 revert/reset/checkout。

## 7. T302 补充单评估（只评估，不改后端）

1. **20 页游标上限（400 行/窗口）**：当前 8 行（集成）/15 行（T301），远低于上限。按 7 天窗口对账，日完成量 ≤57 时不会触顶；一旦 30 天窗口需要逐条对账（按 50 条/日约 1500 行）就会截断。建议：暂不立补充单；设触发阈值——单窗口完成量接近 400 或运营提出 30 天逐条对账时，再评估提高上限/支持 `page_size` 或导出。
2. **列表缺 `latest_version` 与名称搜索仅客户端两处降级**：当前资料库存 4-7 份，列表已能通过 `current_version + latest_import` 区分“生效版本/新版处理状态”，名称搜索在已加载页内可用。建议：暂不立补充单；当资料数超过约 200 份、或运营需要按最新版本排序/精确筛选时再立单，避免为小库存增加接口面。
3. 两项均属体验/规模问题，不影响当前 P3 对账正确性；是否立单请主人拍板。

## 8. 已知限制

1. I6「空窗口 assets 空态」与 T305 定稿口径存在张力：资料列表是“当前库存”口径，空窗口仍列 4 份资料（引用全 0），并非 0 行；用例改用“无匹配筛选 + 空窗口”验证空态，并单独断言空窗口引用全 0。详见 §9 上报 A。
2. 集成种子的 conflict 未写持久引用行（对齐“冲突不计最终引用”口径）；T301 基准库 D5 缺口（conflict 落 2 行）仍存在，属既有产品行为，本任务未改。
3. Trace 覆盖为受控样本（5/8 普通 Trace，1 条 error、2 条未记录），非真实运行分布。
4. 性能探针是 SQL 等价形状，不含应用层逐行聚合与 HTTP/Vite 开销；样本规模小（≤16 请求行），结论只对小库成立。
5. 启动试跑只覆盖 `--offline` 分支；`--owner-live` 真实路径未跑（NOT-RUN，需亲验 GO 与主人授权）。
6. 两套数据均为受控样本，非真实业务数据；所有替身/受控构造均标注 Mock/受控。
7. 测试环境为本机 Windows 11 + PowerShell 7、Chromium；未覆盖其他 OS/浏览器。
8. T306 dispatch 提到的 `perf_probe.py` 在 T302 交付中不存在；本任务按 §3.4 方法新建同名脚本，口径见 §5。

## 9. 上报事项

- **A（口径张力，需项目经理裁决）**：T306 I6 写“assets 空态”，但 T305 已定稿“资产列表为当前库存口径，不随窗口回溯”。实测空窗口仍返回 4 份资料、引用 0。若强行让空窗口 0 行，将改变 T305 口径并动后端查询；本任务未改。建议接受“空窗口引用全 0 + 无匹配筛选空态”的现测口径，或另立任务明确资产列表是否按窗口过滤。
- **B（文档缺口）**：dispatch §3.4 引用 T302 交付的 `perf_probe.py`，该文件实际不存在；已按方法新建 T306 版并标注等价形状，不影响结论，但建议后续任务书引用真实路径。
- **C（既有 D5 缺口）**：T301 已上报“冲突消息持久引用行 2 行 vs 口径 0”，本次复算仍为 2 行；未私修业务代码，继续挂在 P3 待决。
- **D（启动脚本数据目录）**：`start_local.py --offline` 本身无 `--data-dir` 参数，安全隔离依赖 `MKTKB_DATA_DIR` 环境变量；若主人直接双击 `.cmd`，仍会使用 `.env` 推导的真实 `var\`。本次试跑已显式覆盖，建议后续给启动器加显式数据目录参数或在文档中固化该环境变量。
- **E（T303 配置注释）**：为说明 testMatch 收窄，更新了文件头一行注释；不影响任何配置行为。

## 10. 边界自查

- [x] `backend/src/**`、`frontend/src/**`、`schema.d.ts`、`package.json`/`package-lock.json` 零改动（工作区中这些改动均为 T301-T305 在途 P3 改动，T306 未触碰）。核对：这些文件最后修改时间为 2026-11-22 00:33-02:27，均早于 T306 执行窗口（14:20 之后）；T306 窗口内只修改 3 个 Playwright 配置并新增文件。
- [x] git 零写操作：仅用 `git status/log/show/diff/rev-parse` 只读命令；未 add/commit/checkout/reset/stash/clean。
- [x] `var\` 未写：试跑前后 15071 个文件快照一致；所有服务 `MKTKB_DATA_DIR` 指向 T306 隔离目录。
- [x] T301 隔离库只读：复算脚本 `mode=ro`，输出改到 T306 目录；T301 既有文件未覆盖。
- [x] 轮次 reporter 只新增：T303/T304/T305 旧 json/html 修改时间未变。
- [x] 无新依赖：未执行 npm install；`package.json` 的 echarts 为 T301-T305 在途改动，T306 未动。
- [x] 无付费调用：种子/测试全离线；启动试跑 `--offline` 且清空模型键、禁用 OCR。
- [x] 不建索引、不改口径：仅评估，未执行 CREATE INDEX。
- [x] 既有 spec/seed、T301-T305 交付物、`tools/start_local.py` 与两个 `.cmd` 均未修改。
- [x] 真实环境验证全程 NOT-RUN。
