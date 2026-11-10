# P2 OCR 导入 / 来源身份 / 页级费用回执契约 v0.1（T204）

状态：**candidate（T204 交付）**，`schema_version = p2-ocr-ingestion/v0.1`；未经 T900 独立验收前
不得当作正式基线。本契约只冻结 T204 新增模块的行为，**不改** T201 的 `p2_contracts.py` /
`p2_authorization.py`、T203 的 `product_adapter.py` / `p2_runner.py`，也不改产品
API/schema/业务库。本包实现是 **Mock-only**：真实 OCR 在 T206/T207 按同一契约验证。

## 1. 模块与冻结接口

### 1.1 `mktkb.evaluation.p2_ingestion`

| 对象 | 语义 |
|---|---|
| `OcrDocumentPlan`(document_key, path, file_kind, page_count, image_count, tiles_per_page=1, expected_mode) | 一份资料的导入计划（页数/图片数/每页分片）；`planned_calls = 页数或1 × tiles_per_page`，超过受控上限 13 直接拒绝 |
| `OcrImportPlan`(documents, label="") | 计划集合；`pages`（PDF 页）、`images`（图片）与 `planned_calls` 分别计数 |
| `OcrTranscript`(document_key, pages={页: 行}, table=(表头, 数据行) 或 None) | 受控转录（只转录 fixture 页面内容，不内置验收答案）；没有转录的页/表格一律拒绝编造 |
| `MockOcrTransport` | `httpx.BaseTransport` 替身：驱动**真实** `TencentOCRClient` 的编码/签名/解析，0 出网 |
| `OcrCallIdentity` | 一次调用的七元身份 + 两个哈希（见 §2） |
| `OcrSourceBinding` | 服务端可信 document/version → 计划资料 + 来源锚 |
| `OcrPageReceipt` | 一页一次调用的回执（见 §3） |
| `OcrResultCache` / `OcrCacheEntry` / `OcrCacheDecision` | 结果缓存与准入/拒绝判定（见 §4） |
| `ProductOcrSuccess` | 产品 `ocr_call_records` 的只读投影：缓存准入与"检查点复用"认证的唯一依据 |
| `OcrRunSummary` | 一轮 run 的对账：计划/真实请求/缓存命中/检查点复用/失败/缺失/费用 |
| `P2OcrIngestion` | 驱动 `run_one_job(db, store, ocr=gateway, ocr_options={"max_attempts": 1})` |
| `OcrCostCenterBudgetLedger` | `BudgetLedger` 子类：只接受 `kind=ocr`，每笔预留强制 `cost_center=ocr` |

关键方法：

```python
P2OcrIngestion(plan, *, transcripts, ledger, cache=None, cache_ttl_seconds=3600.0,
               max_calls=None, now=None)
P2OcrIngestion.isolated_mock(work_dir, *, plan, transcripts, stage=..., limit_cny=20.0,
                             historical_cny=0.0, stage_limit_cny=9.66, max_requests=400, ...)
ingestion.bind(document_key, *, document_id, version_id) -> OcrSourceBinding
ingestion.run_job(db, store, *, document_key, document_id, version_id) -> JobRunResult
ingestion.finalize(*, document_id, version_id, records, run_id=None) -> OcrRunSummary
ingestion.binding_for_version(document_id, version_id) -> OcrSourceBinding | None
ingestion.receipts / receipts_for(run_id) / runs / ledger_events() / ledger_summary()
ingestion.gateway                       # 注入点（worker 或 create_app）
ingestion.uses_mock_transport -> bool   # 结构性 0 出网证据
```

### 1.2 分层（不许绕过任何一层）

``````
executor(OcrExecutor) → P2OcrIngestion.recognize（身份/计划/缓存/回执）
                      → BudgetedOCRGateway（reserve→recheck→send→settle，run 级）
                      → TencentOCRClient（真实编码/签名/解析）
                      → MockOcrTransport（受控转录，0 出网）
``````

- **每次**供应商调用都先经过 `BudgetLedger.reserve` 与发送前 `recheck`，再 `settle`；
  缓存命中不进入这一层（0 预留、0 结算、0 计费）。
- `BudgetedOCRGateway` 是 **run 级**：它一旦失败即自我停止，下一轮 `run_job` 重新构造；
  钱的上界仍由同一隔离账本阶段额度/请求上限约束（不因换 run 而重置预算）。
- `P2OcrIngestion.stopped` 也是 run 级（见 §5）。

## 2. 来源身份绑定

`OcrCallIdentity` 固定七个字段，缺一项都不是同一次调用：

| 字段 | 来源 | 说明 |
|---|---|---|
| `document_id` / `version_id` | worker 实际持有的 DB 身份 | 解析器/上传文件名无权决定；`OcrExecutor` 用可信来源锚覆盖解析器入参 |
| `page` | 产品解析的页号（图片为 1） | 逐页列条目，不按题数估算 |
| `input_sha256` | 实际图块字节 | 线上再校验一次（传输替身解码 `ImageBase64` 后比对） |
| `mode` | 产品判定 text/table | 决定模型与单价 |
| `provider` / `model` / `region` | `p2_contracts` 冻结值（tencent / GeneralAccurateOCR 或 RecognizeTableAccurateOCR / ap-guangzhou） | 线上校验 `X-TC-Action` 与 `X-TC-Region` |

- `source_scope = sha256("ocr-source-v1|document_id|version_id")`（复用 `providers.types`）。
  **未登记**的来源锚、与绑定不一致的锚，一律在预留与发送**之前**拒绝（`OCR_SOURCE_UNBOUND`）。
- `request_sha256 = sha256("ocr-v2|scope|mode|page|" + tile_bytes)`：与
  `BudgetedOCRGateway` 落账公式逐字节一致；回执记录**账本行里的同一个哈希**，不一致即
  `OCR_LEDGER_BINDING_MISMATCH` 并停止。
- 同一 version 不得绑定到不同 `document_key`（本地即拒绝）。

## 3. 页级费用回执

每页/每块一次调用产生一条 `OcrPageReceipt`（不含正文）：

| 字段 | 含义 |
|---|---|
| `identity` | §2 七元身份 + 两个哈希 + 来源锚 + 该模式成本上界 |
| `status` | `succeeded` / `failed` / `refused` / `invalid_output` |
| `cache` | `miss` / `hit` / `rejected:<reason>` |
| `bound_cny` | 计划上界（text 0.5、table 0.15；固定价，来自 `p2_contracts`） |
| `charged_cny` | 账本该笔 `conservative_charge_cny`（失败页按固定价保守留账，不清零） |
| `reservation_id` / `ledger_request_sha256` | 对回 `reserved` 行；缓存命中为 null/0 |
| `provider_request_id` | 供应商 RequestId（经安全收敛），缺失即 `OCR_USAGE_MISSING` |
| `elapsed_ms` / `tiles` | 单次耗时、该次分片数（本计划恒为 1） |

硬规则（任一触发即**停止**，不写成功、不静默重试）：

1. 缺 usage（无 RequestId）→ `OCR_USAGE_MISSING`；
2. 空片段（无文本且无表格行）→ `OCR_EMPTY_RESULT`，不得记成功、不赋予成功语义；
3. 页失败（供应商错误/超时）→ 该页 `failed`，后续页在网关处拒绝（`OCR_INGESTION_STOPPED`）；
4. 超单页上限（同 (来源锚, 页) 第 2 个 tile）→ `OCR_PAGE_CALL_LIMIT`；超计划调用数 →
   `OCR_PLAN_CALL_LIMIT`；两者都在预留之前拒绝；
5. 预算/授权不足 → `OCRBudgetRefused`（未预留未发送），回执 `refused`、charged=0；
6. 账本归属不一致 → `OCR_LEDGER_BINDING_MISMATCH` 并停止。

成本归属：`OcrCostCenterBudgetLedger` 只允许 `kind=ocr` 且强制 `cost_center=ocr`，
因此 `ledger.summary()["center_accounted_cny"]["ocr"]` 可从账本独立重算，等于逐页回执
`charged_cny` 之和（失败页也计入）。

## 4. 缓存准入与拒绝

- **准入条件**（全部满足）：七元身份完全一致；`origin="observed-provider-call"`（真的有调用发生过）；
  有产品成功审计行 `product_record_id` 且其 `input_sha256` 与本条一致、`provider_request_id`
  非空；未过期（`admitted_at + ttl`）；结果非空。
- 缓存只由 `finalize()` 依据 `ProductOcrSuccess` 写入；`from_payload()` 恢复时逐条重校验，
  非法条目进 `quarantined`（`cache_payload_invalid`），不进可用缓存。
- **拒绝原因**（稳定码，机读；不回显被拒条目的原始值）：

| reason | 触发 | 可达性（B2/N2） |
|---|---|---|
| `cache_source_identity_mismatch` | 同页不同 document/version（两份资料的 page1、同资料换版本） | 可达：`lookup` 在「同 (page, mode) 桶」里看到另一条身份 |
| `cache_input_hash_mismatch` | 同页同模式、图块字节不同 | 可达：同上，桶内候选的 `input_sha256` 不同 |
| `cache_mode_mismatch` | text/table 不同 | **当前路径不可达**：桶的主键是 `(page, mode)`，换模式会落到另一个桶 ⇒ 结果是 `miss`（不复用、也**不判拒绝**）；该码只保留为 `OcrCallIdentity.mismatches()` 的防御分支 |
| `cache_provider_mismatch` / `cache_model_mismatch` / `cache_region_mismatch` | 供应商/模型/区域不符 | **当前路径不可达**：伪造 payload 在 `OcrCallIdentity.from_payload` 就被拒，条目进 `quarantined`（`cache_payload_invalid`），根本不会成为候选；三者同为防御分支 |
| `cache_expired` | 超过 TTL | 可达（命中同一身份后判 TTL） |
| `cache_simulated` | `origin="simulated"`（模拟缓存不得冒充真实效果） | 可达（同身份、非 observed 条目） |
| `cache_provenance_missing` | 无产品成功审计行 / 缺 usage / 空结果 | 可达（删除·迟到·取消路径实测） |

> 诚实说明（R2）：上表 4 个"不可达"码**行为不变**（没有放宽门控），语义是二选一的 fail-safe：
> 换模式 = `miss`（走真实调用，0 复用），伪造身份 = `cache_payload_invalid` 隔离（0 可用条目）。
> 契约按**实际码**描述，避免 T900 按字面复验时把"不可达"当成实现缺失。

> 端到端与单测的口径（B4/N7）：产品检查点会**先短路**已成功页，`OcrResultCache` 的命中因此
> 只能在模块级证明（单测：同身份二次调用 0 请求 0 计费）；端到端证据给的是
> 「产品检查点复用」（`product_checkpoint_reuses`），**不要**把它称作"缓存命中"。两者分开计数。

- 被拒条目**不会被当作结果返回**：网关继续走真实调用（新回执 `cache=rejected:<reason>`）；
  命中与真实调用分别计数（`summary.cache_hits` / `summary.provider_requests`）。
- 迟到/被丢弃的响应没有产品成功审计行 ⇒ `finalize` 拒绝准入（不会"复活"缓存）。

## 5. 计数与停止语义

`finalize()` 的 `OcrRunSummary`：

| 计数 | 含义 |
|---|---|
| `planned_calls` / `planned_pages` | 计划（本包：D07 8 页 + D08 2 页 + D09 1 图 + D10 1 图 = 12 次） |
| `provider_requests` | **本轮**传输替身实际收到的请求数（按 `run_job` 窗口计） |
| `attempts` | 本轮回执数（含失败/被拒尝试；重试轮单独计） |
| `cache_hits` | 缓存命中（0 供应商请求、0 计费） |
| `product_checkpoint_reuses` | 本轮没有调用、但产品已有成功审计行（同一 version/page/mode）且**有 usage** 的页 |
| `failed_pages` / `missing_pages` | 失败页 / 本轮既无回执也无可用审计行的页 |
| `charged_cny` / `bound_cny` | 本轮保守占用 / 计划上界 |

- 停止是 **run 级**：是否在上一轮失败后继续跑下一份资料由调用方决定（T206 在首个服务/授权/预算/
  数据完整性错误后不再启动新 run）。重试是显式动作，会新增真实尝试（按次计费/计数）。
- `plan_matches_provider_requests` 只在"本轮每个计划页各一次真实请求"时为 true；
  重试轮/复用轮用 `product_checkpoint_reuses`、`attempts` 分开说明，不拼成一次完整运行。

## 6. 本包实测口径（2026-11-10，Mock-only）

- 计划 12 次：11 次 text（0.5）+ 1 次 table（0.15）= **5.65 元**上界（D10 被产品规则
  `looks_like_rule_table` 判为 table 模式；既有 `test_rule_table_scan` 同结论，
  早前"全 text=6.00"的估算因此偏高 0.35 元，预算中心 6.0 仍覆盖）。
- 账本：12 次 `reserved` + 12 次 `result`，全部 `cost_center=ocr`，
  `center_accounted_cny = {"ocr": 5.65}`；**真实费用 = 0**（Mock 传输，无真实凭据、无出网）。
- 失败重试：首轮 4 次尝试（第 4 页失败后停），重试轮复用同版本 3 页检查点（0 调用）+ 5 次新调用；
  累计 9 次底层调用，费用口径分别记录，不合并成"12 次完成"。

## 7. 未覆盖 / 后续

- 真实 OCR 调用、真实供应商错误码分布、真实 TTL/价格变动：T206/T207（同一契约）。
- `region` 只在本模块身份与线上头部校验，账本行不含 region（沿用既有 `BudgetLedger` schema）。
- 跨进程缓存持久化（`as_payload`/`from_payload` 已具备）与真实账本接入属 T206 装配；
  本包只证明语义，不写共享账本/GO。
- 结果缓存不改变产品自身的 OCR 检查点；两者命中分别计数（产品检查点由 `finalize` 认证）。
  端到端链路上产品检查点先短路成功页，`OcrResultCache.lookup` 在集成路径里不会产生"命中"——
  见 §4 末尾的口径说明（R2/B4）。
