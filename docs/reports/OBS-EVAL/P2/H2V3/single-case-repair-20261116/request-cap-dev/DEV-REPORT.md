# CAP-UNLIMITED 开发交付（2026-11-16）

## 状态

已实现并完成部分定向开发自测；**完整产品接线回归未完成，不能判定端到端开发验证通过，更不是独立验收或 T207 通过**。按主人要求到此停止，不启动 C26/R0。没有执行私有计划生成、check-only、run、签发 GO 或真实模型请求。

## 数量语义

- P2 plan 和 GO 的 `max_requests` 明确使用 JSON 字符串 `"unlimited"`；预检和授权的剩余次数使用相同字符串。字段缺失、布尔、零、负数、其他字符串及 NaN 均拒绝；既有有限整数及 1600 有限硬顶保持。v3 新计划入口仅接受显式 unlimited，CLI 缺省也是该值。
- 无限计划配有限 GO 拒绝；有限计划配无限 GO 仍按计划有限值。新 GO 与新计划仍须经过现有计划哈希、期限、身份、nonce、路径和预算检查；旧 GO 不自动获得无限权限。
- 无限模式 P2Gate 在账本同一锁内按 `run_id` + `plan_sha256` + `item_id` 统计预留，重开 gate 也不允许超出该计划项次数；相同 run_id 的不同计划摘要分别计数。同 run_id 的历史预留缺计划摘要时拒绝。P2 live 原有 AttemptBudget、操作集合、首错停及零重试仍在。
- 共享账本无限模式仅接受 P2-LIVE 明确字符串，且预留时必须有逐笔守卫；有限账本不能由无限单笔参数放宽。金额计算和金额常量未修改。v3 计划/配置/CLI 在合成测试中一致；完整 v3 绑定文档与产品执行链尚未完成测试。

## 自测证据

所有以下正常完成的测试都使用 `guarded_pytest.py`、合成计划/GO/账本和假发送，父进程中清除代理、禁 dotenv 加载；本机 socket、显式 `urllib ProxyHandler({})` 和 `httpx trust_env=False` 正对照被拦截。守卫为 Windows asyncio 的 socketpair 创建提供内部例外，普通本机连接仍被正对照拦截。**子进程不受该脚本保证**，下述首次跨进程测试不计入零出站证明。

| 证据 | 命令参数（均以 `.venv/Scripts/python.exe -B guarded_pytest.py -p no:cacheprovider` 开始，`PYTHONPATH=backend/src`） | 结果 |
|---|---|---|
| `red2.txt` | `-q test_request_cap.py` | 退出 1，预期红例：旧合同拒绝 `unlimited`；守卫记录 0 次测试网络尝试 |
| `red-item.txt` | `-q test_request_cap.py::test_unlimited_gate_never_exceeds_item_attempts_even_after_reopen` | 退出 1，预期红例：重开 gate 后重复计划项未被拒绝 |
| `final-tests.txt` | `-q test_request_cap.py` | 退出 0，28 passed；守卫记录 0 次测试网络尝试 |
| `collect.txt` | `--collect-only -q test_request_cap.py` | 退出 0，收集 28 项 |
| `regression3.txt` | `-q backend/tests/evaluation/test_p2_authorization.py backend/tests/evaluation/test_p2_holdout_plan.py` | 退出 0，76 passed，1 个上游弃用警告 |
| `attempt.txt` | `-q` 对 `test_plan_index_and_attempt_budget_fail_closed` 和 `test_p2_live_request_ceiling.py` 的三个同步额度检查 | 退出 0，4 passed，1 个上游弃用警告 |

命令中的测试文件位于本目录，完整输出、测试名称及各次 basetemp 路径见对应日志。最终 28 项包括：1601 笔合成历史预留后预检、预留、假发送和结算；有限/无限组合、非法输入、序列化、CLI/配置一致；项目、阶段、成本中心、GO 单笔额度拒绝；按 8.5/6.5/3/2 成本中心拒绝超额；同计划重开拒绝与新计划摘要隔离。测试金额边界是在合成 GO 约束下验证；未证明任意不符合当前 v3 固定计划的 GO 都满足 0.5 元上限。

首次较宽回归 `regression1.txt` 退出 1：83 passed、4 failed。三个异步用例因守卫阻止 Windows 内部 socketpair 而未运行到产品断言，跨进程账本测试亦失败；该跨进程测试使用 multiprocessing spawn，父进程守卫不覆盖子进程，因此这次执行不作为完整零出站证明。调整 socketpair 后 `regression2.txt`、`live1.txt`、`live2.txt` 停滞并被手动中断，没有完整结果，未计为通过；未进行全仓测试。开发守卫及定向验证仍需独立复核，尤其是完整异步产品接线、真实 v3 绑定解析/复算以及跨进程情形。

## 文件与冻结漂移

本轮源码增量仅为 `backend/src/mktkb/evaluation/p2_contracts.py`、`p2_authorization.py`、`p2_holdout_plan.py`、`p2_runner.py`、`backend/src/mktkb/rag/budget.py` 和原本 untracked 的 `tools/p2_h2_v3_controlled_execute.py`。这些文件因本轮累计次数语义允许发生新漂移，旧 freeze 不回填；所有源码前后哈希见 `baseline-hashes.txt`、`final-hashes.txt`。未改评分器、题目、语料或来源 matcher。

`baseline-tracked.diff` 和 `baseline-status.txt` 保存原现场；`incremental.diff` 是本轮六文件增量。五个 tracked 源基线与 v3 未跟踪入口基线均经 SHA-256 与修改前记录匹配（`reconstructed-hashes.txt`，v3 由 `reconstruct_v3_baseline.py` 校验），原有 25 项 tracked 修改保留。`git diff --check` 全工作树退出 1，输出含既有修改的尾随空白，不能称全树检查通过。

预算 `budget.json` 前后均为 `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`；共享账本前后均为 `e564106329ece3cf0d3a0158cbfd321dbfc0a24f1b05b7829c01a7acced6b656`。只计算哈希，未重置 1413 条历史预留或修改真实预算、账本、GO、slot、pending 和历史证据。未改变项目 40 元、阶段 20 元、单笔 0.5 元或 8.5/6.5/3/2 的目标额度。
