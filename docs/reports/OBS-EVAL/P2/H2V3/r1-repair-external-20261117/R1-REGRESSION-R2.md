# R1-REGRESSION-R2：106a/106b 组合回归 + C13/C22 的 HTTP 真实路径判定（T-R1-107）

日期 2026-11-17。执行方：独立验证子智能体（未参与 101–106 开发）。基线 HEAD `97b0066`（172 commits，未变）。
立场：**证伪**——每判 PASS 给命令 + 退出码 + 用例名；并且每条断言都做一次"把修复关掉"的敏感性对照（§3），不靠"跑绿了"下结论。
边界：未改 `backend/src/**`（本会话 11:15–11:29 内 src 零写入；src 末次写入 11:13:40 属 106a/106b 收口）、未改既有测试；
唯一新增为 §2 两个测试文件；无 git 写；未跑全量；无真实外呼（`t09_network_guard` 逐例断言外部出站为 0）；未读 `var/`、`.env`、私有证据。

被测快照：`REPORT-106a.md` 11:11:52、`REPORT-106b.md` 11:15:02，其 src 末次写入 11:13:40；本轮全部实跑在 11:20 之后。

## 1. 判定：C13 / C22 已在 HTTP 真实路径收口（无 FAIL）

| 编号 | 判定 | 用例 | 关键证据（产品真实响应） |
|---|---|---|---|
| C13 | **PASS** | `test_r1_107_http_c13_c22.py::test_c13_bare_followup_over_http_keeps_unique_store_scope`、`::test_c13_legacy_followup_evidence_excludes_other_store` | t1/t3 `sources` 行号集 `{4}`、正文含 `甲区` 且无 `乙区`；t3 legacy 变体模型证据无 `乙店`/`乙区`；政策题 `kind=answer` 含 `区域经理`、`sources` 非空且无门店行；可达性对照：显式"乙店"→`乙区`、行号集 `{5}` |
| C22 | **PASS** | `test_r1_107_http_c13_c22.py::test_c22_primary_store_target_over_http` | `kind=answer`、含 `甲区一层`、无 `乙区二层`、无"未在资料中找到"；`sources` **1 条**（row 4 甲店）；异店只出现 `乙店`+`尚未生效`+`2026-12-01`；反例 `::test_c22_explicit_list_of_both_stores_still_answers_both` 仍两家（`{6,7}`） |
| C22 越店取值 | **PASS** | `test_r1_107_http_c22_leak_shape.py::test_c22_cross_store_value_never_rendered_over_http` | 不钉业务日的形态：含 `甲区一层`、无 `乙区二层`/`2026-12-01`、`sources` 1 条（row 4） |

"真实路径" = 上传 → `run_one_job` 解析/建索引 → 发布 → `POST /api/v1/conversations/{id}/messages`（不直写库；复用 103 夹具写法）。
C22 的"尚未生效"依赖进程级业务日（产品无请求级日期注入）：首个文件按 `tests/conftest.py` 逐字段装配并只额外钉
`rag_business_date="2026-10-28"`；第二个文件**不钉**日期，专门覆盖"异店行参与候选"的越店取值形态。

## 2. 新增测试（仅此两个文件，5 用例）

- `backend/tests/integration/test_r1_107_http_c13_c22.py`（4）：C13 主形（甲店→政策题→裸追问楼层）+ C13 legacy 见证 + C22 主形 + C22 显式两店反例。
- `backend/tests/integration/test_r1_107_http_c22_leak_shape.py`（1）：C22 越店取值形态（不钉业务日）。

## 3. 敏感性（证伪）对照：关掉修复，必须转红

方法：`-p mutant_plugin`（插件在 gitignore 的 `backend/.pytest-tmp/r1107-head-src/`，不入库）按 `R1107_MUTANT=c13|c22` 关掉对应函数，其余不变。

| 变异 | 关闭 | 结果 | 退出码 |
|---|---|---|---|
| c13 | `conversations.service._legacy_store_scope → None` | **1 failed / 3 passed**：`test_c13_legacy_followup_evidence_excludes_other_store` 红 | 1 |
| c22 | `rag.query._primary_store_scope → None` | **1 failed / 3 passed**：`test_c22_primary_store_target_over_http` 红（`kind=not_found`） | 1 |
| c22 | 同上 | **1 failed**（leak 文件）：`test_c22_cross_store_value_never_rendered_over_http` 红 | 1 |

红出的正是原始违规形态（本人跑出，非引用他人报告）：

- c13：`AssertionError: 根据资料：门店：乙店；物品：立牌；位置：乙区；门店：甲店；物品：立牌；位置：甲区`（乙店行进模型证据）。
- c22（leak）：`共 1 条，当前第 1 页显示 1 条。\n- 乙店的宣传海报：生效日期 2026-12-01、位置 乙区二层（来源：终端物料位置表.xlsx）\n未在资料中找到：甲店（该实体没有匹配记录）。`
- c22（钉日期）：`kind=not_found`，`未在资料中找到“乙店”、“甲店”的“宣传海报”记录…`。

⇒ 三条断言对 106a/106b 的修复**确实敏感**；两条反例在变异下仍绿（未过度收窄）。诚实缺口：c13 变异下 C13 主形（裸追问楼层）仍绿
——该问法由结构化内核作答（`sources={4}`）不经 legacy 作用域，legacy 违规面由第二个用例见证（这也是本轮补该见证用例的原因）。

## 4. 组合回归（全部实跑；仓根；`P` = `.\.venv\Scripts\python.exe -B -m pytest <paths> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\r1107`）

| # | 范围 | 退出码 | 结果 |
|---|---|---|---|
| 1 | §2 两个新文件（连跑 2 次） | 0 / 0 | 5 passed / 5 passed |
| 2 | `test_r1_106a_legacy_store_scope.py` + `test_r1_106b_primary_store_target.py` | 0 | 12 passed（4+8） |
| 3 | 101 复现件 5 文件（`work/r1_mechanism_repro/`） | 0 | 19 passed（M1 4／M2 5／M3 3／M4 5／M5 2） |
| 4 | `test_r1_102a_*`+`test_r1_102d_*`+`test_r1_102b_*`+`test_r1_102c_*` | 0 | 30 passed（9+8+6+7） |
| 5 | `test_r1_103_http_structural_numbers.py` + `test_r1_103_http_scope_and_refusal.py` | 0 | 6 passed（3+3） |
| 6 | 保护面 rag 9 文件（`r0_4`、`r0_11`、`r0_c12`×4、`query_state`、`offline_e2e`、`v3_fix1r1`） | 0 | 82 passed |
| 7 | 保护面 e2e/unit 7 文件（`r0_c12` 集成×2、`v3_safety_fix_e2e`、`v3_safety_fix_policy`、`t207_v8_*`×3） | 0 | 44 passed |

合计 **198 passed / 0 failed**（不含 §5 的 2 条既定失败，二者不在本范围表内）。

## 5. 既有失败甄别：`test_s4_stage_limit` / `test_s2h_r3_official_profile`（非本批）

- 工作树：`P backend\tests\rag\test_s4_stage_limit.py backend\tests\unit\test_s2h_r3_official_profile.py` → **2 failed / 20 passed**（退出码 1）。
  `test_s4_stage_limit::test_current_go_and_budget_are_consistent_and_above_three_yuan`：`assert 40 == 20.0 ± 2e-05`（读 `docs/evidence/…/budget.json` 的 `limit_cny`，非 src）；
  `test_s2h_r3_official_profile::test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552`：`ValueError: …预算下限…当前 40.0`（工作树 `qa/service.py:820`）。
- **HEAD 源码对照**：`git archive HEAD backend/src` 导出到 `backend/.pytest-tmp/r1107-head-src`（只读导出，未触索引），
  经 `-p headpath_plugin` 把导出树插到 `sys.path[0]`，同 cwd 复跑 → **同样 2 failed / 20 passed、同断言值**；失败栈指向导出树
  （`…r1107-head-src\backend\src\mktkb\qa\service.py:614`，工作树为 `:820`）⇒ 与 101–106 源码无关。
- 方法更正：`-o pythonpath=<导出>` 在本环境被 editable `.pth` 压过（实测栈仍指工作树），必须用插件/PYTHONPATH 注入；
  与 104 §F1 对 103 的纠正一致。
- 附：101 复现件现 19 passed；M1/M2 文件 10:33–10:34 已按 102a 口径更新并补对照（晚于 103 的 10:31 回归），非产品回归。

## 6. NOT-RUN / 缺口

1. 未跑全量 pytest（按边界）；未跑真实 live/外呼；未跑真实 C13 三回合重放（无授权），只覆盖合成同形 HTTP 三回合。
2. C22 覆盖"异店未来生效"与"异店无窗口"两形态；"异店已过期"形态只在 RAG 层（106b）覆盖。
3. 未覆盖前端展示层（`sources`/正文之外的渲染）；未验证分页第 2 页与 live run 行。
4. C13 的 `_apply_store_scope` 在"唯一门店但题面指向他店物品"时 fail-closed 的分支未加断言（106a 已声明未覆盖）。
