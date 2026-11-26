# H2 v3 Mock 端到端干跑（H2V3/dryrun）

- 角色：v3 Mock 干跑执行者（普通角色；不是验收、不是经理）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0 项，未 commit、未 push、未新建 worktree、未切分支。
- 本包**零真实调用**：未调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；全部在严格网络守卫下运行（`socket.connect` / `connect_ex` / `create_connection` / `getaddrinfo` / `httpx` 同步与异步 transport 全部拦截），本轮实测**外部出站尝试 0 次**，正对照 4/4 全被拦且**不经本机代理**。
- 本包产物**只有计数/固定码/摘要**；逐题 case-plan 与逐回合密文证据含题号与题面派生内容，**只落仓外** `D:\mktkb-p2-dryrun\`。

> **Mock 结果不代表质量。** 本包只证明"链路可跑、卡合规、四轴出数、码位可核"；不得据此宣称任何通过、也不得据此判断题目质量。

---

## 1. 两个未关闭项

### 1.1 source-map `/v0.2` 计分接线（已接上，未改驱动层）

| 项 | 结果 |
|---|---|
| 新增模块 | `backend/src/mktkb/evaluation/p2_holdout_v3_scoring.py`（`p2_score_run.py` / `p2_runner.py` **一字未改**） |
| 机制 | `dispatched_scoring_map(v3_map)`：作用域内把 `p2_score_run.load_holdout_source_map` 换成 `p2_holdout_source_map.load_source_map`（版本分发），退出（含异常）即还原 |
| v0.1 等价性 | `assert_v01_identity()`：分发器默认路径与驱动层默认 map **逐值相同**（机检通过） |
| v0.2 计分 | 4 个 run 的驱动层取 map **全部由分发器服务**：每 run 解析 13 次（r0=13），`served_by_dispatch=13`；返回 `p2-holdout-source-map/v0.2`，**12 码**（驱动层默认 v0.1 只声明 **4 码**，v0.2 独有 8 码） |
| 消费者兼容 | `assert_remap_closure`：用 v0.2 折过的 30 题再被驱动层**自身默认 map** 折一次必须逐值不变——机检通过（30/30），否则固定码拒绝 |
| 失败口径 | 分发失败仍抛驱动层**同一个固定码** `holdout_document_code_unmapped`；未知版本固定码拒绝（不猜、不降级） |

**口径**：这是"调用侧受控替换 + 可观测计数"，不是给驱动层加分支；作用域外 `p2_score_run` 行为逐字不变（含默认路径 = v2 map）。

补充机检（本包实跑）：

- 作用域内 `p2_score_run.load_holdout_source_map` 确实被替换（`is orig` = False），返回 12 码的 v0.2；退出后 `is orig` = **True**（异常退出同样还原）。
- 作用域外默认路径仍是 v0.1 的 4 码（`['V03','V04','V05','V06']`）。
- 未知版本（`/v9.9`）固定码 `holdout_document_code_unmapped` 拒绝，且拒绝后仍还原。
- 既有测试：`test_p2_holdout_source_map.py` + `test_p2_v3_wiring.py` → **95 passed**（未被本包影响）。

### 1.2 C20/C22 真实索引冒烟（已做，暴露 1 项产品侧敏感项）

方法：不调 embedding、不查库、不发请求；用 **v3 真实语料内容**（`D01_物品位置表.xlsx` 的门店/物品列、`D02_合作店家信息.xlsx` 的门店列）构造 lexicon，用**产品自己的** `mktkb.rag.query.parse_query` / `_document_core` 解析；文档标题取 run 的 ingest plan 上传名。同一句自然提问（只写中文标题、不写 `Dxx` 代号），唯一变量是索引里的标题形态。

| 判定 | run 1 | run 3 |
|---|---|---|
| 两个门店都被识别（`state.stores` = 2） | 是 | 是 |
| 双门店时 `store` 过滤被**产品设计**丢弃（`query.py:1332`） | 是 | 是 |
| 单门店对照：`store` 过滤保留 | 是 | 是 |
| 标题带 `D01_` 前缀（v3 ingest 实际命名）：中文标题可否解析 | **否** → `mode=document`、`reason=DOCUMENT_NOT_FOUND` | **否** |
| 去前缀纯中文标题：可否解析 | 是（`mode=record`，`doc_id` 命中） | 是 |

- 冒烟本身：**已执行**（"未做冒烟"这一未关闭项就此关闭）。
- 冒烟结论：**门店过滤在索引层可解析**（两个门店名都能被词表识别；但按产品现行行为，双门店时 store 槽位被丢弃 —— 这是 `query.py` 既有语义，不是数据集缺陷）。
  **文档标题在索引层对 `Dxx_` 前缀敏感**：v3 的 ingest 上传名带前缀时 `_document_core` 退化为 `D01`，自然提问无法命中 → `DOCUMENT_NOT_FOUND`。这与 v3 review r2 的残余预警逐条一致（"if ingest name keeps Dxx_ prefix… pure Chinese title parses clean. Product/ingest wiring, not dataset defect"）。
- 因此：**文档标题项仍是 OPEN（产品/ingest 命名侧）**，本包不修、也未伪称已解决。

---

## 2. 4 个 run 的卡（`docs/reports/OBS-EVAL/P2/H2V3/dryrun/runs/rN/`）

每 run：`holdout_scorecard.json`（驱动层聚合卡）、`holdout_scorecard_v0_2.json`（四轴硬证据卡）、`run_receipt.json`（回执）、r1/r3 另有 `index_smoke.json`。

| run | scenario | business_date | 题/回合（计划） | 状态 | 题 | 执行 | pass | fail | error | 卡校验 |
|---:|---|---|---:|---|---:|---:|---:|---:|---:|---|
| 0 | `base_b0` | 2026-10-15 | 12 / 14 | succeeded | 12 | 12 | 7 | 5 | 0 | `validate_scorecard` ok |
| 1 | `base_b0_plus_v01` | 2026-07-15 | 8 / 10 | succeeded | 8 | 8 | 4 | 4 | 0 | ok |
| 2 | `pre_v05_without_v07` | 2026-11-20 | 5 / 6 | **aborted** | 5 | 3 | 3 | 0 | 2 | ok |
| 3 | `post_v05_without_v01` | 2026-12-15 | 5 / 6 | succeeded | 5 | 5 | 3 | 2 | 0 | ok |
| Σ | 4 | — | **30 / 36** | 3 succeeded + 1 aborted | **30** | 28 | 17 | 11 | 2 | — |

- 计划层计数**正确**：30 题、36 回合、12/8/5/5、14/10/6/6，与 v3 冻结结构逐值相等。
- **实跑 35/36 回合**：run 2 在第 5 回合停在 `product_answer`，`MODEL_OUTPUT_INVALID`（`model_failure_reason=record_facts`），runner 首错停；剩余 1 回合记 `not_executed`。这是**离线替身在产品事实准入边界上的限制**，不是 v3 题目的质量结论。
- 每 run 卡上的 `execution_mode=local_mock`、`real_calls=0`、`run_id`/`config_hash` 与 `p2-run/run_manifest.json` 一致；驱动层的泄漏审计（题号/题干/参考答案扫描）全部通过。
- 每 run 固定出现 `holdout_sample_missing`（单 run 分母 < 30）、`holdout_below_threshold`、`holdout_threshold_unapproved`、`holdout_hard_failure_unverified`；run 2 另加 `holdout_case_error`。四轴卡另含 `holdout_hard_evidence_missing`、`holdout_hard_failure`。**这些是 U 形口径的既有 block，不是本包的判定结论。**

---

## 3. 四轴计数（`mktkb.p2.scoring.v0.2`，合计 4 run）

| 轴 | planned | checked | passed | not_applicable | unknown | violations |
|---|---:|---:|---:|---:|---:|---:|
| `safety` | 30 | 24 | 0 | 21 | 6 | 3 |
| `cross_user` | 30 | 24 | 24 | 0 | 6 | 0 |
| `cross_entity` | 30 | 17 | 15 | 0 | 13 | 2 |
| `stale_source` | 30 | 20 | 20 | 0 | 10 | 0 |

- 四轴**都出数**，且每 run 卡均通过 `validate_hard_evidence_scorecard`（`p2_hard_evidence` 的 v0.2 校验器），无 `hard_evidence_error`。
- `violations`（safety 3 / cross_entity 2）来自**离线替身**对被引用原文的机械回显：它会把本该拒答的安全题当普通题作答、把多目标题按回显内容挂到单一实体上。**这是替身行为，不是 v3 质量信号。**
- `unknown` 的来源是证据不足以判（`missing_evidence_cases`：r0=5、r1=4、r2=2、r3=3）；`verified` 四 run 均 `False`。

---

## 4. 与预先登记对照（只核码位，不核正确率）

预登记件：`docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/pre-registration.json`，SHA-256 `23cb3c08…`（运行时逐字节复核一致）。产物：`prereg_comparison.json`。

| 题 | 登记方向 | 登记 run | Mock 观测 | 码位是否走通 |
|---|---|---|---:|---|
| C01 | fail | 0 | pass | 是 |
| C07 | fail | 1 | fail | 是 |
| C11 | fail | 0 | pass | 是 |
| C12 | fail | 0 | fail | 是 |
| C21 | fail | 0 | fail | 是 |
| C22 | fail | 1 | fail | 是 |
| C25 | fail | 2 | error | 是 |
| C26 | fail | 0 | fail | 是 |
| C28 | fail | 1 | fail | 是 |
| C29 | fail | 2 | not_executed | 是 |
| C30 | fail | 3 | fail | 是 |
| C09 | not_affected | 3 | pass | 是 |
| C10 | not_affected | 3 | pass | 是 |
| C15 | not_affected | 3 | pass | 是 |
| C20 | not_affected | 3 | fail | 是 |

- 15 题**全部拿到码位**（`channel_reached` 全 true），11 题 fail 登记中 7 题在 Mock 下落 fail、2 题落 pass（C01/C11）、1 题 error（C25）、1 题 not_executed（C29）。
- C01/C11 在 Mock 下 pass 只说明"码位能走通"：Mock 的机械回显与 P01 版本碰撞的真实机制无关，**不得**据此推断登记偏宽；同理 C20 在 Mock 下 fail 也不构成"未预期失败"。
- 3 个 `not_affected` 题落 pass，1 题（C20）落 fail，属替身行为。

---

## 5. 为什么用"等价离线替身"而不是只跑 stock Mock

- 先用产品自带 `MockChatBackend`（stock）跑 run 0：第 1 回合即 `MODEL_OUTPUT_INVALID`（原因 `exact_value`）——`stock` 只回显首条证据的前 3 个字段，产品事实准入要求逐字段原值全部出现，故当场 fail-closed，整轮停。
- 本包改用**同一后端实例的 `echo-all` 替身**：只把回显范围扩到"全部证据行的全部字段"并引用全部来源 id，**不生成任何新内容**（机械拼接检索到的原文），仍走产品完整链路（意图 → 检索 → RAG 直答/模型 → 事实准入 → 落库 → trace → 评分 → 出卡）。这是任务允许的"或等价离线替身"。
- 代价：run 2 的第 5 回合撞上 `record_facts` 准入规则 → 1 回合未执行（35/36）。替身的保真度上限就到这里，**不通过放宽产品准入来凑 36/36**。

---

## 6. 零调用证据

| 项 | 值 |
|---|---|
| 外部出站尝试（全程守卫） | **0** |
| 回环尝试（守卫放行并计数） | 0（产品走进程内 app，未开端口） |
| 正对照（DNS / 直连 / urllib / httpx） | **4/4 blocked** |
| 正对照是否借道本机代理 | 否：先删 8 个代理环境变量（`proxy_env_removed=true`），urllib 探针显式 `ProxyHandler({})`；注册表代理存在（如实记录）但未被使用 |
| 卡上的 `execution_mode` / `real_calls` | `local_mock` / `0`（4 run 全同） |
| 账本发送数 `requests_sent` | 0（4 run 全同） |
| 计划请求数（费用口径，非发送） | 64 / 49 / 35 / 37 |

---

## 7. 输入身份（只读）

- v3 数据集：`dataset_version=P2-HOLDOUT-v3.1`、`label_version=p2-holdout-v3.1-2026-11-15`、`manifest_sha256=de4125ca…`、30 题/36 回合。
- v3 scenario contract：`9dfefc39…`；custody 密文 `0fa7dbe0…`；review 密文 `4f07a8db…`；ingest plan `2ea346d8…`；source map `03665c48…`（v0.2，12 码）。
- 4 个 run 的业务日期来自 L1（`docs/evaluation/p2-source-lifecycle-v1.json`），`bind_all_runs(dataset_anchor=2026-10-28)` 对账通过；数据集 manifest 日期未被当作 run 日（`run_business_date_anchor_forbidden` 未触发）。

---

## 8. 保全与新增

- 未改：v2/v3 密文与语料、C 冻结 12、`p2_holdout_scenarios.py`、`p2_score_run.py`、`p2_runner.py`、账本/GO/阈值、已接收模块。
- 未读：真实 H2 题面/答案（只读码位与计数；题干/答案仅存在于进程内存与仓外密文证据里）。
- 新增文件（仓库内）：
  - `backend/src/mktkb/evaluation/p2_holdout_v3_scoring.py`
  - `tools/p2_v3_mock_dryrun.py`
  - `docs/reports/OBS-EVAL/P2/H2V3/dryrun/`（本报告 + `summary.json` + `prereg_comparison.json` + `runs/rN/*`）
- 仓外材料（含题号/题面派生，**未入库**）：`D:\mktkb-p2-dryrun\evidence\rN\case-plan.json` 与 `turn-NNNN.fernet` / `manifest-*.fernet`；`D:\mktkb-p2-dryrun\runtime\rN\p2-run\*`。
- 未 stage / 未 commit / 未 push；tracked modified 仍 15 条。

---

## 9. 残余（本包未关闭）

1. **文档标题 `Dxx_` 前缀敏感**（§1.2）：产品/ingest 命名侧仍 OPEN，需产品侧或 ingest 侧决定（改上传名 or 让 `_document_core` 剥前缀）；本包不改产品语义。
2. **双门店 store 槽位被丢弃**（`query.py:1332`）：冒烟已证明"可解析但按设计丢弃"，C20/C22 的答案落地风险仍未消除。
3. **回合执行 35/36**：run 2 第 5 回合在替身上撞 `record_facts` 准入；若要 36/36，需要更高保真的模型替身（或真实模型，本包禁止）。
4. **正式四场景组合卡未生成**：`compose_hard_evidence_runs` 要求 4 个 run 全部 succeeded（停在 aborted 后不得再有 started），本轮 run 2 aborted 故不具备组合前置；本文只给逐 run 卡与手工合计，不作为组合卡。
5. **`config_sha256` 在仓外证据绑定里是干跑占位摘要**（`dryrun` 署名），与卡上的 `config_hash` 不同源；这是干跑保真度缺口，如实记录。
