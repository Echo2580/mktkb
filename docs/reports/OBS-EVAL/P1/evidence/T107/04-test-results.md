# T107 证据 04：测试预算与结果（§11A）

执行环境：Windows，仓库根目录 `D:\GPT项目\市场部AI知识库`，Python `.venv\Scripts\python.exe`（3.12.7）。
所有命令均 `-B`、`-p no:cacheprovider` 未启用（沿用目录默认）；未运行任何真实 provider。

## 1. 本包（新增测试文件）

```text
cd backend
..\.venv\Scripts\python.exe -B -m pytest tests/evaluation/test_regression_suite.py -q
```

结果：`10 passed, 1 warning in 1.21s`（warning 为既有 Starlette/httpx 弃用提示）。

## 2. 受影响目录（evaluation）

```text
cd backend
..\.venv\Scripts\python.exe -B -m pytest tests/evaluation -q
```

结果：`330 passed, 1 warning in 17.18s`，0 failed / 0 error。

## 3. 全量 `backend/tests`

**NOT-RUN（资源门槛）**：按 handoff §6.6，全量前检查 `FreePhysicalMemory`；本机为
`1.179 GB`（2026-11-05T22:37:47+08:00）与 `1.171 GB`（2026-11-05T22:43:13+08:00），
均 **< 2 GB**，故未启动全量 pytest，避免与其它应用争内存导致 OOM/假失败。
未用 skip/xfail/删断言替代；受影响目录 `backend/tests/evaluation` 已全绿。

## 4. 其它核对

```text
git diff --check                      -> exit 0
git diff --exit-code -- fixtures/evaluation/b0.jsonl fixtures/evaluation/badcase.jsonl -> exit 0
```

- 无 skip/xfail：`Select-String -Path backend\tests\evaluation\test_regression_suite.py -Pattern 'skip|xfail'`
  无输出（无 `pytest.mark.skip` / `pytest.mark.xfail`）。
- 未修改 `docs/evaluation/gate_v0_1.json`、`fixtures/evaluation/{b0,badcase}.jsonl`、`observability/`、业务代码。
- 新增生产依赖：无。
