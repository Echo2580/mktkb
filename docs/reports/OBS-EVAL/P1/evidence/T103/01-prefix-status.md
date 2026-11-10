# T103 证据 01：修复前状态（ERR-04 八个目标题 + b0/badcase/regression）

- 分支 `p1/fix-retrieval`；修复前 HEAD `cbc40f8`（T103 交接单提交）；工作树仅本包允许路径。
- 修复前产品行为来源：`docs/evidence/LOCAL-R1-20261101/TEST-20261104/40q-results.json`（2026-11-04 直接调产品 HTTP，每题新会话，无重试/并发）。该轮是真实模型，本轮**未**重跑真实模型。
- 修复前 `ERROR`（ERR-04）：八个目标题全部 `clarification` + `符合条件的记录过多，请缩小查询条件后重试。`，`sources=0`；实现分支 `conversations/service.py:2013-2017`（修复前）不构造 candidates，前端因此显示「该历史消息未保存候选明细」。

## A. 八个目标题修复前（40Q 实测）

| case | stratum | kind | 关键措辞 | candidates | sources |
| --- | --- | --- | --- | --- | --- |
| Q25 | text | clarification | 符合条件的记录过多，请缩小查询条件后重试。 | 0 | 0 |
| Q26 | text | clarification | 同上 | 0 | 0 |
| Q29 | text | clarification | 同上 | 0 | 0 |
| Q30 | text | clarification | 同上 | 0 | 0 |
| Q34 | ocr | clarification | 同上 | 0 | 0 |
| Q35 | ocr | clarification | 同上 | 0 | 0 |
| Q37 | ocr | clarification | 同上 | 0 | 0 |
| Q38 | ocr | clarification | 同上 | 0 | 0 |

- 同轮 40Q 汇总：`auto_pass=31/40`、`auto_fail=9`（8 题 ERR-04 + Q36 ERR-07）；Q25–Q40 语义/扫描件仅 7/16。

## B. 修复前 b0 / badcase / regression local

命令（仓库根）：`$env:PYTHONPATH="backend/src"; $env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"; .venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite <suite> --mode local --out %TEMP%\t103-prefix\<suite>`，随后 `gate --run` 同一路径。

| suite | run_id | status | gate |
| --- | --- | --- | --- |
| b0 | `b0-local-20261105T175315514116Z-dd93c223` | pass 29 / fail 3 / skipped_requires_ocr 8 | exit 3，hard `[]` |
| badcase | `badcase-local-20261105T175320230801Z-2ea88b3d` | pass 9 / fail 4 | exit 3，hard `[]` |
| regression | `regression-local-20261105T175344426127Z-52857f27` | pass 3 / fail 4 | exit 1，hard `['security_leak']` |

- b0 失败集 = `{Q25,Q26,Q31}`（Q25/Q26 为本地语料缺 D03/D05 的既有 value/source fail；Q31 为既有 local fail，本包不动）。
- regression 修复前：RG001–RG003 pass；RG004–RG007 fail；RG004 = `no_answer`，失败 checks `kind_correct,refusal_unexpected`。
