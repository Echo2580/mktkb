# T103 独立验收证据 01：pytest 复跑

- 环境：Windows，仓库根 `D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`，HEAD `dcb7054`（交付 commit `43b7976`）；工作区 clean。
- 命令：工作目录仓库根，`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`、`$env:PYTHONPATH="backend/src"`，`.venv\Scripts\python.exe -B -m pytest <paths> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`。
- 零真实 provider：pytest 全部由 `backend/tests/conftest.py` 注入离线替身（`chat_model` / `EvidenceEchoGateway`），未读 `.env`、未接触 Holdout。

## A. 本人复跑

| # | 范围 | 结果 | 耗时 | basetemp |
| --- | --- | --- | --- | --- |
| 1 | `backend/tests/unit/test_p1_t103_record_fallback.py` + `backend/tests/integration/test_p1_t103_record_fallback_http.py` | **6 passed** | 1.70s | `t103-pkg` |
| 2 | `backend/tests/unit` | **306 passed** | 6.92s | `t103-unit` |
| 3 | `backend/tests/integration` | 首次 **352 passed + 1 failed**；隔离复跑 **1 passed** | 280.44s / 1.47s | `t103-int` / `t103-g08` |
| 4 | `backend/tests/observability` | **255 passed** | 17.50s | `t103-obs` |
| 5 | `backend/tests`（全量） | **1640 passed, 0 failed, 0 error** | 425.35s（7:05） | `t103-full` |

## B. 唯一失败 = 既有 flake（§11A 隔离复跑 1 次通过）

```text
FAILED backend\tests\integration\test_chat.py::test_g08_short_budget_cancels_inflight_model_call
隔离复跑：1 passed, 1.47s
```

- 该用例断言 0.2s 总预算下模型调用已进入，属时序 flake；T101/T102 验收记录有同名 flake，非本包新增。
- 开发 report §3 写 `tests/integration 353 passed`；本人首次整跑为 352 passed + 1 已知 flake，隔离复跑通过后合计 353，无失败用例差异（仅计数口径）。

## C. 与开发自述对照（只作核对，不作证据）

| 项 | 开发 report | 本人复跑 | 一致 |
| --- | --- | --- | --- |
| 本包 | 6 passed | 6 passed | 是 |
| unit | 306 passed | 306 passed | 是 |
| integration | 353 passed | 352+1 flake；隔离 1 passed | 是（计数口径） |
| observability | 255 passed | 255 passed | 是 |
| 全量 | 1640 passed | 1640 passed | 是 |

结论：**PASS**（无新增失败；既有 flake 隔离复跑通过）。
