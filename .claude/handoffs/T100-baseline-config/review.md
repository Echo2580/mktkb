wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T100 独立验收 review（P1 基线测试耦合修复）

- 任务单：`.claude/handoffs/T100-baseline-config/handoff.md`（§5 判定口径）
- 被验对象：`b35ae72`（父 `ac96f45`，分支 `p1/fix-retrieval`，复跑前工作树干净）
- 判定：**通过** — 0 FAIL / 0 BLOCKED / 0 NOT-RUN；1 项非阻塞偏差（§2.4）
- 方法：只采信我本人复跑输出与只读复算；`report.md` 仅作线索，未用作 PASS 证据。

## 1. 复跑结果（均先设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）

| # | 命令（`-B -m pytest … -q -p no:cacheprovider`） | 我的结果 | 证据 |
|---|---|---|---|
| 1 | `backend/tests/rag/test_s4_stage_limit.py … --basetemp backend\.pytest-tmp\T100-verify` | **8 passed**, 1 warning, 0.25s, exit 0 | `docs/reports/OBS-EVAL/P1/evidence/verify/T100/01-target-pytest.txt` |
| 2 | `backend/tests/rag … --basetemp backend\.pytest-tmp\T100-verify-rag` | **308 passed**, 1 warning, 26.53s, exit 0 | `…/02-rag-pytest.txt` |
| 3 | `backend/tests … --basetemp backend\.pytest-tmp\T100-verify-full` | **1593 passed**, 1 warning, 359.91s (5:59), exit 0；0 failed / 0 error | `…/03-full-pytest.txt` |
| 4 | 配置/账本只读复算 | 见 §2.3 | `…/04-config-ledger-facts.txt` |

- 全量前置内存 `FreePhysicalMemory=2,337,752 KB`（2.23GB ≥2GB → 必须跑）；跑后 `2,776,704 KB`。
- NOT-RUN：无。真实模型/embedding/rerank/OCR：未调用（仅 pytest + 只读解析）。未读 `.env`。

## 2. 验收标准逐条（handoff §5）

### 2.1 测试意图保留 — PASS
- 仍直读真实配置：`backend/tests/rag/test_s4_stage_limit.py:193-196` 读 `S2-LIVE-GO.json` 与 `REAL_BUDGET`（`:27-28` 指向真实账本/预算），不是 fixture 或临时副本。
- 实质关系断言 a–e 齐全（共 16 条 `assert`），无空转：
  - a) GO 每阶段必须在 budget 同名且等额：`:199-202`
  - b) `sum(stages) + historical == limit_cny` 且 `limit_cny == 20.0`：`:205-208`
  - c) `P1-RETRIEVAL == 3.0` 且 `>= 3.0`，min 解析收敛 3.0：`:211-217`
  - d) `S2-DEV == 15.4` 且 `>= BudgetLedger(...).summary().stage_accounted_cny`：`:221-228`
  - e) `REAL_LEDGER` 存在且可被 `summary()` 完整解析：`:223-231`
- 函数名/位置保留（`:183`）；文件 8 个 `test_` 函数与 `ac96f45` 同名同数，`git show b35ae72 -- …` 只改该 1 个函数体。
- 无 `skip`/`xfail`/`pytest.mark`：整文件 grep 0 条；commit diff grep 0 条。
- 旧测试确实已红（修复必要）：独立复算 `limits['S2-DEV'] → KeyError`；`budget['stages']['S2-DEV']==18.4 → False`（实际 15.4）。
- 强度未放宽：旧 4 条断言迁移后仍保留 `S2-DEV > 3.0`（`:222`），并新增“分配覆盖账本占用”等更强断言。
- 附带观察（非本次问题）：未改动区域的注释仍把 `S2-DEV = 18.4` 称为“当前”（模块 docstring `:3-5`、`:69`），与 PRE-2 后的配置不符；因 handoff 要求“同文件其余测试不动”，本次未改，建议 P1 后续清理。不影响断言与验收。

### 2.2 改动范围 — PASS
- `git show --name-status b35ae72`：代码仅 `M backend/tests/rag/test_s4_stage_limit.py`；另 `A` report + 4 份证据（handoff 明确允许）。
- 无 GO/budget/账本/fixtures/业务代码/其他测试改动（name-status 全量核对；文件 SHA 见 §2.3）。
- `b35ae72^ == ac96f45`；`ac96f45..HEAD` 计 **1** 个 commit；消息 `p1/T100 fix baseline test coupling to signed P1 config` 与 §7 一致。
- 我的复跑前 `git status --porcelain` 为空；复跑后仅新增我自己的 `evidence/verify/`（未提交）。

### 2.3 数字复算 — PASS
| 项 | 期望 | 我的实测 | 证据（`verify/T100/04-…`） |
|---|---|---|---|
| GO 阶段 ↔ budget 同名等额 | 全等 | `{"P1-RETRIEVAL":3.0}` == budget P1 3.0 | `:18-22` |
| stages 合计 + 历史 | 20.0 | 19.97 + 0.03 = **20.0** | `:21-23` |
| P1-RETRIEVAL | `==3.0` 且 `>=3.0` | 3.0 / 3.0 | `:22,36` |
| S2-DEV | 15.4 且 ≥ 已占 | 15.4 ≥ **15.02662959999999** | `:22,29,37` |
| GO SHA | 与实际一致 | `39070de5…1df4` ✔ | `:17` |
| budget SHA | 与实际一致 | `084ba9ac…cc58` ✔ | `:20` |
| ledger SHA | 与实际一致 | `ca48b09a…deb1` ✔ | `:24` |
| `summary()` 前后账本 | 不变 | 相同；target/rag/full 后仍相同 | `:25-28` |
| 旧断言失效前提 | 已红 | `S2-DEV` KeyError / 15.4≠18.4 | `:40` |

附注（已核实，非缺陷）：GO 内 `budget_ledger_sha256=f4710b18…a014` ≠ 整本 `ca48b09a…deb1`，这是 `historical_import` 前缀锚点；产品闸门 `ledger_binding_ok` 明确接受“整本或历史前缀”两种绑定（`backend/src/mktkb/live_authorization.py:408-421`），P1 kickoff gate §2.4 坑 b 也要求保持前缀值。T100 未要求校验该字段。

### 2.4 交付纪律 — PASS（附 1 项非阻塞偏差）
- 开发证据恰 4 份（`T100/01–04`）；我的复跑证据恰 4 份。
- `report.md`：首行模型说明 ✔；五段 `## 1`–`## 5` ✔；45 行 ≤80 ✔。
- 无 skip/xfail ✔；`.claude/handoffs` 下仅新增 `T100-baseline-config/report.md`，未改其他 handoff ✔。
- 偏差：handoff §7 要求 report 写 commit sha 与 `git show --stat`，实际 report §4 以“单 commit 无法自引用、禁止 amend”为由改在交付回复给出。判定：**非阻塞**——§5 验收条目不含该条，且 §7 与“1 commit + 不 amend”自相矛盾。

## 3. 与开发方证据的独立对照
- 计数一致：8 / 308 / 1593，与我复跑完全相同；但这只说明其证据可信，PASS 依据仍是我的输出。
- 内存读数不同（其 3.06GB→2.26GB；我 2.23GB→2.65GB），属不同时刻采样，均 ≥2GB，不构成矛盾。
- 其 `01-target-pytest.txt` 头部有编码乱码（路径显示为 `锟斤拷` 类字符），命令与 `8 passed` 结果仍可读；非验收项。

## 4. 未执行 / 限制
- NOT-RUN：无。
- 未改 GO/budget/账本/业务代码/其他测试；未 commit/push/切分支；未读 `.env`。
- 只读 `BudgetLedger.summary()` 前后账本 SHA-256 相同（`ca48b09a…`），确认零写入。

## 5. 结论
**通过**（0 FAIL / 0 BLOCKED / 0 NOT-RUN）。测试意图完整保留且比原版更严格；改动范围、数字、交付纪律均符合 §5。唯一偏差是 report 未内嵌 commit sha/stat（handoff §7 自身矛盾），不影响验收。无返工项。
