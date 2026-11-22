# T302・只读运营接口和权限 — 项目经理验收记录

- 验收依据：`docs/superpowers/plans/2026-11-21-mktkb-p3-operations-taskbook.md` T302 小节、§2、§4；派单 `T302-dispatch.md` §7 完成条件
- 验收日期：2026-11-22
- 交付方：开发窗口（用户执行）；交付说明 `T302-evidence/T302-delivery.md`
- **T302 总结论：PASS**（开发自测 PASS；独立验收 PASS；真实环境验证 NOT-RUN——本期标准验收为离线 + 受控替身 Mock，真实环境验证属后续单独授权事项）

## 一、逐项对账（派单 §7 完成条件）

| # | 完成条件 | 开发自测 | 独立验收 | 真实环境验证 | 证据 |
|---|----------|----------|----------|--------------|------|
| 1 | §5 测试清单全覆盖且通过 | PASS（69/0/0，退出码 0） | PASS（PM 复跑 69/0/0，退出码 0；49 个测试函数 + 参数化逐条映射 C1-C7、S1-S7、T-a~d、E-a~e、对账 5 项，无缺项） | NOT-RUN | `pytest-operations.txt`；PM 复跑 `T302-acceptance-rerun-operations.txt` |
| 2 | T301 样本逐项对账一致，统计=下钻 | PASS（对账表 14 项全一致，预期值未改） | PASS（对账测试含于 69 条复跑；对账表抽查：13 完成、8/1/1/1/1/1、中断 2 单列、非冲突行 13（原始 14 含 S10 删除会话 1 行，口径一致）、去重 6/6、待审核 1、失败导入 1/PARSE_INCOMPLETE、覆盖率 10/13 partial、午夜 S17→11-20/S18→11-21、S05 冲突 2 行不计最终引用且 conflict_flag=true） | NOT-RUN | `T302-reconciliation.md`、`test_reconciliation.py` |
| 3 | 员工越权被拒；不泄露断言通过 | PASS | PASS（代码抽查：6 端点均挂 `Depends(require_role("admin"))`（routes.py:305/410/569/723/808/927）；S1/S2 参数化 401/403；S6 白名单断言、只读字节级断言在复跑中通过） | NOT-RUN | `test_permissions.py`、routes.py |
| 4 | 定向回归退出码 0 | PASS（386/0/0） | PASS（PM 复跑 tests/observability + tests/integration/test_auth.py：386/0/0，退出码 0，用时 116s） | NOT-RUN | `pytest-regression.txt`；PM 复跑 `T302-acceptance-rerun-regression.txt` |
| 5 | OpenAPI 6 条新路径仅 GET；schema.d.ts 由产物生成；build 通过 | PASS | PASS（PM 解析 openapi.json：6 条 /api/v1/operations 路径全部仅 get；PM 复跑 npm.cmd run build 退出码 0，产物 index-CbApAQdQ.js 与开发一致，tsc 含于 build） | NOT-RUN | `api/openapi.json`；PM 复跑 `T302-acceptance-rerun-build.txt` |
| 6 | 边界核查 | PASS（自查清单齐备） | PASS（PM 实核 git status/diff：已跟踪改动仅 main.py（+2 行，diff 与派单允许完全一致）与 schema.d.ts（生成物）；新增仅 operations 包、tests/operations、P3 报告目录；在途改动 +91/+72 原样保留；var\mktkb.sqlite3 及 WAL 2026-11-21 16:42、Trace 库 2026-11-05，均早于 T302 开工，未被写） | NOT-RUN | PM git 实核输出（本记录第二节）；`git-status-start/end.txt` |
| 7 | 交付说明齐备 | PASS（变更清单、证据表、对账、契约登记 18 项、已知限制、上报事项、边界自查 7 节齐备） | PASS | — | `T302-delivery.md` |

## 二、独立验收执行记录（PM 实测）

| 动作 | 命令/方式 | 工作目录 | 退出码 | 结果 | 证据文件（P3/ 下） |
|------|-----------|----------|--------|------|--------------------|
| 复跑本任务测试 | `..\.venv\Scripts\python.exe -B -m pytest tests/operations -q` | backend\ | 0 | 69 通过/0 失败/0 跳过（45.5s） | `T302-acceptance-rerun-operations.txt` |
| 复跑定向回归 | `..\.venv\Scripts\python.exe -B -m pytest tests/observability tests/integration/test_auth.py -q` | backend\ | 0 | 386 通过/0 失败/0 跳过（116.4s） | `T302-acceptance-rerun-regression.txt` |
| 复跑前端构建 | `npm.cmd run build` | frontend\ | 0 | tsc + vite 构建成功，产物哈希与开发一致 | `T302-acceptance-rerun-build.txt` |
| OpenAPI 核对 | ConvertFrom-Json 解析 paths | — | 0 | 6 条 operations 路径全部仅 GET | 本记录 |
| 边界实核 | git status/diff、var\ 时间戳 | 仓库根 | 0 | 仅允许文件改动；var\ 未写 | 本记录 |
| 代码红线抽查 | 读 operations 包 + grep | — | — | admin 依赖 6/6；冲突 citation_count=0、citations 空、来源走 result_json.conflicts；deleted_at 双侧过滤；schemas/routes 明示禁 *_json/stored_path/lease_* | routes.py、queries.py、schemas.py |

## 三、实现决定与偏差处置（交付说明 §4 十八项审查）

- **全部接受**，均与 T301 冻结口径一致或属合理细化，要点：
  - 覆盖率空分母返回 `not_recorded` + 空样本 note，未新增枚举（符合 §6.5 空值语义）。
  - `requests/{id}` 允许读取未完成请求（中断单列的下钻需要），已删除会话/非法 ID 仍 404。
  - `documents.current_version` 无生效版本时取最新版本、按最新版本过滤——与「待审核/失败资料可见」的任务目标一致。
  - 时区 zoneinfo 优先、缺 tzdata 回退固定 UTC+8（中国无夏令时，结果等价），对外恒标 Asia/Shanghai。
  - 失败 message 保守脱敏（含路径/堆栈字样只回 error_code），宁少勿泄，接受。
- **派单 §6 示例导出命令偏差**：Settings 缺必填密码导致示例命令不可用，开发改用仓库既有 `tools/export_openapi.py`（隔离 .env、initialize=False），产物有效，**接受并记录**（派单编制责任在 PM，后续派单修正）。
- E-f（真实 var\eval\runs 只读清点）为可选项未执行，不阻塞；T306 独立验收时补。
- 未加索引，按派单留 T306 实测查询计划后定。

## 四、口径红线对账

| 红线 | 结论 | 依据 |
|------|------|------|
| 完成时间+请求 ID 去重、只计 succeeded、中断单列、已删除会话双侧排除 | PASS | queries.py:303/386；对账 13/2/S10 |
| 最终引用消息+文档/版本去重、排除 conflict；相关问答含冲突且标注（D5 裁决口径） | PASS | queries.py:211/215、routes.py:614-615；对账 6/6、S05 |
| Trace 独立状态、读失败不报覆盖率、纯重放不计、只回实际 Span | PASS | test_trace_states.py 7 条全过 |
| 评测白名单、holdout 扣留、空列表+状态、不发起评测 | PASS | test_evaluation_runs.py 6 条全过 |
| Asia/Shanghai、左闭右开、90 天上限 | PASS | test_windows.py；午夜对账 |
| 仅 admin、归属校验不变、无密钥/原始请求头/Trace 原始属性 | PASS | 权限测试 + S6 白名单断言 + 定向回归 386 过 |
| 无付费调用、var\ 未写、git 无写操作 | PASS | 交付自查 + PM 时间戳/git 实核 |

## 五、已知限制（随候选进入 T306）

1. 窗口聚合为内存计算，大数据量性能未测，索引待 T306 查询计划实测。
2. E-f 真实评测目录清点未执行（可选项）。
3. 脱敏启发式可能误伤含斜杠的正常失败文案（保守方向，可接受）。
4. schema.d.ts 与 T08 旧快照存在生成性结构/排序差异，历史证据保留未动。
5. 全程 Mock（EvidenceEchoGateway），Span 时长与覆盖率不代表线上；真实环境验证 NOT-RUN。
6. 前端页面未做（T303-T305 范围），三条端到端路径 T306 复验。

## 六、结论与下一步

- 开发自测：**PASS**；独立验收：**PASS**；真实环境验证：**NOT-RUN**（按任务书属后续单独授权）。
- **T302 总结论：PASS**。按依赖纪律解除 T303 阻塞；T303 派单待主人示意后发出（开发仍由开发窗口执行）。