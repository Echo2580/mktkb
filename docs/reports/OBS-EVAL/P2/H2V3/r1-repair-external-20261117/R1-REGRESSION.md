# R1-REGRESSION：R1 组合定向回归 + HTTP 同形贯通（T-R1-103）

日期 2026-11-17。执行方：独立验证子智能体（未参与 101/102 开发）。基线 HEAD `97b0066`。
立场：证伪——每条"通过"给命令 + 退出码 + 用例数；既有失败给对照证据，不笼统归因。
边界：未改 `backend/src/**`（会话前后 dirty 均 46 条、`git diff --stat` 逐字相同）；只新增 2 个测试文件与本报告；
未跑全量；无 git 写（仍 172 commits）；无真实外呼（`t09_network_guard` 逐例校验出站 0）；未读 `var/`、`.env`、私有证据。

## 1. 判定

| 机制 | HTTP 同形判定 | 关键证据（真实产品响应） |
|---|---|---|
| M1 整行渲染结构数字 | **PASS** | 正文含 `第 4 行`/`第 5 行`＋`（记录 …）`；`score_public_case` → `value_no_fabricated=pass`；同 run 对照（去 locator `row`）→ `fail`、`extra=["4","5"]` |
| M2 枚举页头计数 | **PASS** | 正文 `共 14 条，当前第 1 页显示 10 条`；响应 `pagination` 六键；HTTP 直连打分与 `ProductTurn.as_dict` 两条采集路都 `pass`；对照（去 `pagination`）→ `fail`、`extra⊆{"10","14"}` 且含 `14` |
| M3 三回合门店范围 | **PASS** | t3 正文只含 `甲区`、被引 locator 行号集 `{4}`；可达性对照：显式"乙店"→ `乙区`、行号集 `{5}` |
| M5 合同/结算账号拒答 | **PASS** | `kind=not_found`、`sources=[]`、正文含"受限"、无联系人/电话/地址/凭据/位置值；合法面对照（只问位置+对接）→ `answer` 含 `甲区` |
| M4 位置+生效 | 未列 HTTP 例（§2 未要求） | 复现件 5 passed；101 判"已由既有修复覆盖" |

**未发现"产品在 HTTP 路径仍未修好"的机制（无 FAIL）。**

## 2. 新增测试（仅此两个文件）

- `backend/tests/integration/test_r1_103_http_structural_numbers.py`：`test_m1_full_row_render_scores_without_fabrication`、
  `test_m2_enumeration_header_counts_are_grounded_by_product_pagination`、
  `test_m2_product_turn_carries_pagination_into_scoring`（`ProductEvalAdapter.ask_turn` → `as_dict` → 打分行）。
- `backend/tests/integration/test_r1_103_http_scope_and_refusal.py`：`test_m3_bare_followup_after_topic_turn_stays_on_first_store`、
  `test_m5_contract_and_settlement_account_question_is_refused_over_http`、`test_m5_location_plus_contact_only_still_answers`。

全部经产品入口 `POST /api/v1/conversations/{id}/messages`；合成数据（甲店/乙店、立牌、甲区/乙区、标识 PA…PN、甲某、010-555500xx、SEQ-000x）。

## 3. 组合回归（全部实际执行；`pytest` = `.\.venv\Scripts\python.exe -B -m pytest <paths> -q -p no:cacheprovider`，仓根）

| # | 范围 | 退出码 | 结果 |
|---|---|---|---|
| 1 | 新增 103 两文件（§2） | 0 | **6 passed**（连跑 3 次均 6 passed，无 flake） |
| 2 | `test_r1_102b_*`、`test_r1_102c_*`、`test_r1_102a_*`、`test_r1_102d_*` | 0 | **30 passed**（6+7+9+8） |
| 3 | 101 复现件 5 文件（实际路径见 §4.1） | 1 | **3 failed / 13 passed**（M1 2F1P、M2 1F2P、M3 3P、M4 5P、M5 2P） |
| 4 | 保护面 rag 9 文件（r0_4、r0_11、r0_c12×4、query_state、offline_e2e、v3_fix1r1） | 0 | **82 passed** |
| 5 | 保护面 e2e/unit 3 文件（v3_safety_fix_e2e、r0_c12b_t7_boundary_e2e、v3_safety_fix_policy） | 0 | **35 passed** |

101 红→绿（本次复跑）：M3 `3 passed`（101 建立时 1P/2F）、M5 `2 passed`（建立时 1P/1F）。

## 4. 既有失败甄别

### 4.1 101 复现件 3 条红例（M1×2、M2×1）＝非本批引入

- 路径：`docs/reports/OBS-EVAL/P2/H2V3/r1-repair-external-20261117/work/r1_mechanism_repro/test_r1_101_m*.py`
  ——**不在** `backend/tests/rag/`（handoff §2.1 路径不存在），按实际路径运行。
- 计数与建立时逐条相同（101 `REPRO-REPORT.md` 表 #1 `2 failed, 1 passed`、#2 `1 failed, 2 passed`），失败用例名相同：
  `test_m1_record_line_has_no_decimal_row_number`、`test_m1_scoring_does_not_count_row_number_as_fabricated`、
  `test_m2_enumeration_header_counts_are_not_scored_as_fabricated`。
- 原因（读码 + 复跑）：两条按旧评分口径断言（只传 `allowed_number_keys=citation_number_keys(...)`，不含 102a 批准的结构 token）；
  M2 文件 docstring 自己写明"若修复选在评分侧…需同步更新口径，而不是判成回归"。
- `test_m1_record_line_has_no_decimal_row_number` 断言产品侧不得写行号：102a 批准的是**评分侧背书**、不删行号（102a 报告 §未覆盖 2 已声明）。
- 结论：这三条是复现件口径未更新，不是产品回归，也不是 101→102 改动引入。

### 4.2 本批之外 3 条（我额外核对 101/102 报告提到的"既有失败"）

- `test_s4_stage_limit::test_current_go_and_budget_are_consistent_and_above_three_yuan`、
  `test_s2h_r3_official_profile`：失败值 `共享预算总上限 … 10.0（当前 40.0）` / GO 阶段额度不符；读
  `docs/evidence/LOCAL-R1-20261101/budget|GO`。用 **HEAD 源码**（`-o pythonpath=<HEAD 导出>/backend/src`，实测
  `mktkb.__file__` 指向导出树）在仓库 cwd 复跑 → 同样 2 failed、同断言值 ⇒ 与 101–102d 源码无关。
- `test_s2b_intent_semantics::test_ambiguous_identifier_candidates_converge`：工作树失败（`conflict ≠ clarification`）。
  同一 **HEAD 源码**在仓库 cwd 复跑 → 同样失败；同一 HEAD 导出树内（cwd=导出树）→ **1 passed**。
  ⇒ 与 101–102d 源码无关，由仓库 cwd 下的未跟踪工件触发（`var/`、`.env`、`docs/evidence` 之类；按边界未读取）。
  102b"与 102b 无关"的方向成立，但其"置空新行为即复现"的依据被更强的 HEAD 源码对照取代。
- 残留：未定位具体工件（越界）；这三条不计入 §3 回归结论。

## 5. NOT-RUN / 缺口

1. 真实 live run 未跑（禁外呼）：M2 的"产品响应 → `ProductTurn.pagination` → 打分"已分段实测，但没有一次真实 run 的 run 行 + gate。
2. 分页第 2 页未跑；M2 只对照首页。
3. 用 HEAD 源码跑新增 HTTP 用例不可用：HEAD 应用在本环境对同类提问返回 `service_error`/`INDEX_NOT_READY`，不能当判别证据；
   M3/M5 的判别依赖 101 建立时的 red 计数 + 本轮同文件同用例名 green 复跑。
4. 非 P2 打分路径（P1 `runner.score_case` 不传结构 token）仍会把 locator 行号当编造——按 102a"默认路径逐字不变"属既定口径，未覆盖。
5. 未跑全量 pytest；未覆盖 legacy 路径的分页/作用域其它分支；未复核 102b 的 `_load_context` 遗留项。
