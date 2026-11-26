# P0「DeepSeek 调用异常最小修复」离线收尾核验报告

- 日期：2026-11-23
- 角色：开发窗口（离线收尾核验，不发起真实 DeepSeek / DashScope / OCR 请求）
- 工作基线：未提交工作区（HEAD = `2f4b006`），未重建、未回滚、未整理用户既有改动

## 1. 一句话结论

**经理口径的「全量 105 failed、比逐目录合计多 1 项」在当前工作区未复现**：两次全量与 8 个目录分别运行的失败 nodeid 集合完全一致（55 项 = 48 failed + 7 errors，三次完全相等）；`evaluation` 当前代码与 HEAD 代码的失败集合对比新增 **0** 项、消失 24 项（均为 HEAD 影子仓库路径/联接环境差异）、共同 50 项。未发现与本次修复直接相关的新增失败，**本任务代码改动 0 个文件**。

## 2. 运行条件（影响结果的关键）

统一环境：

- Python：`.venv` Python 3.12.7；pytest 9.1.1
- 环境变量：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；测试进程内移除 `DEEPSEEK_API_KEY`（防止任何真实调用）
- pytest 参数：`-B -m pytest <目标> -q -p no:cacheprovider -p report_plugin --basetemp <仓库外目录>`
- 机器可读报告：自定义插件 `report_plugin.py`（按 nodeid 记录 passed / failed / error / skipped，落 JSON）
- `backend/tests/conftest.py` 的 `isolate_dotenv_in_test_process` 生效，测试进程不读仓库 `.env`

**basetemp 必须放在仓库外**：`evaluation` 的部分守卫显式拒绝仓库内的证据根 / 私有场景路径（`evidence_root_inside_forbidden`、`scenario_private_path_inside_workspace`、`holdout_root_inside_repo`）。若按派单示例把 `--basetemp` 放在 `backend/.pytest-tmp/` 内，会额外产生 **263 项路径守卫失败**，全量变成 246 failed + 113 errors，与代码无关。本报告所有主结论均采用仓库外 basetemp。

## 3. 全量 vs 逐目录

### 3.1 数字

| 运行 | passed | failed | errors | skipped | 用时 |
| --- | ---: | ---: | ---: | ---: | --- |
| 全量 #1（`backend/tests`） | 5018 | 48 | 7 | 48 | 26m40s |
| 全量 #2（同一环境重复） | 5018 | 48 | 7 | 48 | 24m34s |
| 逐目录合计（8 次独立进程） | 5018 | 48 | 7 | 48 | — |

逐目录明细：

| 目录 | passed | failed | errors | skipped |
| --- | ---: | ---: | ---: | ---: |
| acceptance | 70 | 0 | 0 | 0 |
| evaluation | 2869 | 43 | 7 | 48 |
| independent | 42 | 0 | 0 | 0 |
| integration | 595 | 2 | 0 | 0 |
| observability | 366 | 0 | 0 | 0 |
| operations | 69 | 0 | 0 | 0 |
| rag | 591 | 2 | 0 | 0 |
| unit | 416 | 1 | 0 | 0 |

### 3.2 集合对比（不是数量对比）

失败 nodeid 集合（outcome + nodeid，共 55 项）：

- 全量 #1 == 全量 #2：差集 0；
- 全量 #2 == 逐目录并集：差集 0；
- 逐目录并集 == 全量 #1：差集 0。

**结论：当前条件下不存在「多出的 1 项」。「105 failed / 逐目录 104」暂未复现，保持“疑似当时的 flaky 或顺序依赖，未定位”的判断，未写“已不存在”。**

重复运行次数：全量 2 次、逐目录 8 次、evaluation 专项 2 次（当前代码）、HEAD 基线 2 次（见 §4）、失败用例单点复跑 9 项。

## 4. evaluation：当前代码 vs HEAD 失败集合

### 4.1 方法

无法在原地 `git checkout HEAD`（会破坏用户未提交改动），改用**隔离影子仓库**：

1. 复制 `backend/`（排除 `.pytest-tmp`、`__pycache__`）到 `backend/.pytest-tmp/p0-final/head-repo`；
2. 用 `git archive HEAD` 覆盖本次改动的 8 个源文件（其余文件均与当前工作区一致，包含未提交删除状态）；
3. `docs/var/corpus/fixtures/frontend` 等用目录联接指回当前工作区，保证测试夹具与真实删除状态一致；
4. `PYTHONPATH` 指向影子源码 + `-o pythonpath=`，并用「新增回归在 HEAD 下必然收集失败」验证 HEAD 代码确实生效。

### 4.2 结果

| 集合 | 数量 |
| --- | ---: |
| 当前代码 evaluation（failed 43 + errors 7） | 50 |
| HEAD 代码 evaluation（failed 58 + errors 16） | 74 |
| **新增（当前失败、HEAD 通过）** | **0** |
| **消失（HEAD 失败、当前通过）** | **24** |
| **共同失败** | **50** |

- 新增清单：空。
- 消失清单（24，均为 HEAD 侧环境差异，不计入本次修复成果）：
  - `test_p2_b0.py` 12 项（其中 9 项为 setup error）——HEAD 侧 `b0_link_rejected`（影子仓库目录联接被 `safe_path` 拒绝）；
  - `test_p2_h2_v3_f02_cli.py` 5 项、`test_p2_runner.py` 4 项、`test_p2_evidence_io.py` 1 项、`test_p2_h2_historical_audit.py` 1 项、`test_p2_holdout_plan.py` 1 项——同样属于影子仓库路径/联接/无 `.git` 元数据的环境差异。
- 共同清单 50 项：全部 50 项当前 evaluation 失败在 HEAD 侧同样失败。其中 11 项两侧失败文本逐字一致；39 项 HEAD 侧先被 `b0_link_rejected` 截断，但去掉该环境因素后仍会失败（当前侧证据见 §5）。

### 4.3 关于经理口径「100 failed + 83 errors」

该口径在本机当前工作区**无法精确复现**，可复现的两种运行条件是：

- 仓库外 basetemp：evaluation 43 failed + 7 errors（真实失败）；
- 仓库内 basetemp：evaluation 235 failed + 113 errors（其中 263 项为证据根/场景路径守卫，另有 44 项为工作区未提交删除导致的 `FileNotFound`）。

差异来源已定位为 basetemp 位置与用户未提交删除的文件，不是代码；因此不能用数量对齐代替集合对比，本报告以 nodeid 集合为准。

## 5. 55 项失败分类（均非本任务新增）

### evaluation（50 = 43 failed + 7 errors）

| 类别 | 数量 | 说明 |
| --- | ---: | --- |
| `FileNotFoundError`（未提交删除） | 44 | `docs/superpowers/plans` 38、`var/eval/baselines` 5、`docs/reports/OBS-EVAL/P2/T207-SAFE-DIAG-R1` 1。均在工作区被删除/缺失（`git status` 为 ` D` 或运行时数据不存在），HEAD 侧同样失败 |
| 冻结模块 SHA 不符 | 2 | `test_p2_empty_scope_proof`：`p2_hard_evidence.py` 实际 SHA 与测试冻结值不同；该文件未在本次改动中修改，HEAD 侧同样失败 |
| golden/采集契约漂移 | 4 | `test_cli` 退出码 3、`test_p0_acceptance` 的 `locator.cells` 与 golden 不一致、`test_p2_capture_contract_v02` 两项 `candidate_observation`；HEAD 侧失败文本逐字一致 |
| 其他 | 0 | — |

### 其他目录（5）

| nodeid | 原因 | HEAD 侧 |
| --- | --- | --- |
| `integration/test_t09_d4_same_value_sources.py::test_same_value_single_cited_source_answers_with_that_source` | 证据 `text` 为空，取不到“临时调整至”通知单元 | 同样失败 |
| `integration/test_t09_d4_same_value_sources.py::test_same_value_rejects_echo_from_uncited_row` | 同上 | 同样失败 |
| `rag/test_r2_observability_revision2.py::test_offline_index_capture_and_guard` | `.tmp-r2-obs-baseline/backend_src_mktkb_rag_answer.py` 缺失 | 同样失败 |
| `rag/test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan` | 当前授权预算 0.5 元 vs 断言 ≥3 元（真实授权文件状态） | 同样失败 |
| `unit/test_s2h_r3_official_profile.py::test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552` | 项目总上限 1000 元 vs 期望 40 元（真实授权文件状态） | 同样失败 |

**逐项定位结论：55/55 在当前与 HEAD 两套代码下均失败，新增 0；不做修复。**

## 6. 最小复现尝试

- 对 4 个非文件缺失的 evaluation 失败做单点复跑（`test_p0_acceptance`、两个 capture、`test_cli`）：单独运行均稳定失败，**不是顺序依赖**；
- 对 2 个 integration、3 个 rag/unit 失败做 HEAD 单点复跑：均失败，**与本次修复无关**；
- 全量两次、逐目录八次集合完全一致：**未发现 flaky 或跨目录顺序依赖证据**；
- 由于「多出的 1 项」本身未出现，未触发任何代码修改。

## 7. 代码改动

**本任务代码改动 0 个文件。** 未修改业务代码、测试、`.env`、启动脚本、授权/预算/账本或 `var` 数据；未放宽断言、未跳测、未删测。

## 8. 真实调用与受保护文件

- 真实 DeepSeek / DashScope / OCR 调用：**0 次**（全部 pytest 进程移除 `DEEPSEEK_API_KEY`，未运行任何 live 套件；acceptance/integration 的外网闸门用例通过）；
- `.env`：未修改（mtime 2026-11-01 22:15:57，早于本任务）；
- `一键启动.cmd`、`启动-真实问答.cmd`：未修改；工作区原有改动（2026-11-22 23:28）保持原样；
- GO、`budget.json`、`live-ledger.jsonl`、`authorization/`：未修改、未清空；
- `var/` 真实运行数据：未修改（SQLite mtime 仍为 2026-11-23 08:02:44 / 08:06:13）；
- 未提交删除的 1257 个文件：未恢复、未整理。

## 9. 风险与真实验收条件

剩余风险：

1. 44 项 evaluation 失败由用户未提交删除的文档/基线造成，恢复这些文件前无法得到全绿基线；
2. 冻结 SHA、golden、capture 契约失败属既有基线漂移，需另立任务处理；
3. 授权/预算状态（0.5 元、1000 元）与部分测试断言不一致，属环境口径问题；
4. 证据裁剪后的答案覆盖度风险按经理口径不在本任务返工，仍需真实验收观察是否出现步骤缺失或 `MODEL_OUTPUT_INVALID`；
5. HEAD A/B 使用影子仓库（含目录联接），「消失 24」不能证明修复收益，只能证明无新增。

具备条件：离线层面没有本次新增失败，代码侧满足「仅 1 次 DeepSeek 请求」真实验收的前提。**但真实验收必须等经理另行下达明确指令，本任务未发起、也不宣称真实服务已恢复。**

## 10. 证据文件

目录 `docs/reports/QA-P0-收尾核验-20261123/`：

- `current-full-outside.json` / `.log`：全量 #1
- `current-full-run2.json` / `.log`：全量 #2
- `perdir-*.json` / `.log`：8 个目录分别运行
- `current-eval.json` / `.log`：当前代码 evaluation
- `headcode-eval.json` / `.log`：HEAD 代码 evaluation（影子仓库）
- `current-full.json` / `.log`：仓库内 basetemp 对照（守卫失败对照）
- `failure-sets.json`：nodeid 集合、集合关系、新增/消失/共同清单
- `current-bad-list.txt`：55 项失败原因摘要
- `report_plugin.py`：机器可读报告插件
- 临时目录 `backend/.pytest-tmp/p0-final/` 已按要求清理，未删除其他目录
