# T110 证据 04：测试结果、资源与合规

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

环境：Windows；仓库根 `D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；
每次 pytest 均设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，带 `-B -q -p no:cacheprovider
--basetemp backend\.pytest-tmp\<label>`；同一时间只跑一套 pytest；零真实模型/embedding/rerank/OCR 调用。

## A. pytest

| 范围 | label | 结果 |
| --- | --- | --- |
| 本包 `test_p1_t110_retrieval_metrics.py` | `t110-pkg1` | **17 passed / 0 failed**（1.72s） |
| `test_scorers.py` + `test_gold.py` + 本包 | `t110-targeted2` | **100 passed / 0 failed**（2.32s） |
| `backend/tests/evaluation` | `t110-eval1` | **409 passed / 0 failed / 0 error**（95.25s；T109 基线 392 + 17） |
| 全量 `backend/tests`（第 1 次） | `t110-full1` | 1811 passed / **1 failed**（447.35s）→ 见下 flake |
| 全量 `backend/tests`（第 2 次，内存证据） | `t110-full3` | **1812 passed / 0 failed / 0 error**（448.35s） |

**flake（既有，非本包）**：full1 唯一失败为
`integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call`
（`len(calls)==0`，时序竞态；`_index` #40 与 T005/T107/T108 记录为既有 flake，该文件自
`366046d` 未改、不导入 `mktkb.evaluation`）。按 §11A 隔离复跑 1 次：**1 passed（1.20s）**，
未重跑整套；full2 全绿，未复发。

**内存**：full 第 2 次（label `t110-full3`；`t110-full2` 被下述作废的测量尝试占用）期间
每 30s 轮询 pytest 进程（含 venv launcher 与实际 3.12.7 解释器）的 `PeakWorkingSet64`，
16 个样本覆盖 448s，峰值 **523.5 MB < 2 GB**
（样本 MB：0, 299.4, 335.3, 351.7, 453.2×4, 501.8×2, 523.5×6）。

**测量方法说明**：曾尝试用 `pytest.main()` 进程内包装 + ctypes 取峰值；因缺少
`__main__` 保护，multiprocessing spawn 子进程复跑包装脚本，产生 1110 个 measurement
error，该次数据**作废**（非代码失败）。最终以「CLI 全量 + 外部 30s 轮询」为准（full2）。

## B. 本包测试覆盖（17 条）

- 同 chunk 同排名：1 chunk 3 unit 其中 2 相关（nDCG=1/IDCG(2)）；相关 unit 位于 chunk
  第 3 条时 MRR=1（非 1/3）。
- unit 去重：跨 chunk 重复 unit 只计一次；重复 chunk 占位但不计 gain；`retrieved_units` 去重。
- 部分命中（3/4）、空召回（empty_recall=1）、top-10 按 chunk（第 11 chunk 的命中为 0）。
- 硬过滤违规率（2/3）与无 gold case 剔出所有检索分母。
- 7 案手算整表（证据 02）逐值断言 + `aggregate_metrics` 五字段兼容。
- `relevant_units`：override / 回退 `expected_sources` / 两者皆空无金标 / `unit_key` 0 命中 /
  `unit_key` 重复 / locator identity 冲突 / `record_code`-only / locator 范围返回 unit 集合。

## C. 合规核对

- 只改 handoff §2 允许路径：`evaluation/{gold,scorers}.py`、`backend/tests/`（新增 1 文件，
  既有 `test_scorers.py` 1 条 nDCG 期望按新口径更新——**更新而非删除**，并新增 `retrieved_units`
  断言）、证据 4 份、`report.md`。
- `gate.py` 未改：已消费五个检索指标（`gate.py:1957/2047-2065`），字段名与 P0 兼容；
  阈值/审批未动（T112）。
- 未改 `docs/evaluation/gate_v0_*.json`、b0/badcase/regression 数据、业务代码/API/intent、
  账本/GO、`.env`/Holdout；证据与报告只含合成 case/P0 冻结 run 的聚合数字。
- 未新增依赖；无 `pytest.mark.skip/xfail`；未 push/amend；开工前 `git status --short` 为空；
  单 commit。
