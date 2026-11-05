# T104 证据 03：测试与 local run/gate 前后对照

环境：Windows，仓库根 `D:\GPT项目\市场部AI知识库`，Python `.venv\Scripts\python.exe`（3.12.7）。
除特别注明外均带 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；零真实模型 / embedding / rerank / OCR 调用。
所有 pytest 命令 cwd=`backend`。

## A. 测试

| # | 范围 | 命令 | 结果 |
| --- | --- | --- | --- |
| 1 | 本包（unit 29 + integration 9） | `..\.venv\Scripts\python.exe -B -m pytest tests/unit/test_p1_t104_error_classification.py tests/integration/test_p1_t104_error_classification_http.py -q` | **38 passed**，8.89s |
| 2 | `tests/unit` | `..\.venv\Scripts\python.exe -B -m pytest tests/unit -q` | **335 passed**，8.78s，0 failed/0 error |
| 3 | `tests/observability` | `..\.venv\Scripts\python.exe -B -m pytest tests/observability -q` | **255 passed**，19.25s（trace reason/error_code 与响应一致；既有断言未改） |
| 4 | `tests/integration` | `..\.venv\Scripts\python.exe -B -m pytest tests/integration -q` | **361 passed / 1 failed**，267.67s；唯一失败为已知 flake（见 B） |
| 5 | 全量 | `..\.venv\Scripts\python.exe -B -m pytest tests -q` | **1678 passed**，432.64s，0 failed/0 error；全量前 `FreePhysicalMemory=2.98 GB` |

- 未使用 `skip`/`xfail`/删断言；新增测试无真实 provider 构造，未读 `.env`/Holdout；未新增生产依赖。

## B. 既有 flake 隔离复跑

- 第 4 步失败：`tests/integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call`（0.2s 总预算 vs 慢网关的时序断言）。该用例在 T103 证据 03 已登记为既有 flake。
- 隔离复跑：`..\.venv\Scripts\python.exe -B -m pytest "tests/integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call" -q` → **1 passed**，1.50s。
- 全量（第 5 步）同用例通过，证明非本包引入；失败与通过两次的断言点均为 `elapsed < 1.0 / MODEL_TIMEOUT` 时序，不涉及 error_code 分类。

## C. b0 / badcase / regression local run + gate 前后对照

命令见证据 01；修复后输出目录 `%TEMP%\t104-post\<suite>`。

| suite | 修复前 run_id | 修复后 run_id | 修复前 status | 修复后 status | 修复后 gate | 逐例差异 |
| --- | --- | --- | --- | --- | --- | --- |
| b0 | `b0-local-20261105T190107872966Z-359ed37c` | `b0-local-20261105T192123861912Z-ede10da1` | pass 29 / fail 3 / skipped 8 | **pass 29 / fail 3 / skipped 8** | exit 3，hard `[]` | **0** |
| badcase | `badcase-local-20261105T190118167843Z-c1aad3e1` | `badcase-local-20261105T192133513288Z-018e3089` | pass 9 / fail 4 | **pass 9 / fail 4** | exit 3，hard `[]` | **0** |
| regression | 前包基线（T103 证据 03）：pass 3 / fail 4，hard `['security_leak']` | `regression-local-20261105T192213355912Z-4a2f2f3c` | — | pass 4 / fail 3 | exit 1，hard `['security_leak']` | 与 T103 收口一致；RG001–RG004 pass，RG005–RG007 仍 fail |

- 逐例比较口径：`(case_id, status, outcome.kind, failed check ids)`；b0/badcase 两套件 `case_diffs=0`，hard failures 无新增。
- 修复后 regression 明细：RG001 pass / RG002 pass / RG003 pass / RG004 pass；RG005 `kind=answer`，失败 checks `kind_correct,refusal_expected`（见证据 04 的“营收未短路”残余声明）；RG006 `value_forbidden,kind_correct`；RG007 `kind_correct,refusal_expected`。
