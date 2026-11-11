# P2-T207-FIX-B 独立验收 review（证伪优先，零真实调用）

- 验收角色：独立验收助手（全新上下文，未见开发对话）；分支 `codex/p2-e2e` @ `9a740ce010126af9274b08a2bc60a40767ef217d`（**未 commit**，我离开时 HEAD 不变）。
- 依据：`.claude/handoffs/prompts/P2-T207-FIX-B-verify.md`；开发自述仅作线索，**每条结论均由我独立复跑/自写探针**。
- 只写：本文件 + `evidence/verify/`（2 个探针脚本 + 2 个输出，见 §5）。未改代码/测试/契约/账本/预算/GO，未读 `.env`，未 commit。

## 0 基线（到达 / 离开逐值一致）

| 文件 | sha256 | 大小 | 行数 |
|---|---|---|---|
| `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl` | `6b053520…ee345c`（与任务书一致） | 1,050,298 B | 1095 `\n` |
| `docs/evidence/LOCAL-R1-20261101/budget/budget.json` | `79b21700…a910b1a9`（一致） | 1,738 B | — |
| `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json` | `79a5f318…c19070e`（一致） | 1,232 B | — |

到达与离开各测一次，三元组完全相同 → 本包与我均未写账本/预算/GO。

## 1 逐条判定

| # | 条目 | 判定 | 一句话理由（证据见对应小节） |
|---|---|---|---|
| 1 | 范围合规 | **PASS（附注）** | `git diff --numstat` 只有 10 个允许文件 + 2 个**非本包**文件（PM 索引、并行包 service.py）；三份 SHA 不变；HEAD 未前进；无 fixtures/计划/runbook 改动。 |
| 2 | 硬顶治理 | **PASS** | 两处均为 1600 且不变式仍在；计划层 1600 过 / 1601·2000·2001 拒；GO 层 1600 过 / 1601 拒；无 skip/xfail 新增、无断言删除；P1 8 文件 163 passed。 |
| 3 | 测试与既有失败 | **PASS** | 三文件 118 passed / 1 failed；失败用例函数体与 HEAD 逐字相同、两侧输入文件均未改 → **既有失败**（pilot 后账本合法增长）。 |
| 4 | output_valid（C） | **PASS（附注）** | 合法 usage → `output_valid=True` + 0.000384；空/非 stop/未解析/缺省 → J1 拒（三个稳定 reason）+ 账本保守 0.018688 + 停止。开发「重要更正」逐条成立。 |
| 5 | run_result additive（A） | **PASS** | 我实跑 5 笔 reservation 的 mock 全链：`attempts_reserved=5`＝账本 reservation 数＝summary.gate_reserved，`sum(by_operation)=5`；旧 pilot run_result 仍可读；`P2Gate.result()` 的 `unavailable` 不影响任何产物（产物只走 `P2RunLedger.result(attempt_audit=…)`）。 |
| 6 | summary 三口径（B） | **PASS（附注 C1）** | 三值互不冒充、旧键不回退、pilot 独立重算 0.5713583 / 0.5152943 / 3 一致；**但** J1 拒绝轮会让 `conservative_held_cny` 少记一笔 0.018688（见 §4 C1）。 |
| 7 | 契约与报告 | **PASS（附注 C1）** | 10 个 sha16 逐值一致、report 80 行（≤100）、行数/命令/金额可复现；三份契约含「到值即停」「P1 不构成追加授权」。唯一偏差是 §7.2 对 `conservative_held_cny` 的措辞强于实现（C1）。 |
| 8 | 合规 | **PASS** | 我的全部实跑内置 socket 闸门，外部 connect = 0；live 测试自带 `t09_network_guard`；未 commit。 |

**建议：通过（有条件）**——阻断项 0；C1 作为非阻断跟进（一行代码或一句契约措辞，见 §4/§7），由经理决定是否在 T207 正式矩阵前修掉。

## 2 条目 1：范围与未提交

```
$ git diff --numstat
140  10  backend/src/mktkb/evaluation/p2_contracts.py
127   4  backend/src/mktkb/evaluation/p2_runner.py
 97   8  backend/src/mktkb/evaluation/p2_live.py
  8   1  backend/src/mktkb/live_authorization.py
169   1  backend/tests/evaluation/test_p2_live_wiring.py
113   1  backend/tests/evaluation/test_p2_runner.py
 34   0  backend/tests/evaluation/test_p2_authorization.py
 24   1  docs/evaluation/p2-live-binding-v0_1.md
 21   3  docs/evaluation/p2-run-contract-v0_1.md
 40   1  docs/evaluation/p2-runner-contract-v0_1.md
  6   0  .claude/handoffs/_index.md          <- 非本包（PM 协调索引，本包开始前已在工作区）
 11   1  backend/src/mktkb/conversations/service.py  <- 非本包（并行包 T207-FIX-P，diff 内自带 "T207-FIX-P" 注释）
```

- 三个测试文件里的 2 处 `-1` 都是 **import 行替换**（`from mktkb.providers.types import OCRInput` → `…, CompletionOutput, OCRInput`；`P2_LEDGER_SNAPSHOT_SCHEMA_VERSION` 移动到新位置），无断言被删/放松（`git diff -U0` 全量核对）。
- `git status --porcelain -- backend/src/mktkb/rag backend/src/mktkb/evaluation/p2_authorization.py …/p2_scoring.py` 为空 → `settlement_policy.py`、`controlled_usage.py`、`p2_authorization.py` 未动。
- `docs/superpowers/plans/2026-11-10-mktkb-p2-taskbook.md` mtime `2026-11-10T17:43Z`、`docs/reports/OBS-EVAL/P2/T207/` mtime `2026-11-11T00:44Z`，均早于本包首个改动（`p2_runner.py` `01:06Z`）→ T207 计划/runbook/import recipe 未被本包改写。
- 工作区里 `undefined/`（`00:29Z`）、`docs/面试/`、若干 `.claude/handoffs/prompts/*` 是更早阶段的未跟踪物，本包目录 `T207-FIX-B/` 是唯一新增产物目录。

## 3 条目 2：硬顶 1600（`evidence/verify/probe1_hardcap.*`）

```
HARD_MAX_REQUESTS            = 1600
live_authorization.MAX_GO_REQUESTS = 1600
equal(invariant)             = True
plan(max_requests=1600).max_requests = 1600  total_requests=30
plan(max_requests=1601) -> REFUSED reason=request_cap_over_hard_limit
plan(max_requests=2000) -> REFUSED reason=request_cap_over_hard_limit
plan(max_requests=2001) -> REFUSED reason=request_cap_over_hard_limit
GO scope.max_requests=1600 -> ACCEPTED
GO scope.max_requests=1601 -> REFUSED reason=go_max_requests_over_hard_cap
```

- 计划用例基座是**仓库里 T201 候选计划原件**（我只改 `max_requests`），GO 直接调 `p2_authorization._check_go_payload`（生产校验函数本身），不是开发测试的 helper。
- 同值不变式仍在：`test_p2_authorization.py:481 assert c.HARD_MAX_REQUESTS == live_authorization.MAX_GO_REQUESTS`。
- 钉值 grep（`backend/src`+`backend/tests`）：`1000` 只余 P1 自己的 GO/用例值与 P1 测试常量；`2000` 仍是 `test_authorize_rejects_request_caps` 的**负例**（`go_max_requests_over_hard_cap`，仍 >1600）；`2001` 仍是计划层负例 `request_cap_over_hard_limit`。**没有任何安全阈值被下调**，无 skip/xfail 新增（三文件 3/0/0 与 HEAD 同数，且都是既有「本机无账本则 skip」）。
- P1 受影响用例独立复跑（我点名的 8 个文件）：`163 passed, 1 warning in 8.28s`。
- **事实交代（非缺陷，但需经理知情）**：`MAX_GO_REQUESTS` 是 P1 侧 GO 的**格式合法性上限**，所以 P1 **新开** GO 现在可写 1001…1600（HEAD 时会被拒）。已签 GO 不受影响：真实 `S2-LIVE-GO.json` 的 `scope.max_requests` 仍是 **1000**，闸门取该 GO 自身值（`live_authorization.py:167/207/574/717` 只做 maximum 校验）。这是经理 2026-11-11 落盘「共同天花板」的既定含义，不构成对既有授权的追加。

## 4 条目 4/5/6：C/A/B（`evidence/verify/probe2_output_run_money.*`，第 1 部分=C，第 2 部分=A/B）

### 4.1 C（output_valid）

| 场景 | evidence 三判据 | J1 | 账本 result |
|---|---|---|---|
| 合法 usage + stop/非空/已解析 | stop / T / T / `output_valid=True` | **accepted 0.000384** | `succeeded`，`settlement.output_valid=true` |
| 空内容 | T / F / F / False | 拒 `content_incomplete` → **0.018688** | `unknown`，`conservative_charge_cny=0.018688` |
| 非 stop | length / T / T / False | 拒 `finish_reason_not_stop` → 0.018688 | 同上 |
| 未解析（无 `source_ids` 结构） | stop / T / F / False | 拒 `content_not_parsed` → 0.018688 | 同上 |
| 判据缺省（调用方不传） | None / F / F / False | 拒 `finish_reason_not_stop` → 0.018688 | 同上 |
| usage 缺字段（判据齐） | T / T / T | 拒 `usage_missing:prompt_tokens` → 0.018688 | 同上 |

- `chat_单次上界 = 6144×2e-6 + 800×8e-6 = 0.018688`（`P2PriceProfile.bound_cny` 实算），保守额与之一致。
- 停止：J1 拒绝 `SettlementNotReleasable` → `P2Gate.settle_success` 转 `P2GateError` → runner `except` 记 `STOP_GATE_ERROR` 并停（第 2 部分 D：`status=aborted stop_code=gate_error`）。

**开发「重要更正」逐条独立核对（全部成立）**

1. chat 的 J1 校验**不读** `output_valid`：三判据齐但硬把 `output_valid=False` 的 chat 证据 **仍被 accepted 0.000384**，账本 `settlement.output_valid=false` 照写。
2. 只有 embedding/rerank 的 `_validate_total_evidence` 读它：`output_valid=False` → 拒 `output_invalid`（保守 0.002048 = embedding 上界）；`True` → accepted（40 tok → 2e-05）。
3. 代码行号：`rag/settlement_policy.py:672`（chat 三判据）、`:713`（`if evidence.output_valid is not True`），`_validate_chat_evidence` 段内无 `output_valid`。`rag/settlement_policy.py` 工作区未改（`git status` 空）。
4. pilot 的 0.056064 来自 3 笔 `close_unused`：真实共享账本里 `run_id=p2-t206-pilot-20261111-01` 的 42 条 result 中，`P2_NO_PAID_ATTEMPT:*` 恰 3 笔、每笔 `0.018688`（`0.056064`）；3 笔成功 chat 合计 `0.005742` → `settled_cny=0.061806`。与 `output_valid` 无关。

### 4.2 A（run_result additive）

我自建 1 案（Q01，含 INGEST 索引 / embed / rerank / expand / answer / ocr 计划项），MockTransport 全接住：

```
run status=succeeded stop_code=None sent=1
summary.attempts.scope = all_attempts gate_reserved=5
run_result.attempts_* = scope=all_attempts reserved=5 by_op={'answer':1,'index_embedding':2,'query_embedding':1,'rerank':1}
len(ledger reservations) = 5
attempts_reserved == 门登记 reservation 数 ? True
sum(attempts_by_operation) == attempts_reserved ? True
attempts_by_operation['answer'] == requests_reserved(1) ? True
P2Gate.result(): attempts_scope=unavailable attempts_reserved=0
T206/PILOT/run_result.json -> from_dict 成功 (scope=unavailable, reserved=0, settled_cny=0.061806, requests_reserved=6)
```

- 「A 是否名不副实」判定：**不**。`P2Gate.result()` 在 `backend/src` 里**没有任何调用点**（`git grep` 只命中 `backend/tests/evaluation/test_p2_authorization.py`），`run_result.json` 一律由 `p2_runner.py:874/893` 带 `attempt_audit` 写；门侧 `unavailable` 是诚实标注，且契约 §7.1 已写明。
- 旧键语义不变：`requests_*`/`by_operation`/`by_center_cny` 仍只覆盖 answer 轮（同一 run 里 1 < 5）。

### 4.3 B（summary 三口径）

- **pilot 独立重算**（只读真实账本 + pilot 产物，不经 runner 代码）：
  `保守占用=0.5713583`、`status=succeeded 合计=0.5152943`、`零付费轮=3×0.018688=0.056064`、差 `0.056064`。三值互不冒充，与开发报告一致。
- **我的 mock 全链**：`conservative_held_cny=0.000508 == provider_billed_cny=0.000508`（无零付费轮）、`failed_rounds=settled_failure=0`、`unpaid_rounds=0`；`conservative_held_cny` 与账本 result 保守合计**逐值相等**（0.000508）。
- **账本零写入**：全部 tmp 副本；离开时三份 SHA 未变。

### 4.4 C1（唯一实质发现，非阻断）

**现象**：answer 轮的 J1 结算被拒时（我构造 `usage.total_tokens=999 ≠ 64+32` → `SETTLEMENT_NOT_RELEASABLE:total_mismatch`，停止码 `gate_error`），账本 result 写 `conservative_charge_cny=0.018688`，但 `summary.requests.conservative_held_cny` 只有 0.000124（仅从属尝试），**未含这一笔 0.018688**；`run_result.settled_cny=0.0`、`requests_sent=0`。

```
账本 result 保守合计 = 0.018812
summary.conservative_held_cny = 0.000124
两者一致 ? False
```

**为什么算偏差**：`docs/evaluation/p2-runner-contract-v0_1.md` §7.2 把 `conservative_held_cny` 定义为「本次 run 在门/账本里**已写 result** 的保守占用总额」。该路径账本确有 result，实现却漏记。

**根因（行号）**：`p2_runner.py:1477-1490` 的 `except`（`STOP_GATE_ERROR`）只记失败码，不累加 `ledger.settled_cny`，`record_request(charged_cny=0.0)`；`_money_split`（`p2_runner.py:1071`）用它算 `conservative_held_cny`（`:1846` 写出）。同路径的 `run_result.settled_cny` 是**旧键**，HEAD 起就是这个行为（不属本包回归），但新字段继承了这个缺口。

**影响面**：仅限「有 usage 但 J1 拒（`total_mismatch`/`cache_split_mismatch`/`over_cap_*`）」这类 fail-closed 路径；run 会停，不会多花钱，也不虚报成功；错的是 summary 的**账面口径**（少记 0.018688/笔）。账本本身正确（事实来源未错）。

**最小修法（供经理选）**
1. 代码（1 行级）：`except` 分支补 `ledger.settled_failure += 1; ledger.settled_cny += float(ticket.bound_cny)`（与 `settle_failure` 口径一致），或
2. 文档：§7.2 改为「不含 J1 拒绝轮（`stop_code=gate_error`）」，并加 `rejected_rounds` 键显式暴露。

## 5 自写探针（`evidence/verify/`，2 脚本 + 2 输出）

| 文件 | 覆盖 | 关键点 |
|---|---|---|
| `probe1_hardcap.py` / `.out.txt` | 条目 2 | 常量/不变式、计划层与 GO 层 1600/1601（GO 层直调生产校验函数）、T201 计划原件为基座、P1 新 GO 上限的实际含义 |
| `probe2_output_run_money.py` / `.out.txt` | 条目 4/5/6 | 第 1 部分：真 `BudgetLedger.reserve/settle_usage` 跑 C 与「更正核对」；第 2 部分：`run_live_p2` 全链（MockTransport）+ 旧产物可读 + pilot 独立重算 + C1 复现；内置 socket 外部连接闸门（外部尝试 = 0） |

两个脚本都用 `.venv\Scripts\python.exe`、`cwd=backend` 运行；均不写仓库共享文件（tmp 目录，结束即删）。

## 6 条目 7：契约/报告/证据

- 10 个文件的 sha256 前 16 位与 report §1 表**逐值一致**（contracts `a07f6bcc6017b53c`、runner `13074b67e38ba48d`、live `ca9a300dd3dbf715`、`live_authorization` `29184ab32dddb5e8`、live_wiring `77495479e38af649`、runner_test `2606845be0b9262a`、auth_test `4b7cf149481b7120`、三份契约 `cec037d4c0e3e16f`/`67d34612b5cc1382`/`65ab326cab478852`）；+/- 行数与 `git diff --numstat` 逐值一致。
- `report.md` 80 行（≤100）；§2/§3/§4 的命令、金额（0.000384 / 0.018688 / 0.5713583 / 0.5152943 / 0.056064）均被我独立复现。
- 三份契约：`p2-run-contract` §1.3 有「1600 落盘/实算/到值即停/P1 不构成追加授权」；§3 `max_requests ≤1600`；`p2-runner-contract` §7 新增双口径与三段金额；`p2-live-binding` §10.4/§10.6 写 `output_valid`。**无门槛下调**（只抬天花板，且放宽点由经理落盘）。
- 开发 `evidence/` 4 份可用：`01-pytest.txt`（含 118/1 与失败原文）、`02-output-valid-compare.txt`（修复前后对照）、`03-hardcap-grep.txt`（钉值分类）、`04-contract-diff.txt`（契约 diff）。我抽查 02 的「修复前」前提：HEAD 的 `chat_usage_evidence` 确实硬编码 `finish_reason="stop"`/`content_complete=True`/`content_parse_ok=True`（`git show HEAD:…p2_live.py`），前提成立。

## 7 条目 3：既有失败判定

```
$ .venv/Scripts/python.exe -m pytest tests/evaluation/test_p2_runner.py \
    tests/evaluation/test_p2_live_wiring.py tests/evaluation/test_p2_authorization.py -q
1 failed, 118 passed, 1 warning in 40.37s
FAILED test_p2_authorization.py::test_candidate_snapshot_binds_the_real_shared_ledger
assert '1f46d1b9…' == '6b053520…'
```

- 函数体与 HEAD **逐字相同**（`git show HEAD:` 提取比对，差值仅为我的切片边界多出的空行）。
- 两侧输入都未改：T201 候选快照是已跟踪文件且 `git status` 干净；账本是 `.gitignore` 覆盖的共享文件，SHA = 任务书基线（pilot 前为 `1f46d1b9…`/1011 行，pilot 后 `6b053520…`/1095 行）。
- 该测试只读两个文件 + `live_authorization.historical_prefix_sha256`，与本包改动的任何代码路径无关 → **既有失败**（T201 快照钉的是 pilot 前前缀，账本已合法追加）。
- **不弱化门槛的最小修法建议**：不要改成 `startswith`；应把 T201 候选快照**升版**（新文件/新 `schema_version` 内保留 `historical_prefix_sha256` 指向 1011 行前缀，同时 `ledger_sha256` 指向当前 1095 行），或让该用例断言「快照 sha 必须等于账本**在该快照生成时**的前缀摘要」并由 PM 记录快照基线变更。留经理决定。
- 另：我顺手多跑 4 个 s2h 文件，`test_s2h_r3_official_profile.py::test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552` 失败（`预算总上限必须等于当前项目上限 10.0 元（当前 40.0）`）。我把两处常量在内存里改回 HEAD 值（1000/1000）后**仍失败** → 与硬顶无关，是「真实 budget.json 已按经理 20→40 提额，而该用例未设 `MKTKB_PROJECT_TOTAL_LIMIT_CNY`」的**既有过期**，不属本包。

## 8 限制 / NOT-RUN

1. 无法证明开发「未读 `.env`/H1/H2」——只能证明**我**的复跑没读（`load_live_env` 用显式 env 字典，未触盘）。
2. 未跑全量测试套件（只跑任务书点名的三文件、P1 8 文件、4 个 s2h 附加文件）；其余模块未回归。
3. 未验证 `attempts_by_operation` 在「同一 reservation 同时产生 pre_send 与 settle 回执」时是否仍等于 `attempts_reserved`（代码路径 `p2_live.py:503-504` 在 `_settled_by_gate` 时提前返回，理论不会双计，但我没有构造该负例）。
4. C1 的「生产可达性」：真实 `DeepSeekClient._parse` 已拒绝非 stop/空/非 JSON，所以「输出不完整」端到端只能经 usage 自身不一致（`total_mismatch` 等）触发；我没有真实流量可证其概率。
5. 未复核开发 report §4.3 列的两处历史钉值（`T201/evidence/verify/probe_t201.py:1082`、`T207/evidence/build-plan.py:66`）——两者不在允许改动范围，我只确认它们未被本包修改。

## 9 建议

**通过**（阻断项 0）。附一条非阻断跟进 **C1**（summary `conservative_held_cny` 在 J1 拒绝轮少记一笔上界；建议 T207 正式矩阵前用 §4.4 的最小修法之一消掉）。两条提醒：① P1 新开 GO 的请求上限现可写至 1600（既有 GO 不受影响，属经理落盘语义）；② `test_candidate_snapshot_binds_the_real_shared_ledger` 仍是红的，修它要**升版快照**而不是放宽断言。
