# T100 交接单：P1 基线测试耦合修复（P1 前置小包）

> 基线：分支 `p1/fix-retrieval`（自 `main@083eaef`，P0 已并入）。前置：PRE-2 已签（GO 切换 `P1-RETRIEVAL`、budget 划转已生效）；T100 由主人 2026-11-05 批准新增。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 目标（一句话）
修好 1 条把旧真实配置写死的基线测试，使 `backend/tests/rag/test_s4_stage_limit.py` 在新签署的 GO/budget 下全绿，且保留原测试意图。

## 2. 背景（为什么会红）
- 2026-11-05 主人签了 PRE-2：`S2-LIVE-GO.json` 换成 `stage=P1-RETRIEVAL`（额度 3.0）、`budget.json` 改为 `S2-DEV 15.4 + P1-RETRIEVAL 3.0`（总额 20 不变）。
- 测试 `test_current_go_and_budget_are_consistent_and_above_three_yuan` 直接读**真实** `S2-LIVE-GO.json` 与 `budget.json`，断言 `S2-DEV == 18.4` → 现在 `KeyError: 'S2-DEV'`。
- 定向实测：该文件 **1 failed / 7 passed**；同批 `backend/tests/unit/test_s2h_r3_official_profile.py` 全过（合计 1 failed / 21 passed）。证据：`.claude/handoffs/p1-gate-drafts/baseline-impact-20261105.txt`。
- 这是"配置按主人意志变化"导致的旧断言失效，**不是产品代码缺陷**；测试意图（校验当前真实配置自洽）要保留。

## 3. 交付物（只准写这些路径）
1. `backend/tests/rag/test_s4_stage_limit.py`（只改这一个测试函数及其局部辅助；同文件其余测试不动）
2. `docs/reports/OBS-EVAL/P1/evidence/T100/`（≤4 份关键证据）
3. `.claude/handoffs/T100-baseline-config/report.md`（五段齐全，≤80 行）
4. 1 个 commit（要求见 §7）

**不要写** `.claude/handoffs/**` 其他文件（PM 负责）、不改 `docs/evidence/**`、`var/**`、账本/GO、业务代码。

## 4. 允许 / 禁止
- 允许：只改上述测试文件；只读读取真实 GO/budget/ledger 做一致性断言。
- 禁止：改业务代码、其他测试、评测代码、fixtures、文档；`skip` / `xfail` / 删断言 / 放宽断言；真实模型/embedding/rerank/OCR 调用；读 `.env`；改 `budget.json`/GO/账本；切换分支；push；改 `_index`/handoff。

## 5. 验收标准（逐条可判定）
1. `pytest backend/tests/rag/test_s4_stage_limit.py -q` → **0 failed / 0 error**；该文件无 `skip`/`xfail`（`git diff` 中不得出现 `skip`、`xfail` 字样）。
2. **测试意图保留**：仍直接读真实 `S2-LIVE-GO.json` 与 `budget.json` 并做实质断言，≥4 类关系断言，至少覆盖：
   a) GO 中每个 `scope.stage_limits_cny[stage]` 在 budget `stages` 同名存在且额度相等；
   b) budget `stages` 合计 + `historical_conservative_accounted_cny` == `limit_cny`（20.0）；
   c) `P1-RETRIEVAL` 额度 == 3.0 且 `>= 3.0`（不低于旧硬限）；
   d) `S2-DEV` 分配（15.4）≥ 账本中 S2-DEV 实际已占（用 `BudgetLedger(...).summary()` 只读计算，当前 15.0266296）；
   e) `REAL_LEDGER` 存在且可解析（沿用原断言）。
   （实现方式自定；**不得**改成"只断言文件存在"的空转测试。）
3. 只改 1 个代码文件：`git show --stat HEAD` 中代码改动只有 `backend/tests/rag/test_s4_stage_limit.py`（另有证据与 report 文件，属允许）。
4. 测试预算（技能 §11A）：本包 1 次 + `backend/tests/rag` 目录 1 次 + **全量 1 次**（当前空闲内存 2.24GB ≥ 2GB，应跑全量；只有运行中内存掉到 <2GB 才可标 NOT-RUN 并说明原因）；全量要求 **0 failed / 0 error**。
5. 证据 ≤4 份 + report 五段；回复末尾 ≤10 行交接摘要。

## 6. 必须实际运行的命令（在项目根 `D:\GPT项目\市场部AI知识库`）
```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
.\.venv\Scripts\python.exe -B -m pytest backend/tests/rag/test_s4_stage_limit.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T100
.\.venv\Scripts\python.exe -B -m pytest backend/tests/rag -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T100-rag
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T100-full
```
全量约 5–10 分钟。跑全量前用 `Get-CimInstance Win32_OperatingSystem` 看 `FreePhysicalMemory`（<2GB 则不跑并说明）。

## 7. 提交要求
- 当前分支必须是 `p1/fix-retrieval`；**不要**切换/新建分支，不要 push，不要 amend 历史。
- 提交前 `git status --short` 只应含：测试文件、`docs/reports/OBS-EVAL/P1/evidence/T100/**`、`.claude/handoffs/T100-baseline-config/report.md`。
- **1 个 commit**，消息：`p1/T100 fix baseline test coupling to signed P1 config`。
- report.md 写 commit sha 与 `git show --stat` 摘要。

## 8. 报告格式（五段，≤80 行）
1) 完成内容；2) 验收标准自证（每条 ≤2 行，带命令或 `文件:行`）；3) 实际运行结果（本包 / rag 目录 / 全量各一行 + commit sha + stat）；4) 偏离或未做（无则写"无"）；5) 风险（一句话）。
