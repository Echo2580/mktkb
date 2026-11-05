# T107 独立复跑：测试结果（handoff §6.6）

- 环境：`D:\GPT项目\市场部AI知识库`，`.venv\Scripts\python.exe`（3.12.7，Windows）。
- 每次 pytest 前设置 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；命令统一为
  `.\.venv\Scripts\python.exe -B -m pytest <target> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`，
  工作目录为项目根。
- 未调用真实模型/embedding/rerank/OCR；未读 `.env`/Holdout。

## 内存门槛（`Get-CimInstance Win32_OperatingSystem`）

| 时刻（+08:00） | FreePhysicalMemory | 动作 |
| --- | --- | --- |
| 2026-11-05T22:45:22 | 1.098 GB（<2.0） | 等待，未启动 pytest |
| 2026-11-05T22:46:19 | 3.025 GB（≥2.0） | 开始复跑 |
| 全量 run1 前 / 后 | 2.881 GB / 3.137 GB | 启动并完成 |
| 全量 run2 前 / 后 | 2.521 GB / 2.800 GB | 启动并完成 |

无 NOT-RUN 项。

## 1. 本包

```text
.\.venv\Scripts\python.exe -B -m pytest backend\tests\evaluation\test_regression_suite.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t107-pkg
```

`10 passed, 1 warning in 1.49s`（warning 为既有 Starlette/httpx 弃用提示），0 failed / 0 error。

## 2. 受影响目录

```text
.\.venv\Scripts\python.exe -B -m pytest backend\tests\evaluation -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t107-eval
```

`330 passed, 1 warning in 27.20s`，0 failed / 0 error。

## 3. 全量 run1

```text
.\.venv\Scripts\python.exe -B -m pytest backend\tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t107-full
```

`1 failed, 1602 passed, 1 warning in 378.30s`。

失败项：`backend\tests\integration\test_lifecycle.py::test_concurrent_publish_and_global_revision_cas[v05]`
（`test_lifecycle.py:759 assert winners == [winner]`，实际 `v04` 赢、`v05` 得 `PUBLISH_CONFLICT`）。

归属核查：

- `git diff --stat 366046d..HEAD -- backend/tests/integration/test_lifecycle.py` 无输出；该文件自 `366046d` 未改，`git blame` 全部指向 `366046d`。
- 该测试未导入 `mktkb.evaluation`（`Select-String -Pattern 'evaluation|mktkb.eval'` 无命中），与本 commit 改动面无交集。
- 单独复跑该 nodeid 3 次：`2 passed` ×3（两个参数均通过，每次 2.5s 左右）。

## 4. 全量 run2（flaky 判定）

```text
.\.venv\Scripts\python.exe -B -m pytest backend\tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\t107-full2
```

`1603 passed, 1 warning in 441.00s`，0 failed / 0 error。

结论：run1 的唯一失败是并发发布用例的负载相关时序 flaky（未触碰本包代码，单测与全量复跑均绿），
不是 T107 引入的回归；全量存在该既有 flaky 风险。验收预算上，本次全量执行了 2 次（§11A 只列 1 次），
第 2 次用于区分 flaky 与本包回归，已如实记录。
