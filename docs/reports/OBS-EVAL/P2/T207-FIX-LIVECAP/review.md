# P2-T207-FIX-LIVECAP 独立验收（live 单请求上限 / fail-closed）

- 独立验收助手（全新上下文）；**零真实调用**（全部出站由 `httpx.MockTransport` 接住，凭据均为 verify-only 假串）、
  零网络、未读 `.env`/H1/H2、未 commit、未改代码/测试/文档/夹具/账本/预算/GO。
- 现场：分支 `codex/p2-e2e`，HEAD `24f9cde`（与任务书一致，未新增 commit）。
- 只读复核 + 自写探针复现：`evidence/verify/probe-independent-livecap.py`（刻意不 import 开发新增测试模块）。

## 结论

**接收（阻断 0）**。4 条核心判据全部独立复现成立：数值推导逐值正确、无 OCR 计划 0→3 POST 且无降级、
GO 上限不足启动期 fail-closed（不发送/不预留/不降级/无产物）、含 OCR 计划逐值不变。
另有 3 条**非阻断瑕疵**（2 处文档措辞/序号、报告缺文件 sha），见 §6；不影响功能与安全判据。

## 1 范围合规 — PASS

| 项 | 复核结果 |
|---|---|
| 源码改动 | 仅 `backend/src/mktkb/evaluation/{p2_live.py,product_adapter.py}`（+129 / +25） |
| 新增测试 | 仅 `backend/tests/evaluation/test_p2_live_request_ceiling.py`（6 条；既有测试文件未改） |
| 文档 | `docs/evaluation/p2-live-binding-v0_1.md` §10.10、`PM/T207-runbook.md` §3.2/§9（+40/+53） |
| 禁止面 | `conversations/copy.py`、`fixtures/**`、`p2_scoring`/`scorers`、`rag/providers.py` **均未改** |
| 固定路径 | `docs/evidence/LOCAL-R1-20261101`（账本/预算/GO）`git status` 干净；sha 与 R4PREP 基线一致：ledger `05b54d06…`、budget `79b21700…`、GO `3ed427f4…` |
| skip/xfail | 新测试 grep 空；69 / 84 两次复跑均 0 skipped |
| commit | 无（HEAD 仍为 `24f9cde`） |
| 真实出站 | 新测试用 `t09_network_guard`；我的探针只用 MockTransport，外部尝试 0 |

工作区另有 4 个改动文件属 **R4PREP / 经理文档**（`.claude/handoffs/_index.md`、`T207/report.md` §9、
`PM/T207-PM-decisions-01.md` §11、`PM/T207-cost-and-quota.md` §8），内容与 LIVE-CAP 无关，不计入本包交付面。

## 2 数值推导独立复算 — PASS

| provider | 复算式（代码常量） | 复算值 | `provider_single_request_bounds()` 实测 |
|---|---|---|---|
| embedding | `MAX_EMBEDDING_REQUEST_TOKENS(81920) × 0.5/M`（`evaluation/live.embedding_reserve_cny`） | 0.04096 | 0.04096 |
| rerank | `RagConfig.rerank_max_request_tokens(30000) × 0.8/M`（live 未覆盖该默认值） | 0.024 | 0.024 |
| chat | `6144×2/M + 800×8/M`（`settlement_policy.build_policy(chat)` 冻结 cap） | 0.018688 | 0.018688 |

- 真实计划（只读）：R4（13 项/18 请求/**无 OCR**，sha `00b9fdef…`）`reserve_peak=0.018688` ⇒ effective **0.04096** ≤ GO 0.5；
  公开矩阵计划（233 项/254 请求/**12 OCR**，sha `0b4e55a4…`）`reserve_peak=0.5` ⇒ effective **0.5**，且等于计划峰值（不 replace）。
- `effective = max(计划峰值, 各 provider 单次预留)` 且 ≤ `authorization.max_request_cny`：推导与实测一致；
  边界实测 GO=0.04096 放行、GO=0.040959 以 `live_request_ceiling_insufficient` 拒绝。
- **不写魔法数**：`p2_live.py` 代码段只有 docstring 出现 0.04096/81920/0.018688；实现复用 `evaluation/live` 的权威公式与
  `build_policy`，chat 的 6144/800 也取自 policy 对象而非字面量。

## 3 行为独立复现（MockTransport，零真实） — PASS

自写探针输出 `evidence/verify/probe-independent-livecap.out.json`（计划按真实计划文件的 item/price_profile 复刻）：

```txt
场景                          emb POST  rerank POST  chat  degraded            run / 拒绝
no-OCR 旧语义(effective=峰值)    0         0            0     [embedding_error]   aborted / product_service_error
no-OCR 修复后                    3         1            1     []                  succeeded，config=0.04096
no-OCR + GO 0.02 修复后          0         0            0     —                   live_request_ceiling_insufficient
含 1 页 OCR 旧语义               3         1            1     []                  succeeded，config=0.5
含 1 页 OCR 修复后               3         1            1     []                  succeeded，config=0.5
```

- 旧语义复现方式：把 `resolve_request_ceiling` 退回 effective=计划峰值且不 fail closed，等价于修正前
  `max_request_cny = plan.reserve_peak_cny`（`replace` 未触发 ⇒ 两版配置逐值相同）。
- 修复生效点可观测：无 OCR 计划修复后 `dataclasses.replace` 恰 1 次（`max_request_cny`）；含 OCR 计划 0 次。
- **fail-closed 完整性**：GO 0.02 时 POST 0（embedding/rerank/ocr/chat）、账本 `reserved` 0 次、运行目录**无任何产物**、
  无 `degraded` 记录、异常码 `live_request_ceiling_insufficient`。
- provider 层根因复证（不经过 resolver）：`BailianEmbeddingProvider` 在 `max_request_cny=0.018688` 时抛
  `EmbeddingUnavailable`（0 POST），0.04096 时发 1 POST；`BailianRerankProvider` 在 0.018688 时抛 `RerankError`（0 POST）、
  0.024 时发 1 POST ⇒ 文档里 0.024 是 provider 真正会拒的值。
- 后果更正（见 §6-A）：旧语义下**不是**“看似通过”，而是首回合即 `aborted(product_service_error)`，
  账本仅 1 次 chat 预留并以 `failed/INDEX_NOT_READY` 结算。

## 4 无静默降级通道 — PASS

1. 拒绝发生在 `create_app` 与任何 provider 构造**之前**（`product_adapter.py:1108` 早于 `1117/1176`），该调用
   **无 try/except**，`resolve_request_ceiling` 内也无“降级继续”分支；
2. `run_live_p2` 在 `run_p2` 之前显式 `await build.adapter.start()`（`p2_live.py:1538`），码直达调用方；
   **对照实验**：绕过该行直接 `run_p2`，同一拒绝被吞成 `stop_code=ingest_failed`（status blocked，仍 0 请求）⇒ 证明该行因果；
3. CLI 侧映射为 `{"ok": false, "status": "blocked", "error_code": ...}` + `EXIT_DATA`（`cli.py:733-749`），非成功路径；
4. 落盘正确性：`summary.json` 与 `run_manifest.json` 的 `providers.live.request_ceiling.effective_max_request_cny`
   实测 0.04096（no-OCR）/ 0.5（含 OCR），且只含金额；
5. 残余观察（非阻断）：runner 不把 `index_status.degraded` 当失败条件，live 下靠 `qa/service.ensure_ready` +
   `require_zero_retries` 抛 `QaNotReady` 兜住（实测 aborted）。建议后续在 runner 增加显式断言。

## 5 测试与回归 — PASS

| 复跑 | 结果 |
|---|---|
| `test_p2_live_wiring.py test_p2_runner.py test_p2_live_request_ceiling.py` | **69 passed**（24.25s，独立 `--basetemp`、`-p no:cacheprovider`） |
| 基线核对 `--collect-only`（前两个文件） | **63 collected** ⇒ 63 + 6 逐一对上 |
| `test_p2_ocr_ingestion.py test_p2_authorization.py` | **84 passed** |
| **突变检查**（resolver 退回旧语义后跑新测试） | **4 failed / 2 passed**：effective_ceiling、ceiling_below_provider_reserve、no_ocr_plan_emits_embedding_posts、live_refuses_at_start 全红；provider 公式用例与含 OCR 用例照旧通过 ⇒ 新增回归能抓住 F-1，不是空断言 |

证据：`evidence/verify/pytest-livecap-verify.txt`、`pytest-baseline-collect.txt`、`pytest-ocr-auth-verify.txt`、
`pytest-new-tests-under-legacy-wiring.txt`（突变插件 `legacy_wiring_mutation_plugin.py`）。

## 6 文档 / 证据一致性 — PASS（3 条非阻断瑕疵）

- **开发探针可复现**：重跑 `evidence/probe-livecap.py` 生成 `evidence/verify/repro-dev-probe.out.json`，与落盘
  `probe-livecap.out.json` **逐字节相同**（5 个 case 全等）。
- §10.10 / runbook §3.2「前置 2」/ §9「接线面」的数值、稳定码、`summary.json`+`run_manifest.json` 说法与实现逐值一致；
  R4 / H2 候选 GO 的 `max_request_cny` 实测均为 **0.5**（≥ 0.04096），执行侧不会撞上新拒绝。
- `.p2cap_probe*.py`：仓库根**不存在**（`git ls-files`、目录列表、忽略列表均无实体），无归属争议、未纳入交付。
- **瑕疵 A（措辞，非阻断）**：报告 §1/§4 与 §10.10 沿用 R4PREP 的“不硬停”“看似通过、向量层全灭”。live 实参
  `require_zero_retries=True` 下实测为**首回合即 aborted(product_service_error)**（chat 预留 failed/`INDEX_NOT_READY`）。
  真实后果是「page_count=0 计划跑 live 必然硬失败 + 烧 1 请求 + 零答案」。修复必要性不变，但措辞会让后续读者误判风险形态。
- **瑕疵 B（序号，非阻断）**：runbook §1 新增项插在旧第 3 项之前（源文序号 1,2,4,3），渲染无碍、阅读别扭。
- **瑕疵 C（非阻断）**：报告未给改动文件 sha；本 review 补齐（见下表）。

| 文件 | sha256（前 16） | 字节 |
|---|---|---|
| `p2_live.py` | `f0e42de9e8f2e363` | 66,048 |
| `product_adapter.py` | `f44692fbb2c34225` | 97,997 |
| `test_p2_live_request_ceiling.py` | `c07e5e6792742aa8` | 23,284 |
| `p2-live-binding-v0_1.md` | `874ab89657337949` | 26,663 |
| `T207-runbook.md` | `058840094a969c2a` | 32,155 |

## 7 限制

1. `test_p2_product_e2e.py` **不存在**（任务书笔误，报告已如实标注）：覆盖不受影响——live 装配/端到端由
   `test_p2_live_wiring.py`+`test_p2_runner.py` 承担；新增 6 条 ceiling 回归在 69 passed 内。
2. 未做真实 live run（任务书要求零真实）：F-1 由真实 provider 类 + MockTransport 复现，结论限于装配/发送前后语义。
3. R4/H2 执行前置：GO 的 `authorization.max_request_cny` 须 ≥ 0.04096（候选 GO 均 0.5；runbook 已写“若抛该码就停、不要改代码绕过”）。
4. 口径不一（**非本包引入、非阻断**）：`p2_runner` 的 dry-run 内存授权仍用 `plan.reserve_peak_cny` 作
   `max_request_cny`（`p2_runner.py:545`），no-OCR 计划下为 0.018688；dry-run 不构造真实 provider 故无实际影响，建议后续统一。
5. 未审阅并发包的 conversations/copy 改动（不属本包）。

## 证据清单（`evidence/verify/`）

- `probe-independent-livecap.py` / `probe-independent-livecap.out.json`（10 项自检 `all_pass=true`：derivation /
  provider_guard / 5 个端到端 run / ingest 吞错对照）
- `repro-dev-probe.out.json`（开发探针逐字节复现）
- `pytest-livecap-verify.txt`、`pytest-baseline-collect.txt`、`pytest-ocr-auth-verify.txt`、
  `pytest-new-tests-under-legacy-wiring.txt`、`legacy_wiring_mutation_plugin.py`
