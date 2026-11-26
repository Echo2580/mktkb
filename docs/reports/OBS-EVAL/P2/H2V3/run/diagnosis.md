# v3 基线诊断：`INDEX_NOT_READY` 的成因、最小修复与「修复后 r0 还会不会 abort」

- 诊断包：`v3-run-r2`（**零真实请求**：本包未开任何付费尝试）
- 工作区：`D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`
- 结论：**成因已定位并可逐码复现**——不是嵌写未落盘/事务未提交/异步未 flush，也不是「就绪检查用了错误 revision」；
  是**计划项 `index_embedding` 的请求上界 B 比产品实际所需少 1~2 批**，第 B+1 批在**发送前**被配额拒绝，
  索引停在 19/20 块，状态转 `degraded`，而 live 的 `require_zero_retries=True` 让下一个回合在 `qa.prepare` 里
  **fail-closed**（0 次出站）→ `INDEX_NOT_READY` → 没有 `plan_observed` → `EvidenceCaptureIncomplete` → `adapter_error`。

---

## 1. 证据基础（全部只读/离线）

| 来源 | 用途 |
|---|---|
| `run/run-report.md`、`run/conclusion.json`、`run/preservation-check.json` | 上一轮 r0 中止的结论、账本/金额、保全 |
| `run/r0/card.json`、`status.json`、`run-receipt.json`、`v3-entry-sidecar.json` | 逐 run 事实：9 次尝试（8 embedding + 1 answer）、revision、seal 哈希 |
| `run/preflight/rebind-check-r{0..3}.json` | 四 run 的计划/GO/钱闸口径（961/1137、阶段余 12.8676） |
| `backend/src/mktkb/**`（只读） | `qa.service`、`rag.index`、`rag.providers`、`conversations.service`、`documents.routes`、`p2_live`、`p2_runner`、`p2_authorization` |
| **离线复现** `run/diagnosis/offline-repro.json` + `probe_index_ready.py` | 用产品自己的 ingest/发布/sync/prepare 路径重放四 scenario，零网络 |

上一轮 live 侧可用的固定观测（不读题面/答案，只取码与计数）：

| # | 观测 | 值 |
|---:|---|---|
| 1 | ingest 源 / 发布 | 7 源（下标 0,1,4,6,7,8,9）/ 7 次 publish 全 200 |
| 2 | 产品 revision（pre = post = capture） | **7**（回合内无发布，故不变；不是「未推进」的异常） |
| 3 | `index_embedding` 尝试 | **8 次，全部 http 200**（列出价合计 0.0016655 元） |
| 4 | 回合内 `context_observed` | count=0、empty=true |
| 5 | 采集完整性 | `incomplete`、缺 `plan_observed`、`plan_observation_count_invalid` |
| 6 | chat 尝试 | 1 次、`http_status=null`（**未出站**）、`EvidenceCaptureIncomplete` |
| 7 | runner | `status=aborted`、`stop_code=adapter_error` |

---

## 2. 失败链（逐层、带落点）

```
① 灌库：每次 publish 都同步触发一次 rag 索引 sync
   documents/routes.py:73-78  _sync_qa_index() → qa.notify_knowledge_changed()
   documents/routes.py:179    publish 端点发布成功后调用
   qa/service.py:310-376      sync(): 按产品可见面增量写入 + 逐文档 embed
   rag/index.py:275-359       add_document(embed=True) → 一行文档一次 embed()（只送 cache-miss 文本）
   rag/index.py:443-489       _embed_chunks(): 一次 embed() 送该文档全部待嵌入文本
   rag/providers.py:292-295   真实 provider 按 embedding_batch_size=5 拆批，**一批 = 一次 POST**
        ↓
② 配额：计划项 index_embedding 的 requests 就是「本 run 允许的 POST 批数」上界
   p2_live.py:290-308         AttemptBudget.take(): 用尽即 P2LiveRefused("attempt_quota_exhausted")
   p2_live.py:569-573         GateAttemptLedger.reserve(): 在 begin_attempt/POST **之前**转成 BudgetLedgerInvalid
                              → 不开 reservation、没有 http_status、账本不增行（所以 live 只见 8 行 embedding）
        ↓
③ 降级：产品把这次失败吞成「向量层降级」，记录层仍可用
   rag/index.py:347-350       embedding 异常 → result["embedding_error"]（不抛）
   qa/service.py:344-375      degraded → meta status="degraded"、error_code="BUDGET_LEDGER_INVALID"
        ↓
④ 回合：下一个回合的 prepare 先 ensure_ready，live 零重试 → 直接失败（0 次出站）
   qa/service.py:419          prepare() 第一行 self.ensure_ready()
   qa/service.py:293-302      status=degraded 且 require_zero_retries → QaNotReady("...已降级且要求零自动重试")
   product_adapter.py:1208-1209  live 装配 max_retries=0、require_zero_retries=True
        ↓
⑤ 对外：映射成 INDEX_NOT_READY，且**在 plan_observed 之前**返回
   conversations/service.py:2357-2373  QaNotReady/异常 → _service_error("INDEX_NOT_READY", …)
   conversations/service.py:2375-2392  plan_observed 只在 prepare 成功后才 emit → 本回合必然缺失
        ↓
⑥ 采集/runner：缺 plan_observed → incomplete → EvidenceCaptureIncomplete → adapter_error（首错停）
```

关键否证：

- **不是写未落盘/事务未提交**：8 次 POST 全部 200，`RagChunkEmbedding` 已提交 19 行（复现件 `chunk_embeddings=19/20`），差的是**第 20 块**；
  且下次 `ensure_ready` 并没有重发（`posts_at_prepare=0`），说明状态是 `degraded` 而不是「未同步」。
- **不是异步未 flush**：产品里没有后台索引线程；sync 在请求内同步完成（`qa/service.py:310-376`），且在发布请求的同一调用栈里。
- **不是「就绪检查用了错误 revision」**：`qa/service.py:270-272` 的 `stored == str(current)` 在本例是成立的（`product_revision=7`、
  `rag_revision=8`），失败分支是 `status=="degraded"`（第 293-302 行），与 revision 无关。
- **不是 v3 入口漏了「等待索引就绪」**：v2 入口同样没有该步骤（`tools/p2_h2_controlled_execute.py` 全文件无
  `ensure_ready/index_sync/wait/index_ready` 调用），`p2_runner.py:860-883` 在 ingest 之后直接进首回合。
  产品的就绪判定本来就是**回合内懒执行**的（`qa.prepare → ensure_ready`），所以「补等待」并不能改变本例结局。

---

## 3. 离线复现（零网络、逐码复刻）

方法（`run/diagnosis/probe_index_ready.py`）：

1. 用**产品自己的路径**灌库：HTTP 上传（202）→ `run_one_job` 解析 → publish（200，触发 `qa.sync`）；
2. embedding 换成离线假 provider（无传输层、不出网），按 live 的 `embedding_batch_size=5` 把
   `embed()` 的待嵌入文本折算成真实 POST 批数；
3. 把 `QaEngine.config` 切到 live 口径 `require_zero_retries=True / max_retries=0`；
4. 可选 `cap = 计划项 index_embedding.requests`：超限的那一批**在发送前**抛 `BudgetLedgerInvalid`
   （与 `p2_live.py:569-573` 同码同位置）；
5. 灌库后调用 `qa.prepare()`——这正是产品回合中 `INDEX_NOT_READY` 之前的最后一步。

| scenario | 源 | 计划 B | 现状所需批数 | 缺口 | 复现结果（**按各自 B 实测**） | 单次同步所需批数 | 修复模拟（cap=B） |
|---|---:|---:|---:|---:|---|---:|---|
| `base_b0` | 7 | 8 | **9** | +1 | 8 批放行 → 第 9 批发送前被拒；`degraded/BUDGET_LEDGER_INVALID`，**19/20** 块；`prepare`→`INDEX_NOT_READY`，0 POST | 7 | 7 批 → `ready`，`prepare ok` |
| `base_b0_plus_v01` | 8 | 9 | **10** | +1 | 同步：9 批放行 → 第 10 批被拒；`degraded`，**20/21** 块；`prepare`→`INDEX_NOT_READY`，0 POST | 8 | 8 批 → `ready` |
| `pre_v05_without_v07` | 10 | 11 | **13** | +2 | 11 批放行 → 第 12/13 批被拒；`degraded`，**19/21** 块；`prepare`→`INDEX_NOT_READY`，0 POST | 8 | 8 批 → `ready` |
| `post_v05_without_v01` | 11 | 13 | **15** | +2 | 13 批放行 → 第 14/15 批被拒；`degraded`，**18/20** 块；`prepare`→`INDEX_NOT_READY`，0 POST | 8 | 8 批 → `ready` |

> 四 run 都按「自己的 B」实测到同一条中止链（不是推断）；`run/diagnosis/offline-repro.json` 的 `conclusion.cap_probe_by_run` 是机读版。

live 与 `cap=8` 复现件逐项对齐：

| 观测点 | live（r0） | 离线复现（`cap=8`） |
|---|---|---|
| embedding POST | 8 次，全 200 | 8 批放行（前 6 次 `embed()` 的 2+2+1+1+1+1） |
| 第 9 批 | 无出站、无 http_status、账本无行 | 发送前 `attempt_quota_exhausted→BUDGET_LEDGER_INVALID`，不开 reservation |
| 索引 | 未知（DB 已清理） | 20 块、19 块有向量；`status=degraded`、`error_code=BUDGET_LEDGER_INVALID` |
| 产品 revision | 7（pre/post 不变） | 7（7 次发布） |
| 回合内 embedding | 0 | 0（`posts_at_prepare=0`） |
| 对外码 | `INDEX_NOT_READY` + 缺 `plan_observed` | `INDEX_NOT_READY`（`EMBEDDING_DEGRADED_NO_RETRY`）+ prepare 未返回，故无 plan_observed |

> 也就是说：**B=8 正好把配额花在最后一次发布上**，产品还差 1 批（1 个 chunk）才完整；这不是碎片化的偶发，而是可复算的确定性。

---

## 4. 三个必答问题

**Q1「ingest 完成的判据是什么、revision 如何推进、`context=0` 意味着什么」**

- `ProductEvalAdapter.ingest()`（`product_adapter.py:2011-2052`）的完成判据只有三条：上传 202、worker `succeeded`、
  publish 200；**不检查索引就绪**。索引就绪是回合内懒判定的（`qa.prepare → ensure_ready`）。
- 两次 revision 是两套：产品 `KnowledgeState.revision` 每次发布 +1（`documents/lifecycle.py:288-291` 的
  `UPDATE … SET revision=expected_revision+1`；r0 发布 7 次 → 7）；RAG 索引另有 `rag_meta.revision`
  （r0 复现值 8，`add_document/remove` 各 +1）。捕获到的 `pre/post/capture_revision=7`
  说明**回合内没有发布**，属于一致状态，不是异常。
- `context_observed count=0` 是「答案前没有进入检索」的结果：`qa.prepare` 先失败，`plan_observed` 与任何检索事件都来不及产生。

**Q2「是否必须在回合开始前显式等待索引就绪（v2 有而 v3 漏了）」**

- **不需要，也不是 v3 的漏项**。产品不提供「外部等待」的必要性：`qa.prepare` 自己会 `ensure_ready`（懒同步）。
  v2 入口与 v3 入口都没有该步骤，`p2_runner.py:860-883` 在 ingest 后直接开跑。
- 真正与时序有关的缺陷在**发布钩子**：每发布一次就整体 sync 一次（`documents/routes.py:73-78,179`），
  而中间版本（如 D01 的 V03 → 正常版）会被嵌入后又删除，纯属重复花费（r0：9 批 vs 单次 7 批）。
  这正是「入口/编排层」可以修的地方，见 §6 方案 A。

**Q3「8 次 200 但索引未就绪：写入未落盘/事务未提交/异步未 flush，还是就绪检查用了错误 revision」**

- 都不是。真因是**配额少 1 批**：第 9 批在发送前被拒（`p2_live.py:569-573`），该文档最后 1 个 chunk 没有向量；
  `rag/index.py:347-350` 把异常吞成 `embedding_error`，`qa/service.py:361-375` 把状态写成 `degraded`；
  下一个回合 `qa/service.py:293-302` 因 `require_zero_retries=True` **直接拒绝再发**（所以回合内 0 次 embedding），
  对外即 `INDEX_NOT_READY`。

---

## 5. 根因判定（一句话）

> **v3 的四份计划把 `index_embedding` 的请求上界 B 取自 v2 冻结配方（8/9/11/13），而 v3 语料 + 「每次发布都整体 sync」的
> 真实所需是 9/10/13/15——每个 run 都少 1~2 批；第 B+1 批在发送前被配额拒绝，索引降级，live 零重试策略把它放大成首回合
> `INDEX_NOT_READY`。**

补充证据：`FREEZE-A-report.md` 明确 v3 的 `ingest_batches` 是「逐值等于冻结 `RECIPES`」，即**沿用了 v2 的 B**；
而 v3 语料的块数已不同（r0 实测 20 块/6 文档/7 次发布）。

---

## 6. 最小修复方案

### 方案 A（推荐，成本更低、语义不变）：把「逐次发布同步」改成「灌库后一次性正式同步」

不改产品核心语义、不改语料/题集/阈值，只改**评测适配器的编排**（`backend/src/mktkb/evaluation/product_adapter.py::ingest`，8 行）：

```diff
         receipts: list[IngestReceipt] = []
         admin = self._session(self._users_spec[0][0])
-        for source in chosen.sources:
-            resolved = self._resolve_ingest_source(source)
-            receipt = await self._ingest_one(admin, resolved)
-            self._remember_ingest_receipt(str(source.document_ref or source.name), receipt)
-            receipts.append(receipt)
+        # 灌库期暂停发布钩子的逐次索引同步：否则每个新版本（含随后被取代的历史版本）都会单独嵌入一次，
+        # 而计划项 index_embedding 只是**尝试上限**，多发一次即在发送前被拒（见 p2_live.py:569-573）。
+        app_qa = getattr(self._app.state, "qa", None)
+        self._app.state.qa = None
+        try:
+            for source in chosen.sources:
+                resolved = self._resolve_ingest_source(source)
+                receipt = await self._ingest_one(admin, resolved)
+                self._remember_ingest_receipt(str(source.document_ref or source.name), receipt)
+                receipts.append(receipt)
+        finally:
+            self._app.state.qa = app_qa
+        # 灌库后一次性正式同步：失败/降级在这里以稳定码暴露（首个回合之前，零 chat、零答案）。
+        self._qa.ensure_ready()
         self.ingest_receipts.extend(receipts)
         return receipts
```

- 效果（已离线验证，`run/diagnosis/offline-repro.json`）：四 run 的 `index_embedding` 从 9/10/13/15 降到 **7/8/8/8**，
  `status=ready`、`chunk_embeddings == chunks`、`prepare ok`（即 `plan_observed` 能发出），且**都在现有 B=8/9/11/13 之内**。
- 风险/代价：
  1. `product_adapter.py` 在 **C 冻结 12** 内，改动会改 `code_version`（`CODE_SCOPES=backend/src/mktkb`，全部 .py 参与摘要）
     → 旧 binding 必被判 `code_changed_since_plan`，**必须重绑**；这也是本包不能自行落地的原因（见 §8）。
  2. 失败码迁移：真实 embedding 故障从「第 0 回合 `INDEX_NOT_READY`（先烧 1 次 chat 预留）」变成「ingest 阶段 `ingest_failed`（零 chat）」。
     语义更安全，但审计码变了，需在证据规范里登记。
  3. mock/dryrun 路径同样生效（索引一次建成），需重跑 dryrun 与 P2 定向测试，确认没有断言依赖「每次发布后同步」。
  4. 单文档批数仍受 B 约束（本语料每文档 ≤2 批，r0 余量 1 批、r1 余量 1 批），语料冻结下可复算。

### 方案 B（备选，纯制品口，但更重）：把 B 调到 9/10/13/15（或留余量 10/11/14/16）

- 需要改：`p2_holdout_scenarios.py::RECIPES`（protected_repo）+ `docs/evaluation/p2-h2-scenarios-H2v3.json`（protected_repo，
  冻结契约）→ `scenario_contract_sha256` 变 → **新计划 + 新 GO + 重绑 + 重新冻结**；
- 成本 +1/+1/+2/+2 请求/run（相对现状），且**不减少**重复嵌入的浪费（仍是逐次发布同步）；
- 优点：不改任何 `.py` 运行时语义（除配方常量）；缺点：冻结件改动面更大、需要新一轮审核。

> 若只想跑一次基线而不动代码：方案 B 也能让 r0 不 abort（离线 `cap=9` 已证明 `ready`），但它把冻结契约一起改了，
> 授权级别高于方案 A。

---

## 7. 修复后 r0 会不会再次 abort

| 情形 | 结论 | 依据 |
|---|---|---|
| **什么都不改，直接开跑** | **会**，且与上一轮同码同因（首回合 `INDEX_NOT_READY`，约 9 请求 / ~0.02 元） | 离线 `cap=8` 逐项复刻：8 批放行 → 第 9 批发送前被拒 → `degraded` → `prepare` 0 POST 失败 |
| 只做方案 A（编排修复）+ 重绑 | **不会**（对 `INDEX_NOT_READY` 而言）：7 批 ≤ B=8，索引 `ready`、20/20 块，`prepare ok` | 四 scenario 的 `--defer-sync --cap=B` 复现全绿 |
| 只做方案 B（B=9/10/13/15）+ 重发计划/GO/重绑 | **不会**：`cap=9` 时 r0 恰好在最后一批成功，`ready`、`prepare ok` | 离线 `cap=None` 跑出 9 批 → ready |

修复后仍存在的**非中止类**残余（不改变「不 abort」，但会影响个别题）：`Dxx_` 上传名前缀导致文档标题解析退化
（dryrun §1.2，`DOCUMENT_NOT_FOUND`）、双门店时 store 槽位按既有语义被丢弃（`rag/query.py` 现状）。
这两项属产品/ingest 命名侧，本包未动。

---

## 8. 额度与金额（阶段 2）

- GO：4 份 `scope.max_requests` 1137 → **1150**（仅该字段；`authorization` 散文字符串里的「1137 cumulative requests」**未动**，见残余 R3）。
  逐 run 改前/改后 payload SHA-256 与逐叶子 diff 见 `run/go-amend-evidence.json`；旧字节归档为
  `P2-LIVE-GO.v3-max1150-r{0..3}.previous.archived.json`（不覆盖既有归档）。
- **重要发现：只改 GO 不改变有效上限**。`p2_authorization.py:620` 取 `min(plan.max_requests, GO.scope.max_requests)`，
  而四份计划的 `max_requests` 也是 1137（`plan-private --max-requests` 的产物）→ 有效上限仍是 1137，余量仍是 **176**。
  若要让「四 run 最坏 185」真正有余量，需要**用 `plan-private --max-requests 1150` 重发计划**（`plan_sha256` 变 → GO 需重发
  `scope.plan_sha256` → 重绑）。本包未做（超出「仅调该字段」的授权）。
- 金额未动：项目 40 元、阶段 20 元、单请求 0.5 元；账本仍 `9d4b957a…`（1923 行、961/961 配对）、预算仍 `79b21700…`。
  本包零请求，`requests_used` 仍 961。
- 一致性交叉验证：改前 r0 GO payload SHA `7bc70c01…` = 上一轮 `run/r0/card.json` 的 `go_sha256`（同一份授权，未错位）；
  改后 `check-only`（`diagnosis/go-amend-check-r2.json`）`go_binding`/`plan_binding`/`zero_write`/`zero_send` 全绿，
  `go.max_requests=1150`、`requests_used=961`、账本/预算前后同值。

---

## 9. 残余（交经理决策）

| # | 残余 | 级别 | 说明 / 下一步 |
|---:|---|---|---|
| D1 | 索引批数缺口（本诊断主因） | 高 | 方案 A（改 1 个 C 冻结评测文件 + 重绑）或方案 B（改冻结配方 + 重发计划/GO）。**需经理授权其一** |
| D2 | 有效请求上限仍 1137 | 中 | `min(plan=1137, GO=1150)`；需 `plan-private --max-requests 1150` 重发计划 + GO `plan_sha256` 重发 + 重绑 |
| D3 | GO 散文字段仍写 1137 | 低 | 「保持其余字段不变」的直接后果；机器字段以 `scope.max_requests=1150` 为准，是否同步改散文需经理定 |
| D4 | 修复后代码身份变化 | 中 | 方案 A 改 `product_adapter.py` → `code_version` 变 → 四份 binding 失效，需重绑（上一轮 `rebind` 流程可复用） |
| D5 | `Dxx_` 前缀 / 双门店槽位 | 中 | 已知产品/ingest 命名侧问题，只影响个别题，不阻塞 run |
| D6 | 失败码语义迁移 | 低 | 方案 A 会把「首回合 INDEX_NOT_READY」变成「ingest_failed」；需在证据规范登记 |

## 10. 本包未改动

C 冻结 12（12/12 未变）、v2/v3 语料与密文（13/13 未变）、`fixtures/acceptance-h2v3`（13/13 未变）、评测模块代码、
账本内容（零请求，字节停在上一轮结束值）、30 题/标签/阈值、暫存 0 项、未 stage/commit/push、未新建 worktree/切分支。
保全复核：`run/round2-notrun/preservation-check.json`（唯一变化 = 4 份授权 GO + 上一轮账本增量）。
