# T101 独立复跑证据 01：pytest

- 环境：`p1/fix-retrieval`，HEAD `a7282b3`；`.venv\Scripts\python.exe`（Python 3.12.7）；项目根。
- 每次 pytest 前：`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；`PYTHONPATH=backend/src`。
- 命令统一：`python -B -m pytest <paths> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`。

## A. 本包测试（1 次）

```text
backend/tests/unit/test_p1_t101_intent_vocab.py
backend/tests/unit/test_p1_t101_document_answer.py
backend/tests/integration/test_p1_t101_vocab_context.py
backend/tests/integration/test_chat.py::test_g03_negative_not_found_without_fabrication
```

```text
............                                                             [100%]
12 passed, 1 warning in 7.58s
```

- 3 个 T101 文件本身 11 例；额外加入 `test_chat` 的 g03 节点（含 `test_chat.py:401`「宣传海报的采购价格是多少？」→ `not_found`）共 12 例。
- 该 g03 节点另单独复跑：`1 passed in 2.05s`（含 7 个 not_found 负例，`sources==[]`，无模型调用）。

## B. integration 目录（1 次）

```text
backend/tests/integration
```

```text
349 passed, 1 warning in 277.73s (0:04:37)
exit 0
```

## C. 全量 `backend/tests`（1 次）

```text
FreePhysicalMemory_GB=2.87
backend/tests
1614 passed, 1 warning in 398.84s (0:06:38)
exit 0
```

- 0 failed / 0 error；未出现开发方报告记录的 2 个既有 flake（`test_g08_short_budget...`、`test_lifecycle...`）。
- 内存 2.87GB ≥ 2GB，未触发 NOT-RUN。

## D. 只读定位

- `test_chat.py:401` 的文本经 Python 读取确认为「宣传海报的采购价格是多少？」；该用例 `test_g03_negative_not_found_without_fabrication` 在 A 中通过。
- 新增测试文件无 `skip`/`xfail`/`pytest.mark`；commit 未修改既有测试文件（`git show --name-only a7282b3 -- backend/tests` 仅三个新文件）。
