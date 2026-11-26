# R2-REGRESSION：T-R2-203 组合回归 + HTTP 贯通 + 敏感性对照

日期：2026-11-17。范围：R2 修后候选版本（含 T-R2-202C 的 9 hunk）。
cwd = `backend/`；`..\ .venv\Scripts\python.exe -X utf8 -m pytest … -q -p no:cacheprovider --basetemp=<仓库外>`。
开发侧（203A/203B/203C 三个独立执行者）与经理独立复跑分别记录。

## 1. 结论

| 项 | 结果 |
|---|---|
| 组合回归（203B，23 节点） | **789 passed / 3 failed / 0 error**；三红均为既有失败（§4），**无节点因本批转红** |
| 分页/结构数字专项（203A，11 节点） | **87 passed / 0 failed**；`total 1→2` 的新数字在 **P2 口径**下有出处，但**该结论有条件**：`pagination` 与页头同生同灭（页头只在 `answer.py:917` 产生且同函数下发 `pagination`），一旦 `pagination` 缺失，同样文本仍判 fail（`extra={"1","2"}`，独立验收已复现）⇒ 不得表述为"无条件有出处" |
| HTTP 正式链路（203C，4 文件 21 例） | **21 passed**；C29/C25/C14 三条链路全部走 上传→解析/索引→发布→`POST /messages` |
| 敏感性对照（4 类） | **4/4 成立**（关掉修复即回红，恢复即回绿） |
| 出站 / 子进程守卫 | 所有运行 `external == []`；F1 全部 5 例 `subprocess` 计数 `== []` |
| 经理独立复跑 | 203C 21 passed（exit 0）、202A+202B+202C+R0 join 40 passed（exit 0）、202A+202B 20 passed（exit 0） |

## 2. 节点总表（203B，命令见其报告 §1）

| # | 范围 | 结果 |
|---|---|---|
| N01–N03 | 本包：202A 机制 13 / 202C 联结 13 / 202B 身份 7 | 33 passed |
| N04–N06 | 判定链：`test_r0_repair_same_round_inputs` 48 / `test_p2_evidence_rescore` 20 / `…_axes` 22 | 90 passed |
| N07 | matcher 相关：全树 grep 无独立文件，并入 N04–N06 | — |
| N08 | v0.6 `test_r1_108_compat_v06` | 26 passed |
| N09 | 继承链（refusal_compat + c16_empty_scope + v05_projection_mirror + p2_empty_scope_proof） | 215 passed |
| N10 | 结构数字 102a 9 / 分页 102d 8 | 17 passed |
| N11 | C12 跨表/contact（6 文件，含 c12b_t7_e2e、c12_join、text_face_recall） | 40 passed |
| N12 | 106b 多门店主目标 + 106a legacy 范围 | 12 passed |
| N13–N14 | 102c 凭据拒答 7 / 102b 唯一门店追问 6 | 13 passed |
| N15 | 拒答/安全面（p1_refusal×2、r1_103_scope_and_refusal、v3_safety_fix×2、t207_security_precedence、t207_v8_safety_contract） | 64 passed |
| N16–N17 | 业务日期过滤 6 / stale 版本状态 49 | 55 passed |
| N18 | 实体（entity_key_parity、retrieval、chunking、conversations、query_state） | 77 passed |
| N19 | 捕获/评分（capture_entity_readiness_e2e 4、cross_entity_scope_v02 37、axes_adapter_v2 49、eval_tool_repair 22） | 112 passed |
| N20 | 追加：r1_103_http_structural_numbers、r1_107_http_c13_c22、r1_107_http_c22_leak_shape | 8 passed |

203A 另跑：102d 8、102a 9、103 HTTP 结构 3、103 HTTP 范围/拒答 3、104 评分探针 9、104 范围探针 10、202C 13、202A 13、
`tests/rag/test_r2_regressions.py` 6、自建探针 7+6 ⇒ **87 passed / 0 failed**。

## 3. HTTP 正式链路见证（203C）

链路：multipart 上传 → `run_one_job`（解析/建索引）→ publish（带 `expected_revision`）→ `POST /api/v1/conversations/{id}/messages`；`prepare/answer` 仅作补充证据。

| 见证 | 用例 | 关键断言（不只 200/kind） | 红态（关掉修复） |
|---|---|---|---|
| **F1a/F1b** C29 路径 | `test_f1a_http_enumerate_turn_joins_store_level_value`、`test_f1b_…_named_store_turn…` | 正文同时含位置值与店家级值；`sources` **恰 2 条、两份不同文档**；`status=active`、`version_number`==发布回执、`published_at` 非空、`locator.header_row`；**店家行 `locator.row` 指向被问门店行（同表另一行属于另店）**；事实两角色各绑自己版本；触发条件 `record/enumerate/filters=[item]|[item,store]/field_roles={location,status}`；模型 0 调用 | 关 `rag.retrieval._store_join_chunks` → `sources` 只剩物品文档 1 条、正文无店家级值（A/B 同时），恢复回绿 |
| **F1 legacy 见证** | `test_f1_legacy_join_is_witnessed_and_independently_falsifiable` | legacy 形态绿（2 值/2 来源） | 关 `retrieval.service._store_join_ids` → `service_error MODEL_OUTPUT_INVALID`、0 来源、证据只剩物品行；**同开关下 F1a 仍绿** ⇒ 两修复互不吞并 |
| **F2** C25 身份 | `test_f2_same_shape_keys_byte_equal_and_cross_entity_passes` | `facts[0].entity_key` 与 `db_projection.units[fact.source_unit_id].entity_key` **UTF-8 逐字节相等**；两公开入口均 `("passed","frozen_targets_match_ok")` | 还原 `rag/chunking._entity` 旧名称复合键 → 键不等、两入口 `("unknown","entity_identity_unresolved")`，恢复回绿 |
| **F2 相邻安全反例** | `test_f2_adjacent_other_entity_still_violates_over_http` | 问另一店另一实体 → 仍 `violation/other_entity_used`（不得因本批转 passed） | — |
| **F3** C14 两回合 | `test_f3_two_turn_inheritance_and_revision_over_http`、`…_capture_as_of_and_pre_revision`、`…_business_date_closed_interval_boundary`、`…_no_host_clock_control_without_business_date` | T2 裸追问仍同目标、`sources` 与 T1 **逐字段相同**、`as_of==2026-11-20`；`result_revision==pre_revision==commit.revision_before/after==capture_revision`；日期闭区间 11-19/11-22 红、11-20/11-21 绿；`rag_business_date=None` 时 `as_of=null` 且行可见 ⇒ **不取宿主时钟** | — |
| **F4** 集合恒等式 | `test_f4_r2_case_plan_identity_over_public_artifact`、`…_public_validator_accepts_unmutated_case_plan`、`…_case_set_mutations_are_all_rejected` | 集合恰 `{C08,C14,C19,C25,C29}`、回合 6、`turn_index=0..5` 连续唯一、C14 恰 2、业务日 2026-11-20；未变异件通过**同一公开校验器**；多一题/少一题/重复/换题 4 变异全部 `EntryError: case_plan_coverage_invalid` | — |

## 4. 既有失败甄别（关键更正）

| 失败 | 改后（含 202C） | 关掉 202C（pre-202C 沙箱） | `git archive HEAD` 源码 | 判定 |
|---|---|---|---|---|
| `rag/test_s4_stage_limit.py` | 7p/**1f**（`assert 40 == 20.0`） | 同值 | **同值红** | **HEAD 既有**，非本批 |
| `unit/test_s2h_r3_official_profile.py` | 13p/**1f**（预算下限 40 vs 20） | 同值 | **同值红** | **HEAD 既有**，非本批 |
| `integration/test_s2b_intent_semantics.py` | 7p/**1f**（`'conflict' == 'clarification'`） | **同值** | **8p/0f 绿** | **不是 HEAD 既有**；由**其它未提交 src 批次**耦合引入，非 202C（pre-202C 同值）、亦非 R1 102b/c（R1 已证关闭后仍红） |

> **材料更正（写入本包，供经理收口）**：R1 收口件 `FINAL-REPORT.md:41` 与 `R1-REGRESSION-R2.md:62-67` 曾表述"3 条既有失败均已用 HEAD 源码对照证明非本批引入"。
> 本批复现任务书 §7 的警告：**s2b 在 HEAD 上是绿的**，所以它不能被称作"HEAD 既有失败"。正确表述有三种，不可混用：
> ① HEAD 既有 = s4、s2h；② worktree 既有且非本批、非 R1 = s2b（来源未定位到单文件：+HEAD `conversations/*` 仍 4f、+HEAD `qa/service.py` 4f、+HEAD `retrieval/service.py` 5f、+HEAD `rag/query.py` ImportError）；
> ③ 本批引入 = **none**（pre-202C 沙箱下 N01+N02 由 26 绿变 **13 failed / 13 passed**，证明新用例确实钉住 202C；而 102b/102c/106a/106b/102d 在 pre-202C 下仍 33 passed）。
> 基线方法更正：`git archive HEAD` **不能**充当"改前"基线（HEAD 早于 R0/R1 与 202C；实测 HEAD 下 102d 8 failed、102a collection ImportError）。
> 正确基线 = **worktree − 目标 hunk**（本次用仓库外沙箱 + `git apply -R`，三文件 LF 归一化 sha 与 202C 记载的 pre-202C 值 3/3 相等）。

## 5. 轴裁决未变

- 与 202B 等价集合复跑 **74 passed**；核心断言仍 `("passed","frozen_targets_match_ok")`，反例仍 fail-closed
  （`violation/other_entity_used`、`violation/citation_entity_mismatch`、`unknown/entity_identity_unresolved`）。
- 硬失败并集与 unknown 不隐藏：`derive_hard_failed` 并集用例、`check_consistency` 拒绝隐藏 unknown、unknown 不被升为 pass/N-A 等用例全绿。
- 202C 反例面全绿（C1–C7，详见 `R2-CASE-MATRIX.md`）。

## 6. 202C 的已知残留（本包不改，登记待决）

> 独立验收（`evidence/08-independent/R2-INDEPENDENT-REVIEW.md`）对 §6 有两处更正，已并入：
> ① D1 的成因是**行基数**（两条店家行同属同一 active 版本），**不是**版本过滤缺陷——此前归因错误，撤回；
> ② D1 在合成条件下**确实可达**（独立探针 `d5a` 跑出「合作中」与「已终止」同时输出、`sources=3`），故独立验收判 **D=FAIL**。
> 因此本表 D1 的处置由"不改、登记"升级为"**必须闭环**"：见 §6.1 的守卫补丁（T-R2-202D）。

| 码 | 现象 | 可达性判断（对 R2 五题） | 处置 |
|---|---|---|---|
| `R2-203A-D1` → **已闭环**（T-R2-202D） | 同一门店存在 **2 条**店家行（**同属同一 active 版本**）时全部并入 ⇒ 正文出现互斥状态值，仅靠记录指纹区分（`total=3/returned=3/sources=3` 算术自洽、语义不自洽） | **合成可达**（独立探针 d5a 已跑出）；真实语料 `店家信息`(D02) 为 S01–S04 每店一条、业务日只活一版 ⇒ 对 R2 五题预期不可达，但**不能以此豁免**（行基数属产品不变量，不是语料巧合） | **已修**：`_store_join_chunks` 加 fail-closed 唯一性守卫——按派生门店值命中的店家行**恰好 1 条**才联结，0 条 / >1 条一律不联结，`diagnostics["store_join"]` 用固定码 `joined` / `store_row_missing` / `store_row_ambiguous` 区分。详见 §6.1 |
| `R2-203A-D2` | 多页时联结店家行排在物品行前，第一页可能拿不到被问字段（`retrieval.py:687` 按 label 排序） | 默认 `page_size=10`（`rag/query.py:1596`），C29 形态 `total=2` ⇒ **不可达**；仅 `total>page_size` 时成立 | 不改：登记；若后续出现多行多页案例再评估排序键 |
| `R2-203A-D3` | 联结轮次 `diag` 新增 `filter_miss` 并优先于 `limit_dropped`，可能造成"过滤过紧"假阳性归因 | 只影响评测 `diag` 归因，产品答案路径不传 `diag`（`rag/answer.py:187`）；不进入 R2 的 12 项质量或四轴 | 不改：登记；若评测侧需要"联结专用码"须另立合同并同步闭集 |
| `R2-203A-D4` | P1 口径 `runner.py` 五处 `score_case` 不传结构 token；若金标含旧计数可能 pass→fail | **不在 R2 链路**（P2 走 `p2_scoring` 的结构 token 通道） | 登记，不在本包处理 |

### 6.1 D1 的闭环补丁（T-R2-202D，fail-closed 唯一性守卫）

| 项 | 内容 |
|---|---|
| 改动 | 仅 `backend/src/mktkb/rag/retrieval.py`，**4 hunk**（+60 −14）。`answer.py b89622be…`、`facts.py cf795cfd…` 未动 |
| 新 sha256 | `retrieval.py d43530922355206746e40316d6dd5a875da6a3081c68db866cffa2d61b2abdaa`（37514B；改前 `aee14c82…`/34458B） |
| 守卫语义 | 按派生门店值命中的店家行**恰好 1 条**才联结；0 条 / **>1 条**一律不联结；`diagnostics["store_join"]` = `joined` / `store_row_missing` / `store_row_ambiguous`（只出固定码，不出门店名/行数/chunk_ids） |
| 唯一性判据 | 按 `record_unit_id or chunk_id` 计数 == 1 |
| 触发条件 | **一行未改**（`mode=record` + `enumerate` + 跨级 field_role + `filters` 含 item + 唯一物品目标 + 门店值唯一） |
| "恰好 1 条"行为 | **逐字节不变**：`total=2/returned=2/sources=2` 两值都在；把唯一性检查强制恒真（=改前判定）复跑同一问，`kind/text/sources/pagination` 完全相等 |
| 红态（改前） | 同店 2 行 → 正文同时出现「合作中」「已终止」、`sources=[物品, 店家, 店家]`、`total=3/returned=3`、rows=[4,5,6] |
| 绿态（改后） | 同店 2 行 → 不联结：`sources` 仅物品 1 条、**无任何店家级值**、`store_join=store_row_ambiguous`；同店 1 行 → 仍 2 值 2 来源 |
| 敏感性 | 令唯一性检查恒真 → 回到红（两值并出、`sources` 3 条、`total=3`）；`undo()` → 与绿态完全相等 |
| 新增用例 | `backend/tests/integration/test_r2_202d_uniqueness.py`（14 passed，含 0/1/2 行三态 + C1–C7 + 敏感性；`t09_network_guard` + `no_subprocess`，显式 `external==[]`） |
| 回归 | 202C 13、202A 13、203C f1/f2/f3/f4 = 5/3/7/6、R0 `c12_join` 7、`c12b_t7_e2e` 7、102d 8、102a 9 —— **全绿**；独立验收探针 `d5a` 按预期转红（该探针断言的是缺陷本身，交验收方更新） |
| 回滚 | `evidence/05-fix/R2-202D-MINE-rollback.patch.txt`，`git apply --check -R` exit 0；反向应用后 `retrieval.py` 回到 `aee14c82…` 且字节与快照相同 |
| 残留 | `store_row_ambiguous` 同时覆盖"命中 >1 行"与"同一物品行多个门店值"（细分需改诊断契约）；真实语料 ingest 上的可达性属 T-R2-205 |

## 7. NOT-RUN / 缺口

1. 全量 pytest（按提速策略）；旧验收全部历史用例未重跑。
2. 真实 provider / live H2 / OCR 出站；C29 在**真实语料**上的端到端绿；真实模型输出契约。
3. `HEAD` 基线下的判定链·202B·捕获评分·实体节点（HEAD 缺 19 个未跟踪 src 模块，`ModuleNotFoundError` ⇒ 该面 HEAD 对照不成立）。
4. `test_p2_eval_tool_repair_e2e.py`、`test_s2h_r2_conservative_profile.py` 未点名未跑。
5. 并发发布 / 深分页 / `rag_business_date` 与题面显式日期冲突矩阵未测。
6. 203C 有 6 处"被迫调整的断言"（详见其报告 §5），均**非降强度**：T2 问法改为可满足形态并把继承断言加严为"两回合 `sources` 逐字段相同"；
   "模型 0 调用"改为"≤2 次且模型证据不含另一家店"（该形态按设计走 legacy+模型）；改用 `commit_observed`/`capture_revision` 覆盖更广等。
