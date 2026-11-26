# H2 v3 语料返工 R1 · 开发报告（`P2-HOLDOUT-v3`）

- 角色：v3 语料返工 R1（普通开发；不做验收，不写 `pass/PASS`）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0，0 commit，未新建 worktree、未切分支。
- 上一轮结论：`PARTIAL`（keyspace 29/36，7 条不可对齐）。根因：`V05`/`V06` 的 `失效日期` **整列留空** ⇒ 产品 `_find_header_index` 把数据行当表头。
- 本轮裁定（经理 2026-11-15）：**暂缓修产品解析器**，改数据侧用**显式哨兵值**。
- 本轮**零真实调用**：11 次运行外部连接尝试 **0**，正对照证明守卫会拦（`evidence-r1/10r1-zero-call.json`）。
- 本报告不含任何题面/答案/目标值/密文；`evidence-r1/` 下全部为公开件与本地复算结果。

## 1. 结论

| # | 任务 | 状态 | 依据 |
|---:|---|---|---|
| 1 | 6 个工作簿 `失效日期` 整列为空 → 显式哨兵 `未声明`（11 格） | **COMPLETE** | `02r1-cell-diff.json`、`07r1-effective-range-proof.json` |
| 1a | 表头识别恢复 → keyspace **36/36 可对齐**（逐条判定） | **COMPLETE** | `04r1-keyspace-proof.json`（§5 逐条表） |
| 1b | `_effective_range` 语义**不变**（哨兵不被解析成日期） | **COMPLETE** | `07r1-effective-range-proof.json`（§6） |
| 1c | `生效日期` 列不变；被改的原有单元格 **0** | **COMPLETE** | `02r1-cell-diff.json`：投影 475 格差 0；R1 vs R0 差 = 11 格且只在 `失效日期` |
| 2 | 重出 manifest 与 source-map（SHA 必变），旧 SHA 记档 | **COMPLETE** | §3 对照表；`06r1-source-map.json` |
| 3 | 修 L1 `records_rows` 2→4，并扫描同类不一致 | **COMPLETE** | `08r1-consistency-selfcheck.json`（49/49） |
| 4 | 修规格 §7「不动的工作表 6 张」→ 8 张 | **COMPLETE** | 同上（实测 14 表 = 6 目标 + 8 非目标） |
| 5 | 登记产品缺陷 `EXCEL-HEADER-EMPTY-COLUMN`（不修） | **COMPLETE** | `product-defects-found.md`、`11r1-defect-repro.json` |
| 6 | 重跑规范化摘要 + 「原列投影 v3==v2」证明 | **COMPLETE** | `05r1-normalized-digest.json`：`equal = true` |

**总体 `COMPLETE`（本角色口径：本轮的 6 项交付全部产出且证据自测通过）。**
本角色**不做验收判定**：`COMPLETE` 只表示「该做的做了、该证的证了」，不表示「v3 可以冻结」。
冻结仍需独立验收 + 双人重算 + G1–G10 逐项实测（规格 §6）。

## 2. 哨兵决策：为什么是 `未声明`，不是 `长期有效`

| 项 | 决策 |
|---|---|
| 字面值 | **`未声明`**（三字，UTF-8，无空格/标点/数字） |
| 写入位置 | 仅 `失效日期` 列中**原本为 null（not_asserted）**的格 |
| 语义 | `未声明` ⟺ L1 `effective_to = null` ⟺ `_effective_range` 该侧跳过；**不等于「无限有效」** |
| 规格落点 | 改动规格 §1.4 + 新增 §1.5（写死字面值、一一对应、禁止第三形态） |
| manifest 落点 | `lifecycle.effective_to_sentinel` 块（含 `maps_to` / `one_to_one` / `not_a_date` / 两条 why） |

**为什么否掉 `长期有效`**（任务允许二选一，这里给出否掉的理由）：

1. L1 的 `null_rule` 写死「`effective_to` 为 null 表示**未声明失效日**，语义是 not_asserted，
   **绝不等价于『无限有效』**」。写 `长期有效` 等于让语料**断言一个 L1 明确否认的业务事实**——
   这不是占位，是语义造假：人读语料会认为该记录永不过期，而判据侧仍按"该侧跳过"处理，
   **人读与机读会永久分歧**。
2. 上一轮规格 §1.4 的禁令清单里本来就把 `长期有效` 与 `null`/`9999-12-31` 并列禁止，理由相同。
   本轮要加哨兵，正确做法是**加一个语义正确的哨兵**，而不是解禁一个语义错误的。
3. `未声明` 已在上轮做过模拟验证（`evidence/08-header-detection-finding.json`
   `alternative_shape_simulation.placeholder = "未声明"`：V05 表头恢复第 7 行、V06 恢复第 4 行、
   `_effective_range` 与留空逐值相同）。本轮把模拟升级为**冻结分类器函数级实测**（§6）。

**为什么哨兵不会破坏 R-AX-5「双侧非空」**：`R-AX-5` 说的是**窗口两侧**（`effective_from` 与
`effective_to`）都要非 null，不是"单元格非空"。哨兵不改变 `_effective_range` 的返回值
（仍是 `("range", from, None)`），因此 runs 2/3 的「终端版本右侧未声明」结构事实不变——
这一点已写进规格 §1.5.1 的最后一行，防止后续有人拿"该列非空"去凑双侧非空。

## 3. 语料与各件 SHA256（旧 → 新对照）

### 3.1 被改的两个工作簿（本轮只动了这两个文件的字节）

| 文件 | R0 bytes | R0 sha256 | R1 bytes | R1 sha256 |
|---|---:|---|---:|---|
| `variants/V05_物品位置表_新版V3_移除P01.xlsx` | 24673 | `9b2c413c32b1c4df2c8e8099336ea4a37aab2c14a3de85e6967f4ae8df8c88d2` | **25154** | **`2deb0e23b95404fe6d65b428ca671c2e4780c8a6a7d3cd5d460bf5b3f4b2dbd7`** |
| `variants/V06_合作店家信息_新电话.xlsx` | 20787 | `5ebd41bd64c0401c96869524bc1202c0183bbd44d7db8ae67d5ef6477f3983fc` | **21059** | **`cfaaced86b81e3d417053617bb0fbf698e70abfa18998078d059e9bdec73ffd1`** |

### 3.2 其余 10 个源：与 R0 **逐字节相同**

`D01`、`D02`、`V03`、`V04` 四个 xlsx 的 `失效日期` 本来全是日期、一格未动，故字节与 R0 完全一致
（`D01 85b261fc…`、`D02 c8f11400…`、`V03 5b0f9081…`、`V04 50577431…`，与 R0 报告逐字相同）；
6 个 docx/pdf 仍与 v2 逐字节相同。**证据**：`09r1-preservation.json` 的
`delivery_changed` 恰为 `{V05, V06, manifest.json}`、`delivery_unchanged` 恰为其余 10 个。

> 易读错的地方：上一轮 §2.1 的表把 6 个 xlsx 都标成「改（+2 列）」，容易被顺推成"R1 又改了 6 个"。
> 本轮明确：**R1 的语料字节改动面 = 2 个文件 / 11 个单元格**；另外 4 个 xlsx 与 R0 **逐字节相同**。

### 3.3 身份件（旧 → 新）

| 件 | R0 bytes / sha256 | R1 bytes / sha256 |
|---|---|---|
| `fixtures/acceptance-h2v3/manifest.json` | 16967 / `c69baa8f1c963a37c2c414f7e56bdc0b30388295fe7d01ca30980e1e9a7f3e15` | **19435** / **`1b3885a7ce36676b3642dea9316f644b4cd0468ac4e1493780a31996ab4dd07c`** |
| `docs/evaluation/p2-holdout-v3.source-map.json` | 2402 / `7ded23f19304be292a9b42de58f2058a84a0196e69723b561f4e5ccdb0772b93` | **2648** / **`03665c48c0716e45e0a6313c6f1823e6714c996d85254f01283fc0ef5ed2e8b8`** |
| `docs/evaluation/p2-source-lifecycle-v1.json`（L1） | 35962 / `92f1186927b458aa65eda7b7abd5aa8f3e9e52323627a398d8560c02e17451aa` | **35962** / **`cc2ad0be2a3d884987d9f74b32e25181d752a8b497093afba42ccef8d87541d1`** |
| `docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md` | 27455 / `d803619ed9c20c5df87ffd9dc567eb10f80806cf9aab7623f408e84f67136b31` | **32231** / **`6d64ee795c090016e569182a21dca2f1f048659ddb25982be255ee65b892b4e8`** |

L1 的字节数**正好没变**（`2`→`4` 同宽），所以只能靠 SHA 区分——这正是为什么清单必须记 SHA 而非 size。

`source-map` 的内容改动只有两处被指向件的 SHA（`lifecycle_ref.sha256`、`corpus_ref.manifest_sha256`）
外加一条 `basis` 说明；`sources` 的 12 条 `(doc_code, version_number)` 与 v0.1 已声明的四个值一字未改
（`06r1-source-map.py` 内 fail-closed 校验）。

## 4. 一级证据：原列投影 0 改动 + 「R1 vs R0」逐格差

口径 = 规格 §3.1：把 v3 裁回原列数后与 v2 逐格比较 `(值, 值类型)` 与样式签名
（`number_format/font/fill/border/alignment/protection`），另比表名与顺序、可见性、合并范围、
行高列宽、数据有效性、条件格式、表格对象、`max_column` 增长。

`02r1-cell-diff.json`：

| 项 | 值 |
|---|---:|
| 工作簿 / 表 / 格 | 6 / **14** / **475** |
| 原列投影差异 | **0** |
| `existing_cells_modified` | **0** |
| 目标表 / 非目标表 | 6 / **8**（4 `备用物料表` + 4 `旧草稿`） |
| 新列数据格槽 | 78 = **67 个日期** + **11 个哨兵** + **0 个空格** |
| 哨兵落点错配 | **0** |
| 新列越界格 / 新列合并 | 0 / 0 |

**R1 vs R0 的逐格差**（R0 交付件已被原地覆盖，故用**上一轮生成器**在临时目录重放，并用
`00r1-baseline.json` 里记录的 R0 交付 SHA 交叉校验重放结果 —— `r0_reconstruction_matches_baseline_all = true`）：

| 项 | 值 | 含义 |
|---|---:|---|
| 差异格总数 | **11** | 只有这 11 格变了 |
| `失效日期`：空 → `未声明` | **11** | 就是本轮要改的那 11 格 |
| `失效日期`：`未声明` → 空 | 0 | 没有反向改动 |
| **`生效日期` 列差异** | **0** | **「`生效日期` 列不变」的逐格证明** |
| 其它任何差异 | **0** | 原有单元格一格未动 |

## 5. keyspace proof：36/36 可对齐（逐条）

做法（`04r1-keyspace-proof.py`）：真实 `parse_document` 解析 6 个 xlsx → 真实
`retrieval.index.analyze_fields` 求 `(entity_type, entity_key, entity_filters)` → 真实
`retrieval.tokenize.normalize_value` 复算 id 段；target 声明取自出题计划 §5；窗口/上传集取自 L1。
每条 target 检查 11 项（上一轮 9 项 + R1 新增 2 项哨兵投影检查）。

| 项 | R0 | **R1** |
|---|---:|---:|
| 声明 target 的题 | 30 | **30** |
| target 实例 | 36 | **36** |
| **可对齐** | 29 | **36** |
| **不可对齐** | 7 | **0** |
| 受影响题 | 6 | **0** |
| 表头误判的来源 | V05、V06 | **无** |

逐条判定（`effective_to_raw` 一列直接看出哨兵与日期的分工）：

| 题 / run | target | 来源 | `失效日期` 原文 | 分支 | `entity_key` | 可对齐 |
|---|---|---|---|---|---|---|
| C01 r0 | P01@D01v2 | D01 | `2026-10-31` | date | `item\|id:p01` | ✅ |
| C02 r0 | P03@D01v2 | D01 | `2026-10-31` | date | `item\|id:p03` | ✅ |
| C03 r0 | S01@D02v1 | D02 | `2026-11-15` | date | `store\|id:s01` | ✅ |
| C04 r0 | P02@D01v2 | D01 | `2026-10-31` | date | `item\|id:p02` | ✅ |
| C05 r1 | P07@D01v2 | D01 | `2026-10-31` | date | `item\|id:p07` | ✅ |
| C06 r1 | S03@D02v1 | D02 | `2026-11-15` | date | `store\|id:s03` | ✅ |
| C07 r1 | P04@D01v2 | D01 | `2026-10-31` | date | `item\|id:p04` | ✅ |
| C07 r1 | **P08@D01v2** | D01 | `2026-10-15` | date | `item\|id:p08` | ✅ |
| C08 r2 | P02@D01v3 | V04 | `2026-11-30` | date | `item\|id:p02` | ✅ |
| **C09 r3** | **P08@D01v4** | V05 | **`未声明`** | sentinel | `item\|id:p08` | ✅（R0 ❌） |
| **C10 r3** | **S02@D02v2** | V06 | **`未声明`** | sentinel | `store\|id:s02` | ✅（R0 ❌） |
| C11 r0 | P01@D01v2 | D01 | `2026-10-31` | date | `item\|id:p01` | ✅ |
| C12 r0 | P02@D01v2 | D01 | `2026-10-31` | date | `item\|id:p02` | ✅ |
| C12 r0 | S02@D02v1 | D02 | `2026-11-15` | date | `store\|id:s02` | ✅ |
| C13 r1 | P03@D01v2 | D01 | `2026-10-31` | date | `item\|id:p03` | ✅ |
| C14 r2 | P04@D01v3 | V04 | `2026-11-30` | date | `item\|id:p04` | ✅ |
| **C15 r3** | **P07@D01v4** | V05 | **`未声明`** | sentinel | `item\|id:p07` | ✅（R0 ❌） |
| C16 r0 | S03@D02v1 | D02 | `2026-11-15` | date | `store\|id:s03` | ✅ |
| C17 r0 | S04@D02v1 | D02 | `2026-11-15` | date | `store\|id:s04` | ✅ |
| C18 r1 | P07@D01v2 | D01 | `2026-10-31` | date | `item\|id:p07` | ✅ |
| C19 r2 | P02@D01v3 | V04 | `2026-11-30` | date | `item\|id:p02` | ✅ |
| **C20 r3** | **P08@D01v4** | V05 | **`未声明`** | sentinel | `item\|id:p08` | ✅（R0 ❌） |
| C21 r0 | P01@D01v2 | D01 | `2026-10-31` | date | `item\|id:p01` | ✅ |
| C22 r1 | P01@D01v2 | D01 | `2026-10-31` | date | `item\|id:p01` | ✅ |
| C23 r0 | P08@D01v2 | D01 | `2026-10-15` | date | `item\|id:p08` | ✅ |
| C24 r1 | P02@D01v2 | D01 | `2026-10-31` | date | `item\|id:p02` | ✅ |
| C25 r2 | P01@D01v3 | V04 | `2026-11-30` | date | `item\|id:p01` | ✅ |
| C26 r0 | P01@D01v2 | D01 | `2026-10-31` | date | `item\|id:p01` | ✅ |
| C26 r0 | S01@D02v1 | D02 | `2026-11-15` | date | `store\|id:s01` | ✅ |
| C27 r0 | S01@D02v1 | D02 | `2026-11-15` | date | `store\|id:s01` | ✅ |
| C28 r1 | P08@D01v2 | D01 | `2026-10-15` | date | `item\|id:p08` | ✅ |
| C28 r1 | S02@D02v1 | D02 | `2026-11-15` | date | `store\|id:s02` | ✅ |
| C29 r2 | P03@D01v3 | V04 | `2026-11-30` | date | `item\|id:p03` | ✅ |
| **C29 r2** | **S03@D02v2** | V06 | **`未声明`** | sentinel | `store\|id:s03` | ✅（R0 ❌） |
| **C30 r3** | **P07@D01v4** | V05 | **`未声明`** | sentinel | `item\|id:p07` | ✅（R0 ❌） |
| **C30 r3** | **S02@D02v2** | V06 | **`未声明`** | sentinel | `store\|id:s02` | ✅（R0 ❌） |

> 表里 7 条标「R0 ❌」的正是上一轮不可对齐的那 7 条（`P08@D01v4` ×3、`P07@D01v4` ×2、
> `S02@D02v2` ×2、`S03@D02v2` ×1 按出现次数计；去重后 4 个（记录,版本）组合）。
> 现在它们全部走 `sentinel_not_asserted` 分支，`entity_key` 是 id 型且与运行期逐键逐值相等。

### 5.1 哨兵审计（全局）

| 项 | 值 |
|---|---:|
| 含哨兵的 unit | **11** |
| 按来源分布 | V05 = **7**、V06 = **4**、D01/D02/V03/V04 = **0** |
| 非法 `失效日期` 形态（既非日期也非哨兵） | **0** |
| 表头判定与声明不符的来源 | **0** |

### 5.2 反向探针（防止把不可对齐硬凑成可对齐，全部仍成立）

| 探针 | 值 |
|---|---:|
| `备用物料表` unit 数 / 其中非 id 型 / id 型 | 4 / 4 / 0 |
| 隐藏表 `旧草稿` 在文件里存在 / 被入库 | 4 / **0** |
| `P05`/`P06` 出现在 target 声明 | **0** |
| `document\|` 或 uuid 型键 | **0** |
| 同一记录跨版本 `entity_key` 不稳定条数 | **0**（稳定 12） |

## 6. `_effective_range` 语义不变：函数级证明

`07r1-effective-range-proof.json`。**不重写规则**，直接调冻结分类器与产品 chunking 的真实函数。

### 6.1 表头恢复

| 文件 | 声明表头行 | R0 实测 | **R1 实测** | R0 unit | **R1 unit** |
|---|---:|---:|---:|---:|---:|
| V03 | 7 | 7 | **7** | 9 | 9 |
| D01 | 7 | 7 | **7** | 9 | 9 |
| V04 | 7 | 7 | **7** | 9 | 9 |
| **V05** | **7** | **8** ❌ | **7** ✅ | 7 | **8** |
| D02 | 4 | 4 | **4** | 4 | 4 |
| **V06** | **4** | **5** ❌ | **4** ✅ | 3 | **4** |

### 6.2 等价性判据（逐 unit）

对每个 unit 造 `失效日期` 的四种形态——**现状（哨兵）**、**掩回 R0 的 `None`**、`""`、键缺失——
分别调 `p2_hard_evidence._effective_range({"raw_fields": …})`，要求三元组逐值相等。
「掩回 `None`」不是猜的：解析器对每个表头都写 `fields[name] = value`（`excel.py:319-325`），
所以 R0 的留空格在 `fields` 里**就是** `None`。

| 项 | 值 |
|---|---:|
| 参与比较的 unit 总数 | 43 |
| 其中「原本留空」（R1 装哨兵）的 unit | **11** |
| 三元组不一致的 unit | **0** |
| `chunking.effective_dates` 不一致的 unit | **0** |
| 哨兵 unit 的三元组取值 | 7× `("range","2026-12-01",None)`（V05 / D01 v4）、4× `("range","2026-11-16",None)`（V06 / D02 v2） |
| `_collect_dates(fields, EFFECTIVE_TO_KEYS)` 对哨兵 unit | **`[]`**（该侧被跳过，没有被解析成日期） |

> 说明：非哨兵 unit 的 `失效日期` 是真日期，掩成 `None` 当然会变——那是另一件事，且那些文件
> 与 R0 **逐字节相同**（§3.2）。所以等价性只在 11 个哨兵 unit 上有意义，本报告按此口径比较，
> 不拿"全域都相等"这种假命题充数。

### 6.3 哨兵不会被解析成日期（四条独立证据）

| 调用 | 结果 |
|---|---|
| `p2_hard_evidence._parse_date_text("未声明")` | `None` |
| `rag.chunking.parse_date("未声明")` | `None` |
| `rag.chunking.effective_dates({"失效日期": "未声明"})` | `(None, None)` —— 与留空同值 |
| `p2_hard_evidence._collect_dates({"失效日期": "未声明"}, EFFECTIVE_TO_KEYS)` | `[]` |

产品检索侧同理：`rag/retrieval.py:207-210` 的 `effective_to IS NULL` 分支照旧命中
（`chunking.effective_dates` 给 `None`），闭区间比较不被哨兵污染。

## 7. L1 一致性修复与「还有没有第三处」

### 7.1 已修的一处

`docs/evaluation/p2-source-lifecycle-v1.json` 的 `coverage_selfcheck.totals.records_rows`：
**2 → 4**（`records[]` 实为 4 行：P02 / P05 / P06 / P08）。只改这一个数字，不动任何窗口值、
不动 `pre_freeze_revision`、不动 `invariants_preserved`。

L1 自身声明「冻结后只能出 v3.1」，但本轮仍在 `pre_freeze`（`pre_freeze_revision.status` 明写
「本表尚未进入任何 freeze 清单，故本轮可修」），且改的是**计数元数据**而非设计事实值，
所以不构成对已冻结内容的回填。

### 7.2 同类不一致扫描（这才是回答"还有没有第三处"的方式）

`08r1-consistency-selfcheck.py` 把 L1 里**每个可复算的计数**逐条从数组重算，共 **49** 条断言：

| 组 | 条数 | 结果 |
|---|---:|---|
| `coverage_selfcheck.totals`（含 `records_rows`、`distinct_version_windows`、`contiguity_violations`、`terminal_not_open_violations`、`built_at_collisions` 等） | 10 | 全过 |
| `records[]`（⊆ 版本窗口、主键唯一） | 2 | 全过 |
| `per_run_dates`（cases / turns / slot_checks / slot_cardinality_one / stale_decidable_cases / window==position） | 6 | 全过 |
| `anchor_2026_10_28`（8 槽位基数 1；声明值 == 重算值） | 2 | 全过 |
| `invariants_preserved` 四条 | 4 | 全过 |
| `version_number_bijection.mismatch_count` | 1 | 全过 |
| 规格 §7 表数（实测 14 表 / 6 目标 / 8 非目标 / 4 备用 / 4 旧草稿）+ 5 条正文措辞 | 9 | 全过 |
| manifest `lifecycle.totals` 与实测（12 文件、14 表、78 格、11 哨兵、0 空格、0 改格、12 表头、4 偏离行、逐文件 SHA、`built_at`、哨兵字面值） | 15 | 全过 |

**结论：除已修的 `records_rows` 外，L1 没有第二处「计数与数组不符」。**
（唯一被我**改错**过一次的是本脚本自己的 `manifest.files_count` 断言——我按 5/7 写，实测是
`normal 6 + variants 6`；这条断言当场报错，说明这套扫描确实会抓错，包括抓我的错。已改正。）

### 7.3 过程中发现的第三处「数字与实物不符」（在上一轮报告里，未静默改）

上一轮 `dev-report.md` §2.1 把 `manifest.json` 记为 **16682 bytes**；实测（R1 开工前基线，
即 R0 交付件）是 **16967 bytes**，而 **SHA256 与上一轮声明完全一致**
（`c69baa8f…`，且 `evidence/03-determinism.json` 里 run1/run2/delivered 三方同值）。
即：**SHA 对、字节数错**，属报告笔误，不是产物问题。

处置：**不动 R0 报告的正文数字**（那是历史记录），只在 `dev-report.md` 顶部加一行横幅指向本报告，
并在本报告此处留证。R1 报告里的 manifest 字节数用实测值。

## 8. 文档不一致修复（规格 §7）

| 项 | R0 规格 | 实测 | R1 规格 |
|---|---:|---:|---|
| 不动的工作表 | 6 张（4 + 2） | **8 张** | **8 张（4 个 `备用物料表` + 4 个 `旧草稿`）** |
| 目标表 | 6 张 | 6 张 | 6 张 |
| 6 个 xlsx 的表总数 | —（未写） | **14 张** | 已在 §7 附注里点明 6 + 8 = 14 |

成因：4 个 D01 族工作簿（V03/D01/V04/V05）各带 `物品位置` + `备用物料表` + `旧草稿` 三张表；
`D02`/`V06` 只有 `店家信息` 一张表。所以非目标表 = 4 + 4 = 8，不是 4 + 2。

规格本轮另加：顶部 R1 修订说明、§1.5 全节（哨兵）、§1.4 的 null 分支改指向 §1.5、
§2.1 代码块注释、§7 的 R1 附注（含"78 = 67 日期 + 11 哨兵 + 0 空格"）。

## 9. 产品缺陷登记（只登记，不修）

- 文件：`docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/product-defects-found.md`
- 条目：**`EXCEL-HEADER-EMPTY-COLUMN`　状态 `OPEN`（未修复）**
- 最小复现：`evidence-r1/11r1-defect-repro.py` → `11r1-defect-repro.json`，
  **合成数据**（表名 `示例表`、5 列、1 表头行 + 2 数据行、标识 `X01/X02`），
  **不含任何题面/标签/答案/目标值**。实测 `verdict = REPRODUCED`（8/8）：
  - 缺陷形态：`header_row = 2`、`fields` 键全是业务值、`_effective_range = ("none", None, None)`
  - 绕开形态（写哨兵）：`header_row = 1`、`fields` 键全是表头、`_effective_range = ("range","2026-01-01",None)`
- 影响：无 `标识`（实体键退化为 uuid 型）／无日期（`_effective_range` 返回 `none`，日期检查整段失效）／
  **静默错解析**（不抛异常、不告警、`quality.complete` 仍 true，`text` 里"键=上一行的值"）。
- 暂缓修依据：经理 2026-11-15 裁定「先冻结 v3 量具，产品修复单独开包」。
- v3 里的绕开范围：只覆盖 `V05`(7 格) / `V06`(4 格)，只让 v3 语料不再触发；
  **产品对任何"整列为空"的表仍会同样错解析，缺陷本体一行未改**。
- 产品代码未被改动：`09r1-preservation.json` 的
  `frozen_inputs.product_parser_unchanged = true`、`checks.product_parser_unchanged = true`。

## 10. 规范化摘要（双人重算判据）

方案**逐字沿用上一轮**（不换算法，否则跨轮不可比）：逐文件 → xlsx 取「表名顺序 + 每表
`state/max_row/max_col` + A1..矩形全部 `[row,col,data_type,text]`（空格也输出）+ merged +
col_widths + row_heights」；docx/pdf 取 `{bytes, sha256}`；整体
`json.dumps(..., ensure_ascii=True, sort_keys=True, separators=(",",":"))` 后 SHA-256。

| 摘要 | R0 | **R1** | 预期 |
|---|---|---|---|
| `v3_normalized` | `393514997dc26db0bf92d3800312203a15f2adbe46060f6783b4228321b41d35` | **`be386e0065164960274ee77ad168fc6d3f11e84bf593b1e19adc50350593cbd9`** | **必须变**（11 格由空变哨兵） |
| `original_column_projection.v3_digest` | `363f8eb6…d6a1c6` | `363f8eb66aea27041715225f5f2baebdda317aa65f9f67a42026793c05d6a1c6` | **必须不变** |
| `original_column_projection.v2_digest` | `363f8eb6…d6a1c6` | `363f8eb66aea27041715225f5f2baebdda317aa65f9f67a42026793c05d6a1c6` | **必须不变** |
| `original_column_projection.equal` | `true` | **`true`** | **必须仍为 true** |

**「原列投影 v3 == v2」仍成立**：12/12 文件逐文件摘要相等（`per_file_equal` 全 true）。
哨兵只落在第 2 新列，投影裁掉新列后它根本不参与比较——这就是"业务内容一个字没动"的单一字符串证明。

第三方复算（照抄即可）：

```powershell
Set-Location -LiteralPath 'D:\GPT项目\市场部AI知识库'
$ev = 'docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\v3-corpus\evidence-r1'
.\.venv\Scripts\python.exe -B "$ev\05r1-normalized-digest.py"
# 比 v3_normalized.digest == be386e00…cbd9；original_column_projection.equal 必须为 true
```

## 11. 零真实调用（`10r1-zero-call.json` → `ZERO_EXTERNAL_CALLS`）

守卫复用上一轮那份（`../evidence/netguard/`，未改写；SHA 已记入 payload）：拦
`socket.connect/connect_ex/create_connection/getaddrinfo`、`http.client`、`httpx` 传输层；回环放行。

| 项 | 值 |
|---|---:|
| 运行次数（含正对照） | **11** |
| 业务进程外部连接尝试 | **0** |
| 正对照：外部 `connect` 被拦 / 外部 DNS 被拦 | ✅ / ✅ |
| 守卫落盘次数 | 11 |
| 全部脚本 exit 0 | ✅（keyspace 本轮也是 0，因为已 aligned） |

**口径如实**：上面 11 次是**带守卫**的运行。开发过程中我也单独跑过同一批脚本（不带
`PYTHONPATH` 注入），那些运行**没有**守卫计数——它们不是"零调用"的证据来源，只是调试。
本次全部脚本的静态事实是：只读本地文件、只 `subprocess` 拉起同目录的 python 脚本、只用
`openpyxl` / `json` / `hashlib` / `pathlib`，**没有任何 socket / http / 网络库调用**。
若复核方要求"每一次运行都被守卫覆盖"，把上面的 `10r1-zero-call.py` 当作**唯一**权威运行集即可。


## 12. 保全（`09r1-preservation.json` → `PRESERVED`）

| 项 | 值 |
|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b00667…`（未变，0 commit） |
| 暂存区 | **空**（未 `stage`/`commit`/`push`） |
| tracked modified | **15**，路径逐条与基线相同 |
| untracked | 224 → **224**（新增 **0**：本轮改动全落在已被 `??` 折叠的 `Q1A-EVAL-REPAIR/` 与已 untracked 的 v3 件上） |
| `fixtures/acceptance/**` | 35 个文件逐字节不变 |
| C 冻结 12 | 逐项相等（含 `p2_hard_evidence.py`、`retrieval/index.py`、`rag/chunking.py`） |
| 冻结输入件（含 `ingestion/parsers/excel.py`、`rag/retrieval.py`、`p2_holdout_scenarios.py`） | 逐件 SHA 不变 |
| 授权改动集合 | 恰为 {L1, 规格, source-map, v3 manifest} —— 与预期集合逐项相等，无第五件 |
| 未读私有件 | 真实 H2 题面/标签/答案/密文/key/`.env`/保管会话/runbook **均未打开**；未写任何含题面值/目标值的临时明文 |

### 12.1 关于上一轮「快照覆盖基线」的过程问题

上一轮收尾时重跑流水线，`00-snapshot-before.py` 把真正的"开工前快照"覆盖成了"现在"，
后来靠减法重建才补回。本轮做法：

1. **先采基线、后做任何写入**：`00r1-baseline.py` 是第一个执行的脚本，落盘时间早于第一次生成；
2. **幂等保护写死**：脚本里 `if OUT.exists(): raise SystemExit(...)`，且**不提供重建开关**；
3. **不重跑上一轮的 `00-snapshot-before.py`**（它的保护是"已存在即拒绝"，本轮根本不需要它）；
4. 保全核对以 `00r1-baseline.json` 为「之前」侧，且把**授权改动面**单列，不把"本轮本该改的件"
   和"越界改动"混成一个数字——这样即使我改多了，也会在 `authorized_changes_are_exactly_the_expected_set`
   上直接暴露。

`09r1-preservation.json` 的 `checks` **17 项全 true**，`result = PRESERVED`。

## 13. 偏差 / 观察（逐条，供复核）

1. **哨兵字面值不是 `长期有效`**：任务允许二选一，本报告 §2 给了否掉 `长期有效` 的三条理由
   （L1 `null_rule` 明确否认"无限有效"；上一轮 §1.4 本就把它列为禁止值；`未声明` 已有上轮模拟）。
   若经理坚持 `长期有效`，那是**改语义口径**，需要重写规格 §1.5 并重出全部 SHA —— 本角色不自行改。
2. **R1 的语料字节改动面只有 2 个文件 / 11 格**（V05、V06），不是 6 个 xlsx（§3.2）。
3. **L1 字节数没变（35962）而 SHA 变了**：`2`→`4` 同宽。清单必须记 SHA，记 size 抓不到。
4. **上一轮报告 §2.1 的 manifest 字节数 16682 是笔误**，实测 16967（SHA 一致）。已在 `dev-report.md`
   顶部加横幅说明，未改其正文数字（§7.3）。
5. **`p2_holdout_scenarios.py:287` 的 `fixtures/acceptance` 路径前缀校验**（上一轮 §10.5 提出）
   **本轮仍未处置**：v3 ingest plan 的 path 指 `fixtures/acceptance-h2v3/`，会被该断言拒绝。
   这是"生成 plan 之前"的阻塞项，不在本轮 6 项任务内，**保持 OPEN**。
6. **`备用物料表` 4 个 unit 仍全部非 id 型**（结构性，不做补偿）；`旧草稿` 仍 0 入库。
7. **`_effective_range` 等价性只在 11 个哨兵 unit 上有意义**（§6.2 说明），没有把"全域相等"当结论。
8. **规范化摘要算法未换**，所以 `v3_normalized` 的 R0/R1 两个值可直接比；若换算法，跨轮就不可比。

## 14. 残余与下一步（需要裁定，本角色不自行处置）

| # | 事项 | 影响 | 建议 |
|---:|---|---|---|
| 1 | **产品缺陷 `EXCEL-HEADER-EMPTY-COLUMN` 仍 OPEN** | 任何"整列为空"的表都会静默错解析 | 单独开包修 `_find_header_index` + 全量 xlsx 回归 |
| 2 | **v3 ingest plan 路径前缀校验**（`p2_holdout_scenarios.py:287`） | v3 plan 会被拒 | 新 loader 分支 / 新 schema / 或接受改码验收 |
| 3 | **双人重算与冻结** | 尚未做 | 按规格 §6.6 由第二角色独立复算 12 源 + 9 公开件的 SHA 与规范化摘要 |
| 4 | **哨兵值是否需进 L1** | L1 目前不记哨兵 | 若认为"哨兵"属设计事实，需在 L1 增字段 ⇒ 但那会改 L1 语义面，建议留在规格与 manifest |
| 5 | 本报告与 `evidence-r1/` 全部为公开件 | — | 可随评审流转，不含题面/答案/目标值/密文 |

## 15. 复算入口（第三方照此可独立重跑）

```powershell
Set-Location -LiteralPath 'D:\GPT项目\市场部AI知识库'
$ev = 'docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\v3-corpus\evidence-r1'

# 0) 基线（只能采一次；已存在即拒绝）
.\.venv\Scripts\python.exe -B "$ev\00r1-baseline.py"

# 1) 重建语料（空目录干跑，或原地覆盖 13 个已知路径）
.\.venv\Scripts\python.exe -B "$ev\01r1-build-corpus.py" --output "$env:TEMP\v3r1"
.\.venv\Scripts\python.exe -B "$ev\01r1-build-corpus.py" --output fixtures/acceptance-h2v3 --replace-existing

# 2) 一级证据：原列投影 0 改动 + 哨兵落点 + R1 vs R0 逐格差
.\.venv\Scripts\python.exe -B "$ev\02r1-verify-cells.py"

# 3) 字节确定性（13/13 三方相等）
.\.venv\Scripts\python.exe -B "$ev\03r1-determinism.py"

# 4) keyspace：预期 36/36 aligned（exit 0）
.\.venv\Scripts\python.exe -B "$ev\04r1-keyspace-proof.py"

# 5) 规范化摘要：v3 digest 变、投影仍等
.\.venv\Scripts\python.exe -B "$ev\05r1-normalized-digest.py"

# 6) 重出 source map（三处 SHA 均变）
.\.venv\Scripts\python.exe -B "$ev\06r1-source-map.py"

# 7) 表头恢复 + _effective_range 语义不变
.\.venv\Scripts\python.exe -B "$ev\07r1-effective-range-proof.py"

# 8) L1 / 规格 / manifest 计数对账（49 条）
.\.venv\Scripts\python.exe -B "$ev\08r1-consistency-selfcheck.py"

# 9) 产品缺陷最小复现（合成数据）
.\.venv\Scripts\python.exe -B "$ev\11r1-defect-repro.py"

# 10) 保全（16 项）与零调用（11 次 + 正对照）
.\.venv\Scripts\python.exe -B "$ev\09r1-preservation.py"
.\.venv\Scripts\python.exe -B "$ev\10r1-zero-call.py"
```
