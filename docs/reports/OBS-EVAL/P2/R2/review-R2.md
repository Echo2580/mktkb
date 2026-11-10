# P2-R2 独立复验报告（T203/T204/T205 遗留加固）

- 角色：P2-R2 **独立复验助手**（全新上下文，非开发者/经理）。**证伪优先**：所有判定都自己跑/自己写探针，不引用开发者自验结论。
- 现场：`codex/p2-e2e` @ `d850b49`，R2 **未提交**（`git diff --name-only` = 17 个 tracked 文件，与经理印核一致）。
- 边界：只读 + 只写 `R2/review-R2.md` 与 `R2/evidence/verify-r2/`；**未**改源码/测试/报告/契约/证据；未 commit/push；未读 `.env`/H1/H2；未跑全仓；全程 Mock，出站 0。

## 1. 结论：12 项全部 PASS（0 阻断，8 条非阻断发现）

| # | 项 | 判定 | 关键依据（自跑） |
|---|---|---|---|
| A1 | detail 是顶层分解 + 稳定错误码 | **PASS** | 自写 5 例：一致接受(4)；只抬顶层→`provider_network_detail_mismatch`；分解之和≠detail→同码；缺 detail / 缺分量键→同码；全链路 `run_p2` 抛同码且**不写 summary.json** |
| A2 | RAG post_counters 增量 | **PASS** | 自写变体（每轮 2 次 POST，与开发者用例数字不同）：逐轮 `outbound=[2,2]`、`real_requests=2`、`billed=0.037376`、`detail=(chat 0, rag 4)`、顶层 4、`settled==billed` |
| A3 | 恢复 `outbound_network`，旧 probe1 可跑 | **PASS** | `provider_calls()` 四个 provider 键齐全且 chat==detail.chat；**归档 probe1 字节同源副本亲自复跑：25 断言 / 0 失败 / `external=[]`**，`provider_outbound_zero` 读 `chat.outbound_network` |
| A4 | `question_store` 是策略标签 | **PASS** | holdout 全链路 summary=`policy:delete-at-close`、public=`policy:keep-in-isolated-dir`、`question_store_measurement` 指向 `close()` 的 `seal_receipt`（实测 `{"question_store":"deleted",...}`）；契约 §3 同步 |
| B1 | probe 不覆写归档证据 | **PASS** | `probe_t204.py` 默认复跑 exit 0，`evidence/02-probe-output.txt` 前后 `805dc852…`/7786B **字节不变**；`--out <本人目录>` 正确落 7786B 且归档仍不变 |
| B2/B4 | 4 个不可达码措辞 / 命中口径 | **PASS** | 实测：换模式→`miss`（无 reason）；同页换字节→`cache_input_hash_mismatch`；伪造 provider/region→`from_payload` 即 `cache_payload_invalid` 隔离（0 条目）⇒ 4 码确不可达；`p2_ingestion.py` sha/16 `2eda2b3207b3a734` 且 **git diff 为空**（门控未动）；T204 report §3 与契约 §4/§7 已分开「单测命中 vs 产品检查点复用」 |
| B3 | 仅注释、行为不变 | **PASS（路径偏差已披露）** | `git diff -U0` 变动 7 行全为注释，非注释变更行 **0**；`looks_like_rule_table(D10)==True`、`test_rule_table_scan` 6 passed、T204 18 passed |
| C1 | L/真实标记（原 2b FAIL） | **PASS** | 四类对象（CaseScore/PublicScorecard/HoldoutScorecard/GateDecision）均带 `execution_mode`+`real_calls` 并入 `to_dict()`；默认 `local_mock/0`；`real_calls=1`→`real_calls_without_live_mode`；`"real"`→`execution_mode_invalid`；`-1`→`real_calls_invalid`；矩阵混模式→`execution_mode_mixed`；gate 从 public+holdout 派生并与调用方声明核对 |
| C2 | F01 标签自相矛盾 | **PASS** | 自写：照实回答（含 `×100%`）→ pass；**把 `reference_answer` 去掉后同一回答→ fail(value_no_fabricated)**（证明修复必要）；缺 90%→fail(value_hit)；换 95%→fail(value_no_fabricated)；用 `score_turn` 造正确产品轮 → pass（e2e PASS 分支可达）；`fixtures/` git 状态为空（冻结未动） |
| C3 | 证据 UTF-8 / 重生成确定 | **PASS** | `02-reproduction.txt` 4272B、无 U+FFFD、中文可读；`-X utf8` 重生成与归档 **sha256 完全一致**（`6ccec007dd7c30ed`） |
| C4 | run_id 绑定 | **PASS** | 干净判定 `run_id=run-p2 / local_mock / 0` 且放行；异 run scorecard→`run_binding_mismatch` + `quality_exit_code=3` 不放行；显式冲突→`run_id_mismatch` 抛错；config_hash 级绑定报告已写留 T206/T209 |
| 范围/回归 | 文件面 + 6 套件 + 账本 | **PASS** | 17 个 tracked 文件均在允许面内（偏差见 F-R2-7/8）；`gate.py`/`p2_ingestion.py`/fixtures/三份 review/业务代码 **零改动**；复跑 **30 / 70 / 18 / 51 / 109 / 6** 全 exit 0；`live-ledger.jsonl`=`1f46d1b9…`(958277B)、`budget.json`=`084ba9ac…`(1444B) 与 T203 记录一致、mtime 未变；`P2-LIVE-GO.json` 不存在 |

命令（仓库根，`.venv\Scripts\python.exe`，UTF-8）：
```
-m pytest backend/tests/evaluation/test_p2_runner.py backend/tests/integration/test_p2_product_e2e.py -q   -> 30 passed
-m pytest backend/tests/evaluation/test_p2_authorization.py -q                                            -> 70 passed
-m pytest backend/tests/evaluation/test_p2_ocr_ingestion.py backend/tests/integration/test_p2_ocr_source_identity.py -q -> 18 passed
-m pytest backend/tests/evaluation/test_p2_scoring.py test_p2_gate.py backend/tests/integration/test_p2_public_controls.py -q -> 51 passed
-m pytest backend/tests/evaluation/test_gate.py test_gate_quality.py -q                                   -> 109 passed
-m pytest backend/tests/unit/test_rule_table_scan.py -q                                                   -> 6 passed
-X utf8 -B docs/reports/OBS-EVAL/P2/R2/evidence/verify-r2/probe_verify_r2.py                              -> 53 checks / 0 failed
```

## 2. 非阻断发现（不阻断 R2 通过，建议 T206/T209 处理）

1. **F-R2-1（A1，note）**：交叉校验只在写产物时执行——不一致时 `run_p2` 抛错且**不写 summary.json**；真实 live run 会“已花钱、无产物”。建议首次发送前校验或在该路径补 failure 记录。
2. **F-R2-2（A1，note）**：`provider_network_detail_mismatch` 只是 `ValueError` 的消息前缀，无 `.code`（`P2ScoringError` 才有），机读依赖消息文本。
3. **F-R2-3（C4，note）**：实测把 `run_manifest.run_id` 去掉后 `run_binding_mismatch` 不触发、`decision.run_id=None` 仍可放行。真实 runner 恒写 `run_id`，故不阻断；建议 manifest.run_id 必填、缺失即 unknown。
4. **F-R2-4（A1，info）**：`max(0, int(...))` 会把负值静默归零（顶层 -3 + detail 全 0 → 接受为 0），不报“负值非法”。
5. **F-R2-5（B1 同族，note）**：T203 `probe1` 仍把 `probe1_result.json` 写在自身目录旁（同类问题只修了 T204）。本次用字节同源副本在本人目录复跑，未动 T203 证据；R2 目录外因此新增了该未跟踪文件。
6. **F-R2-6（A4，info）**：标签改名后 `verify-r1/probe_verify_r1.py:751` 仍断言 `deleted-at-close`（开发者已披露），`T203/report.md:116` 的 §F6 正文仍写旧值、由文末 R2 段更正。
7. **F-R2-7（范围，info）**：`.claude/handoffs/_index.md`（+6/-0）也被改，不在 dev.md 允许清单内，属流程簿记而非源码/测试/报告。
8. **F-R2-8（A2，info）**：A2 用例在机器计数器 `rag.providers._record_post_attempt`（`providers.py:348/666/1002` 的真实计数源）上注入，非端到端 RAG HTTP；作为“测量口径”成立，作为“RAG 链路”证据仍归 T206。

## 3. 未覆盖 / 残留（如实）

- 未跑全仓 pytest；未跑真实 live 链 / 真实 `P2Gate` 正向 / 真实账本与 GO（T206）；未跑浏览器链路（T207）。
- 按源码判定 `verify-r1/probe_verify_r1.py` 的 F6 断言已随 A4 改名过时，**未复跑**（历史时点探针，开发者已披露）。
- C2 的 e2e PASS 分支当前由产品状态走 fail 分支（F01 产品仍缺 90%）；我用 `score_turn` 造正确轮证明该分支可达，但“产品修好后真跑该分支”属 T207。
- 复跑 probe 时 `probe_t204.py` 会重建自管临时目录（`backend/.pytest-tmp/`，已被 gitignore），`probe1` 用系统 temp；均未触碰受版本控制的源码/测试/报告/证据。

## 4. 证据入口（4 项 + 1 个生成器）

1. `evidence/verify-r2/01-suites.txt`：6 条命令 + 退出码 + 耗时 + 原始输出尾部。
2. `evidence/verify-r2/02-probes.txt`：主探针 53 条断言全文、probe1 复跑、B1 前后 sha、C3 重生成比对、D10 事实核对。
3. `evidence/verify-r2/03-scope-hashes.txt`：改动面、禁改面零改动、冻结 fixtures、账本/budget/GO 哈希、注释-only 证明。
4. `evidence/verify-r2/04-verdicts.json`：逐项判定与发现的机读版。
- 生成器（可复跑）：`evidence/verify-r2/probe_verify_r2.py`；probe1 副本 `evidence/verify-r2/scripts/probe1_product_entry_netguard.py`（sha256 与 T203 归档件一致）。
