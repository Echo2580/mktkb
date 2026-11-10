# P2-T204 开发报告：OCR 导入 / 缓存 / 发布 / 来源身份（Mock-only）

- 角色：P2-T204 开发助手（全新上下文），只实施 T204，不自验通过。
- provider/model/effort：由宿主入口决定（任务书 §12 规定 `wb / cn:deepseek-v4.1-flash / max`）；本包没有自检模型入口的接口，故不声称"已核"。
- 分支/HEAD：`codex/p2-e2e` @ `eed3355`（起止一致；未切分支、未 commit/push、未建 worktree）。
- 真实调用：**0**（全 Mock，证据见 §5）；未读 `.env`/H1/H2，未碰 `var/`，未装依赖，未改既有源码/测试。

## 1. 改动清单（只动 P2-T204-dev.md 允许的文件）

| 状态 | 文件 | 行数 | sha256 前 16 | 说明 |
|---|---|---|---|---|
| 新增 | `backend/src/mktkb/evaluation/p2_ingestion.py` | 1834 | `2eda2b3207b3a734` | 受控转录/来源身份/页级回执/缓存准入 |
| 新增 | `backend/tests/evaluation/test_p2_ocr_ingestion.py` | 564 | `379fba543b46bc54` | 13 用例（计划/计费/缓存/反例） |
| 新增 | `backend/tests/integration/test_p2_ocr_source_identity.py` | 619 | `03ab49f7e31d8fdc` | 5 用例（D07–D10 产品链路 + 串用/重试/取消） |
| 新增 | `docs/evaluation/p2-ocr-contract-v0_1.md` | 165 | `7acbea032f585baa` | 绑定/缓存/费用回执契约 |
| 新增 | `docs/reports/OBS-EVAL/P2/T204/` | — | — | 本报告 + `evidence/`（3 入口） |

**既有文件改动：0。** 最小连接全部落在既有可注入形参上：`ingestion.worker.run_one_job(db, store, ocr=..., ocr_options={"max_attempts": 1})`、
`main.create_app(settings, ocr_gateway=...)`、`providers.ocr_budgeted.BudgetedOCRGateway`、`providers.tencent_ocr.TencentOCRClient(transport=...)`、
`rag.budget.BudgetLedger`，因此无需改 `product_adapter.py` / worker / 解析器 / 上传/发布/来源权限 / 产品 API/schema。
上传/发布/问答/来源详情走产品 HTTP 路由（`TestClient`/ASGI），worker 由本模块用同一 DB/Store 驱动。

## 2. 接口（契约 §1）

- `P2OcrIngestion(plan, *, transcripts, ledger, cache=None, cache_ttl_seconds=3600, max_calls=None, now=None)`；
  `.isolated_mock(work_dir, *, plan, transcripts, stage, limit_cny, historical_cny, stage_limit_cny, max_requests, ...)`。
- `bind(document_key, *, document_id, version_id)` / `run_job(db, store, *, document_key, document_id, version_id) -> JobRunResult` /
  `finalize(*, document_id, version_id, records, run_id=None) -> OcrRunSummary`；观测面 `receipts/receipts_for/runs/ledger_events/ledger_summary`、
  `gateway`（注入点）、`uses_mock_transport`。
- `OcrImportPlan/OcrDocumentPlan/OcrTranscript/OcrCallIdentity/OcrSourceBinding/OcrPageReceipt/OcrResultCache/OcrRunSummary/ProductOcrSuccess`。

## 3. 任务书 T204 五条 → 实现与用例

1. **受控 OCR 转录（Mock，不冒充真实）**：`MockOcrTransport` 是 `httpx` 传输替身，驱动**真实** `TencentOCRClient`
   的编码/签名/解析；转录只来自 `tests/acceptance/support/ocr_transcripts.py`，未登记的页/表格返回错误（不编造）。
   12 次调用计划（D07 8 页 + D08 2 页 + D09 1 图 + D10 1 图）与实际逐页一致：`test_d07_d10_...`（集成）、
   `test_twelve_mock_calls_...`（单测）；每页分片 1 ≤ 产品上限 `ParseLimits().ocr_max_tiles=64`。
2. **来源身份绑定**：七元身份（document/version/page/input hash/provider/model/region）+ 两个哈希；未登记来源锚在
   预留/发送前拒绝。跨文档 page1、同文档换版本、换图块三种串用都拒绝：
   `test_cross_document_page1_and_new_version_do_not_share_ocr_cache`（三份身份、同一图块 hash `7e16ef249ed1`、3 次真实调用）、
   `test_cache_reuse_across_documents_versions_and_tiles_is_rejected`。取消/删除后不续页、迟到响应不写成功/不进缓存：
   `test_cancel_or_delete_during_ocr_stops_later_pages_and_discards_late_result`（参数化 cancel/delete）。
3. **页级费用回执**：每页一次 `reserve→recheck→send→settle`，账本类强制 `kind=ocr`/`cost_center=ocr`；回执带
   `reservation_id`+`request_sha256`（回执与账本行逐个对上）。缺 usage/空片段/页失败/超单页上限/预算不足/账本归属不符
   都在成功之前停下：`test_missing_usage_and_empty_text_never_count_as_success`、`test_page_failure_stops_later_pages`、
   `test_budget_shortage_stops_before_send`、`test_unbound_source_and_unplanned_page_are_refused_before_reserve`。
4. **端到端一致性**：上传→解析→发布→索引（4 份资料/13 单元）→问答引用→来源详情，引用单元与发布版本的
   document/version/page 一致、文本等于该页受控转录（D10 为 table row 的 fields）：
   `test_d07_d10_ocr_import_publish_index_and_citation_trace_to_same_unit`。
   三类证据：无缓存（新调用 miss）、合法真实缓存命中（`test_same_identity_second_call_hits_legal_cache_without_new_charge`，
   0 请求/0 计费）+ 产品检查点复用（重试用例 `product_checkpoint_reuses=3` 且逐页 `certified`）、
   伪造/过期缓存拒绝（`test_forged_expired_and_simulated_cache_entries_are_refused`）。
   **口径（R2/B4/N7）**：端到端链路上产品检查点**先短路**已成功页，`OcrResultCache` 命中只能在模块级证明
   （单测）；端到端给的是「产品检查点复用」，两者分别计数，不混称"缓存命中"。
5. **反例**：取消/删除中断、迟到响应不写、页失败停、预算不足停、缓存串用拒绝、`finalize` 只按产品成功审计行准入
   （`test_cache_admission_requires_product_success_record`）。

## 4. 实测口径（Mock，费用=0）

- 计划 12 次：11×text（0.5）+ 1×table（0.15）= **5.65 元**上界；账本 12 `reserved` + 12 `result`，
  全部 `cost_center=ocr`，`center_accounted_cny={"ocr": 5.65}`。
- 失败重试：首轮 4 次尝试（第 4 页 OCR_UNAVAILABLE → 后续页在网关处 OCR_INGESTION_STOPPED，报告可见），
  重试轮复用同版本 3 页检查点（0 调用）+ 5 次新调用 = 9 次底层调用；`charged=2.5`（第 4 页失败那笔另计 0.5）。
- 取消/删除：第 3 页在途取消，`calls_during=calls_after=3`，第 4–8 页未调用；第 3 页记录 `discarded`、
  回执 `rejected:cache_provenance_missing`，缓存只有第 1–2 页。

## 5. 验证（只跑本包两文件）

- 命令：`.\.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p2_ocr_ingestion.py backend/tests/integration/test_p2_ocr_source_identity.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t204`
- 结果：**18 passed**（13 + 5），exit 0，18.0s（证据 `evidence/01-pytest.txt`）。
- **未跑旧用例**：既有源码/测试 0 改动，无受影响模块（`backend/` 下只多 3 个新文件）。
- **0 真实调用证据**（三方互证）：
  1) 两测试文件 `pytestmark` 挂 `t09_network_guard`（外部 socket/httpx 请求即 fail）；
  2) 结构断言 `ingestion.uses_mock_transport is True`（真实客户端只接传输替身）；
  3) `evidence/02-probe-output.txt`：socket/httpx 闸门实测 `external_outbound_attempts=[]`
     （loopback 22 次为 ASGI/事件循环自管道，非出站）。

## 6. 证据（3 入口）

| 入口 | 内容 |
|---|---|
| `evidence/01-pytest.txt` | 指定命令输出（18 passed，exit 0） |
| `evidence/02-probe-output.txt` | A 零出站 12 次调用 / B 产品链路 12 次计划=实际+引用身份 / C 串用·重试·取消计数 |
| `evidence/probe_t204.py` | 可复跑生成器；R2 起默认打印 stdout、**不再覆写** `02-probe-output.txt`（要落盘用 `--out`） |

## 7. 偏差 / 限制 / 请验收关注

- **D10 模式**：产品 `looks_like_rule_table` 判 D10 为 **table**（既有 `test_rule_table_scan` 同结论），
  故 12 页计费是 **5.65** 而非按"全 text"估的 6.00（差 0.35）；T206 的价格/中心基线据此修正，
  6.0 的中心额度仍覆盖。
- **停止是 run 级**：`BudgetedOCRGateway` 一旦失败自我停止，因此每轮 `run_job` 重建该包装（钱的上界仍由同一
  账本阶段约束）；"失败后是否继续下一份资料"由调用方决定，T206 需在首个失败后不再启动新 run。
- **跨文档同字节上传被产品自身挡住**：`duplicate content` 守卫拒绝同一字节的第二份资料，故集成用例用
  "像素相同、文件字节不同"的再保存图（OCR 图块 hash 仍相同）来证明串用拒绝；字节级串用由单测覆盖。
- 未做（属 T205/T206/T207）：真实 OCR、真实 TTL/价格、真实账本/GO 接入、评分与硬门禁；`region` 只在身份
  与线上头部校验（账本行沿用既有 schema 不含 region）。
- 待独立验收：行为/计数以 `probe_t204.py` 可复跑；未声称"已通过"。

## R2 加固（2026-11-10，对照 T204 验收 N1/N2/N6/N7）

- 现场/边界：`codex/p2-e2e` @ `d850b49`（未 commit/push）；只改允许文件；真实调用 **0**，未读 `.env`/H1/H2、未联网。
  **行为零改动**：`p2_ingestion.py` 未动；本包只改契约措辞、探针输出方式与一行注释。
- **B1(N1) 复跑不再自改证据**：`evidence/probe_t204.py` 默认只打印 stdout，落盘需显式 `--out`，stdout/stderr 强制 UTF-8。
  实测复跑后 `evidence/02-probe-output.txt` 字节不变（7786B / `805dc852…`）；探针 exit 0、`external_outbound_attempts=[]`、`loopback_attempts=22`。
- **B2(N2) 契约 §4 拒绝码措辞**：`cache_mode_mismatch` 与 `cache_provider/model/region_mismatch` 标为**当前路径不可达的防御分支**，
  并写明实际语义——换模式落到 `(page, mode)` 另一个桶 ⇒ `miss`（不复用）；伪造身份在 `OcrCallIdentity.from_payload` 被拒 ⇒
  `cache_payload_invalid` 隔离（0 可用条目）。门控未放宽。
- **B3(N6) 过时注释**：`backend/tests/acceptance/support/ocr_transcripts.py:79` 原写"D10 判定为 text 模式"与现行为（table，
  `test_rule_table_scan` 断言 True）相反，已改为 table 并注明"行为未改"。任务单写的 `backend/src/mktkb/providers/ocr_transcripts.py`
  不存在；实际文件在 tests 支持目录，本次仅改注释。
- **B4(N7) 端到端"缓存命中"口径**：契约 §4/§7 与本报告 §3 已区分「单测缓存命中」与「产品检查点复用」。
- 复跑（本机亲跑）：`pytest test_p2_ocr_ingestion.py test_p2_ocr_source_identity.py` → **18 passed**；`test_rule_table_scan.py` → 6 passed；
  `probe_t204.py` → exit 0、出站 0。原始输出见 `../R2/evidence/01-pytest.txt`、`../R2/evidence/02-probe-outputs.txt`；统一报告 `../R2/report.md`。


## T206-PRE 补充（2026-11-11，绑定与失败语义）

- 现场/边界：`codex/p2-e2e` @ `a8f2a6b`（未 commit）；**本包业务代码零改动**
  （`p2_ingestion.py` 未动、缓存/OCR 语义未动）；真实调用 **0**，未读 `.env`/H1/H2、未联网。
- 本包不参与本轮新增的 trace 身份/引用证据/config_hash 绑定（那是 T203 运行器与 T205 评分侧的口径），
  但 T206 真实 pilot 会复用同一份 run 产物：OCR 页面计数与 `cache_input_hash` 身份仍由本包契约
  （`p2-ingestion-v0_1`）约束，未放宽。
- 回归：`test_p2_ocr_ingestion.py` + `integration/test_p2_ocr_source_identity.py` → **18 passed**（未改动用例）。
- 绑定契约入口：`docs/evaluation/p2-live-binding-v0_1.md`；本包报告与证据未改。
