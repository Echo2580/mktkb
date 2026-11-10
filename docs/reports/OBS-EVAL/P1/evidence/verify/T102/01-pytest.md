# T102 独立验收证据 01：pytest 复跑

- 环境：Windows，仓库根 `D:\GPT项目\市场部AI知识库`，`.venv\Scripts\python.exe` 3.12.7；分支 `p1/fix-retrieval`，HEAD `85d9ffc`；工作区 clean。
- 全部命令：工作目录仓库根，`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`，`-B -m pytest <paths> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`。
- 零真实模型/embedding/rerank/OCR：pytest 使用 `tests/conftest.py` 的离线替身；evaluation 使用 `provider_mode=offline`。
- 全量前内存 `FreePhysicalMemory=2.7 GB`（≥2GB）；全量期间未 OOM。

## A. 运行结果（本人复跑）

| # | 范围 | 结果 | 耗时 | basetemp |
| --- | --- | --- | --- | --- |
| 1 | `backend/tests/rag/test_p1_t102_state_inheritance.py` + `backend/tests/integration/test_p1_t102_state_inheritance.py` | **20 passed** | 2.13s | `t102-pkg` |
| 2 | `backend/tests/rag` | **326 passed** | 21.88s | `t102-rag` |
| 3 | `backend/tests/integration` | 首次 **350 passed + 1 failed**；隔离复跑 **1 passed** | 265.19s / 1.48s | `t102-int` / `t102-g08` |
| 4 | `backend/tests/observability` | **255 passed** | 17.71s | `t102-obs` |
| 5 | `backend/tests`（全量） | **1634 passed, 0 failed, 0 error** | 394.71s | `t102-full` |

## B. 唯一失败 = 既有 flake（按 §11A 隔离复跑 1 次）

```text
FAILED backend\tests\integration\test_chat.py::test_g08_short_budget_cancels_inflight_model_call
assert 0 == 1  # gateway.calls 未进入（0.2s 预算时序）
隔离复跑：python -B -m pytest ".../test_chat.py::test_g08_short_budget_cancels_inflight_model_call" -q
        → 1 passed, 1.48s
```

- 该用例与 T102 无关：改的是 0.2s 总预算下模型调用是否已进入；T102 未改 `conversations/`、`qa/`、模型路径。
- 与 T101 验收记录、T102 report §3 的同一 flake 名称/症状一致，非新增失败。

## C. 与开发自述对照（只作核对，不作证据）

| 项 | 开发 report | 本人复跑 | 一致 |
| --- | --- | --- | --- |
| 本包 | 20 passed | 20 passed | 是 |
| rag | 326 passed | 326 passed | 是 |
| integration | 351 passed（先 350+1 flake，再整跑） | 350+1 flake，隔离复跑 1 passed | 是 |
| observability | 255 passed | 255 passed | 是 |
| 全量 | 1634 passed | 1634 passed | 是 |

结论：**PASS**（无新增失败；既有 flake 隔离复跑通过）。
