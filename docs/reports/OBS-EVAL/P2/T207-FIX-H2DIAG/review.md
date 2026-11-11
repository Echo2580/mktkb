# P2-T207-FIX-H2DIAG 独立验收：返工 / 不接收

主人，本包存在防泄漏阻断，不能接收。独立合成 30 题的正常诊断数值正确，但“稳定代码外形”不足以证明内容是已登记代码；英文题干片段能够通过生成侧和写盘前审计。按本轮 A 路径，本报告只给拒收证据，由经理按授权回退 H2DIAG 后收口暂停；不发起付费测试、T208/T209/T900 或新修复包。

- 验收日期：2026-11-11；分支 `codex/p2-e2e`；验收对象 `HEAD 93a89ec92682260c186256a98521becb49f413c8` 上的未提交 H2DIAG 改动。
- 验收来源：全新宿主内置独立子代理；读取验收提示、开发报告、三份开发证据、代码差异及必要测试装配。旧 `evidence/verify/` 的边界脚本仅用于比较覆盖范围，未沿用其结论。
- 本次只写本报告与 `evidence/verify-current/`；测试合成临时文件使用经理明确提供的可写 visualizations 临时根。未改源码、测试、契约、夹具、账本、预算或 GO；未 commit。
- 被审 3 个源码/测试文件、2 份契约的 SHA256 及完整差异已固定在 `evidence/verify-current/reviewed-files-sha256.json`、`reviewed-diff.patch`，对应拒收时版本。

## 逐条判定

| 提示条款 | 判定 | 本次证据与结论 |
|---|---|---|
| 1. 范围 | PASS（本包） | 修改集中于 `p2_runner.py`、`p2_score_run.py`、1 个测试、2 份契约及 runbook 诊断段；其他 PM/交接文档为已告知的并行文档工作。`p2_scoring.py`、`scorers.py`、业务与 fixtures 无本包差异；新增测试无 skip/xfail。HEAD 未变。固定三文件前后 hash 一致。 |
| 2. 正常诊断正确性 | PASS（聚合）；运行层部分未验证 | 验收方自行构造并加密 30 题、10/5/5/5/5 分层、36 回合，经真实 dataset loader 解封，仅合成数据；逐值比较六类诊断及每层四表，全部相等。23 pass / 4 fail / 3 error，错误码和=3；2 题未执行。末轮判定、部分来源命中和缺映射已覆盖。另构造首行 service_error + 29 未执行的 aborted 行聚合，错误码=MODEL_UNAVAILABLE×1 + not_executed×29、ends_observed=0。该探针不是 run_p2 E2E；完整 aborted E2E 因宿主 socketpair 挂起未完成。 |
| 3. 防泄漏（关键） | **FAIL / 阻断** | 正常卡扫描 case_id、全部题干/多轮题面、参考答案、金标值及自建文档标记，0 命中；中文 kind、空格、超长、数组、未登记顶层键、H2- 前缀、整题题干 7 类均退为全 error 卡。但英文题干片段、英文文档内容、嵌套未登记字段及末尾换行均被放行。生成侧 kind 同样可复现；详见 B1/B2。公开 run 不写卡/清残留的本次 E2E 未完成，不能标为通过。 |
| 4. 语义 | 部分 PASS，整体 FAIL | 来源按 missing_index 只给未命中 D02 记失败，已命中 D01 不背锅；拒答分母只计观察到的结局，末轮 kind 正确。未知英文 kind 却记作合法结局，增加 ends_observed；形态白名单替代明细键禁令未保持原有泄漏约束，不能接受“更严”表述。 |
| 5. 回归与合规 | **NOT-COMPLETED（回归）**；边界合规 PASS | 本次完整 27/173 未完成。同步 21 例复跑通过，6 个 E2E 明确 deselected，不能等同 27 passed。完整组先遇 TEMP 权限，再遇 asyncio socketpair/accept 挂起，取栈后只中断自有会话；未改 skip/xfail。计数口径经合成卡和差异观察保持 additive；不能凭历史 173 passed 认定本次回归全通过。 |
| 6. 限制与 T207 收口 | PASS（如实记录限制）；本包仍拒收 | p2-score CLI 不带诊断是显式范围；兜底仅原因码×分母避免编造分布，可接受为限制。真实 H2 未重跑，不能倒推既有 run 已具备新诊断，更不能使 T207/发布变绿。暂停收口可保留失败事实；本包防泄漏阻断需先按授权回退。 |

## 阻断问题与最小复现

### B1（P1）：任意符合正则的英文片段成为“稳定代码”，可进入产物

位置：`backend/src/mktkb/evaluation/p2_runner.py:1956`、`:1997`、`:2005`、`:2236`。

`_diag_code` 与诊断审计只检查 `[A-Za-z][A-Za-z0-9_.:-]{0,63}`，没有验证 kind/check/doc/error 等各维度的已登记语义。完整题干/参考答案的逐题 needle 无法发现其英文子片段或任意文档正文。验收方合成题干包含片段 `InventoryFragmentSecret`；将该片段设为单题末轮 `product.kind`，直接走共享打分、诊断生成与 `_holdout_scorecard_artifact`，得到：

```json
{"kind_matrix":{"answer":{"InventoryFragmentSecret":1}},"ends_observed":1}
```

卡 `errors=0`，没有因泄漏退为全 error，片段原样保留。此复现没有 monkeypatch 审计或生成函数，证明生成侧同样有缺口。它还把未登记 kind 当成了产品结局。

独立在完整卡审计入口注入以下对象，也被接受，卡仍为原有 `errors=3`，并保留对应合成文本；预期应是 `errors=30`、稳定 `holdout_scorecard_leak`：

```json
{"kind_matrix":{"answer":{"InventoryFragmentSecret":1}}}
{"failing_checks":{"SYNTHETICDOCUMENTSECRET":1}}
{"source_mapping":{"reference_answer":"SYNTHETICDOCUMENTSECRET"}}
```

第三项说明只登记顶层键、随后让整个 diagnostics 子树豁免明细字段名，会允许错误嵌套结构及 `reference_answer` 等字段。正常 `answer` 作为 kind 键需要允许，但不能据此把诊断内所有结构位置都解除语义约束。本条直接不满足“只出稳定代码/计数、题干片段和未登记键 fail-closed”的验收要求。

### B2（P2）：`$` 与 `match` 允许代码键带末尾换行

位置：同文件 `:1956`、`:2254`、`:2267`。Python 正则 `$` 可匹配末尾换行之前，`match` 没有要求消费完整输入。独立注入 `errors_by_code={"SYNTHETIC_ERROR\n":1}` 后审计通过，换行仍在键中，卡未退化；与文档“任何空白 fail-closed”的承诺不符。生成侧 `strip` 不弥补写盘前审计自身的缺口。

本验收未修上述问题；本轮按经理指示执行拒收和回退路线，不提出额外付费或新包执行请求。

## 本次命令、退出码及证据

所有 Python 命令使用本仓 `.venv/Scripts/python.exe -B -X utf8`；pytest 带 `-p no:cacheprovider --no-header`。下述相对测试路径以 `backend/` 为 cwd。

| 命令 / 操作 | 退出码 / 状态 | 证据 |
|---|---|---|
| `python -m pytest tests/evaluation/test_p2_holdout_scorecard.py -q -p no:cacheprovider --no-header`，默认 TEMP | 1；21 passed、6 setup errors（TEMP 不可写） | `evidence/verify-current/tests-holdout.txt` |
| `python -m pytest tests/evaluation/test_p2_score_run.py tests/evaluation/test_p2_scoring.py tests/evaluation/test_p2_runner.py tests/evaluation/test_p2_live_wiring.py tests/evaluation/test_p2_holdout_plan.py tests/evaluation/test_cli.py -q -p no:cacheprovider --no-header`，默认 TEMP | 中断；工具会话退出1，无最终 pytest 总结 | `tests-adjacent.txt`，有 TEMP 相关错误，随后运行层挂起 |
| 上述两组分别设 TEMP/TMP 到可写 visualizations 根后重跑 | 两组均中断；工具会话退出1，无最终 pytest 总结 | `tests-holdout-retry.txt`、`tests-adjacent-retry.txt`（无完整输出，不能据此认定通过） |
| holdout 组 `-vv -o faulthandler_timeout=20 --basetemp <可写临时根>/run1` | 20秒栈已取得后中断，工具会话退出1 | `tests-holdout-debug.txt`：`asyncio.run → proactor_events._make_self_pipe → socket._fallback_socketpair → accept` 阻塞 |
| holdout 同步21例：原命令加 `-k` 明确排除以上6个 run_p2 E2E（完整选择器见下） | **0；21 passed、6 deselected** | `tests-sync-only.txt` |
| `.venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207-FIX-H2DIAG/evidence/verify-current/independent_probe.py`，设置可写 TEMP/TMP | **0；探针执行完成，观测4项安全FAIL** | `independent_probe.py`、`independent-probe.txt`。退出0表示观测脚本完成，不代表被验包通过；输出明确标记反例FAIL |
| `git diff`/`git status`/`git branch --show-current`/`git rev-parse HEAD`、固定文件 hash | 0（首次复合命令末尾 `rg --files` 无匹配使整个壳退出1，不是 Git 失败） | 源码差异及 hash 快照；未产生 commit |

同步复跑选择器：

```text
not test_holdout_run_writes_aggregate_scorecard_without_case_details and not test_holdout_run_midway_error_never_invents_pass and not test_holdout_run_with_answering_product_counts_23_pass and not test_holdout_run_without_product_text_returns_to_zero_pass and not test_public_run_never_writes_holdout_scorecard and not test_aborted_holdout_run_writes_diagnostics_for_executed_rows
```

一次验收脚本编写期的 oracle 失败来自自建 product 缺少单位级 evidence，随后补齐合成 evidence 后完整逐值断言通过；另一次脚本 identity 形状错误已修正。它们不是产品缺陷，也未借此修改被验源码或测试。最终探针输出完整保留。原开发报告的 27/173 passed 仅为开发历史证据，本次未独立复现，不能当成本次通过。

## 合规、不可变文件及剩余限制

- 未读取工作区 `.env`、真实密钥、真实 H1/H2 题干、答案、逐题 trace；未读真实 H2 run 的 gate/summary/manifest 全量。封存与 key 均为脚本当场生成的合成数据，临时目录退出时删除。
- 合成探针复用 `t09_network_guard`，结束断言 `external_attempts=0`；定向 holdout/runner/live_wiring 模块复用既有网络 guard。无任何真实网络或模型调用命令；无付费测试。
- `live-ledger.jsonl`、`budget.json`、`P2-LIVE-GO.json` 只计算 hash，没有读取内容。`protected-before.json`、`protected-after.json` 一致，依次 SHA256 为 `1648405845fd5e19b593e610b92f8505fdfd78a9e57079648dc14673576785d7`、`79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`、`3ed427f42ac2eeedff489505b94f730eadba1dc38f1b9adecf94d25750b02a7c`。
- 本次没有完成产品 E2E、公开 run 清残留复跑和相邻173例回归；宿主 socketpair 问题单独记录，不据此断言产品本身失败。拒收理由来自已完成且可重复的同步防泄漏反例。
- 未重跑真实 H2、未验证任何真实模型质量提升；没有把 hard_failures=0 等同安全通过，也没有改变原 scorecard 门禁/计数口径。

**最终建议：返工 / 不接收 H2DIAG。先按本轮已授权回退该包，保留本报告与反例证据；T207 如实收口后暂停。**
