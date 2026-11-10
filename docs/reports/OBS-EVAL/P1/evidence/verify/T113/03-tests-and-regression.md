# T113 独立验收证据 03：测试、回归、门禁与合规

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`（验收方，非交付物）

## A. pytest（cwd=仓库根；每次前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`）

验收环境的 `backend\.pytest-tmp` 对本进程不可写（`mkdir` → `PermissionError`），
且本沙箱把 POSIX `0o700` 映射为创建者自己也无法进入的 ACL（pytest 的 `tmp_path` /
评测临时索引会失败）。因此验收使用两个**不改交付物**的进程内 shim：
`_scratch/pytest_runner.py` 把临时目录 mode 强制 0o777 后调用 `pytest.main`；
`_scratch/eval_shim.py` 同法调用 evaluation CLI。测试代码、业务代码、交付物未改。

| 范围 | 命令（摘要） | 结果 |
| --- | --- | --- |
| 本包 `tests/observability/test_routes.py` | `python -B _scratch\pytest_runner.py backend/tests/observability/test_routes.py -q -p no:cacheprovider --basetemp _scratch\pt113v-routes2` | **35 passed**, 1 warning, 12.42s |
| `tests/observability` | 同上 `backend/tests/observability` | **290 passed**, 1 warning, 27.39s |
| 全量第 1 次（未 patch `os.mkdir`） | 同上 `backend/tests` | 1755 passed, **85 failed / 18 errors**, 759.09s |
| 全量第 2 次（patch `os.mkdir`） | 同上 `backend/tests` | 1812 passed, **46 failed**, 505.08s |

全量第 2 次的 46 个失败**全部是环境写权限**，不是 T113 代码：

```text
43 × backend/tests/acceptance/test_t09_*  -> PermissionError:
     docs\evidence\T09\D1\actual\...（T09 证据目录对本进程只读）
3  × backend/tests/rag/test_budget*.py / test_s4_stage_limit.py -> PermissionError:
     docs\evidence\LOCAL-R1-20261101\budget\live-ledger.jsonl.lock
```

无任何 `backend/tests/observability` / `test_routes.py` 失败；两次全量的总数
（1755+103=1858、1812+46=1858）与开发自报 1858 条一致。第 1 次的 18 个 error 是
`%TEMP%\mktkb-eval-*`/`mktkb-eval-holdout-*` 的 0o700 目录不可进入；第 2 次 patch
后消失，进一步证明是环境而非代码。既有 flake
`test_g08_short_budget_cancels_inflight_model_call` 与
`integration/test_lifecycle.py::test_concurrent_publish_and_global_revision_cas[v05]`
在本轮全量中未失败，未触发隔离复跑。**全量结论：BLOCKED（环境），不是 PASS；**
T113 相关测试全绿，且无失败落在 T113 路径。

## B. b0 / badcase / regression local + gate

命令（cwd=仓库根；`_scratch/eval_shim.py` 仅 workaround 0o700；CLI 自身零真实调用）：

```text
python -B _scratch\eval_shim.py run  --suite <b0|badcase|regression> --mode local --out _scratch\eval\T113\<suite>
python -B _scratch\eval_shim.py gate --run _scratch\eval\T113\<suite> --config docs\evaluation\gate_v0_1.json
```

| suite | rows | 当前 run_id | gate |
| --- | ---: | --- | --- |
| b0 | 40/40 | `b0-local-20261109T092816796765Z-9aa3b4cf` | exit 3, hard `[]`, unknown 42 |
| badcase | 13/13 | `badcase-local-20261109T092823510029Z-2c592086` | exit 3, hard `[]`, unknown 94 |
| regression | 7/7 | `regression-local-20261109T092915927679Z-d0791bab` | exit 3, hard `[]`, unknown 80 |

逐例签名 `(status, outcome.kind, sorted(check_id,status), error.code)` 与
retrieved 单位集合（`_scratch/compare_runs.py`）：

```text
b0          vs var\eval\runs\p0-b0               signature_diffs=0  retrieved_diffs=0
badcase     vs var\eval\runs\p0-badcase          signature_diffs=0  retrieved_diffs=0
regression  vs backend\.pytest-tmp\T109-R2\eval\regression-current
                                                  signature_diffs=0  retrieved_diffs=0
```

regression 基线取 T109-R2 的收口运行（`var/eval/runs` 只有 p0-b0/p0-badcase，没有
p0-regression）；gate 基线 hard 均为 `[]`、unknown 42/94/80，与当前一致。exit 3 仍是
既有 `min_sample`/阈值未审批（T112），不是本包新增硬失败。

## C. 范围 / 合规 / 形式

- `git show --stat 9edc003`：**9 files, +2101**；全部在 handoff 允许路径
  （`observability/routes.py`、`observability/store.py`、`main.py`、本包测试、
  `report.md`、4 份证据）。`git diff 10bb42b..9edc003 -- pyproject.toml backend/pyproject.toml uv.lock` 为空；无新依赖。
- 单个 dev commit `9edc003`（父 `10bb42b`）；`git diff 9edc003..HEAD --stat` 只动
  `.claude/handoffs/**`（PM 簿记）。tracked 工作树 clean；`_scratch/` 与既有 T114
  handoff 为未跟踪（验收临时探针，不入交付）。
- 本包测试是新增文件，无 `pytest.mark.skip/xfail`、无删改既有断言；证据 4 份、
  `report.md` 80 行、五段。**报告/证据 01 把父提交写成 `fcc3434`（实际 `10bb42b`）**，
  属文档笔误（LOW，非代码缺陷）。
- 零真实模型/embedding/rerank/OCR：所有探针用 `Settings(_env_file=None)` 与 fake/offline；
  evaluation 三套 local 用离线索引；未打印/读取 `.env`；Holdout 只用合成秘密文本，
  未打开 `docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/` 逐题内容（全量执行既有测试，
  未查看其输出内容）。未 commit/push/切分支/改交付物。

## D. 结论

本包 35 / observability 290 / b0-badcase-regression 0 diff / gate hard `[]` 均 PASS；
全量 46 失败为 `docs/evidence` 只读导致的环境阻断（BLOCKED），不计为 T113 失败，
但全量 0 failed 的验收项在本环境**未能证明**。
