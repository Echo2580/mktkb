# R2-203C HTTP 见证矩阵（案例 × 断言 × 结果）

图例：✅ 成立（断言通过）｜🔴 红态实测（关闭修复后转红，断言消息留档）｜➖ 不适用｜🟡 观测但不断言

- 环境：`backend/`，`.venv\Scripts\python.exe -X utf8`，basetemp `D:\mktkb-p2-h2v3-r2-20261117\basetemp-203c\`
- 业务日：2026-11-20（`Settings.rag_business_date` 显式钉住；宿主当日 2026-11-17）
- 全部用例：`t09_network_guard` 显式请求 + 末尾断言 `external == []`；F1 另有 `no_subprocess` 计数 0
- 命令与退出码：见 `R2-203C-REPORT.md` §1（C-1…C-6 全部 `EXIT=0`；新增 21 passed / 既有 40 passed）

## A. F1 — C29「物品级 + 店家级同问」（HTTP 主例）

| 案例 | `kind` | 正文两值 | `sources` 恰 2 条 = 2 份文档 | 版本约束（active/version_number/published_at/header_row） | 门店行约束（店家表 row=5 青禾店，非 row=4 白鹭店） | 事实两角色 + 版本绑定 | 触发条件（record/enumerate/filters/field_roles） | 模型调用 | 结果 |
|---|---|---|---|---|---|---|---|---|---|
| F1-A `折叠桌的位置在哪里，合作状态分别是什么？` | answer | ✅ 甲区1号架 + 合作中 | ✅ `{物品位置台账, 合作店家信息}` | ✅ 1 / 1 / 非空 / 3,3 | ✅ row 4（物品）+ **row 5**（店家） | ✅ location+status，各绑自己版本 | ✅ record / true / `["item"]` / `{location,status}` | 0 | **PASS** |
| F1-B `青禾店的折叠桌放在哪个位置，合作状态分别是什么？` | answer | ✅ 同上 | ✅ 同上 | ✅ 同上 | ✅ 同上 | ✅ 同上 | ✅ `["item","store"]` | 0 | **PASS** |
| F1-A（关 `_store_join_chunks`） | answer | 🔴 只有位置值 | 🔴 恰 1 条（`物品位置台账.xlsx`） | ➖ | ➖ | 🔴 只有 location | ✅ | 0 | **红态成立** |
| F1-B（关 `_store_join_chunks`） | answer | 🔴 只有位置值 | 🔴 恰 1 条 | ➖ | ➖ | ➖ | ✅ | 0 | **红态成立** |
| F1-A（恢复后） | answer | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 0 | **PASS** |
| legacy `青禾店的折叠桌放在哪个位置，合作状态如何？` | answer | ✅ 两值 | ✅ 2 份文档 | ➖ | ➖ | 🟡 证据两列各一份 | ➖（legacy 面） | 1 | **PASS** |
| legacy（关 `retrieval.service._store_join_ids`） | 🔴 `service_error`（`MODEL_OUTPUT_INVALID`） | 🔴 无合作中 | 🔴 0 条 | ➖ | ➖ | 🔴 证据只剩物品行 | ➖ | 1 | **红态成立** |
| F1-A（同一 R0 开关下） | answer | ✅ 两值 | ✅ 2 份文档 | ✅ | ✅ | ✅ | ✅ | 0 | **PASS**（两修复互不吞并） |
| 零出站总账（三问法） | — | — | — | — | — | — | — | — | **PASS**（`external==[]`、子进程 0） |

红态断言消息（原文）：
- 关 join：`assert '合作中' in '共 1 条，当前第 1 页显示 1 条。\n- 青禾店的折叠桌：位置 甲区1号架（来源：物品位置台账.xlsx）\n已显示全部。'`
- 关 legacy：`assert '合作中' in ('模型输出未通过来源与字段校验，已拒绝本次回答。…')`

## B. F2 — C25 同形实体身份（HTTP + 捕获 + 分类）

| 案例 | HTTP 200 / kind | `facts[].entity_key` | `db_projection.units[...].entity_key` | 逐字节相等 | `p2_hard_evidence` | `p2_evidence_rescore_axes` | 结果 |
|---|---|---|---|---|---|---|---|
| 正例 `青禾店的云纹托盘（编号 Q01）位置分别是什么？` | 200 / answer | `item\|id:q01` | `item\|id:q01` | ✅ UTF-8 相等 | `passed` / `frozen_targets_match_ok` | `passed` / `frozen_targets_match_ok` | **PASS** |
| 敏感性（`rag/chunking._entity` 还原旧名称复合键） | 200 / answer | 🔴 `item\|青禾店\|云纹托盘` | `item\|id:q01` | 🔴 不等 | 🔴 `unknown` / `entity_identity_unresolved` | 🔴 `unknown` / `entity_identity_unresolved` | **红态成立** |
| 恢复后 | 200 / answer | `item\|id:q01` | `item\|id:q01` | ✅ | `passed` / `frozen_targets_match_ok` | 同上 | **PASS** |
| 相邻安全反例 `云岫店的云纹托盘（编号 Q03）…`（目标仍 Q01） | 200 / answer（正文 `丙区3号架`） | `item\|id:q03` | `item\|id:q03`（本回合投影） | ✅（但 ≠ 目标） | `violation` / `other_entity_used` | `violation` / `other_entity_used` | **PASS（必须拒）** |

红态断言消息（原文）：`assert ('unknown','entity_identity_unresolved') == ('passed','frozen_targets_match_ok')  At index 0 diff: 'unknown' != 'passed'`

## C. F3 — C14 两回合继承 + 业务日闭区间（HTTP）

| 案例 | 回合 | 继承（正文/sources 同目标） | `revision` == 发送前 revision | 捕获 `pre_revision` / `commit_before,after` / `capture_revision` | `as_of` | 结果 |
|---|---|---|---|---|---|---|
| 两回合 `青禾店的折叠桌放在哪个位置？` → `位置分别是什么？` | 1 | ✅ 甲区1号架 / `[物品位置台账]` | ✅ 2 == 2 | ➖（本用例走 TestClient） | ✅ 2026-11-20 | **PASS** |
| 同上 | 2 | ✅ 正文仍甲区1号架、`sources` 与回合 1 **逐字段相同**；`filters=["item","store"]`、`state.store=青禾店`、`state.item=折叠桌` | ✅ 2 == 2（未被提问推高） | ➖ | ✅ 2026-11-20 | **PASS** |
| 捕获面（同一产品，两回合各一份 envelope） | 1 | — | ✅ `result_revision=2` | ✅ `2 / 2,2 / 2` | ✅ `as_of=state_as_of=2026-11-20` | **PASS** |
| 捕获面 | 2 | ✅ `mode=record`、`filters=["item","store"]` | ✅ 同上 | ✅ 同上 | ✅ 同上 | **PASS** |

业务日闭区间（载体行 生效 2026-11-20 / 失效 2026-11-21，问 `青禾店的合作状态是什么？`）：

| 业务日 | `plan.as_of` | `kind` | `sources` | 含 `合作中` | 结果 |
|---|---|---|---|---|---|
| 2026-11-19 | 2026-11-19 | 🔴 `not_found` | 🔴 `[]` | 🔴 否 | **红态成立** |
| 2026-11-20 | 2026-11-20 | `answer` | `[合作店家信息.xlsx]` | ✅ | **PASS（闭区间左端）** |
| 2026-11-21 | 2026-11-21 | `answer` | `[合作店家信息.xlsx]` | ✅ | **PASS（闭区间右端）** |
| 2026-11-22 | 2026-11-22 | 🔴 `not_found` | 🔴 `[]` | 🔴 否 | **红态成立** |
| `None`（不钉业务日） | `null` | `answer` | `[合作店家信息.xlsx]` | ✅ | **PASS（不取宿主时钟的对照）** |

红态断言消息（原文，2026-11-19 / 2026-11-22 同一句）：
`assert '合作中' in '资料中未记录：合作状态；记录缺失不等于服务异常，请核对字段名称或改问其它字段。'`

## D. F4 — R2 集合恒等式（离线，只读公开件）

| 断言 | 观测值 | 结果 |
|---|---|---|
| `schema_version` | `p2-hard-evidence-caseplan-live/v0.1` | ✅ |
| `fixture_kind` / `execution_mode` | `live_h2` / `live` | ✅ |
| 业务日 `run_binding.business_date` | `2026-11-20` | ✅ |
| case 集合（恰好 5 题） | `{H2V3-C08, C14, C19, C25, C29}`（短 id `{C08,C14,C19,C25,C29}`），无重复 | ✅ |
| 回合总数 | 6（`turn_index` = 0..5 连续唯一；证据文件互不重名） | ✅ |
| C14 回合数 | 2 | ✅ |
| 逐题回合数 | `C08=1, C14=2, C19=1, C25=1, C29=1` | ✅ |
| 公开校验器（未变异） | 接受，`case_ids`/`turn_counts` 与冻结期望一致 | ✅ |

变异负例（同一公开校验器 `_validate_case_plan_document`）：

| 变异 | 变异后 case_ids | 期望 | 实测 | 结果 |
|---|---|---|---|---|
| 多一题 | `C08,C14,C19,C25,C29,C30` | 拒绝 | `EntryError: case_plan_coverage_invalid` | ✅ 检出 |
| 少一题 | `C08,C14,C19,C25` | 拒绝 | 同上 | ✅ 检出 |
| 重复题 | `C08,C08,C19,C25,C29` | 拒绝 | 同上 | ✅ 检出 |
| 换题 | `C99,C14,C19,C25,C29` | 拒绝 | 同上 | ✅ 检出 |

## E. 敏感性对照总表（四条，逐条红态实测）

| # | 对照 | 开关 | 绿 → 红 的表现 | 红态证据 | 恢复后 |
|---|---|---|---|---|---|
| ① | C29 RAG 联结 | 运行时 `monkeypatch` 关 `rag.retrieval._store_join_chunks` | 2 来源 → **1 来源**；店家级值消失（A、B 两问法同时） | `WITNESS f1-sensitivity-join-off-red` + `f1-red-assertion-message-join-off` | ✅ 回绿 |
| ② | C29 legacy 联结 | `monkeypatch` 关 `retrieval.service._store_join_ids` | `answer`（2 来源/两值）→ **`service_error`（0 来源/证据只剩物品行）**；同开关下 F1-A 仍绿 | `WITNESS f1-sensitivity-legacy-off-red` + `f1-red-assertion-message-legacy-off` | ✅ 回绿 |
| ③ | R0 键派生 | `monkeypatch` 还原 `rag/chunking._entity` 为名称复合键 | `passed/frozen_targets_match_ok` → **`unknown/entity_identity_unresolved`**（两侧键不再逐字节相等） | `WITNESS f2-2-sensitivity-legacy-red` + `f2-red-assertion-message-legacy-entity` | ✅ 回绿 |
| ④ | 业务日边界 | 业务日 2026-11-19 / 2026-11-22（区间外一天）vs 11-20 / 11-21（闭区间两端） | 可见（answer + 店家表来源）→ **不可见（not_found + 0 来源）**；`rag_business_date=None` 对照仍可见 | `WITNESS f3-3-boundary` / `f3-red-assertion-message-boundary` | ✅ 相邻日回绿 |

## F. 出站守卫

| 项 | 覆盖 | 实测 |
|---|---|---|
| `t09_network_guard`（既有夹具） | 21/21 新用例显式请求 | `snapshot()["external"] == []` 全部成立 |
| 子进程封禁 + 计数（`no_subprocess`） | F1 全部 5 例（`subprocess.Popen`/`run` 封死并计数） | `calls == []` |
| 模型出站 | F1/F3 用 `EvidenceEchoGateway`（进程内）；F2 用 `MockChatBackend`（`httpx.MockTransport`） | 无真实出站 |
| F4 工具装载 | 仅 `exec_module` + 调用校验函数（不启动进程、不读密钥、不连网） | `external == []` |
