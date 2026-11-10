# P2-T206-LIVE-R1 独立复验（review-R1）

- 角色：独立复验助手（全新上下文，证伪优先）。**零真实调用**；未读 `.env`/H1/H2；未改源码/测试/报告/契约/证据；
  未 commit/push；未跑全仓。现场 `codex/p2-e2e` @ `9a8272a`（R1 未提交）。
- 证据：`evidence/verify-r1/`（01 五套复跑 / 02 自写探针输出 / 03 范围与资金面 / probe_r1.py）。
- **结论：通过。** F1–F6 五项返工全部成立（自写探针独立复现，不引用开发助手的断言）；回归、范围、资金面、零出站均无异常。
  另有 3 条**非阻断**观察（§3）与 1 组未覆盖（§4）。

## 1 逐条判定

| # | 项 | 判定 | 复验实测 |
|---|---|---|---|
| F1 | expand-* 真实归属 | **PASS** | 自写 fake-gateway 探针：同轮第 1 次 answer chat 发送 1 次；第 2 次在**发送前**被 `chat_attempt_exceeds_plan` 拒，POST 仍为 1（`p2_live.py:1015-1027`）。expansion 独立成笔：回执 `expand-Q01-t1` reserve+settle=0.000384（按 usage）、中心 `answer_retrieval`、配额 `expand-Q01-t1=1`/`answer-Q01-t1=0`（`p2_live.py:844-868,1006-1009`）。产品真实路径（空库 Q25）：`purposes={'query_expansion':1}`、`calls.chat=0/expansion=1`、answer 轮 `close_unused`（`P2_NO_PAID_ATTEMPT:not_found` 0.018688 保守占用）。计划缺 expand 项 → `attempt_item_unknown`，0 POST/0 reservation（不借 answer 的钱） |
| F2 | 批级配额 | **PASS** | 12 文本/batch5 → POST `[5,5,2]`=3、配额 3、reservation 3、result 3（`calls=3 / embed_calls=1`）；计划 `requests=2` → POST 2 后第 3 批**发送前** `attempt_quota_exhausted`，POST/配额/reservation 均停在 2。take 在 `reserve()`（每次底层 POST 前一刻），不在 `embed()`（`p2_live.py:441-448` vs `747-757`） |
| F3 | CLI 真测试 | **PASS** | 用例先写合法计划并置齐 env，断言 stdout `error_code=path_missing`、`requests_sent=0`、未建应用目录（`test_p2_live_wiring.py:504-563`）。我独立跑同一 CLI：exit 3 + 该 JSON；计划缺失 → `plan_unreadable: FileNotFoundError`；坏 JSON → `plan_json_invalid`（`cli.py:550-561`）。**非空转证明**：换一个存在的 draft GO → 同命令得到**不同**码 `go_plan_id_mismatch`，说明确实进入门分支，不是 FileNotFoundError 假通过 |
| F4/F5 | 码名一致 + OCR 价/模式门 | **PASS** | runbook 列出的 9 个稳定码在代码中**全部存在**；`go_missing` 仅出现在"旧版写错"的更正句。OCR：text 计划项上请求 `mode=table` → `ocr_mode_plan_mismatch`，**0 新增 POST、0 新增 reservation**；正常页按计划项价 0.5 结算（`p2_live.py:897-928`）；ocr-contract §3、run-contract §11.4 与实现逐字一致 |
| F6 | live retrieved（零付费） | **PASS** | E2E（Q01 + D01 + fake transport + 真实门）：`retrieved==evidence_ids==cited`（各 1）、`cited⊆retrieved` → `citation_required=pass`；删候选 → `fail`（`hard_failures=['citation_required']`）。零额外调用：`chat_calls=1`、`purposes={'answer':1}`、embedding 3 POST/rerank 1（均为产品自身检索）、`outbound=0`、`attempts.gate_reserved=5=expected_reservations`。结构性闸门：live 下 `retrieval_candidates()` 直接 `RuntimeError`（`product_adapter.py:1550`）。捕获点=answer 请求的 `CompletionInput.evidence`（`p2_live.py:1042-1056`）：模型拿到什么就取什么，不重放、不说谎 |
| 6 | 回归/范围/安全 | **PASS** | live 12 / T203 105 / T204 18 / T205 56 / gate 109，退出码全 0（证据 01）。账本 958,277 B/`1f46d1b9…`、预算 1,444 B/`084ba9ac…` 未变、`P2-LIVE-GO.json` 不存在；探针 socket 闸门 external=0（loopback=6 全为 asyncio self-pipe），5 套 `t09_network_guard` 通过。R1 交付面全部在清单内；fixtures/gate.py/p2_ingestion/业务 API 无改动。注：复验期间**并发 PLAN-R1** 改了 `PM/P2-LIVE-readiness.md` 并新增 `p2-pilot-plan/GO.CANDIDATE v0_2`（非本包、非我所写，未验证；证据 03 §5） |
| 7 | 真实性 | **PASS** | report §R1 与 05/07 证据同我的复跑一致（12/105/18/56/109；3 POST=3 配额；tight → 2 POST + 发送前拒；`expand-Q25-t1` 0.000384；`retrieved==evidence_ids`）；`test_p2_live_wiring.py` 12 个 `def test_`，无 skip/xfail |

## 2 被证伪的旧问题（R1 确实修好）

1. 旧 F1（expansion 顶账 answer-*）：现在回执/账本/配额都在 `expand-*`；answer-* 只在真发送时结算，否则 `close_unused`。
2. 旧 F2（按 `embed()` 计配额）：现在按真实 POST 计，批次放大在**发送前**停住。
3. 旧 F3（用例空转）：写计划 + 断稳定码；反例（存在 GO）给出不同码，证明分支真达。
4. 旧 F4/F5（`go_missing`、OCR 价目口径）：码名与实现一致；页价只由计划项模型决定，并加了运行时模式门。
5. 旧"live 无法通过 citation_required"：现在零付费通过，且缺候选仍 fail-closed。

## 3 非阻断观察（不要求返工）

1. **配额先于预留**：`AttemptBudget.take` 在 `gate.begin_attempt` 之前；门拒绝时配额已扣而无 reservation，
   run-contract §11.2"预留数与配额扣减数逐条一致"只在**正常发送路径**成立（拒绝即整门停止，不会超支）。
   建议措辞改为"发送路径一致"，或把 take 挪到 `begin_attempt` 之后。
2. **live 的 citation 检查独立性弱于 mock**：`retrieved` 恰等于产品交给模型的 evidence（也是它校验引用用的
   `allowed` 集），所以 `citation_not_in_evidence` 在 live 作答轮结构上不会触发；仍能拦
   `citation_missing`/`citation_not_unit_level`。建议在 live-binding §2b 加一句，避免读者以为 live 仍独立复核检索。
3. **观测口径**：`_complete_expansion` 先计数后发送，配额/门拒绝时 `expansion_calls` 会记 1 而实际 0 POST（只影响观测）。

## 4 未覆盖（NOT-RUN）

- rag 内核直答轮 / 真实零付费 answer 轮的 E2E：未构造。已用"kind=answer + retrieved=[]"反例证明 gate 会 `fail`，
  并核对代码路径（`product_adapter.py:1987`：非 answer 或无 chat → 空候选）确认 fail-closed 方向。
- 真实 provider/OCR/H2/Ragas/Langfuse/全仓；`provider_billed_cny` 仍是 null（金额=保守占用，不是账单）。
- 12 页 OCR / 可重试路径；`--mode live` × holdout 组合。
- pilot 灌库批数：批级配额后 `ingest-index-embedding.requests=30` 是"30 批"上界，未跑真实 ingest 无法给出实际批数
  （runbook §4.4 已要求签发 GO 前复核；并发 PLAN-R1 已产出 v0_2，**本复验未验证**）。

## 5 证据索引

`evidence/verify-r1/01-rerun.txt`（5 套复跑原样命令/尾行/退出码）、`02-probe-out.txt`（F1/F2/F6/F3/F4/F5 + 安全面原始输出）、
`03-scope-hashes.txt`（改动面/受保护文件/账本预算 GO 哈希/出站）、`probe_r1.py`（自写探针，生成 02）。
