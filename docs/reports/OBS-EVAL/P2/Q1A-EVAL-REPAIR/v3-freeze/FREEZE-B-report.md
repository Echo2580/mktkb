# H2 v3 冻结 B：v3 标注密文 + freeze 清单

- 角色：v3 冻结 B（普通角色；范围限定）。**非**独立验收、**非**经理、**非**保管、**非**独立复核。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0，0 commit；未新建 worktree、未切分支。
- 本包只做本地文件读写、Fernet 加解密、SHA 复算与本地 loader 校验；**零真实调用、零真实请求**。未读真实 H2 题面/答案明文；v3 密文按冻结职责读取，只取结构字段与标注语义字段。

---

## 1. 交付清单

| # | 路径 | 字节 | SHA-256 |
|---|---|---:|---|
| 1 | `D:\mktkb-p2-holdout\v3\annotations-v0_2.fernet`（新文件） | 42424 | `0fa7dbe0e233db87732a60a245c1baa74a3c48e28de892f7b9a07cadfc40c543` |
| 2 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/p2-holdout-v3.freeze.json` | 见 verify 输出 | 自哈希不在其 `artifacts[]` 内（自指），由 `verify-freeze.py` 打印 |
| 3 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/verify-freeze.py` | 见 freeze 清单 | 见 freeze 清单 |
| 4 | 本报告 | 见 freeze 清单 | 见 freeze 清单 |

标注密文读回：Fernet 解密后与写入前明文**逐字节相等**（`readback_equal = true`）；明文 31746 B，`p2-h2-custody/v0.2` 载荷的 `payload_sha256 = 78940fd6e3c0e2ca64686590d3c418d5158ca8851204642cc253d65f4963e0ca`。**未覆盖任何既有文件**。

## 2. 标注投影规则（不新增判据、不臆造）

每一案 `axes` 恰四轴、每轴恰 7 字段。取值链如下（`targets.jsonl` / `authoring-record.jsonl` 均从 v3 密文在内存读出）：

| 轴 | applicability | criterion | reason | target_refs | targets | as_of | temporal_intent |
|---|---|---|---|---|---|---|---|
| `safety` | `targets.safety.applicability`（25 N/A；5 required = C26–C30） | `targets.safety.criterion` 原值（`benign_business` / `must_refuse_security` / `forbidden_content`） | N/A → `benign_business`；`must_refuse_security` → `explicit_security`；`forbidden_content` → `explicit_forbidden` | required 时 = 全部 `forbidden_sources` 下标；N/A 时空 | 空 | `null` | `not_applicable` |
| `cross_user` | `required`（30/30；与 `authoring.axes_required[0]` 逐案相等） | `owner_context` | `all_user_contexts` | 空 | 空 | `null` | `not_applicable` |
| `cross_entity` | `targets.cross_entity.applicability`（30 required） | `targets.cross_entity.criterion`（24 `structured_target` + 6 `multi_target`） | `structured_target` → `explicit_single_target`；`multi_target` → `explicit_multi_target` | 全部 `expected_sources` 下标（28 案非空；C16/C17 为空集） | `targets.cross_entity.targets` 的**三键投影**（`entity_type`/`entity_key`/`filters`），共 36 个实例（24 单 + 6 双） | `null` | `not_applicable` |
| `stale_source` | `required`（30/30） | `lifecycle_dates` | `business_date_default` | `expected_sources` 全部下标 + 与 `traps` 的 `(source_code, record_code)` 匹配的 `forbidden_sources` 下标（3 条） | 空 | `targets.stale_source.as_of`（= 该题 run 的 `business_date`；4 个 run 日来自 L1 窗口约束） | `targets.stale_source.temporal_intent`（`current`） |

- 30 案的 `axes_required` 顺序为 `[cross_user, cross_entity, stale_source, safety]`，与面板逐案对齐；`safety required` 恰为 C26–C30，`safety not_applicable` 25，合计 95 required / 25 N/A，与 `p2-holdout-v3.authoring-aggregate.json` 的 `axis_attitudes` 一致。
- `stale_source.used_units` 共 34 条，与 28 个非空 `expected_sources` 的 34 个引用**一一对应**；C16/C17 的 `used_units` 为空（空集使用证明），`target_refs` 也随之为空，但不改 `applicability=required`。
- 未从题面文本推断任何 reason：`reason` 只由 criterion 的固定映射或轴契约常量产生；`stale_source` 统一取 `business_date_default`，因为 `as_of` 由 run 的 `business_date` 推出（L1 窗口覆盖），authoring 记录未给逐题 reason 区分，写 `explicit_temporal`/`published_lifecycle` 会是臆造。
- 轴计数（loader 同口径）：`safety 5 required / 25 N/A / 0 unknown`；`cross_user`、`cross_entity`、`stale_source` 各 `30 required / 0 N/A / 0 unknown`；`scenario_counts = base_b0 12 / base_b0_plus_v01 8 / pre_v05_without_v07 5 / post_v05_without_v01 5 / unknown 0`。与 `H2V3/PM/review-aggregate.json` 逐值相等。
- 载荷 `bindings` 8 键与 loader `:183-187` 重算逐值相等（manifest `de4125ca…`、cases `5c86fbfb…`、source-map `03665c48…`、ingest `2ea346d8…`、schema `9fbe4b33…`、scenario contract `9dfefc39…`、`P2-HOLDOUT-v3.1`、`p2-holdout-v3.1-2026-11-15`）。
- 输出只有密文；仓库内不落任何题面/答案/逐题 target 明文。本报告只给聚合计数。

## 3. loader 边界（真实件 + 两个明确标注的临时探针）

| 运行 | 输入 | 停在 | 结论 |
|---|---|---|---|
| A（真实件） | v3 标注密文 + `v3\review-v0_2.fernet`（不存在） | 固定码 `scenario_input_unreadable`，帧 `p2_holdout_scenarios_v3.py:193` | 标注密文已被读到；下一缺件是 review 密文 |
| B（临时占位） | v3 标注密文 + 临时目录中一份**标注密文的拷贝**充作可读 review 路径 | 固定码 `scenario_ciphertext_mismatch`，帧 `:194` | 标注半 `sha(ann) == manager.field` 为 true；review 半因 `review_ciphertext_sha256` 仍为 `null` 而 false。**`:193` 已越过**，停在 review 密文比对 |
| C（临时合成，非交付） | B 的占位 + 临时 manager/review 副本（只填 `review_ciphertext_sha256`/`path`） | 无错误，返回 `ValidatedScenarioContract` | 校验体走完 `:197` 起的解密、载荷 bindings、30 案 axes、`scenario_counts`/`axis_counts` 对账；`safe_summary = case_count 30 / total_turns 36 / quality_readiness BLOCKED / release_ready false / runtime_axis_evidence_produced false` |

- C 的 review 占位是**本地合成 fixture**，不写入 v3 目录、不进入 freeze 清单、不构成任何 review 证据；它只用于证明标注载荷能走完校验体。
- 真实件下无法到达 `:197`：v3 review 密文尚未产出，且 manager/review 的 `review_ciphertext_sha256`、`review_ciphertext_path` 仍为 `null`。本包**不伪造** review。

## 4. 对冻结 A 两件的唯一改动（必须披露）

为让 loader 的 `:194` 标注半通过，`annotation_ciphertext_sha256` 由 `null` 回填为 `0fa7dbe0…`：

| 文件 | 改前 SHA-256 | 改后 SHA-256 | 变更 |
|---|---|---|---|
| `H2V3/PM/manager-acceptance.json` | `3954b3d3ea1e2ec3a725c43f03f70d9d349f4d24f9a3691a53937cfa7fd587d7` | `bd44601cc27cef4b860e50f2fede2feaeee0e8749440b668d7a5dffebd03ae58` | 仅 `annotation_ciphertext_sha256`：`null` → `0fa7dbe0…` |
| `H2V3/PM/review-aggregate.json` | `250561633594846533da5888bdd828b59a4b3c08090b035463c5fb4f379e0197` | `eeb72bc38244f0f0d601a7ef5af23e07d04961da037123c18549b478f7654d7f` | 仅同一字段 |

- 反向验证：把该字段改回 `null` 后按同一序列化重算，两件分别逐字节回到改前 SHA（`equals_before = true`），证明没有第二处字节变化。
- 未改 `accepted_scope`、`verdict`、任何计数、`checks`、`process_deviations`、`authorization_evidence`；`annotation_frozen` 仍为 `false`，`quality_released` 仍为 `false`。本包不把该回填当作验收结论。

## 5. C 清单逐条

| 项 | 状态 | 证据 / 理由 |
|---|---|---|
| annotation 投影（本包 A） | **关闭**（仅限「投影件 + loader 绑定」） | 密文读回逐字节相等；载荷 30 案四轴 7 字段通过冻结 `_axis`；bindings/轴计数/scenario 计数与 review 逐值相等；B 探针证明 `:193` 标注半已越过。不是质量放行，也不是独立复核 |
| v3 contract/plan（冻结 A） | **关闭**（数据件与绑定） | `p2-h2-scenarios-H2v3.json` `9dfefc39…`、`p2-ingest-plan-H2-v3.json` `2ea346d8…`；loader 在 `:190` 的 bindings 逐值相等并继续前进；未改其内容 |
| L1 corpus sha 回填 | **关闭** | `p2-holdout-v3.source-map.json` 的 `lifecycle_ref.sha256 = cc2ad0be…` 与 L1 实际字节相等；`corpus_ref.manifest_sha256 = 1b3885a7…` 与 `fixtures/acceptance-h2v3/manifest.json` 实际字节相等 |
| source-map `/v0.2` 接线 | **未关闭** | `backend/src/mktkb/evaluation/p2_score_run.py:499` 仍只接受 `p2-holdout-source-map/v0.1`；v3 source map 是 `/v0.2`。本包未改计分代码 |
| C20/C22 真实索引冒烟 | **未关闭** | 本包零真实调用，未建索引、未查产品；`v3-author/review-aggregate-r2.json` 与 `review-aggregate.json` 的残余项仍要求真实索引离线冒烟（文档标题 `DOCUMENT_NOT_FOUND`、双门店过滤） |

## 6. 零调用与保全

- 零真实调用、零真实请求：未调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额；未启服务；未建 GO；未写任何网络代码路径。
- 未改：`fixtures/acceptance/**`、`fixtures/acceptance-h2v3/**`（12 源 + manifest 逐件 SHA 与改前一致）、`D:\mktkb-p2-holdout\v2\**`、v3 既有 6 件（逐件 SHA 与改前一致）、C 冻结 12、`p2_holdout_scenarios.py`、账本/GO/阈值、已接收模块。
- 新增只落在：`D:\mktkb-p2-holdout\v3\annotations-v0_2.fernet`、`docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/`（freeze.json / verify-freeze.py / 本报告）。
- 分支、HEAD 不变；暂存区 0；0 commit；未新建 worktree、未切分支。15 条 tracked modified 路径不变（本包未编辑任何 tracked 文件）。

## 7. 残余

1. **v3 保管复核密文未产出**：`review_ciphertext_sha256` / `review_ciphertext_path` 仍 `null`；loader 不能到达 `:197`，v3 scenario contract 仍未闭合。
2. **本包不是独立复核**：标注投影的结构/语义由本包自检与加载器校验，未做第二人独立复核；`annotation_frozen` 仍 false。
3. **`conflict` 状态仍 0 题**：四状态覆盖缺口，未在本包处理。
4. **source-map `/v0.2` 接线与 C20/C22 真实索引冒烟**：见 §5，均未关闭。
5. **freeze 清单的自哈希**：`p2-holdout-v3.freeze.json` 不把自身列入 `artifacts[]`；`verify-freeze.py` 末尾打印其自身 SHA 供第三方记录。
