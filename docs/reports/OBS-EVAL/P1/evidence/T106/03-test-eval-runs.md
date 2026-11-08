# T106 证据 03：测试与 local run/gate 前后对照

环境：Windows，仓库根 `D:\GPT项目\市场部AI知识库`，`.venv\Scripts\python.exe`
（3.12.7）。pytest 均带 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`-B`、
`-q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`；零真实
模型/embedding/rerank/OCR 调用，未读 `.env`/Holdout。

## A. 测试（最终树）

| # | 范围 | label | 结果 |
| --- | --- | --- | --- |
| 1 | 本包 8 条映射/三要素/覆盖测试 | `t106-copy5` | **8 passed**，0.03s |
| 2 | `backend/tests/unit` | `t106-unit2` | **343 passed**，6.39s |
| 3 | `backend/tests/observability` | `t106-obs3` | **255 passed**，15.33s |
| 4 | `backend/tests/integration` | `t106-int2` | **380 passed / 1 failed**，256.38s；唯一失败为既有 flake `test_g08_short_budget_cancels_inflight_model_call`（时序断言），隔离复跑 `t106-flake` → **1 passed**，1.31s |
| 5 | 全量 `backend/tests` | `t106-full2` | **1726 passed / 0 failed / 0 error**，400.70s；跑前 `FreePhysicalMemory=4,048,820 KB`（约 3.86 GB），无需轮询等待 |

- 全量包含本包新增 8 条（343 unit = T105 的 335 + 8）。
- 未使用 skip/xfail/删断言；未新增生产依赖。

## B. b0 / badcase local run + gate（P0 冻结基线 → 本包）

命令（cwd=仓库根，`$env:PYTHONPATH="backend/src"`）：
`python -B -m mktkb.evaluation.cli run --suite <suite> --mode local --out backend\.pytest-tmp\t106-eval\after2\<suite>`，
随后 `gate --run <同上>`。

| suite | 基线 run_id | 本包 run_id | 状态 | gate | 逐例差异 |
| --- | --- | --- | --- | --- | --- |
| b0 | `b0-local-20261105T090359232489Z-6e3eb84c`（`var/eval/runs/p0-b0`） | `b0-local-20261108T094419554592Z-9c0e154c` | pass 29 / fail 3 / skipped_requires_ocr 8（不变） | exit 3，hard `[]` | **0 / 40** |
| badcase | `badcase-local-20261105T090409960294Z-f03d4b5f`（`var/eval/runs/p0-badcase`） | `badcase-local-20261108T094423687130Z-53784204` | pass 9 / fail 4（不变） | exit 3，hard `[]` | **0 / 13** |

逐例口径 `(case_id, status, outcome.kind, failed check ids)`；两套件 `case_diffs=0`，
失败集仍为 b0 Q25/Q26/Q31、badcase N05/N06/N09/N11，`kind` 未变。文案相关 check
无差异（D-3 取值变化未触发任何 value/source/kind check 变化）。

## C. regression（`17c0e63` 基线 → 当前）

基线：detached worktree `$TEMP\t106-baseline`（`17c0e63`，`mktkb.__file__` 指向
baseline 副本）`regression-local-20261108T094008270406Z-45e19f74` → pass 4 / fail 3，
gate exit 1，hard `['security_leak']`。
当前：`regression-local-20261108T094446258122Z-5a44219e` → **pass 5 / fail 2**，
gate exit 3，hard `[]`。

- 逐例仅 **RG006** `fail/answer/(kind_correct,value_forbidden)` → `pass/clarification/()`；
  这是 T105 已收口的指代澄清修复，不是本包文案变化。
- RG001–RG004 保持 pass；RG005/RG007 失败 checks 仍为 `kind_correct,refusal_expected`；
  gate hard 名由 `['security_leak']` 收缩为 `[]`，无新增 hard 名。

## D. 前端

- `npm run build`（含 `tsc --noEmit`）通过：`✓ 40 modules transformed`，
  `dist/assets/index-8bSjLtTU.js 367.01 kB`。
- `npx playwright test e2e/02-chat.spec.ts --project=functional` → **7 passed**（19.9s）。
- acceptance runner label `t106`：`backend\tests\acceptance\support\run_browser_acceptance.py
  --label t106 --playwright-args "e2e/acceptance-02-kinds.spec.ts"` →
  **PLAYWRIGHT EXIT 0**，`expected=5 / unexpected=0`，outbound external `[]`。
