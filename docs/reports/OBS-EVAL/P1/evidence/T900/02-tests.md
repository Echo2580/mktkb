# T900 证据 02：全量 / 定向 / local 三套 / 前端

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 环境与全量（只跑 1 次）

```text
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
跑前 FreePhysicalMemory = 5310 MB（≥2GB）
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider ^
  --basetemp backend\.pytest-tmp\t900-full
-> 1933 passed, 1 warning in 498.11s (0:08:18)；EXIT=0；无 flake、无隔离复跑
```

唯一 warning 为既有 `StarletteDeprecationWarning`（httpx/testclient），与 P1 无关。

## B. 定向套件（407 条；非全量）

```text
pytest -q --basetemp backend\.pytest-tmp\t900-targeted <T100/T101/T102/T103/T104/T105/
T106/T107/T108/T109/T110/T112/T113/T114 本包测试文件>
-> 407 passed, 1 warning in 137.36s；EXIT=0
```

覆盖：`test_s4_stage_limit`（T100）、T101–T106 各包定向、`test_regression_suite`、
`test_holdout_suite`、`test_multiturn_runner`、T110 指标/scorer、T112 gate/baseline、
T113 `test_routes`、T114 `test_routes_security`。无 skip/xfail 被触发。

## C. local 三套 + gate

```text
for suite in b0 badcase regression:
  python -B -m mktkb.evaluation.cli run --suite <suite> --mode local ^
    --out backend\.pytest-tmp\t900-local-20261109225051\<suite>
-> b0 exit 0 (40 cases)；badcase exit 0 (13)；regression exit 0 (7)
```

| suite | status_counts | Recall/MRR/nDCG | hard_filter / empty_recall | 对 P0 逐例签名 |
| --- | --- | --- | --- | --- |
| b0 | pass 29 / fail 3 / skipped_ocr 8 | 0.96875 / 0.96875 / 0.96875 | 0.0 / 0.03125 | **sig_diffs=0/40** |
| badcase | pass 9 / fail 4 | 0.7855614973 / 0.85 / 0.7499953095 | 0.0 / 0.1 | **sig_diffs=0/13** |
| regression | pass 5 / fail 2 | 1.0 / 0.75 / 0.8154648768 | 0.0 / 0.0 | 无 P0 regression run；RG005/RG007 fail，RG006 pass |

签名 = `(case_id, status, outcome.kind, error.code, [(check_id,status)...])`。b0/badcase 的
P0 对照为 `var/eval/runs/p0-b0`、`p0-badcase`（只读）。

gate 用 `docs/evaluation/gate_v0_1.json`（local run manifest 的 gate_version）：
三套均 `exit 3`、`hard_failures=[]`、`quality=unknown/config_status=unapproved`，
quality failures 0；unknown 为既有 `thresholds_unapproved` 等。用 v0.2 配置评估 local run
会因 `manifest.gate_version != config.gate_version` 提前 exit 3（预期 fail closed）。

独立复算：从 `cases.jsonl` 的 `outcome.retrieved` + `gold.relevant_unit_ids` 按 chunk 排名
重算 macro Recall/MRR/nDCG，b0 与 badcase 均逐位等于 `summary.json`（见 §D）。

## D. 前端

```text
cd frontend
npm run typecheck      -> exit 0
vite build --outDir ..\.claude\handoffs\_scratch\T900\frontend-dist --emptyOutDir
-> 40 modules transformed；built in 261ms；exit 0
```

e2e 未跑（NOT-RUN：无浏览器/服务装配；T106 收口时已记录 7 passed，本次不复跑）。
