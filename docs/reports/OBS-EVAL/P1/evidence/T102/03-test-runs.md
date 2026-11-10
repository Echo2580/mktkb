# T102 证据 03：测试运行与预算

环境：Windows，仓库根 `D:\GPT项目\市场部AI知识库`，Python `.venv\Scripts\python.exe`（3.12.7）。
所有 pytest 命令均带 `-B`、`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；零真实模型/embedding/rerank/OCR 调用。

| # | 范围 | 命令（cwd） | 结果 |
| --- | --- | --- | --- |
| 1 | 本包（新增 2 文件） | `cd backend; ..\.venv\Scripts\python.exe -B -m pytest tests/rag/test_p1_t102_state_inheritance.py tests/integration/test_p1_t102_state_inheritance.py -q` | **20 passed**，5.17s（仓库根等价命令同结果 2.55s） |
| 2 | `backend/tests/rag` | `cd backend; ..\.venv\Scripts\python.exe -B -m pytest tests/rag -q` | **326 passed**，22.53s，0 failed/0 error |
| 3 | `backend/tests/integration` | `cd backend; ..\.venv\Scripts\python.exe -B -m pytest tests/integration -q` | 最终 **351 passed**，289.20s |
| 4 | `backend/tests/observability` | `cd backend; ..\.venv\Scripts\python.exe -B -m pytest tests/observability -q` | **255 passed**，20.49s；trace path/outcome 未被破坏 |
| 5 | 全量 `backend/tests` | `cd backend; ..\.venv\Scripts\python.exe -B -m pytest tests -q` | **1634 passed**，438.56s，0 failed/0 error |

## 既有 flake 隔离复跑

- 第 3 项首次运行：**350 passed + 1 failed** `tests/integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call`（T101 报告已记录的时序 flake：0.2s 预算下模型调用未进入）。
- 隔离复跑 1 次：`python -B -m pytest "tests/integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call" -q` → **1 passed**，1.84s。
- 最终整套重跑：**351 passed**（无失败）。未使用 skip/xfail/删断言/放宽。

## 资源与清洁检查

- 全量前内存轮询：`FreePhysicalMemory=2.63 GB`（≥2GB 门槛）；全量运行期间未 OOM。
- `git -c core.whitespace=cr-at-eol diff --check` → exit 0（仓库 `query.py` 为 CRLF，默认 `diff --check` 会把 CR 误报为行尾空白；用 `cr-at-eol` 口径核对）。
- 新增测试无 `pytest.mark.skip` / `xfail`；无真实 provider 构造；未读 `.env`/Holdout。
