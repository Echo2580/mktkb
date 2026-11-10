# P2-T204 独立验收：OCR 导入 / 缓存 / 发布 / 来源身份

- 角色：独立验收助手（全新上下文），证伪优先。只写本文件与 `evidence/verify/`；未改源码/测试/报告/契约，未 commit/push。
- 现场：`codex/p2-e2e` @ `eed3355`。`git diff HEAD --stat` = 仅 `.claude/handoffs/_index.md`（+6 行协调文档）；
  新增未跟踪：`p2_ingestion.py`(1834)、两测试(564/619)、`p2-ocr-contract-v0_1.md`(165)、report+evidence。**既有源码 0 改动**。
- 结论：**8/8 条 PASS**；7 条 NOTE（N1–N7）均不阻断。不宣称 P2 整体通过。

## 1. 零真实调用 — PASS

- 复跑 probe：`external_outbound_attempts=[]`、`loopback_attempts=22`（`evidence/verify/03-probe-rerun.txt`）。
- 两测试模块 `pytestmark=usefixtures("t09_network_guard")`；该 fixture 拦截 socket/httpx 外部目标并在 teardown 断言
  external==[]（`backend/tests/acceptance/support/netguard.py:96-127`），不是口头声明。
- `ingestion.uses_mock_transport is True` 为结构断言（真实 `TencentOCRClient` 只接 `MockOcrTransport`）。
- 共享账本/budget **起止一致**：ledger `1f46d1b9…fde7390`（958,277B、1011 非空行）、budget `084ba9ac…cc58`；
  逐行复算 505 reserved / 505 result，中心 `{embedding 259, rerank 164, chat 78, ocr 4}`，**无 T204 新增行**；
  budget 目录仅 `budget.json`+`live-ledger.jsonl`（无 .lock）。
- 三份新文件无 `os.environ/dotenv/holdout` 引用；未读 `.env`/H1/H2。

## 2. 12 页计划=实际、页级回执、5.65 口径 — PASS

- 独立量 fixture（`verify/01-check.py`）：D07 **8 页**（每页 pdfplumber 文本层 0 字）、D08 **2 页**（0 字）、
  D09 1200×700、D10 1240×620；`looks_like_rule_table(D10)=True`、D09=False → **11 text + 1 table**。
- 单价来自产品常量 `providers/ocr_budgeted.py:54-55`（0.5 / 0.15）与 `p2-run-contract-v0_1.md:84` 同值。
- **从原始账本行独立复算**（不经 dev 的断言）：12 reserved / 12 result、全部 `kind=ocr`、`cost_center=ocr`、
  `GeneralAccurateOCR 11 + RecognizeTableAccurateOCR 1`、合计 **5.65**、0 条 reserved 缺 result、12 个不同 request_sha256。
- 每页回执可归属：`reservation_id` ∈ 预留行、`ledger_request_sha256 == identity.request_sha256`、`bound_cny/charged_cny` 分列。

## 3. 七元身份绑定与串用拒绝 — PASS

- 自写探针复现（`verify/01-check.py` → `02-check-output.txt`）：同一图块字节下，
  跨文档 page1 → `cache_source_identity_mismatch`；同文档换 version → 同上；换图块字节 → `cache_input_hash_mismatch`。
- 身份构造拒绝伪造 provider/model/region 与 page=0；未登记来源锚/计划外页在**预留与发送前**拒绝（`p2_ingestion.py:1425-1442`）；
  同 version 绑不同资料被拒（:1350-1352）。

## 4. 三类缓存 + 删除/取消/迟到响应 — PASS（N2/N7）

- 无缓存：B 场景 12 次全 `miss`，12 次真实请求。
- 合法命中：单测 `test_same_identity_second_call…`（0 请求 0 计费，`cache_hits`/`provider_requests` 分列）；
  端到端为产品检查点复用 `product_checkpoint_reuses=3`，逐页 `certified` 且有 RequestId。
- 伪造/过期/模拟：`cache_payload_invalid` 隔离（0 可用条目）、`cache_expired`、`cache_simulated`（探针复现）。
- 取消/删除：`calls_during=calls_after=3`、第 4–8 页 0 调用、第 3 页产品记录 `discarded`、finalize
  `rejected:cache_provenance_missing`、缓存只剩第 1–2 页（probe C + 集成测试 532-619）。

## 5. 失败与费用 — PASS

- 缺 usage → `invalid_output`（已预留的 0.5 不清零）；空片段 → `OCR_EMPTY_RESULT`；页失败后后续页在网关处
  `OCR_INGESTION_STOPPED`（0 请求）；同页第 2 tile → `OCR_PAGE_CALL_LIMIT`（预留前）；预算不足 → `refused`、charged=0。
- **重试 4+5=9 实测**：原始账本 9 reserved / 9 result、合计 4.5 元、8 个不同 request_sha256
  （第 4 页首轮与重试同身份），与 report 的"4 次尝试 + 5 次新调用"一致。
- 停止是 run 级，T206 注意点已写进契约 §5 与 report §7（首个失败后不得启动新 run）。

## 6. 端到端一致性 + 产品路径未改 — PASS

- 集成用例全程产品 HTTP：上传 202 → `ingestion.worker.run_one_job`（同 DB/Store）→ publish 200 →
  索引 4 份/13 单元 → `POST /conversations/{id}/messages` → `GET /messages/{mid}/sources/{sid}`。
- 引用单元 document/version/page 与发布版本一致；D07 正文 == 该页受控转录；D10 `unit.fields` == 表格首行；
  `source_status=active`、`real_provider_built=False`（规则路径零 chat）。
- `git diff HEAD` 既有源码 0 改动；两测试文件 0 处 monkeypatch（未替换产品解析/worker/鉴权）。

## 7. 复跑 — PASS

```
.venv\Scripts\python.exe -B -m pytest backend/tests/evaluation/test_p2_ocr_ingestion.py \
  backend/tests/integration/test_p2_ocr_source_identity.py -q -p no:cacheprovider \
  --basetemp backend/.pytest-tmp/p2-t204-verify
-> 18 passed, 1 warning in 17.90s, exit 0   (dev 记 17.87s)
```

`probe_t204.py` 复跑 exit 0，`external_outbound_attempts=[]`。未跑全仓。

## 8. 证据真实性 — PASS（N1）

- report §1 表列的 4 个 hash 逐行一致：`p2_ingestion 2eda2b3207b3a734/1834`、单测 `379fba543b46bc54/564`、
  集成 `03ab49f7e31d8fdc/619`、契约 `7acbea032f585baa/165`。我另在起跑时自记的 4 项亦一致：
  report `d96bd989…/96`、`01-pytest.txt 9d24822b0c180bdf`、`02-probe-output.txt 805dc852b66205fe`（还原后）、
  `probe_t204.py 33f6fd3c4ad25732`。
- 无 skip/xfail；临时产物只在 gitignore 的 `backend/.pytest-tmp/`。

## 发现（NOTE，不阻断）

- **N1 复跑会自改证据**：`probe_t204.py` 直接重写 `evidence/02-probe-output.txt`（report §6 亦写"重跑即重建"）。
  我按验收项 7 复跑后该文件被改写（同 7786 字节，仅随机 UUID/派生 id 变化），已逐 token 回填原值还原：
  字节数 7786、sha256 前缀 `805dc852b66205fe` 与原值一致。建议生成器改写 `evidence/verify/` 或 stdout。
- **N2 契约 §4 的 4 个拒绝码不可达**：`cache_mode_mismatch`（text→table 实为 **miss**，次级索引按 (page,mode) 分桶）；
  `cache_provider/model/region_mismatch`（伪造 payload 在 `from_payload` 被 `OcrCallIdentity` 拒 → 记 `cache_payload_invalid`）。
  行为 fail-safe（不复用、0 可用条目），但契约表需改为实际码，否则 T900 按字面会判不符。
- **N3 账本行无 page 字段**：页归属靠 `request_sha256`（含 page），契约 §2/§3 已声明；T206 不要期望账本页码列。
- **N4 重试同页 hash 重复**：9 次调用只有 8 个不同 request_sha256（第 4 页两次同身份）；计数须按 reservation 行。
- **N5 T206 预算风险（实测）**：ocr 中心 6.0（taskbook:286 已采纳）只覆盖无重试上界 5.65；实测 D07 一次失败+重试
  即 9 次/4.5 元。B0 任一份重试就会超中心 → GO 预检须显式计入重试额度或把重试纳入上界。
- **N6 既有注释过时**：`backend/tests/acceptance/support/ocr_transcripts.py:79` 仍写"D10 判 text"，与现行为（table）及
  `backend/tests/unit/test_rule_table_scan.py:38-39`（断言 True）冲突；T204 未改该文件是正确的，但会误导后续读者。
- **N7 端到端缓存命中不可达**：产品检查点先短路已成功页，`OcrResultCache` 命中只能模块级证明（单测）；
  端到端给的是"产品检查点复用"。二者已分别计数，措辞不要混称"缓存命中"。

## 我实际执行的

1. 上文指定 pytest；2. `probe_t204.py` 复跑；3. 自写 `verify/01-check.py`（fixture 形状/D10 判表/共享账本复算/
   七元身份与缓存矩阵/伪造 payload/探针账本原始行复算）；4. 只读查证：`git status/diff`、文件 hash、
   `ocr_budgeted.py`/`budget.py`/`parsers/image.py`/`product_adapter.py` 关键片段。

## 未覆盖

- 真实 OCR/真实 TTL 与价格变动/真实账本与 GO 接入（T206/T207）；本包 5.65 是**计划上界**，真实费用=0。
- 建议：**接收 T204**；N1/N2 作为 T205 前契约与脚本修订项；N5 作为 T206 GO 预检必答项。
