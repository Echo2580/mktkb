wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T100 报告：P1 基线测试耦合修复（P1 前置小包）

> 基线 `p1/fix-retrieval` @ `ac96f45`；任务单 `.claude/handoffs/T100-baseline-config/handoff.md`。未切换/新建分支，未 push。

## 1. 完成内容

- 只改 `backend/tests/rag/test_s4_stage_limit.py:183` 的 `test_current_go_and_budget_are_consistent_and_above_three_yuan`：删除写死的 `S2-DEV == 18.4`，改为直读签署后的真实 GO/budget/账本做结构关系断言（a–e 五类）。
- 强度保留：GO 每个阶段 ↔ budget 同名等额；阶段合计 + 历史 0.03 == 20.0；`P1-RETRIEVAL == 3.0` 且 `>= 3.0`；`S2-DEV == 15.4` 且 `>= BudgetLedger(...).summary().stage_accounted_cny`（只读重放，当前 15.0266296）；`REAL_LEDGER` 存在且可解析。
- 未改业务代码、其他测试、fixtures、GO/budget/账本；无 skip/xfail/删断言。

| 交付物 | 内容 |
| --- | --- |
| 测试 | `backend/tests/rag/test_s4_stage_limit.py`（仅 1 个函数，+42/−6） |
| 证据 | `docs/reports/OBS-EVAL/P1/evidence/T100/01–04`（4 份） |
| 报告 | 本文件 |

## 2. 验收标准自证

1. 本包 0 failed：`01-target-pytest.txt`（`8 passed`）；无 skip/xfail：`git diff -- backend/tests/rag/test_s4_stage_limit.py | Select-String 'skip|xfail'` 无输出，整文件 grep 亦无。
2. ≥4 类关系断言：`test_s4_stage_limit.py:198`(a)、`:204`(b)、`:210`(c)、`:219`(d)、`:230`(e)；全部直读真实 GO/budget，`summary()` 只读。
3. 单代码文件：`git show --stat HEAD` 中代码改动只有 `backend/tests/rag/test_s4_stage_limit.py`（另有证据与报告，属允许）。
4. 测试预算：本包 1 次 + `backend/tests/rag` 1 次 + 全量 1 次；全量 0 failed / 0 error。
5. 证据 4 份 + 本报告五段；证据 04 记录 GO/budget/ledger 的 SHA-256，`summary()` 前后账本哈希一致（只读证明）。

## 3. 实际运行结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 本包 | `8 passed, 1 warning in 0.25s` | `01-target-pytest.txt` |
| `backend/tests/rag` | `308 passed, 1 warning in 21.49s` | `02-rag-pytest.txt` |
| 全量 `backend/tests` | `1593 passed, 1 warning in 362.25s (0:06:02)`，0 failed/0 error | `03-full-pytest.txt` |
| 内存门槛 | 全量前 `3,209,540 KB`；全量后 `2,365,992 KB`（均 ≥2GB） | `03-full-pytest.txt` |

提交：单 commit `p1/T100 fix baseline test coupling to signed P1 config`（不 push、未 amend 历史）。commit sha 与最终 `git show --stat` 于提交后采集，见交付回复；单 commit 无法在自身内容记录自身 sha，沿用 T004b 口径（未 amend）。

## 4. 偏离或未做

- 无功能偏离。说明：handoff §7 要求 report 写 commit sha，但单 commit 自引用 sha 不可能且禁止 amend，故 sha/stat 写入提交后的交付回复（T004b 同口径）。
- 全量启动前内存一度 `1.82GB`（<2GB）；等待回升到 `3.06GB` 后才运行，结束 `2.26GB`，未标 NOT-RUN。

## 5. 风险

- 该测试仍直读真实 GO/budget/账本：主人再次调整额度或对账时需同步更新预期值。这是“校验当前真实配置自洽”的固有耦合，不是产品回归。
