# R1-INDEPENDENT-REVIEW：R1 修复批独立验收（T-R1-104）

日期 2026-11-17。执行方：独立验收子智能体（未参与 101–103 开发）。HEAD `97b0066`。立场：**证伪**。
边界：只新增探针测试与本报告；未改 `backend/src/**`、未改既有测试；无 git 写（仍 172 commits）；未跑全量；
无真实外呼（未起服务、未发产品请求）；未读 `var/`、`.env`、私有证据。所有 PASS 均有本人跑出的命令/退出码/用例名。

## 1. 判定总表

| # | 标准 | 判定 | 我的证据（一行） |
|---|---|---|---|
| 1 | 机制闭环（M1/M2/M3/M5 含 HTTP） | **PASS** | 103 两 HTTP 文件 `3 passed`×2（exit 0）；M2 有分页 pass／去分页 fail 对照由 103 用例 + 我的探针各跑一次 |
| 2 | 评分增量未放水 | **PASS** | 自造 `87`（金标/题面/引用/分页皆无）→ `extra=["87"]` fail；默认路径 HEAD A/B `IDENTICAL=True` |
| 3 | 无 case 特判/硬编码 | **PASS** | `backend/src` 内 `H2V3-C` 命中 0；无 `case_id==`/文档名分支；批次测试实体全为合成 |
| 4 | 改动范围 | **PASS**（附注） | 11-17 被动过的 src 仅 6 个，其中 5 个在允许清单；批次标识只出现在 scorers/p2_scoring/product_adapter/query |
| 5 | 既有断言未被削弱 | **PASS**（附注） | 10 个 tracked 测试改动全部早于本批；全仓仅删 1 条 assert（`test_chunking.py`，11-16 17:21，等强度改值） |
| 6 | 既有失败甄别 | **PASS**（纠正 103 证据） | s4/s2h：HEAD 源码同断言同值（10.0 vs 40.0）；s2b：关闭 102b/102c 行为开关后仍复现，但 103 的 HEAD 对照不成立（见 §4-F1） |

结论：**未发现本批引入的产品回归或放水；无 FAIL。** §4 列 2 项已声明的残余风险 + 1 项对 103 报告证据链的纠正。

## 2. 复跑证据（命令前缀 `P` = `.\.venv\Scripts\python.exe -B -m pytest`，仓根，`-q -p no:cacheprovider --basetemp backend\.pytest-tmp\r1104-*`）

| # | 对象 | 退出码 | 结果（本人实跑） |
|---|---|---|---|
| 1 | `work\r1_mechanism_repro`（101 五文件，现口径） | 0 | **19 passed**（2.85s）；逐文件 M1 4／M2 5／M3 3／M4 5／M5 2 |
| 2 | `test_r1_102a_structural_numbers.py` | 0 | 9 passed |
| 3 | `test_r1_102d_turn_pagination.py` | 0 | 8 passed |
| 4 | `test_r1_102b_cross_turn_store_scope.py` | 0 | 6 passed |
| 5 | `test_r1_102c_restricted_multifield.py` | 0 | 7 passed |
| 6 | `integration\test_r1_103_http_structural_numbers.py` | 0 | 3 passed（M1 整行、M2 页头、M2 `ProductTurn` 采集） |
| 7 | `integration\test_r1_103_http_scope_and_refusal.py` | 0 | 3 passed（M3、M5 拒答、M5 合法面） |
| 8 | 我的探针两文件（`work\r1_104_probes`） | 0 | **19 passed**（2.24s） |
| 9 | 三条既有失败（工作树，同 session） | 1 | 3 failed / 13 passed |
| 10 | 三条既有失败（`PYTHONPATH=<HEAD 导出>/backend/src`） | 1 / 0 | s4+s2h：2 failed（同值）；s2b：**1 passed**（连跑 3 次） |
| 11 | 默认路径签名 A/B（`default_path_signature.py`） | 0 | 工作树 vs HEAD 归一化 JSON **逐字相同** |

断言有效性抽查（不是引用别人报告）：M1 HTTP 用例去掉产品 locator `row` 后同一答案 → `fail` 且
`extra==["4","5"]`；M2 去掉 `pagination` → `fail` 且 `extra⊇{"14"}`；M3 显式“乙店”→ `乙区`、来源行 `{5}`；
M5 只问位置+对接 → `answer`。这些对照在用例内部，我复跑通过 ⇒ 断言非空转。

## 3. 对抗探针（自建，19 用例；文件 `work\r1_104_probes\`）

`test_r1_104_scoring_probes.py`（9，`score_public_case` 全路径）：
1. `test_probe_fabricated_business_number_still_fails`：正文 `87` 无任何出处 → fail，`extra==["87"]`。
2. `test_probe_pagination_lie_still_fails`：正文 `共 3 条`、`pagination.total=2` → fail，`extra==["3"]`。
3. `test_probe_pagination_counts_are_grounded_only_when_reported`：同答案有分页 pass（`structural_numbers≥3`）／无分页 fail。
4. `test_probe_row_number_not_backed_by_locator_still_fails`：locator `row=7`、正文 `第 9 行` → fail，`extra==["9"]`。
5. `test_probe_control_locator_row_number_passes`：`第 7 行`+`row=7` → pass（防探针空转）。
6. `test_probe_non_int_pagination_counts_do_not_ground_numbers`：`total="2"` 字符串 → 2 仍 fail。
7. `test_probe_non_count_pagination_key_does_not_ground_numbers`：`revision=42` → 42 仍 fail。
8. `test_probe_locator_int_business_value_is_grounded_by_structure`：locator `quantity=5` → 5 被判有出处（见 §4-F2）。
9. `test_probe_adapter_pagination_whitelist_and_types`：`_pagination_of` 缺省/None→`{}`；字符串计量/`bool` 丢弃、`next_page=None` 保留、非白名单键丢弃。

`test_r1_104_scope_refusal_probes.py`（10，RAG 内核，合成甲/乙店）：
1–3. 显式“乙店的立牌放在哪？”（三种换话题措辞）→ `filters.store=乙店`、只 `乙区`、事实集不含甲店（**不被 102b 收窄**）。
4. “甲店和乙店的立牌放在哪？”→ `filters` 无 `store`、正文同时含 `甲区`/`乙区`（多店仍多店）。
5–6. “甲店立牌由谁对接？”／“甲店立牌的对接人是谁？”→ `answer`、含 `甲某`（**不被 102c 误拒**）。
7. 甲店作用域后问“乙店的立牌由谁对接？”→ 只 `乙某`，不泄漏 `甲某`。
8–9. “合同申请流程是什么？”／“账号申请要走什么流程？”→ 非 `SECURITY_*`（凭据词不吞政策题）。
10. 连续两次政策题 → 非记录作答、`filters.store≠甲店`（暂存作用域不越界）。

## 4. 发现

**F1（纠正 103，非产品问题）**：`R1-REGRESSION.md` §4.2 称 s2b「用 HEAD 源码在仓库 cwd 复跑 → 同样失败」。
我用 `git archive` 导出 HEAD 到临时目录并以 `PYTHONPATH` 指向它（自检 `mktkb.__file__` 指向导出树），
`test_ambiguous_identifier_candidates_converge` **1 passed，连跑 3 次全绿**；工作树同用例 1 failed（`conflict≠clarification`）。
⇒ 该失败**依赖工作树源码**，103 的对照证据不成立（很可能其 `-o pythonpath=` 未真正生效，未能确证）。
替代实验（更强）：把工作树 `backend/src` 整体复制到临时目录，仅关闭 102b/102c 三个行为开关
（`retain_store_scope=False`、`store_scope=None`、去掉凭据词拒答分支）后复跑 → **仍 `conflict≠clarification`**；
且 102b/102c 的判据全部以“上一轮唯一门店/换话题”或“凭据词”为前置条件，而失败发生在**新会话首轮**，本批改动不可达。
⇒「s2b 非本批引入」结论成立，但依据应换成上述两点，而不是 103 的 HEAD 对照。

**F2（已声明的口径残余，实测确认）**：`citation_structural_number_keys` 收集 locator 里**任意**非排除键整数，
`quantity=5` 这类业务值会被当作结构 token 放行（`value_no_fabricated=pass`）。102a §未覆盖 3 已声明；属批准口径的边界，
非本批隐性放宽，但"locator 出现业务性 int 列"时 `value_no_fabricated` 会失效，建议后续把结构键白名单化（`row`/`header_row`…）。

**F3（已声明的词面宽度，实测确认）**：“甲店立牌有合同吗？”（状态提问）→ `SECURITY_RESTRICTED_CONTACT` 误拒。
102c §4.2 已声明；不影响 handoff 要求的“只问联系人”反例（该面 2 条全绿）。

## 5. 未覆盖 / NOT-RUN

1. 未跑全量 pytest（按边界）；未验证 102a 报告的 `tests/evaluation` 2638 passed。
2. 未跑真实 live run / 分页第 2 页；M2 只在首页与 `ProductTurn` 采集段闭环。
3. “既有 38 项 tracked 基线”未逐项核对（无基线清单）。实测 39 个 `M`，其中 `.claude/handoffs/_index.md`（10:24，PM 协调）
   非产品文件；其余 38 与 handoff 口径一致。范围判定依据是批次标识 grep + mtime，不是逐文件 diff 归因。
4. `work\r1_mechanism_repro` 五文件为 untracked，**无法 diff** 101 初版断言；按当前内容判断：M1/M2 已按批准的 102a 口径
   改写（原“正文不得出现行号/页头计数”红断言撤销），但新增 4 条对照仍 fail（`extra=["7"]`、`extra=["3"]`、无分页 fail），
   M3/M4/M5 断言仍对准机制（filters/kind/facts），未发现空转。
5. 102c 词面向量更宽的其他业务提问（如“合同编号规则”）未穷举；F3 只给一个可复现例子。
6. 未复核 `_load_context` legacy 跨店遗留项与 102b 报告 §风险 的一致性（超出本单）。

## 6. 产物

- 本报告。
- `work\r1_104_probes\test_r1_104_scoring_probes.py`（9）、`test_r1_104_scope_refusal_probes.py`（10）。
- `work\r1_104_probes\default_path_signature.py`（HEAD/工作树默认路径 A/B 脚本）、`_explore_shapes.py`（探查用，非交付断言）。
- 未改任何 `backend/**` 与既有测试；新增文件均在报告目录内。
