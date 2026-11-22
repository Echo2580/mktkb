# T301・基线和数据核对 — 项目经理验收记录（定稿）

- 验收依据：`docs/superpowers/plans/2026-11-21-mktkb-p3-operations-taskbook.md`（2026-11-21 复核修订版）T301 小节、§2、§4
- 验收日期：2026-11-21
- 基线：分支 `codex/p2-e2e`，HEAD `0d6ba61d0c6253550adf26888dab935ffe4310b1`（开工与定稿两次实核一致）；P2 v0.3 发布参照候选 `7556efd`，发布记录提交 `cb74457`；发布后 3 提交 `04515f3` / `2d4d839` / `0d6ba61` 已逐一核对改动统计
- **T301 总结论：PASS**（开发自测 PASS；独立验收 PASS；真实环境验证 NOT-RUN——本期标准验收为离线 + 受控替身 Mock，真实环境验证属后续单独授权事项）
- **上报主人裁决事项：D5（冲突消息持久引用行，代码与任务书 §2 口径出入，已实测确认）**，详见第五节；不阻塞 T302（API 约定已按任务书口径冻结，查询侧可实现）

## 一、交付物清单

| 工作包 | 交付物 | 路径（相对 docs/reports/OBS-EVAL/P3/） |
| --- | --- | --- |
| A 审计与口径冻结 | 主审计文档（定稿） | `T301-data-audit.md` |
| A | git 只读证据 / 只读探针及输出 / 表核对脚本 | `T301-audit-git-output.txt`、`T301-audit-probe.py`、`T301-audit-probe-output.txt`、`T301-audit-tables.py` |
| B 隔离样本与复算 | 样本矩阵（19 条） | `T301-isolated/T301-sample-matrix.md` |
| B | 独立复算表 | `T301-isolated/T301-recomputation.md` |
| B | Trace 两态抽查 | `T301-isolated/T301-trace-probe.md` |
| B | 生成/复算/探针/渲染脚本、隔离测试、隔离库与证据 JSON | `T301-isolated/scripts/`、`tests/`、`evidence/` |
| 项目经理独立验收 | 副本复跑证据 | `T301-acceptance-rerun-evidence.txt`（副本目录 `T301-acceptance-rerun/`） |
| 项目经理独立验收 | 自写只读 SQL 核对脚本与输出（26 项） | `T301-acceptance-verify.py`、`T301-acceptance-verify-output.txt` |

## 二、逐项对账（T301 验收清单）

| # | 完成条件 | 开发自测 | 独立验收 | 真实环境验证 | 证据位置 |
|---|----------|----------|----------|--------------|----------|
| 1 | 实际基线记录（HEAD、发布后提交清单、在途改动） | PASS | PASS（PM 两次 git 实核一致） | NOT-RUN（不适用） | 审计 §1；`T301-audit-git-output.txt` |
| 2 | 路由与数据表核对、关联键、无法回溯字段、已知缺项 | PASS | PASS（抽查 D5 引用 service.py:1970-2086、holdout routes.py:861-866、第三路径 contracts.py:36 均属实） | NOT-RUN | 审计 §2、§2.4 |
| 3 | 隔离环境正常入口样本覆盖六场景；罕见状态受控标注 | PASS | PASS（19 条=14 正常入口+1 故障替身缝+4 受控，均标注；副本复跑重新生成仍全过） | NOT-RUN | 样本矩阵 §2-3；复跑证据 |
| 4 | 样本矩阵+独立复算表；四专项独立预期值 | PASS | PASS（PM 自写 SQL 26 项全 PASS：同文档多引用去重 6/6、午夜 S17→11-20/S18→11-21、失败导入 1/PARSE_INCOMPLETE、待审核 1） | NOT-RUN | 复算表 §2-8；`T301-acceptance-verify-output.txt` |
| 5 | 每个首版指标有来源/时间字段/去重键/过滤条件/空值语义 | PASS | PASS（12 项指标逐行齐备，含空分母「无样本」语义） | NOT-RUN | 审计 §3 |
| 6 | Trace 两态抽查、请求-Trace 关联、重放标记、可用阶段、旧版引用字段 | PASS | PASS（启用 12 条 Trace 关联键全命中；关闭态 S15 无 Trace 行无 X-Trace-ID；重放 replayed=1/status=replayed/Span 0；旧版 v1 字段可展示；PM SQL 复核一致） | NOT-RUN | Trace 抽查 §2-6；审计 §2.3/4.7/4.8 |
| 7 | 冻结 RAG 与 legacy 两套 Span→阶段映射与缺失语义 | PASS | PASS（代码埋点+契约必需表+reason 降级集冻结；B 实测三路径 Span 全落映射内，无冲突；条件 Span index_sync/query_expansion 未触发、缺失语义已冻结） | NOT-RUN | 审计 §4（含对账结论） |
| 8 | 评测批次白名单（含 holdout 只读聚合与详情扣留）写入 API 约定 | PASS | PASS（判定字段、holdout 扣留、空批次空列表+状态、P3 不发起评测、有引用占比≠业务正确率均成文；代码引用抽查属实） | NOT-RUN | 审计 §5 |
| 9 | 已删除会话与冲突来源口径写入 API 状态约定 | PASS | PASS（双侧排除经 S10 样本+PM SQL 验证；冲突口径按任务书冻结，D5 差异如实标注上报） | NOT-RUN | 审计 §6.2/6.3 |

## 三、口径红线对账（T301 冻结，后续不得私改）

| 红线 | 审计落点 | 样本/复算验证 | 结论 |
|------|----------|----------------|------|
| 问答量按完成时间+请求 ID 去重、只计已提交；重放不增量；已删除会话双侧排除 | §3#1-3、§6.2 | 13 完成（重放复用同请求行）、S10 双侧排除、中断 2 单列 | PASS |
| 最终引用按结果消息+文档/版本去重；冲突来源取结果 JSON conflicts、相关问答含冲突单独标注、最终引用不含冲突 | §3#8-9、§6.3 | 非冲突行 13、去重对 6/6；冲突行 2 实测存在但按口径剔除（D5 上报） | PASS（口径冻结；D5 待裁决） |
| 只渲染实际记录阶段；Trace 关闭/不可用/未记录/部分覆盖独立状态 | §4、§6.4 | 三路径实测 Span 全落映射；disabled/untracked 独立计数；未记录≠0ms | PASS |
| 评测批次白名单；P3 不发起评测；有引用占比≠业务正确率 | §5.2、§3#11 | 规则成文并经代码抽查；现存 8 个 run 目录只读清单 | PASS |
| Asia/Shanghai 聚合、日历日左闭右开 UTC 窗口 | §6.1 | 午夜边界 S17/S18 归属正确（PM SQL 独立复核） | PASS |
| 运营仅 admin；归属校验与旧版引用/原件规则不变；证据无密钥/原始请求头/Trace 原始属性 | §2.2、§6.6 | 文档与证据仅含关联键/计数/Span 名/时长；隔离测试凭据为测试固定值，非生产密钥 | PASS |

## 四、验证证据登记

后端命令规范：`backend/` 目录下 `..\.venv\Scripts\python.exe -B -m pytest` 接具体测试路径（配置在 backend/pyproject.toml，副本复跑加 `-c pyproject.toml` 强制指定）。

| 执行方 | 命令 | 测试路径 | 退出码 | 通过/失败/跳过 | 证据文件 |
|--------|------|----------|--------|----------------|----------|
| 开发 B（自测） | `..\.venv\Scripts\python.exe -B -m pytest -c pyproject.toml "../docs/reports/OBS-EVAL/P3/T301-isolated/tests/test_t301_isolated.py" -v` | T301-isolated/tests/test_t301_isolated.py | 0 | 1/0/0 | `T301-isolated/evidence/pytest/t301-pytest-run.txt` |
| 项目经理（独立复跑，副本） | 同上，路径换 `T301-acceptance-rerun/tests/test_t301_isolated.py` | T301-acceptance-rerun/tests/test_t301_isolated.py | 0 | 1/0/0 | `T301-acceptance-rerun-evidence.txt` |
| 项目经理（独立 SQL 核对） | `.venv\Scripts\python.exe -B T301-acceptance-verify.py`（只读 mode=ro，自写 SQL，不复用 B 脚本） | 对 B 交付隔离库 26 项 | 0 | 26 PASS/0 FAIL | `T301-acceptance-verify-output.txt` |

独立复跑在副本目录进行（生成脚本每次重建隔离库并覆盖证据 JSON，为保护 B 交付原件与文档中关联键的一致性，不在原目录重跑）。复跑断言覆盖：15 样本结果类型、受控标注、复算一致性、六类分布、午夜归属、删除排除、引用去重与冲突剔除、覆盖率 10/13 与状态分布、三路径 Span、重放配对、关闭态、旧版引用字段。

## 五、上报主人裁决事项与已知限制

### D5（需主人裁决，不阻塞 T302）

- **事实**：任务书 §2 规定「冲突消息不产生持久引用行」；实际代码（`conversations/service.py:1970-1979` 冲突来源并入 `_reference_ids`、`2036-2038` 清空分支未覆盖 conflict、`2066-2086` active 来源写 `MessageSource`）会为冲突消息落持久引用行。隔离样本 S05（正常入口、两方来源均 active）实测落 2 行，项目经理独立 SQL 复核一致。
- **处置**：未改代码、未改任务书。API 约定按任务书口径冻结：「最终引用」计数排除 `kind='conflict'` 消息，冲突两方来源以 `result_json.conflicts` 为准，相关问答含冲突并单独标注。T302 查询侧按 kind 过滤即可满足口径，无需改提交链路。
- **请主人裁决**：是否另行安排提交链路代码修复（属 P3 只读范围外）；或确认以查询侧排除为 P3 正式口径并在任务书后续修订中补记数据行为差异。

### 其他差异与缺口（已记录，按任务书流程处置）

- D1/D2：代码实际 Span 超出任务书列举（RAG 多 exact/lexical/vector_recall、embedding_query、hard_filter、rerank、fact_validate；legacy 多 entity_conflict_check、query_expansion、model_failure）——主阶段标签只映射业务必需 Span，子 Span 作可展开细节，不改任务书。
- D3：第三路径值 `legacy_with_rag_candidates` 按 legacy 变体共用映射（契约与实测一致）。
- D4：Trace outcome 枚举为业务六类超集（no_answer/ambiguous/error）；六类分布以业务消息 kind 为准，两套枚举不混用。
- G1：本地快照缺口已由隔离矩阵闭环；仅重试 attempt>1 场景仍无样本，待真实流量补充。
- G2/G3：评测批次列表接口、冲突来源聚合查询属 T302/T305 实现范围。
- G4：启动路径变更（04515f3、0d6ba61 之一键启动脚本与 tools/start_local.py）纳入 T306 启动/回退与 P2 回归核对。

### 已知限制

- 午夜边界为受控固定时间样本，未等待真实墙钟跨日；knowledge_changed 经故障替身缝注入触发（HTTP 与提交链路仍走正常代码）。
- 「部分覆盖 / Trace 读取失败」状态本次未观测到样本，判定依据按代码冻结（审计 §4.7）。
- 现存评测制品无 holdout 批次，holdout 扣留规则按代码冻结，待后续批次落地实测对账。
- 重放链路 `previous_trace_id` 实测为 null（未回填），串联依赖同一产品请求 ID；该链仅适用重试场景（审计已更正）。
- 隔离替身环境 Span 时长不代表线上性能；覆盖率、查询性能待 T302/T306 实测。
- 全程离线 + 受控替身（Mock），无真实模型/OCR/Ragas 付费调用。

## 六、边界遵守核查（定稿时实测）

- [x] 仅新增 `docs/reports/OBS-EVAL/P3/**`；git status 与开工快照逐条一致，未改任何现有文件
- [x] 在途改动（`.claude/handoffs/_index.md` +91、`P2/T207-QUALITY-REPAIR/manager.md` +72）与未跟踪 P2 证据原样保留
- [x] 未写 `var/` 业务库与 Trace 库数据：两主库文件与 WAL 修改时间均早于 T301 开工（业务库 2026-11-21 16:42、Trace 库 2026-11-05）；A 的只读探针（mode=ro、仅 SELECT）触碰了 `-shm` 共享内存侧文件（23:33，SQLite WAL 只读连接的运行时副作用），无数据写入，如实记录
- [x] 隔离库、样本、复算全部在 `T301-isolated/`（及验收副本 `T301-acceptance-rerun/`）内
- [x] git 仅只读命令；未安装 echarts、未生成 OpenAPI 类型（属后续任务）
- [x] 证据不含生产密钥、原始请求头、Trace 原始属性（隔离测试凭据为测试固定值）

## 七、结论

- 开发自测：**PASS**（B pytest 退出码 0，1/0/0；A 审计证据齐备）
- 独立验收：**PASS**（PM 副本复跑退出码 0，1/0/0；自写只读 SQL 26/26 PASS；代码引用抽查属实；边界核查全过）
- 真实环境验证：**NOT-RUN**（T301 标准验收为离线+Mock；真实环境验证按任务书属后续单独授权事项）
- **T301 总结论：PASS**。口径已冻结（审计 §3-6），D5 上报主人裁决（不阻塞 T302）。按依赖纪律，下一单为 T302 只读运营接口和权限，待主人知悉 D5 后派发。