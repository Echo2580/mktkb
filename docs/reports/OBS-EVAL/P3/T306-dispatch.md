# T306 开发交接提示词（集成验收与候选交付）

> 全文复制给开发窗口。P3 收口任务，无并行窗口；T301-T305 已全部验收 PASS。
> 派单人：项目经理。日期：2026-11-22。

## 0. 角色与铁律

你是开发执行者，做 T306：集成复验 + 最小 P2 回归 + 指标复算 + 性能实测 + 启动/回退核对 + 发布候选材料。**不改任何业务代码**（backend\src、frontend\src 全部只读）；本任务只允许动 §2 列出的测试基础设施与新增证据/文档。

1. 工作目录 `D:\GPT项目\市场部AI知识库`；Windows + PowerShell 7，Bash 不可用；前端 `npm.cmd`/`npx.cmd`；后端 pytest 必须在 `backend\` 下用 `..\.venv\Scripts\python.exe -B -m pytest` 接具体路径（配置在 backend/pyproject.toml，勿从仓库根裸跑）。
2. 禁止付费调用：不发真实模型/OCR/Ragas 请求；外部模型一律替身并标注 `Mock`。启动核对只允许离线/Mock 模式（§3.6）。
3. 禁写 `var\`（业务库与 Trace 库）；所有服务用 `MKTKB_DATA_DIR` 指隔离目录。T301 隔离库只读（复算脚本用只读连接）。
4. **git 无任何写操作**（add/commit/checkout/reset/stash/clean 全禁）。发布候选=材料+提交方案建议，由主人决定提交；回退方式只写文档不执行。
5. T301-T305 既有交付物只读；唯一例外见 §2.1（三个 Playwright 配置的已裁决整改 + 各证据目录下**新增**轮次子目录，不得覆盖/修改既有文件）。工作区在途改动（.claude/handoffs、P2 证据等）原样保留。
6. 发现回归或口径不一致：**停下写上报事项**，不私改业务代码、不私改冻结口径。
7. 交付只认变更清单 + 证据（命令/退出码/通过失败跳过数）+ 已知限制；开发自测、独立验收、真实环境验证三列分开，真实环境全程 NOT-RUN（须主人单独授权）。数字用阿拉伯数字。

## 1. 必读（按顺序）

1. 任务书 `docs\superpowers\plans\2026-11-21-mktkb-p3-operations-taskbook.md` **T306 小节 + §4 推进和接收标准**（发布条件 4 条）。
2. `T301-data-audit.md` §3-§6（口径与 Span 映射）；`T301-isolated\T301-recomputation.md`（预期值）与 `scripts\t301_recompute.py`、`t301_common.py`（复算入口，先读再用）。
3. `T302-evidence\T302-delivery.md` §4（18 项契约）；`T303-acceptance.md` §三（4 项裁决）；`T304-acceptance.md` §四/§八；`T305-acceptance.md` §四/§六（移交本任务的事项清单）。
4. 启动路径变更（只读 git 命令查看）：`git show 04515f3`（新增 一键启动.cmd）、`git show 0d6ba61`（tools/start_local.py +26/-、一键启动.cmd、启动-真实问答.cmd）；实读 `tools\start_local.py`、`一键启动.cmd`、`启动-真实问答.cmd` 全文，弄清离线/Mock 开关与数据目录覆盖方式。
5. 现有测试基础设施：`frontend\playwright.operations.config.ts`、`playwright.operations-qa.config.ts`、`playwright.operations-assets.config.ts`、`e2e\operations-overview.spec.ts`、`operations-qa.spec.ts`、`operations-assets-page.spec.ts`、三个 seed 脚本（集成种子可组合复用其构造逻辑）。
6. P2 发布参照：`docs\reports\OBS-EVAL\P2\FOLLOW-UP\requalification\release-decision.v0_3.md`（候选 7556efd、发布记录 cb74457）。

## 2. 文件归属

### 2.1 允许修改（仅限已裁决的测试基础设施整改）

| 文件 | 允许的改动 |
| --- | --- |
| `frontend\playwright.operations.config.ts` | ① testMatch 收窄为 `/operations-overview.*\.spec\.ts/`；② reporter 输出改为按轮次子目录（如 `T303-evidence\rounds\<UTC时间戳>\`，只新增不覆盖既有 json/html）；③ 加 gracefulShutdown（signal SIGTERM、timeout 1000）与 stdout/stderr ignore，preview 改直启 `node node_modules/vite/bin/vite.js`（照 T305 配置写法）。**端口 8288/5299、数据目录、用例断言、其余配置一律不动** |
| `frontend\playwright.operations-qa.config.ts` | 同上②③（reporter 轮次子目录在 T304-evidence 下新增）；testMatch/端口/双栈/T304_STACK 不动 |
| `frontend\playwright.operations-assets.config.ts` | 仅②（reporter 轮次子目录）；其余不动 |

### 2.2 新增（T306 独占）

- `frontend\e2e\operations-integration-seed.py`、`frontend\e2e\operations-integration.spec.ts`
- `frontend\playwright.operations-integration.config.ts`（主栈 8291/5303，Trace 关闭栈 8293/5304，数据目录 `T306-evidence\isolated-var`，trusted origins 各自对应；照 T304 双栈模式）
- `docs\reports\OBS-EVAL\P3\T306-evidence\`（全部证据、性能脚本与结果、轮次报告）
- `docs\reports\OBS-EVAL\P3\T306-delivery.md`、`T306-release-candidate.md`

### 2.3 冻结

`backend\src\**`、`frontend\src\**`、`schema.d.ts`、`package.json`/`package-lock.json`（不装依赖）、三个既有 spec 与 seed、T301-T305 全部既有交付物（含隔离库数据）、`tools\start_local.py` 与两个 .cmd（只读核对，不改）。

## 3. 工作项

### 3.1 配置整改 + 全套回归（开发自测）

整改 §2.1 后依次跑并留日志（每条记退出码与通过/失败/跳过数）：

```powershell
# 后端（在 backend\ 下）
..\.venv\Scripts\python.exe -B -m pytest tests/operations -v
..\.venv\Scripts\python.exe -B -m pytest tests/integration/test_chat.py tests/integration/test_answer_commit.py tests/integration/test_p1_source_bridge.py tests/integration/test_auth.py tests/observability -v
# 前端（在 frontend\ 下）
npm.cmd run build
npx.cmd playwright test --config=playwright.operations.config.ts
npx.cmd playwright test --config=playwright.operations-qa.config.ts
npx.cmd playwright test --config=playwright.operations-assets.config.ts
```

预期基线：operations 69/0/0；P2 最小回归集 0 失败（跳过数如实记录并说明原因）；build 0；T303 26/0、T304 19/1（desktop Q10 设计性 skip）、T305 20/0。testMatch 收窄后 T303 配置不再需要文件名过滤即只跑 overview——验证这一点。若 P2 回归出现失败：先定位是否 P3 改动影响（对照冻结清单），写上报，不修业务代码。

### 3.2 指标复算（同一候选两套数据）

1. **T301 基准复算**：用 `t301_recompute.py` 对 T301 隔离库只读复算，逐项核对 T301 预期：完成 13；六类 8/1/1/1/1/1；中断 2；非冲突持久引用行 13；文档/版本去重对 6/6；待审核 1；生效资料 5；失败导入 1（PARSE_INCOMPLETE）；覆盖率 10/13 partial；S17→2026-11-20、S18→2026-11-21；S05 持久 2 行最终引用 0。输出对照表存证据。
2. **集成种子复算**：种子打印期望值 JSON；用只读 SQL/脚本对集成隔离库复算 overview 各计数与下钻明细（完成量按 finished_at+请求 ID 去重只计 succeeded、引用按结果消息+文档/版本去重排除 conflict、已删除会话双侧排除），断言 overview==明细复算。I1-I3 用例同时断言页面值==种子期望。

### 3.3 三条端到端路径 + 覆盖面（I1-I8，desktop 1440×900 + mobile 390×844）

集成种子最低覆盖：≥2 日问答（answer 带 active 引用、not_found、conflict 两方均 active、service_error）、Trace recorded/not_recorded、1 个失败导入文档（PARSE_INCOMPLETE 类，旧版继续生效）、1 个待审核文档、1 个评测 run（含 holdout 可选）、空窗口数据；构造逻辑可组合 T304/T305 种子。

| # | 用例 | 断言要点 |
| --- | --- | --- |
| I1 | 首页→趋势日期→问答明细 | 总览点趋势某天→/operations/requests 该日窗口，总数==总览该日完成量；打开抽屉核对问题/结果/引用与种子一致 |
| I2 | 结果分布→冲突详情→核对版本 | 总览点 conflict→requests kind=conflict→抽屉两方卡片值/名称/版本与种子一致；两方版本状态均 active（可跳资产页抽屉核对版本号）；引用数 0 |
| I3 | 待处理→导入失败详情→关联问答 | 总览待处理失败项→/operations/documents 带 document_id+state，总数==failed_total；抽屉失败块含 error_code 与「V{n} 失败，V{m} 继续生效」；「查看关联问答」→requests 页 document_id 过滤生效且横幅在位（T304↔T305 实跑串联） |
| I4 | 员工门禁 | employee 三页均门禁文案；直调 overview/requests/documents/详情/evaluation-runs 均 403 |
| I5 | Trace 关闭栈 | 8293/5304 栈上 I1/I2 业务内容可读，阶段区「Trace 已关闭」；主栈 not_recorded 请求显示「本次未记录执行过程」 |
| I6 | 空窗口 | 空窗口下总览计 0 无假百分比、requests/assets 空态、评测空目录不出现 |
| I7 | 移动端 | 390 宽完整走通 I3 一条链（总览→失败详情→关联问答） |
| I8 | 评测摘要 | 批次分母/状态与受控 run 一致；holdout 扣留徽章；无发起入口 |

### 3.4 性能实测（只读，不建索引）

- 脚本放 `T306-evidence\scripts\perf_probe.py`：对集成隔离库与 T301 隔离库（只读连接），在 today/7d/30d 窗口下测 overview/requests/documents 核心查询耗时（各 ≥5 次取中位数与最大值），附样本规模（行数/文档数/窗口）。
- 对核心查询跑 `EXPLAIN QUERY PLAN` 原文存档；发现全表扫描/瓶颈只写评估与建议（是否值得索引、预计收益），**不执行 CREATE INDEX**，留给主人决定。
- 也可用 TestClient 对隔离 app 测 API 端到端耗时（标注口径：进程内/含网络）。

### 3.5 T302 补充单评估（只评估，不改后端）

对照 T303 裁决①与 T305 上报①，基于实测数据回答：①20 页游标上限在当前与可预见规模下是否影响对账；②列表缺 latest_version/name 搜索的两处降级是否值得立 T302 补充单。给出建议与理由，写入交付说明，主人拍板。

### 3.6 启动与回退核对（离线限定）

1. 实读 `tools\start_local.py`、`一键启动.cmd`、`启动-真实问答.cmd`，梳理 04515f3/0d6ba61 引入的 real-first 逻辑与离线回退分支。
2. **安全试跑**：仅当能把数据目录覆盖到隔离目录、且确认走离线/Mock 分支（不触发真实模型/付费）时，试跑一键启动的离线路径，验证能起服务并到达登录/问答页（Mock 替身），记录命令与结果；试跑结束清理自己起的进程。**若无法安全隔离（会写 var\ 或触发真实调用），不跑**，记 NOT-RUN + 静态审查结论与原因。
3. 回退方式只写文档：P2 发布参照 7556efd / 发布记录 cb74457；P3 候选当前为工作区未提交改动，回退=主人批准后按提交方案 revert 或丢弃工作区 P3 改动（列出精确文件清单），**不执行任何回退动作**。

### 3.7 发布候选材料（T306-release-candidate.md）

按任务书 §4 发布条件 4 条逐条对照自证，包含：

1. 候选版本描述：基线 HEAD 0d6ba61 + 工作区 P3 改动清单（按 backend operations / frontend operations / e2e 与配置 / docs 证据分组），**建议的提交拆分方案**（供主人批准后执行，本窗口不提交）。
2. 变更说明（T301-T305 汇总，引用各验收记录链接）。
3. 启动与回退方式（§3.6 结论）。
4. 测试证据总表：开发自测 / 独立验收（引用 T301-T305 验收记录 + 本任务复跑）/ 真实环境验证（NOT-RUN，须主人授权）三列。
5. 受控替身范围（Mock 标注）、测过的环境（Windows/端口/隔离目录）、剩余限制汇总（各任务已知限制 + 本任务新增）、待验证事项。
6. 上报事项与 T302 补充单建议（§3.5）。

## 4. 验收完成条件（对齐任务书 T306 + §4）

1. 后端 operations 69/0/0 + 最小 P2 回归集 0 失败；build 0；三套既有 Playwright 全绿（26/19+1skip/20）；testMatch 收窄生效且轮次 reporter 不覆盖旧证据。
2. I1-I8 双 project 全过；三条端到端路径含管理员/员工/无 Trace/空数据/移动端覆盖；T304↔T305 参数串联实跑通过。
3. T301 基准复算逐项一致 + 集成种子 overview==明细复算；员工 403 实查；旧版引用只给元信息实查。
4. 性能报告含样本规模、耗时统计、查询计划原文；无索引改动。
5. 启动核对有结论（安全试跑或 NOT-RUN+静态审查）；回退方式成文未执行。
6. 发布候选材料齐备（§3.7 六项）；git 零写操作、var\ 未写、业务代码零改动、无新依赖、无付费调用。
7. `T306-delivery.md`：变更清单（含 §2.1 三个配置的精确 diff）、证据表、已知限制、上报事项、边界自查。

## 5. 红线速查

- [ ] 业务代码（backend\src、frontend\src）零改动；只动 §2.1 配置与 §2.2 新增
- [ ] git 无写操作；回退只写文档；在途改动原样保留
- [ ] var\ 未写；T301 隔离库只读；轮次 reporter 只新增不覆盖
- [ ] 无付费调用；启动试跑仅限可隔离的离线分支，否则 NOT-RUN
- [ ] 不建索引、不改口径；回归失败先上报不私修
- [ ] 三列证据分开；真实环境 NOT-RUN；Mock 标注