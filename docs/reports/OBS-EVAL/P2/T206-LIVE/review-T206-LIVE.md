# P2-T206-LIVE 独立验收（review）

- 角色：独立验收助手（全新上下文，证伪优先）。**零真实调用**；未读 `.env`/H1/H2；未改源码/测试/报告/契约/证据；
  未 commit/push；未跑全仓。现场 `codex/p2-e2e` @ `9a8272a`（T206-LIVE 未提交）。
- 证据：`evidence/verify-t206-live/`（01 复跑 / 02 CLI 拒绝 / 03 live 探针 / probe.py 自写探针）。
- **结论：不通过（小返工）。** 资金面与默认 mock 安全全部成立，G1–G6 接线真实可跑；
  但有 2 处**契约与实现矛盾**可复现（query_expansion 真实发送、计划项配额口径）+ 1 条**空转测试**，
  另 2 处低危文档漂移。pilot 前可修，不需重做。

## 1 逐条判定（对照 verify 提示词）

| # | 项 | 判定 | 依据 |
|---|---|---|---|
| 1 | 默认安全 | **PASS** | 适配器默认 `mode=mock`/`is_mock=True`；live 缺 wiring / mock 带 wiring / 非法 mode 一律构造期 ValueError；CLI `--mode` 默认 `dry-run`；T203 105 + T205 56 + gate 109 全绿（证据 01） |
| 2 | G1 真实适配器 | **PASS** | `_start_live` 构造真实 `DeepSeekClient`/`BailianEmbeddingProvider`/`BailianRerankProvider`/`build_ocr_gateway`；`_NoOcrGateway` 只在 mock 分支；探针 B 实测 4 条真实 provider 链（证据 03 B） |
| 3 | G2 真实门+驱动 | **PASS**（产品行为） | 固定路径 GO/预算/账本 + `production_ready`（env 总额匹配）；我自写 6 类 CLI 探针全部 exit 3、`requests_sent=0`、`--out` 从未创建（证据 02）。**但**开发助手对应的 GO 用例空转，见 F3 |
| 4 | G3 OCR | **PASS** | 探针 I：真实 `TencentOCRClient`（`TC3-HMAC-SHA256`、`GeneralAccurateOCR`、host=ocr.tencentcloudapi.com），每页 1 笔 `ocr` 预留/0.5、中心 ocr，第二页 `attempt_item_exhausted` 且无额外出站（证据 03 I） |
| 5 | G4 usage | **PASS** | chat 用响应 usage（含 cache 拆分）结算 0.000384；缺 usage → `usage_evidence_missing` + 0.018688 保守占用后停，未伪造；零付费轮次 `close_unused`（`P2_NO_PAID_ATTEMPT`）不停止（证据 03 B/C/E1） |
| 6 | G5/G6 | **PASS** | 5 笔预留 / 5 条结果 / 全部带中心；`gate_reserved=expected=5`；`network` 分解含 `ocr_outbound_attempts` 且恒等式成立。注：配额口径另有问题，归入 #8 |
| 7 | 零真实调用 | **PASS** | 探针内置 socket/getaddrinfo/httpx 默认传输闸门，全程 EXTERNAL=[]；共享账本 958277 B/`1f46d1b9…`、预算 1444 B/`084ba9ac…` 未变；GO 不存在（证据 03 末） |
| 8 | 契约/runbook 一致 | **FAIL** | F1（query_expansion）、F2（配额口径）、F4（runbook 码名 `go_missing` 实为 `path_missing`）、F5（OCR 价目口径） |
| 9 | 已知限制真实性 | **FAIL（部分）** | 三条已列限制全部**真实**（见 §2）；但**漏了一条真实存在的发送路径**（query_expansion，F1），且 `attempt_quota_exhausted` 的"不偷偷多发"表述不成立（F2） |
| 10 | 复跑 | **PASS** | 9 / 105 / 18 / 56 / 109，与经理印核一致（证据 01） |

## 2 三条已列限制的复核（均为真实，未伪装通过）

1. **live 不重放检索候选**：探针 B 的作答轮 `product.kind=answer, retrieved=0, sources=1`；`gate.py:1697`
   以 cited_units − retrieved_units 判 `citation_not_in_evidence` → 确实不可通过。
2. **计划项配额 = item.requests**：存在，但口径错，见 F2。
3. **QaEngine 未接 index.budget**：`QaEngine(embedder=…, reranker=…)` 下 `RagIndex` 不会自建 provider（`rag/index.py:76-108`）；
   会自建的 `_live_document_answer`（`rag/answer.py:789`）在 live 适配器空 chat 配置下构造即抛 → `CHAT_UNAVAILABLE`，**不发不付**
   （`rag/providers.py:899`）。探针 E1 亦显示 record 轮 0 次 chat。

## 3 缺陷（按严重度）

**F1（HIGH·可复现·契约失实）query_expansion 有真实发送，且被记到 answer-* 项**
- 复现：`probe.py` E2 —— 空库 + 正文型问题跑 live，`chat purposes={'query_expansion': 1}`，
  预算项却是 `answer-V01-t1`（计划里另有 `expand-V01-t1` 从未使用），并以 succeeded/0.000384 结算。
- 冲突：`docs/evaluation/p2-live-binding-v0_1.md` §10.5(2) 明写"产品当前检索路径没有 query expansion 调用；
  计划里该类项只是上界声明，不会被消耗"。实际 `conversations/service.py:2183-2191` 在 `evidence.kind=="none"`
  且有问题词项时**真实调用**模型（purpose=query_expansion）。`GatedChatGateway` 只允许每轮 1 次 chat，
  所以该笔要么被 answer 预留顶账（本轮），要么把随后的作答 chat 发送前拒绝（`chat_attempt_exceeds_plan`）
  使该轮变 `service_error`。
- 影响：不是漏账/超支（每笔都有预留、上限受控），但"计划项=资金身份"不成立，且 §10.5(2) 会误导 GO 签发人。
- 最小修复目标：要么把 `query_expansion` 接到 `expand-*` 计划项（`GatedChatGateway` 按 purpose 选 item），
  要么把 §10.5(2) 改成如实描述（存在该路径 + 当前 fail-closed 方式 + 需新计划/新 GO）。不得两处都不改。

**F2（MEDIUM·可复现·契约与实现不符）计划项配额按 embed() 调用计，不按底层请求计**
- 复现：`probe.py` D —— ingest 计划项 `requests=1`，6 条文本被 `embedding_batch_size=5` 拆成 2 次 POST，
  产生 **2 笔** `index_embedding` 预留，**没有**触发 `attempt_quota_exhausted`（该 run 仍 succeeded）。
- 冲突：`p2-run-contract` §11.2"同一计划项最多 `item.requests` 次尝试…不做多发一次再解释"、
  T206-LIVE report §6.3"多发一次 embedding/rerank 会在发送前停住（不偷偷多发）"。
  实际 `GatedEmbeddingProvider.embed` 每次调用只 take 一次，批次内每批各发一次（各带预留）。
- 影响：不超支（逐批预留、全局 `max_requests` 仍由账本管），但计划上界可被批次放大，契约表述失真。
- 最小修复：take 移到批级（或在 `GateAttemptLedger.reserve` 内 take），或把契约/report 改为"按 embed 调用计"。

**F3（MEDIUM·可复现）回归用例空转**
- `backend/tests/evaluation/test_p2_live_wiring.py::test_cli_live_refuses_without_go_before_building_adapter`
  传 `--plan str(tmp_path/"plan.json")`，但该文件从未写入 → 在 `_read_json` 就以 `FileNotFoundError` 退出 3
  （`cli.py:922` 捕获 OSError 返回 EXIT_DATA），断言"exit==3 且目录不存在"必然成立，**没有走到 live/GO 分支**。
- 复现：`probe.py` H（同一调用 stderr=`ERROR: FileNotFoundError…`；换成真实计划才得到 `path_missing`）。
- 最小修复：用例里先写计划文件，并断言拒绝码（`path_missing`）。

**F4（LOW）runbook 停止码名不存在**：runbook §4 列 `go_missing`，实际固定路径缺失报 `path_missing`（证据 02 B）。

**F5（LOW）OCR 价目口径**：契约 §11.4 写"text 0.5 / table 0.15"，实现按计划项 `price_cny_per_page` 固定结算，
不区分 mode（探针 I 用 0.5）；表述与实现不一致，或未实现按模式定价。

## 4 未覆盖（NOT-RUN）

- 真实 provider/OCR/Ragas/Langfuse/H2/全仓；`provider_billed_cny` 仍为 null（金额是保守占用口径，不是账单）。
- `attempt_accounting_mismatch` 与 `pre_send_refused` 的失败注入（仅代码审读：`p2_runner.py:929-980`、`p2_authorization.py:1121/1249`）。
- 12 页 OCR / 可重试路径（计划只有 1 页）。
- `--mode live` 与 holdout visibility 组合未跑。

## 5 证据与复现

- `evidence/verify-t206-live/01-pytest.txt`：5 套复跑（9/105/18/56/109）。
- `evidence/verify-t206-live/02-cli-refusals.txt`：6 类 CLI 发送前拒绝 + F3 空转证明。
- `evidence/verify-t206-live/03-live-probes.txt`：A/B/C/D/E1/E2/I 探针原始输出 + 资金面哈希。
- `evidence/verify-t206-live/probe.py`：自写探针（生成 02/03；tmp GO/预算/账本副本 + socket 闸门）。
