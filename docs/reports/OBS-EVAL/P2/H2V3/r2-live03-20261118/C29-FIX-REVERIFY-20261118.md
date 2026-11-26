# C29 修复独立复验报告（2026-11-18，零外发）

复验者：独立复测会话（未参与本轮 C29 修复实现）。本报告只验收，不改产品代码、评分器、冻结题目或标签。全部数据为自建合成虚构件，未读 fixtures、题面、私有材料、真实 case_id 或期望值；全程离线 provider + 零出站守卫 + 零子进程断言。

## 0. 结论（先行）

- **离线独立复验：C29 修复本身通过。** 定向 23 项、扩展覆盖 60 项、自建探针 9 项全部通过；rag+integration 全量回归 1167 过 / 3 失败（2 项为已知 C-1 残留、1 项为预算提额后的陈旧断言，均非本轮引入，见 §3/§6）；unit 层 404 过 / 1 环境性失败（补授权环境变量后全绿，§5）。跨店按子句取值、记录行/版本绑定、重排隔离、反例 fail-closed、小页翻页绑定均实测成立，敏感性对照证明绿态由本轮修复入口产生。
- **已知残留（非本轮新引入）：** 206b 探针 2 项失败，即上一轮独立复验已登记的阻塞项 C-1——`sources[].locator.cells` 整行快照带出受限列值。失败面与历史记录逐项同形（18 过 / 2 失败），裁决权仍在主人（脱敏 locator 或书面接受）。本轮 C29 两店形态同样可达该面（见 §4 观测）。
- **真实 R2：未执行。** 本轮无专门授权（保管人/执行者/受控窗口/外发范围/供应商与金额上限未确认，无新计划、新 GO）。真实状态仍记 attempt4 的 **4/5**（硬失败 0、必要轴 unknown 0，C29 唯一失败项）。

## 1. 环境身份

| 项 | 值 |
| --- | --- |
| 分支 | `codex/p2-e2e` |
| HEAD | `97b0066726e5b8d6f94cbc0b63a890084550c106` |
| 工作树 | 39 个已跟踪文件修改、0 暂存（与任务书基线一致）；复验仅新增 1 个未跟踪探针文件，未做任何 git 写操作 |
| Python | 仓库 `.venv\Scripts\python.exe`（-B -X utf8） |
| 临时目录 | 全部仓外 `D:\mktkb-c29-reverify-20261118\basetemp*` |

受查修复文件 SHA-256（复验开工时实测）：

| 文件 | SHA-256 |
| --- | --- |
| backend/src/mktkb/rag/query.py | `75badba4b068e983d545f2a383d8514babf38df9302372618af588b98581be28` |
| backend/src/mktkb/rag/types.py | `b066b3b10391b79e388f18702f84b0d30835d299b1e32b1196ad5931729667b5` |
| backend/src/mktkb/rag/retrieval.py | `ebf5df19b8b728fa92d2e197770190e9514acc5ed6b605fa6b0246d328f19582` |
| backend/src/mktkb/rag/answer.py | `e8a151b20d6bc2203fc7070781d8770947f0dc439be056448b0b55aec945f6cd` |
| backend/src/mktkb/rag/facts.py | `2a27f946d68ca47f7d705aa874aef850e45232b645af40ade26434cbfbd6ec40` |

## 2. 复跑命令与结果（全部亲自执行）

| # | 命令（仓库根） | 结果 | 退出码 |
| --- | --- | --- | --- |
| 1 | `pytest backend/tests/rag/test_r1_102b_cross_turn_store_scope.py backend/tests/integration/test_r2_202c_c29_join_rag.py -q` | **23 passed**（9 + 14） | 0 |
| 2 | `pytest …test_r2_202a_c29_mechanism_synthetic.py …test_r2_202d_uniqueness.py …test_r2_206a_contact_gate.py …test_r2_206b_contact_gate_increment.py …test_r2_203c_f1_http_join_witness.py -q` | 60 passed / **2 failed**（206b C-1 已知残留，见 §3） | 1（pytest 失败码；管道尾命令回显 0，以 pytest 汇总为准） |
| 3 | `pytest …test_r2_206b_contact_gate_increment.py …test_r2_206a_contact_gate.py -q` | 28 passed / 2 failed（同上两例） | 1 |
| 4 | `pytest backend/tests/integration/test_c29_reverify_20261118_independent.py -q -s --basetemp=仓外` | **9 passed**（自建探针，§4） | 0 |
| 5 | `pytest backend/tests/unit -q` | 404 passed / 1 failed（环境性，见 §5） | 1 |
| 6 | `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40 pytest backend/tests/unit/test_s2h_r3_official_profile.py -q` | **14 passed**（补授权环境变量后全绿） | 0 |
| 7 | `pytest backend/tests/rag backend/tests/integration -q --basetemp=仓外`（全量回归） | **1167 passed / 3 failed**，456.67 s（§6） | 1 |

覆盖项对照任务要求：

- 门店记录唯一性：202d 全过 + 自建探针「同店重复店家行 / 重复物品行 → MULTIPLE_ENTITIES、零事实零引用」。
- 受限联系字段拒答：206a 全过；206b 冻结面 B1/B2/B3/B4a/B4b 全过；自建主例附电话请求 → phone 角色剔除、正文/事实无受限值、模型 0 调用。
- 既有分页：102b `test_explicit_field_scopes_survive_paging` 过 + 自建小页（page_size=1）HTTP 翻页探针过。
- 同店联结：202c R1/R2 主例、203c-f1 HTTP 联结见证、legacy/RAG 双入口互不吞并敏感性全过。

## 3. 206b 两项失败的归因（非本轮新回归）

失败用例：`test_c_locator_cells_must_not_expose_restricted_values[a1_mixed3 / a2_mixed4]`。
实测泄露值：`020-00000011`、`示范巷27号`、`合成负责人·丙`（206b 自建合成数据集），位于 `sources[1].locator.cells[*].display`（店家行整行快照）。

归因证据：`docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/10-attempt2/R2-206B-REVIEW.md` §0/§1C/§3-R1 已登记同一阻塞项 C-1：

1. 整行 `locator.cells` 是**既有** citation 设计（店家级单独问题在 206B 改前树同样带出整行值）；206B 批次的贡献只是让原本整题拒答的混合题首次走到该面。
2. 该轮独立复验即为 **18 passed / 2 failed**，与本次复跑逐项同形；本轮 C29 修复未触碰 locator 构造（ingestion 期写入）与该两例的触发链路。
3. 冻结评分器 `value_forbidden` 只扫正文、不扫 sources，故该残留不影响 R2 质量判分，但**不能**以"C29 转绿"当作"无泄漏"证据。

处置：保留为待主人裁决的阻塞项（脱敏 locator，或书面接受并登记 follow-up）。本轮不修。

## 4. 自建探针（9 项全过）与关键观测

文件：`backend/tests/integration/test_c29_reverify_20261118_independent.py`（新增未跟踪）。
数据集：枫杨店/云杉店、同名物品「亚克力牌」、位置 丙区3号架/丁区5号架、状态 合作中/暂停合作、电话 020-00000021/22。两份 xlsx 经真实上传→解析→发布，问答走 `POST /api/v1/conversations/{id}/messages`。

| 探针 | 判定 | 要点 |
| --- | --- | --- |
| 主例：甲店物品位置 + 乙店合作状态 | PASS | 正文两值各归其店（无串店）；事实 `{(location,丙区3号架),(status,暂停合作)}`、实体标签 `{枫杨店的亚克力牌, 云杉店}`；来源 2 条、`status=active`、`version_number=1`、行号 物品表 row4 / 店家表 row5；内核引用 `version_id` = 本轮刚发布版本；模型 0 调用 |
| 重排输入面 | PASS | `plan.record_field_stores={location:枫杨店,status:云杉店}`；店家行进精确证据面（exact=2）但**不在融合候选**（fused=1）；重排真实执行（offline-lexical，candidates=1），输入不含店家整行 |
| 附电话请求 | PASS | phone 角色剔除；正文/事实无电话/联系人值；两值与两来源不变 |
| 同店重复店家行（2 条有效） | PASS | HTTP 歧义拒答（kind=not_found + 歧义文案），内核 reason=MULTIPLE_ENTITIES；零事实零引用，不从另一店补值 |
| 同店重复物品行（2 条有效） | PASS | 同上 fail-closed |
| 乙店店家行缺失 | PASS | 只答甲店位置（kind=answer），无乙店状态、无甲店状态顶替，来源仅物品表 |
| 乙店店家行过期（失效 2026-10-31 < 业务日 2026-11-18） | PASS | 同上，过期行不并入 |
| 甲店物品行过期 | PASS | 不答过期位置、不拿乙店位置顶替；只答乙店状态（来源仅店家表）——记录为实际行为 |
| 小页容量（page_size=1）HTTP 翻页 | PASS | 第 1 页 1 值 1 来源（行号正确）、第 2 页补另一值另一来源（active 版本）；两页均无串店值/受限值；翻页计划 `record_field_stores` 与首轮逐字一致、page=2 |
| 敏感性：关掉 `_record_field_stores` 入口 | PASS | 主例回到修前形态：两店位置跨店枚举、无店家级值/来源（证明绿态由本轮入口产生） |

**引用定位载荷的实际表现（任务点名的记录项）：** C29 两店形态下，被引用的乙店店家行 `locator.cells` 整行快照带出该店自己的受限值（实测 `020-00000022`、`合成对接人·己`）。与 §3 的 C-1 同一既有机制；正文、事实、模型证据、重排输入均闭合。该面是否可接受仍待主人裁决。

零外发审计：全部探针挂 `t09_network_guard`（`external == []`）+ `no_subprocess`（0 次）；主例显式断言通过。

## 5. unit 层 1 项环境性失败（非产品缺陷）

`test_s2h_r3_official_profile.py::test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552`：
读历史快照预算（limit_cny=40），而未改动的 `live_authorization.py` 钱闸默认项目总上限 10 元，需主人追加授权环境变量 `MKTKB_PROJECT_TOTAL_LIMIT_CNY`。复验 shell 未带该变量 → 拒绝；带上 `=40` 后该文件 **14/14 全过**。涉及文件（live_authorization.py、快照预算、该测试）均不在本轮改动清单。判定：环境性，不计为修复缺陷。

## 6. 全量回归（rag + integration）

命令：`pytest backend/tests/rag backend/tests/integration -q -p no:cacheprovider --basetemp=D:/mktkb-c29-reverify-20261118/basetemp-full`。
结果：**1167 passed / 3 failed**，456.67 s，pytest 退出码 1。三项失败逐一归因，均非本轮 C29 修复引入：

| 失败用例 | 归因 |
| --- | --- |
| 206b `test_c_locator_cells_must_not_expose_restricted_values[a1_mixed3]` | 已知残留 C-1（§3），与上轮独立复验同形 |
| 206b `…[a2_mixed4]` | 同上 |
| `test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan` | 陈旧断言：只读校验历史 S2-LIVE-GO 时代的预算并写死 `limit_cny == 20.0`；现行正式预算经主人提额已为 40 元（快照文件本身即 40）。该测试文件不在本轮 39 项改动内，不涉及 C29 链路。实测 `assert 40 == 20.0` 失败 |

除上述 3 项外，rag + integration 全量 1167 项通过，含本轮修复涉及的全部既有保护面（202a/202c/202d/203c/206a、102b、分页、同店联结、安全拒答、预算结算等）。

## 7. 真实 R2 状态与阻塞

- 本轮**未执行**任何真实外发；未生成新计划、未签发/使用 GO、未动账本。
- 阻塞：第二阶段需要主人或书面委托方确认本轮保管人、执行者、受控窗口、数据外发范围、供应商与金额上限，并签发绑定实时账本历史前缀 SHA-256 的新 GO。attempt4 的授权与 GO 已耗用，不可复用。
- 在获得上述授权前，真实状态维持 attempt4：**质量 4/5、硬失败 0、必要轴 unknown 0，C29 唯一失败项**。
- 另需主人先裁决 §3 的 C-1 残留（locator 脱敏或书面接受）；否则即便 C29 转绿，独立复验口径下该暴露面仍是未闭合阻塞。

## 8. 证据路径

- 本报告：`docs/reports/OBS-EVAL/P2/H2V3/r2-live03-20261118/C29-FIX-REVERIFY-20261118.md`
- 自建探针：`backend/tests/integration/test_c29_reverify_20261118_independent.py`
- 历史 C-1 登记：`docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/10-attempt2/R2-206B-REVIEW.md`
- attempt4 基线：`docs/reports/OBS-EVAL/P2/H2V3/r2-live03-20261118/ATTEMPT4-RUN-REPORT.md`
- 临时装配（仓外）：`D:\mktkb-c29-reverify-20261118\basetemp*`