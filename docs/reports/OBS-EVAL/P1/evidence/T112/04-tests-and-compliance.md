# T112 证据 04：测试、本地 P0 对照与合规

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 测试（cwd=仓库根；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）

```text
.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_t112_gate_baseline.py -q ^
  --basetemp=backend\.pytest-tmp\t112-pkg
  -> 13 passed

.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation -q ^
  --basetemp=backend\.pytest-tmp\t112-eval
  -> 433 passed in 89.73s（T111 后 420 + 本包 13）

.\.venv\Scripts\python.exe -B -m pytest backend/tests -q ^
  --basetemp=backend\.pytest-tmp\t112-full
  -> 1933 passed, 1 warning in 787.08s（0 failed / 0 error；轮询峰值 RSS 509.1MB < 2GB）
```

新增测试覆盖：v0.2 契约（schema/gate_version/8 硬门禁/suites/检索 5 指标/四字段/
非法配置拒绝）、v0.1 仍可加载、全量守卫（b0+40+冻结 sha，39 题/改字节/错 suite/
`--pilot` 互斥均拒绝）、CLI 默认不放行、live run manifest 版本、live v0.2 gate
exit 3（hard `[]`、retrieval-only 过滤）、v0.1 live 仍 exit 4、`--calibrate` 逐字节
可复现且不写回配置、live baseline 身份仅 v0.2、unapproved 拒绝审批、approved
临时副本接受审批并往返加载。

## B. 本地 P0 对照（只读 P0 baseline/config，未改）

```text
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite <suite> --mode local ^
  --out backend\.pytest-tmp\T112\eval\<suite>
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T112\eval\<suite>

b0         rows 40/40  signature diffs=0  gate exit 3  hard=[]  scored=32  unknown=42
badcase    rows 13/13  signature diffs=0  gate exit 3  hard=[]  scored=13  unknown=94
regression rows 7/7    signature diffs=0  gate exit 3  hard=[]  scored=7   unknown=80
```

签名 = `(status, outcome.kind, [(check_id,status)...], error.code)`；diff 对手为
`backend/.pytest-tmp/T114/eval/<suite>`（T114 收口 run）。exit 3 均为既有
`min_sample_missing` + `thresholds_unapproved`（P0 gate 未审批），无新增 hard failure。

## C. 合规

- 只改/新增 handoff §2 允许路径：`gate.py` / `baseline.py` / `live.py` / `runner.py` /
  `docs/evaluation/gate_v0_2.json` / `tests/evaluation/test_t112_gate_baseline.py` /
  本证据 + `report.md`。
- 未改业务代码/API/schema/`conversations`/`intent.py`/检索算法/fixtures 既有数据/
  P0 `gate_v0_1.json`/P0 baseline；未读 Holdout；无新依赖。
- 账本/GO 只读运行（预留/结算），**未 commit**；`var/eval/runs/*` 与 scratch 均
  gitignored；未 push/amend；无 skip/xfail/删断言。
- 证据不含凭据、`.env` 值、GO 原文、答案原文或逐题明细；只含聚合指标、公开哈希、
  账本计数。`provider_billed_cny=null`，成本只写保守口径。
- `gate_v0_2.json` 保持 `status=unapproved`；R0 未审批、未执行 `baseline approve`
  （前置条件未满足：gate exit 3 + config unapproved）。

## D. NOT-RUN（范围诚实）

- **badcase / regression / holdout 的 live 运行：NOT-RUN** —— 主人 2026-11-09 方案 A
  只放行 b0 全量 40 题一次（总请求 ≤300）；本包未扩大套件、未重跑 b0。
- **gate_v0_2 审批 / baseline approve：NOT-RUN** —— 属 R1；需主人书面批准阈值与
  baseline 信息后另派落盘。
- 与 P0 baseline 的跨版本比较：NOT-RUN（P1 baseline 尚未建立；跨版本按设计只分析）。
