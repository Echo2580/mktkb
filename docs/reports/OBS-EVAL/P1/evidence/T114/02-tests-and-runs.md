# T114 证据 02：测试与评测回归

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. pytest（cwd=仓库根；每次前 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）

```text
backend/tests/observability/test_routes_security.py -q
  -> 62 passed, 1 warning in 17.44s
backend/tests/observability -q
  -> 352 passed, 1 warning in 59.49s
backend/tests -q
  -> 1920 passed, 1 warning in 547.36s (0 failed / 0 error)
     跑前 FreePhysicalMemory=3,628,672 KB（≥2GB）
```

唯一 warning 为既有 `StarletteDeprecationWarning`（httpx/testclient），非本包引入；
全量 0 failed/0 error，未触发既有 flake 隔离复跑。全量含本包 62 条：
1858（T113 基线）+ 62 = 1920。

## B. b0 / badcase / regression local + gate（只读基线）

命令（未写 `var/eval/runs/p0-*`）：

```text
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run  --suite <suite> --mode local --out backend\.pytest-tmp\T114\eval\<suite>
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T114\eval\<suite>
```

| suite | run_id | rows | status_counts | gate |
| --- | --- | ---: | --- | --- |
| b0 | `b0-local-20261109T102119799626Z-4eac0fda` | 40/40 | pass 29 / fail 3 / skipped 8 | exit 3，hard `[]`，unknown 42 |
| badcase | `badcase-local-20261109T102124052127Z-f51e3fef` | 13/13 | pass 9 / fail 4 | exit 3，hard `[]`，unknown 94 |
| regression | `regression-local-20261109T102146258723Z-a2891506` | 7/7 | pass 5 / fail 2 | exit 3，hard `[]`，unknown 80 |

逐例签名 `(status, outcome.kind, sorted(check_id,status), error.code)` 与 retrieved
单位集合对照（`compare_runs.py`）：

```text
b0          vs var\eval\runs\p0-b0                          signature_diffs=0  retrieved_diffs=0
badcase     vs var\eval\runs\p0-badcase                     signature_diffs=0  retrieved_diffs=0
regression  vs backend\.pytest-tmp\T109-R2\eval\regression-current
                                                            signature_diffs=0  retrieved_diffs=0
```

gate exit 3 仍为既有 `min_sample_missing` + `thresholds_unapproved`（T112 暂缓），
三套 `hard_failures` 均为 `[]`，无新增硬失败；regression 状态与 T109-R2 一致。

## C. 本包测试覆盖清单

权限矩阵（401/403/200 ×4）、错误信封、鉴权顺序、404/未知 request、非法
window/id、编码穿越、时间窗合法/非法、超大窗口、分页 NOT-APPLICABLE、trace 关闭
降级、成功/错误响应白名单与秘密文本、holdout 仅聚合、OpenAPI 4 路径/仅 GET/
401/403/快照一致性。逐条位置见 `01-auth-matrix-and-boundaries.md`。
