# T101 证据 03：测试运行记录（最终状态，每组 1 次）

- 分支 `p1/fix-retrieval`；环境 `PYTHONPATH=backend/src`、`.venv\Scripts\python.exe`（Python 3.12.7）、`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`。
- 所有 run 均为 offline；未读 `.env`，未调用真实模型/embedding/rerank/OCR。

## A. 本包测试（1 次）

```text
cd backend
..\.venv\Scripts\python.exe -B -m pytest tests/unit/test_p1_t101_intent_vocab.py tests/unit/test_p1_t101_document_answer.py tests/integration/test_p1_t101_vocab_context.py -q
```

```text
...........
11 passed, 1 warning in 5.90s
```

- 覆盖：意图层法规优先/泛化词语境/明确字段保持（5 例）；法规题整段 + 非法规题单句逐字节不变（2 例）；产品路径 6 题不截断、E120 三值+来源、宣传海报采购价格仍 not_found、门店+物品的价格仍 not_found（4 例）。

## B. integration 目录（1 次；最终状态复跑 1 次）

```text
cd backend
..\.venv\Scripts\python.exe -B -m pytest tests/integration -q
```

```text
349 passed, 1 warning in 287.92s (0:04:47)      # 首次
348 passed, 1 failed, 1 warning in 289.81s       # 裁定 A 后复跑
FAILED tests/integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call
```

- `test_g08` 是 0.2s 总预算 vs 2s 慢模型的时序用例；复跑时 `gateway.calls==0`（请求在模型调用前已被预算取消），与本包改动无关。隔离复跑 1 次：

```text
..\.venv\Scripts\python.exe -B -m pytest "tests/integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call" -q
1 passed, 1 warning in 2.31s
```

- 含 `tests/integration/test_chat.py::test_g03_negative_not_found_without_fabrication`（`test_chat.py:401`「宣传海报的采购价格是多少？」→ `not_found`）与 `test_s2b_intent_semantics.py`（标识/裸补槽语义）。

## C. 全量（1 次，最终状态）

```text
cd backend
..\.venv\Scripts\python.exe -B -m pytest tests -q
```

```text
1 failed, 1613 passed, 1 warning in 421.86s (0:07:01)
FAILED tests/integration/test_lifecycle.py::test_concurrent_publish_and_global_revision_cas[v05]
```

- 运行前 `FreePhysicalMemory=3.0GB`（≥2GB，未触发 NOT-RUN）。
- 该失败是 handoff §11A 点名的既有 flake（并发发布 CAS 竞态，`delays` 打点未生效，v04 抢先）。隔离复跑 1 次：

```text
..\.venv\Scripts\python.exe -B -m pytest tests/integration/test_lifecycle.py::test_concurrent_publish_and_global_revision_cas -q
2 passed, 1 warning in 2.49s
```

- 按 §11A 只记录、不据此返工；本包改动（意图词表/字段识别/法规题整段抽取）不涉及发布事务与并发锁。

## D. 评测 run/gate（b0 / badcase / regression）

```text
$env:PYTHONPATH="backend/src"
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite <suite> --mode local --out <tmp>
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run <tmp>
```

| suite | 修复前 | 修复后（最终状态） |
| --- | --- | --- |
| b0 | pass 29 / fail 3 / skipped 8；hard `[]`；exit 3 | 同左（逐例 0 变化） |
| badcase | pass 9 / fail 4；hard `[]`；exit 3 | 同左（逐例 0 变化） |
| regression | fail 7；hard `['security_leak','pagination_contract']`；exit 1 | pass 1（RG001）+ fail 6；hard 同左；RG001 clarification→pass |

- 逐例比较脚本只读 `cases.jsonl` 的 `(status, outcome.kind)`；b0/badcase diff 为空；regression RG002–RG007 失败 checks 逐条不变。
- RG001 转正的证明链（整段抽取 + reference_answer 补发布日）见证据 04。
