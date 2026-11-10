# P2-T203 开发报告：产品端到端运行器（隔离应用 + Mock 证据）

- 角色：P2-T203 开发助手（全新上下文），只实施 T203，不自验通过。
- provider/model/effort：由宿主入口决定（任务书 §12 规定 `wb / cn:deepseek-v4.1-flash / max`）；本包**没有**自检模型入口的接口，故不声称"已核"。
- 分支/HEAD：`codex/p2-e2e` @ `97fba10`（起止一致；未切分支、未 commit/push/worktree）。
- 真实调用：**0**（全 Mock，证据见 §6），未读 `.env`，未碰 `var/`，未装依赖。

## 1. 改动清单（只动 P2-T203-dev.md 允许的文件）

| 状态 | 文件 | 行数 | sha256 前 16 | 说明 |
|---|---|---|---|---|
| 新增 | `backend/src/mktkb/evaluation/product_adapter.py` | 1186 | `b7d3f372d65a3f70` | 隔离应用 + Mock provider + 产品 HTTP 驱动 |
| 新增 | `backend/src/mktkb/evaluation/p2_runner.py` | 1186 | `dd90e8cc49d1286d` | 逐轮编排/门序/停止语义/产物 |
| 改动 | `backend/src/mktkb/evaluation/cli.py` | +147/-0 | `1e5fab3faee815a9` | 只加 `p2-run` 子命令，旧命令未改 |
| 改动 | `backend/src/mktkb/evaluation/p2_authorization.py` | +4/-0 | `f2cc2f09c7f51ac7` | T201 遗留 ② 小加固（见 §7） |
| 新增 | `backend/tests/evaluation/test_p2_runner.py` | 877 | `ac75b860c3b734fe` | 14 用例（编排/门/反例/holdout/CLI） |
| 新增 | `backend/tests/integration/test_p2_product_e2e.py` | 441 | `517885e9f6d23ada` | 4 用例（产品真实链路） |
| 改动 | `backend/tests/evaluation/test_p2_authorization.py` | +15/-0 | `dc6267ccc344ec5e` | 对应加固的 1 个用例 |
| 新增 | `docs/evaluation/p2-runner-contract-v0_1.md` | 124 | `36de5bc2e5a8d4fa` | 接口/产物/停止码契约 |
| 新增 | `docs/reports/OBS-EVAL/P2/T203/` | — | — | 本报告 + `evidence/`（3 入口） |

> R1 加固改动了上表中 4 个代码/测试文件，行数与哈希已变——以 `## R1 加固` 的表格为准。

未改：`live.py`、`qa/service.py`、`rag/*`、产品路由/模型/schema、`p2_contracts.py`、其它既有测试。

## 2. 接口

- `ProductEvalAdapter(out_dir, *, ingest_plan, dataset, chat, users, turn_timeout_seconds=60, trace_enabled, trace_content_mode="hash", purge_traces_on_close, label)`：
  `async start/ingest/ask_turn/close`（§6.2 冻结签名）+ 只读观测面（`open_conversation/source_detail/list_messages/messages_in_db/provider_calls`）。
  全部动作经产品 HTTP（ASGI）：上传 → worker 解析 → 发布 → 提问 → 消息/来源详情；**不调** `RagIndex.ask`。
- `async run_p2(plan, *, adapter, authorization, dataset=None, gate=None, cancel=None, now=None, settle_evidence=None) -> P2RunResult`。
- `build_dry_run_authorization(plan, preflight, *, issued_by, ttl_seconds, now, nonce)`：`production_ready=False` 的空跑授权（非 GO）。
- CLI：`cli p2-run --plan P --snapshot S --out D [--cases C] [--ingest F ...] [--visibility holdout --holdout-manifest M]`（预检不过 exit 3、不建目录）。

**偏差声明**（相对任务书 §6.2 的 `run_p2(plan, *, adapter, authorization)`）：新增的 `dataset/gate/cancel/now/settle_evidence`
都是带默认值的关键字参数，三参数调用形式仍成立（dataset 缺省取 `adapter.dataset`）；返回值仍是 T201 的 `P2RunResult`，
逐题/逐轮细节只在产物文件里。理由与影响已写入契约文档 §1.2。

## 3. 产物（`<out_dir>/p2-run/`）

`run_manifest.json`（dataset/manifest/plan/授权/pipeline 代码哈希/provider/隔离路径/ingest）、`summary.json`、`run_result.json`、
`gate.json`（`quality_gate="deferred-to-T205"`）；公开 run 加 `cases.jsonl`+`requests.jsonl`；holdout 只写 `holdout_aggregate.json`（无 case_id/题干，item_id 只留 sha256）。

## 4. 任务书 T203 五条 + 反例对照（测试名可 grep）

| 要求 | 落点 |
|---|---|
| P1 不回退；P2 默认/dry-run 不构建真实 provider | `test_default_adapter_builds_no_real_provider`（`model_gateway is None`、`MODEL_NOT_CONFIGURED`）；`live.py` 零改动 |
| 隔离应用 + 独立库/用户 + 上传/解析/发布/索引 | `test_product_path_end_to_end_with_mock_providers`（tmp 内路径、202/succeeded/200、revision=3、ready/3 docs） |
| 每 case 独立会话、多轮同会话逐轮 trace | 同上（两轮两条 trace）+ `test_dry_run_completes_without_production_ready` |
| 同 `client_request_id` 不重复消息/不重复付费 | 同上（`message_id/request_id` 相同、消息数不变、`chat.call_count` 不变） |
| Mock embedding/rerank/chat 注入；两分支都过产品入口 | 同上 + dry-run（`trace_path` = `rag`/`legacy`/`legacy_with_rag_candidates`；chat=MockTransport） |
| 引用转换、持久化、来源详情权限、有效版本复核 | 同上（sources 摘要 locator/version/status、详情 200 vs 他人 403、旧版本 410 superseded、新版本 ≥v2） |
| 产物五件套 + holdout 只聚合 + trace 保护 + 失败留现场 | 五件套见 §3；`test_holdout_run_writes_aggregate_only_and_purges_traces`（无 cases/requests、trace 库删除、产物零题干）；失败现场见 §5 停止码用例 |
| 与 T201 门衔接（production_ready 才能发、空跑≠成功） | `test_real_adapter_without_production_ready_never_sends`（HTTP=0）、`test_mock_gate_runs_full_send_sequence_without_billing`（门序 begin/confirm/settle + `real_requests=0`）、`test_empty_run_is_blocked_not_succeeded` |
| 反例：取消 / 超时 / 无候选拒答 / 多轮中间失败 / 知识库变化 / 服务错误后不付费 | `test_cancel_between_cases…`、`test_turn_timeout_stops_run_without_retry`（0.2s 客户端硬截止、chat=1 次）、反例三态见下、`test_knowledge_changed_while_turn_in_flight`（产品自身 `knowledge_changed`）、`test_service_error_stops_and_does_not_pay_again`（503 后 chat=1 次、后续 case 未执行） |

"无候选拒答"：`test_dry_run…` 的 `P04`（火星店）产品返回 `not_found` 且该轮 **0 次 chat**（规则路径合法零 chat）——
R1 起这条是**真实断言**（逐轮实测 `provider_calls.chat==0` 且 `kind=not_found`，见 R1/F4）；
"多轮中间失败"：`test_plan_item_missing_fails_closed` + 超时/服务错误用例（同一轮失败即停，后续 case 记 `not_executed`）。

## 5. 实际命令与结果（只跑本包文件；另附加固后的 T201 套件）

```
pytest backend/tests/evaluation/test_p2_runner.py backend/tests/integration/test_p2_product_e2e.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t203
→ 18 passed（16.0s）
pytest backend/tests/evaluation/test_p2_authorization.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t203-auth
→ 70 passed（原 69 + 加固 1）
```
↑ 前缀 `.\.venv\Scripts\python.exe -B -m`；原始输出见证据 1

未跑：`test_p1_source_bridge.py`/`test_p1_refusal_scope_http.py`（未改公共转换）、全仓 `backend/tests`、浏览器/Playwright（T900）。

## 6. 真实调用 = 0 的证据（三方互证）

1. 网络闸门：两个测试文件都 `pytest.mark.usefixtures("t09_network_guard")`（复用 `tests/acceptance/support/netguard.py`，不复制），
   任何**外部**出站即测试失败；18 个用例全绿（R1 后 27）⇒ 外部尝试 0。
2. provider 身份：chat 走**真实** `DeepSeekClient` + `httpx.MockTransport`（`manifest.providers.chat.transport`），
   `outbound_network=0`（R1 起是传输层的**实测**结果：Mock 调用计入"拦截"，不进出站计数）；
   embedding/rerank 是离线计数替身（`FakeEmbeddingProvider`/`LexicalReranker` 包装）；OCR 未使用。
3. 供应商 POST 计数：`mktkb.rag.providers.post_counters()` 全 0（RAG 真实 HTTP 的机器计数）。
4. 资金/请求回执：`run_result.requests_sent=0`、`summary.requests.real_requests=0`、`billed_cny=0`、`production_ready=False`
   （R1 起 `real_requests/billed_cny/outbound_attempts` 是**实测值**：传输层 + RAG 供应商 POST 计数，不是常量）；
   未创建/写入共享账本与 GO（`ledger_path="in-memory:dry-run"`）。
5. 隔离：`Settings(_env_file=None)` + 会话级 `.env` 隔离（既有 conftest），全部产物落在 `backend/.pytest-tmp/`（gitignore）。

## 7. T201 遗留 ② 小加固（已在 report 声明）

`P2Gate._assert_center_accounting` 增加 `set(centers) ⊆ COST_CENTERS` 校验（+4 行，reason=`cost_center_unregistered`），
并加 1 个用例；T201 套件 70 passed。其余 T201 接口/固定路径/账本语义未动。

## 8. 限制与未做项（如实）

- **真实 P2Gate 预留/结算链未真跑**：真实 `P2Gate` 只能建在固定账本/GO 上（会写共享账）；已用**桩门**（`is_mock_gate=True`）验证门序与拒绝路径，
  并**拒绝**"Mock 适配器 + 真实门"。真实链与 `UsageEvidence` 由 T206 经 `settle_evidence` 注入。
- 本包只执行 `answer` 操作；`ocr/judge/independent` 仍只是计划项（T204/T208）。
- H2 用**合成**题集验证"只产聚合/trace 删除/无题干泄漏"，未读真实 H2（真实受限运行属 T206）。
- 未触及：T201 遗留 ④（`P2Gate.open` 私有注入改构造期）、遗留 ⑤（`gate.result()` 空跑语义本体；runner 用 `no_case_executed` 区分）；
  超时反例用 0.2s 缩短**客户端**硬截止复现（60s 口径取自 `BUDGET_SECONDS`，未改产品限额）。未做提交/推送/合并。

## 9. 证据入口（≤4）

1. `evidence/pytest-p2-t203.txt`：18 passed + T201 加固后 70 passed 的原始输出。
2. `evidence/p2-t203-digest.json`：从实际产物聚合的机器证据（五件套、mock_gate、blocked、timeout、holdout 聚合、文件 sha256、真实调用=0）。
3. 契约 `docs/evaluation/p2-runner-contract-v0_1.md`（本报告即第 4 入口）。
4. R1 加固证据 `evidence/r1/`：`pytest-r1-runner-e2e.txt`（27 passed）、`pytest-r1-auth.txt`（70 passed）、
   `r1-digest.json`（F1 实测/F2 stop_code/F3 拒绝/F6 封存前后命中）与可复跑探针源码。

## R1 加固（2026-11-10，对照独立验收 F1–F6）

- 现场/边界：`codex/p2-e2e` @ `897a751`（未 commit/push）；只改本包允许文件；真实调用 **0**，未读 `.env`/H1/H2、未联网；全部为正向加固（无行为回退）。
- **F1 证据完整性**：`NetworkMeter` 包住注入给 `DeepSeekClient` 的传输（MockTransport 记"拦截"、真实传输记"出站"），RAG 供应商 POST 取 `post_counters()` 增量；每轮前后快照相减 → `requests.jsonl.provider_calls/charged_cny`；`real_requests`=实测出站>0 的请求数、`billed_cny`=其实际结算额、`network.outbound_attempts`/`provider_calls().outbound_network`=实测总出站。缺测量字段直接报错、**不按 0 兜底**；顺带修正成功结算不累计 `settled_cny`（曾表现"成功却 0 元"）。
- **F2 live 护栏**：live 追加硬断言 `isinstance(gate, P2Gate)` 且无 `is_mock_gate`；桩门/鸭子门 → 发送前 `blocked/live_requires_real_gate`（门 0 步、适配器 0 行）；`gate.json.real_sends_allowed` = live + production_ready + 全部发送前检查通过。
- **F3 holdout fail-closed**：`visibility=holdout` 且 `purge_traces_on_close=False` → 一行都不跑：`blocked/holdout_requires_purge`、`failure.stage=holdout_policy`、不灌库/不建会话/不调 provider、trace 库不建（`trace_retention=refused-before-start`）。
- **F6 H2 防泄漏**：holdout `close()` 删隔离业务库 `data/mktkb.sqlite3`（+ `-wal/-shm/-journal`；题干明文在会话/消息/请求表），返回 `seal_receipt`，删不干净即报错；公开/dry-run 不动。哨兵题干测试：close 前命中、close 后 **0 命中**，聚合产物照旧；`summary.holdout.question_store=deleted-at-close`。
- **F4/F5**：`test_dry_run…` 补真断言 P04 `kind=not_found` + 该轮 `provider_calls.chat==0`（另有轮次 chat>0 作对照）；新增 `adapter_must_be_mock`（真实适配器+无门）与多轮中间失败（第 2 轮 503，保留 stage/case/turn/item/ticket）两个测试。

**改动文件（行数 / sha256 前 16）**：`product_adapter.py` 1300/`a782e211355825d9`；`p2_runner.py` 1315/`7c6a011fbe8d569a`；`test_p2_runner.py` 1205/`36e6b7f137b618be`；`test_p2_product_e2e.py` 445/`378a7e8aa26f9f9b`；契约 `p2-runner-contract-v0_1.md` 145/`4c7d3b6e19c46b9e`（已同步 §1.1/§2/§3/§4/§5）。

**复跑（本机亲跑）**

```
./.venv/Scripts/python.exe -B -m pytest backend/tests/evaluation/test_p2_runner.py backend/tests/integration/test_p2_product_e2e.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t203-r1
→ 27 passed, 1 warning in 21.50s（T203 时 18；R1 净增 9 个用例）
./.venv/Scripts/python.exe -B -m pytest backend/tests/evaluation/test_p2_authorization.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t203-r1-auth
→ 70 passed, 1 warning in 1.55s
./.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/T203/evidence/r1/probe_r1_f1_f2_f3_f6.py
→ F1 mock：real_requests=0/billed=0/outbound=0（拦截 1）；注入 2 次出站/轮：real=2、billed=0.037376、outbound=4
   F2：live_requires_real_gate + real_sends_allowed=false + 门 0 步；F3：holdout_requires_purge + provider 0 次
   F6：close 前明文命中 1 → close 后 0；业务库/trace 库均不存在，holdout_aggregate.json 仍在
```

**残留（如实）**：① 真实 `P2Gate` 的**正向** live 链仍未真跑（需固定 GO/账本，归 T206）——R1 只证"桩门/鸭子门必被拒 + 只有真实 `P2Gate` 过类型判定"；② "真实传输会让出站>0"由注入计数测试证明，T206 首次真实发送需复核同一字段；③ 封存只删业务库（题干），索引/存储语料副本与聚合产物保留；④ mock_gate 的 `run_result.settled_cny` 由 0 变 0.018688/轮（与 `settle_success` 同口径），`summary.requests.billed_cny` 仍按实测出站计 0，两套口径见契约 §5。⑤ 编号对照：review.md 的 F6 是"产品预算/结算包装未进本包链路"（按任务书归 T206，需真实 `build_gateway`）；R1 修的 F6 指验收"残留风险"里的 holdout 业务库题干明文。
