# P2-T207-FIX-B 开发报告：pilot 返工②③⑤ + output_valid 结算缺口 + 请求硬顶 1600

- 角色：T207-FIX-B 开发助手（全新上下文）；分支 `codex/p2-e2e` @ `9a740ce`（**未 commit、未 push**）。
- 零真实调用：全部 Mock / `httpx.MockTransport`；未联网、未读 `.env`/H1/H2；未动账本/预算/GO/计划/runbook。
- 范围：`T207-fix-scope.md` §A/§B/§C/§G + `T207-PM-decisions-01.md` §3（硬顶 1600 经理已落盘授权）。

## 1 改动清单（+增/−删 行；sha16 = 文件 sha256 前 16 位）

| 文件 | +/− | sha16 | 改动 |
|---|---|---|---|
| `backend/src/mktkb/evaluation/p2_contracts.py` | +140/−10 | `a07f6bcc6017b53c` | `HARD_MAX_REQUESTS 1000→1600`（附实算/到值即停/跨范围说明）；`P2RunResult` 增 `attempts_scope/attempts_reserved/attempts_by_operation/attempts_by_center_cny`（默认 `unavailable`，旧产物仍可读） |
| `backend/src/mktkb/evaluation/p2_runner.py` | +127/−4 | `13074b67e38ba48d` | `_attempt_result_fields`（由 `attempt_audit` 填全量尝试口径）、`_money_split`（保守占用/供应商证据/零付费轮三段）、`summary.requests` 增 `scope/failed_rounds/unpaid_rounds/conservative_held_cny/provider_billed_cny`、`summary.attempts.scope` |
| `backend/src/mktkb/evaluation/p2_live.py` | +97/−8 | `ca9a300dd3dbf715` | `chat_output_validity`（stop+非空+解析结构三判据）、`chat_usage_evidence` 增三判据入参（缺省 fail-closed）并写 `output_valid`、`TurnContext` 捕获判据、expansion/answer 两条调用点传判据 |
| `backend/src/mktkb/live_authorization.py` | +8/−1 | `29184ab32dddb5e8` | `MAX_GO_REQUESTS 1000→1600`（与 `HARD_MAX_REQUESTS` 同值；CRLF 保持） |
| `backend/tests/evaluation/test_p2_live_wiring.py` | +169/−1 | `77495479e38af649` | 新增 3 例：三判据、结算金额、`run_result.attempts_reserved == gate_reserved` + 三段金额 |
| `backend/tests/evaluation/test_p2_runner.py` | +113/−1 | `2606845be0b9262a` | 新增 2 例：run_result additive 键向后兼容、pilot 口径三段回放 |
| `backend/tests/evaluation/test_p2_authorization.py` | +34/−0 | `4b7cf149481b7120` | 新增 1 例：两常量钉 1600；计划/GO 1600 可用、1601 拒绝 |
| `docs/evaluation/p2-run-contract-v0_1.md` | +21/−3 | `cec037d4c0e3e16f` | §1.3 硬顶 1600 + 落盘记录/实算/到值即停/P1 不构成追加授权；§3 `max_requests ≤1600`；§7 `attempts_*` |
| `docs/evaluation/p2-runner-contract-v0_1.md` | +40/−1 | `67d34612b5cc1382` | 新增 §7：answer 单侧 vs 全量、三段金额、`output_valid`/`paid_attempt` 语义 |
| `docs/evaluation/p2-live-binding-v0_1.md` | +24/−1 | `65ab326cab478852` | §10.4 增"输出判据不成立→保守上界+停止"；新增 §10.6 `output_valid`/`paid_attempt` |

未改：`p2_authorization.py`、`rag/settlement_policy.py`、`rag/controlled_usage.py`、`p2_scoring.py`、fixtures、账本/预算/GO、
T207 计划/runbook；既有断言一条未删未放宽（测试文件的 −1 行是 import 行替换），无 skip/xfail。

证据：`evidence/` 下 4 份（`01-pytest.txt`、`02-output-valid-compare.txt`、`03-hardcap-grep.txt`、`04-contract-diff.txt`）
+ 1 个生成脚本 `output-valid-compare.py`（② 的可复现来源，不计为独立证据）。

## 2 验证（命令与原始结果见 `evidence/01-pytest.txt`）

- 任务书命令（三文件）：**118 passed, 1 failed**。唯一失败 `test_candidate_snapshot_binds_the_real_shared_ledger`
  为**既有失败**：它只比较 T201 候选快照（钉 pilot 前前缀 `1f46d1b9…`）与共享账本现文（`6b053520…`，pilot 追加后
  1095 行），两文件本包均未改（`git status` 为空），完整原因见 `evidence/01-pytest.txt` 附注。
- P1 受影响用例（grep 定位后点名 8 个文件，含 `test_live_runner/test_live_request_accounting/test_t112_gate_baseline/
  test_s2b_live_gate/test_budget*/test_budget_settlement*`）：**163 passed**。
- 硬顶钉值 grep 与逐条分类：`evidence/03-hardcap-grep.txt`；契约 diff：`evidence/04-contract-diff.txt`。

## 3 修复前后金额对比（`evidence/02-output-valid-compare.txt`，chat 上界 0.018688 元）

| 场景 | 修复前 | 修复后 |
|---|---|---|
| 合法输出 + 完整 usage | accepted，0.000384；账本 `output_valid=false` | accepted，0.000384；`output_valid=true` |
| 空内容 | accepted，0.000384（内容标志被硬编码 True） | 拒绝 `content_incomplete` → 保守 **0.018688** + 停止 |
| 非 stop 完成态 | accepted，0.000384 | 拒绝 `finish_reason_not_stop` → 0.018688 |
| JSON 未解析 | accepted，0.000384 | 拒绝 `content_not_parsed` → 0.018688 |
| usage 缺字段 | 拒绝 0.018688 | 拒绝 0.018688（不变） |
| 调用方未给判据 | accepted，0.000384 | 拒绝 → 0.018688（缺省 fail-closed） |

pilot 三段复核（`test_summary_money_split_replays_pilot_totals` 断言）：`conservative_held_cny=0.5713583`、
`provider_billed_cny=0.5152943`、`unpaid_rounds=3`，差额 `0.056064 = 3×0.018688`（零付费轮保守留账，不是供应商花费）。

## 4 偏差与限制（如实）

1. **fix-scope §C 的前提经实测不成立**：J1 的 chat 校验不读 `output_valid`（`settlement_policy.py:667-705`），只有
   embedding/rerank 的 `_validate_total_evidence`（`:713`）读它；pilot 3 笔 chat 早已按 usage 结算（0.000384/笔）。
   所以本次修复的**金额方向**是"合法轮不变、无效输出由按 usage 入账改为保守上界+停止"（记账缺口），
   pilot 的 0.056064 保守额来自 3 笔零付费轮的 `close_unused`，与 `output_valid` 无关。
2. **JSON 解析无法在 P2 层复核原始正文**（客户端解析后只保留语义字段）：改用"purpose 解析结构存在"作凭据
   （answer=`source_ids`、expansion=`query_terms`，`providers/deepseek.py:240-273`），输出对象若自带
   `finish_reason` 则按其值判定；已在两份契约写明，不宣称"重放了 JSON 解析"。
3. **硬顶跨范围**：`MAX_GO_REQUESTS` 也是 P1 天花板；P1 已签 GO 的 `max_requests` 仍各自生效（两侧取 min），
   不构成追加授权。两处**历史钉值未同步**（不在允许文件）：`T201/evidence/verify/probe_t201.py:1082`（T201 存档证据，
   重跑会失败属预期）、`T207/evidence/build-plan.py:66`（A 包矩阵工具，待 A 包按 1600 重建）。
4. `P2Gate.result()`（`p2_authorization.py`，本包禁改）产出的 `P2RunResult` 带 `attempts_scope="unavailable"`；
   只有 runner 产物填全量尝试。已在 `p2-run-contract` 写明，避免两处被读成同一口径。
5. 工作区里 `.claude/handoffs/_index.md` 的改动在本包开始前就已存在；`backend/src/mktkb/conversations/service.py`
   是**并行包 T207-FIX-P** 的写入（本包未读改、未参与验证）。本包只写上述 10 个文件 + 本目录。

## 5 回退方式

```bash
git checkout -- backend/src/mktkb/evaluation/p2_contracts.py backend/src/mktkb/evaluation/p2_runner.py \
  backend/src/mktkb/evaluation/p2_live.py backend/src/mktkb/live_authorization.py \
  backend/tests/evaluation/test_p2_live_wiring.py backend/tests/evaluation/test_p2_runner.py \
  backend/tests/evaluation/test_p2_authorization.py docs/evaluation/p2-run-contract-v0_1.md \
  docs/evaluation/p2-runner-contract-v0_1.md docs/evaluation/p2-live-binding-v0_1.md
rm -r docs/reports/OBS-EVAL/P2/T207-FIX-B
```

无需数据回退：本包未写账本/预算/GO/run 产物（全部 tmp 目录，`--basetemp backend/.pytest-tmp/…`）。
