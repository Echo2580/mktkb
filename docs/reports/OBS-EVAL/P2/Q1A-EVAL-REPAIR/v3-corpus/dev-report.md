# H2 v3 语料生成 · 开发报告（`P2-HOLDOUT-v3`）

> **⚠ 本文件是 R0 的历史记录，结论已被返工 R1 取代。**
> 上一轮判 `PARTIAL`（keyspace 29/36）。经理 2026-11-15 裁定「暂缓修产品解析器，改数据侧用显式哨兵」后，
> R1 已把 `失效日期` 的 11 个空格外改为哨兵 `未声明`，keyspace 现为 **36/36 可对齐**，
> 语料 / manifest / source-map 的 SHA 全部换新。**当前有效报告：`dev-report-r1.md`。**
>
> 另：本文件 §2.1 表格把 `manifest.json` 记为 16682 bytes，**实测为 16967**（SHA256 与本文一致，
> 属笔误）。为保留历史记录，正文未改；更正见 `dev-report-r1.md` §7.3。


- 角色：v3 语料生成开发助手（普通开发；不做验收，不写 `pass/PASS`）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0，0 commit，未新建 worktree、未切分支。
- 依据（只读，逐份核对 SHA256）：改动规格 `d803619e…`、出题计划 `ed5da038…`、判据 v1.1 `0ec6c392…`、L1 `92f11869…`、v2 source-map v0.1 `86c86767…`、v2 语料 manifest `68899152…`。
- 本轮**零真实调用**：全部脚本在进程级出站守卫下运行，9 次运行外部连接尝试 **0**，正对照证明守卫会拦（`evidence/09-zero-call.json`）。

## 1. 结论

| 任务项 | 状态 | 依据 |
|---|---|---|
| 1. 生成 `fixtures/acceptance-h2v3/`（12 源 + 2 列 + 6 份字节不变） | **COMPLETE** | `evidence/02-cell-diff.json`、`evidence/03-determinism.json` |
| 2. `manifest.json`（v3，dataset/label 版本 + 逐文件 SHA + 生命周期列声明） | **COMPLETE** | `fixtures/acceptance-h2v3/manifest.json` |
| 3. `p2-holdout-v3.source-map.json`（v0.2，12 码双射 + 两个引用） | **COMPLETE** | `evidence/06-source-map.json` |
| 4. keyspace proof（30 题 36 条 target 逐一判定） | **PARTIAL：29 可对齐 / 7 不可对齐** | `evidence/04-keyspace-proof.json`、`evidence/08-header-detection-finding.json` |
| 5. 双人重算方案（规范化摘要 + 第三方复算步骤） | **COMPLETE（方案已落地并自测）** | `evidence/05-normalized-digest.py`、`evidence/05-normalized-digest.json` |

**总体 `PARTIAL`**：语料/清单/源映射按规格产出且逐格零改动、双跑字节一致；但 36 条 target 中有 **7 条**在当前产品解析器下**不可对齐**，根因不在语料值，而在 `ingestion/parsers/excel.py:_find_header_index` 的表头启发式与「`失效日期` 留空」的结构冲突（§7）。该冲突需要裁定，不在本角色权限内自行改产品代码或改规格。

## 2. 交付件与 SHA256

### 2.1 语料（12 个源 + 1 个 manifest）

| 文件 | 类型 | bytes | sha256 | 字节 |
|---|---|---:|---|---|
| `normal/D01_物品位置表.xlsx` | xlsx | 25542 | `85b261fc2ad12c06325f12d6f756785da70d45f7da5e80e4e6eaea821e4d5b25` | 改（+2 列） |
| `normal/D02_合作店家信息.xlsx` | xlsx | 21003 | `c8f114007b9a6e681e498b9cbad798333ce9bda94222cf9dd219af797a58ff6e` | 改（+2 列） |
| `normal/D03_市场部工作指南.docx` | docx | 37107 | `adbf69b520a2385a6a92b83929bb0ced68b1d6e925de994e150cff0fcee30c2e` | 不变 |
| `normal/D04_活动策划流程.docx` | docx | 37032 | `cb64bcfd86acf35b2135ee812fcda1cda4106b0d863d6ca964d3cc6029c830f3` | 不变 |
| `normal/D05_物料领用规范.pdf` | pdf-text | 36604 | `c38a13436be8552df4b388ab82fdfba20362e19a2d8f747522430e16fad0fda6` | 不变 |
| `normal/D06_店家资料维护说明.pdf` | pdf-text | 33032 | `30edb4383c37dc77b51eb2a8d71b8cacc4539576792d6a1c80702526a08d1dea` | 不变 |
| `variants/V01_临时物料位置通知.pdf` | pdf-text | 32110 | `50e74141e2cf032202108b51afaee11df8b5816bfd3130113bd99c992dddc131` | 不变 |
| `variants/V03_物品位置表_历史V1.xlsx` | xlsx | 25542 | `5b0f9081cddbf3fe6867ccf08f4b88cf2f86ce8d6a12a9d6b386e28e59161f4b` | 改（+2 列） |
| `variants/V04_物品位置表_新版V3.xlsx` | xlsx | 25517 | `505774317e0d609b358290a102aa990b7049a65f5c9bcb1ec530d5e44b46cb75` | 改（+2 列） |
| `variants/V05_物品位置表_新版V3_移除P01.xlsx` | xlsx | 24673 | `9b2c413c32b1c4df2c8e8099336ea4a37aab2c14a3de85e6967f4ae8df8c88d2` | 改（+2 列） |
| `variants/V06_合作店家信息_新电话.xlsx` | xlsx | 20787 | `5ebd41bd64c0401c96869524bc1202c0183bbd44d7db8ae67d5ef6477f3983fc` | 改（+2 列） |
| `variants/V07_物料位置独立通知.pdf` | pdf-text | 31396 | `0805ee4307ce36cc703d674f7cfabb194bc318fcaef139721afe3235339f0616` | 不变 |
| `manifest.json` | JSON | 16682 | `c69baa8f1c963a37c2c414f7e56bdc0b30388295fe7d01ca30980e1e9a7f3e15` | 新件 |

6 个不变文件与 v2 对应文件**逐字节相等**（`copyfile` 复制，未重编码/未重打包）：`evidence/02-cell-diff.json` 的 `unchanged_files` 块按 `read_bytes()` 做逐字节比较，`unchanged_byte_identical = 6 / expected_unchanged = 6`、`docx_pdf_identical = 6`；同时 6 个被改 xlsx 的 SHA256 全部与 v2 不同（`changed_files_sha_differs = 6`）。`evidence/03-determinism.json` 另证双跑与交付件三方一致。

### 2.2 其他交付件

| 件 | bytes | sha256 |
|---|---:|---|
| `docs/evaluation/p2-holdout-v3.source-map.json` | 2402 | `7ded23f19304be292a9b42de58f2058a84a0196e69723b561f4e5ccdb0772b93` |
| `fixtures/acceptance-h2v3/manifest.json` | 16682 | `c69baa8f1c963a37c2c414f7e56bdc0b30388295fe7d01ca30980e1e9a7f3e15` |

## 3. 生成规则（值只来自 L1）

- **取值**：`sources[]` 版本窗口为默认；`records[]` 命中则用记录级窗口。全部值来自 L1，脚本内**不硬编码任何日期**，并且 `02`/`04` 各自**重新实现** L1 读取（不 import 生成器），以保证第三方可独立复算。
- **写入位置**：`物品位置` 的 `F/G`（表头行 7）、`店家信息` 的 `G/H`（表头行 4）；表头逐字 `生效日期` / `失效日期`。
- **行对齐按 `标识` 值，不按行号**（V05 少 P01，行号会错位）。
- **格式**：`YYYY-MM-DD` 文本单元格（不是 Excel 日期序列号；`02` 对 67 个日期格断言 `data_type == 's'`，`non_text_date_cells = 0`）。
- **`effective_to = null`**：留空单元格（V05 7 格、V06 4 格，共 11 格），不写 `null`/`9999-12-31`/`长期有效`。
- **记录级偏离只落 4 行**：`D01 v2` 的 `P02/P05/P06/P08`（其余行严格继承版本窗口）。

计数：数据行 **39**、数据格槽 **78**（写入 67 + 留空 11）、表头格 **12**、新增格槽合计 **90**；被改的原有单元格 **0**。

## 4. 一级证据：逐格比对（原列投影矩阵）

口径 = 规格 §3.1：把 v3 裁回原列数后与 v2 逐格比较 `(值, 值类型)` 与样式签名（`number_format/font/fill/border/alignment/protection`），另比表名与顺序、可见性、合并范围、行高列宽、数据有效性、条件格式、表格对象、`max_column` 增长。

结果（`evidence/02-cell-diff.json`）：**6 个工作簿 / 14 张表 / 475 格逐格比较，差异 0**；`existing_cells_modified = 0`；表头逐字、表名与顺序、可见性（`旧草稿` 仍 hidden）、合并/行高/列宽/有效性/条件格式/表格全部相等；新列无合并、无越界单元格。

> 过程中发现并修掉一个会让「逐格全等」不成立的细节：v2 的 `别名` 列有 8 个**存在但为空**的 `inlineStr` 单元格（4 文件 × 2 格），openpyxl 保存时会丢弃它们，读回后类型从 `inlineStr` 退化为 `n`。生成器改为「把这些位置物化为空串再保存」（`01-build-corpus.py:preserve_empty_typed_cells`），读回与原文件一致，8 格因此不再是差异。

日期本身另做一次独立校验：`02` 按 L1 重算每行期望窗口并逐格比对，`new_column_dates_mismatched = 0`、`non_text_date_cells = 0`。

## 5. 二级证据：确定性与「双人重算」

### 5.1 生成器确定性（已实测）

- 固定项：zip entry 顺序 = v2 原始顺序；entry 时间戳固定 `1980-01-01T00:00:00`；压缩方式 `ZIP_STORED`（不依赖 zlib 版本）；`create_system = 0`、`external_attr = 0`；`docProps/core.xml` 与 `docProps/app.xml` **取回 v2 原始字节**（openpyxl 会把 `dcterms:modified` 改成当前时间，取回即消除漂移）。
- 实测（`evidence/03-determinism.json`）：同一生成器在两个全新临时目录各跑一次，13/13 文件（12 源 + manifest）SHA256 与仓库交付件**三方全等**；CPython 3.12.7 / openpyxl 3.1.5。
- 代价：`ZIP_STORED` 使 xlsx 体积变大（如 D01 6758 → 25542 字节）。这是规格 §3.2 允许的降级，换取「跨机器字节可复现」；若要求体积，可改 `ZIP_DEFLATED` 并把判据完全交给 §5.2 的规范化摘要。

### 5.2 规范化摘要（双人重算的**必须相等**判据）

方案写死在 `evidence/05-normalized-digest.py`：逐文件 → xlsx 取「表名顺序 + 每表 `state/max_row/max_col` + A1..矩形全部 `[row,col,data_type,text]`（空格也输出）+ merged + col_widths + row_heights」；docx/pdf 取 `{bytes, sha256}`；整体 `json.dumps(..., ensure_ascii=True, sort_keys=True, separators=(",",":"))` 后取 SHA-256。

本轮值：

- `v3_normalized.digest = 393514997dc26db0bf92d3800312203a15f2adbe46060f6783b4228321b41d35`
- `original_column_projection`（v3 裁回 v2 列/行后重算）与 v2 对应摘要 **相等**：`v3_digest == v2_digest`，12/12 文件逐文件相等 ⇒ 单一字符串即可证明「除新增两列外业务内容没变」。

第三方复算步骤（写进 `05` 的 `third_party_recompute`，也在此复述）：

1. 在同一分支同一工作树里跑 `.venv\Scripts\python.exe 05-normalized-digest.py`；
2. 比 `v3_normalized.digest` 是否逐字等于上面的值；
3. 确认 `original_column_projection.equal == true`；
4. **只比规范化摘要，不比 zip 字节**；zip 字节（`03-determinism.json`）只作观测记录。

## 6. docx / pdf 字节相等证据

D03、D04（docx）与 D05、D06、V01、V07（pdf-text）共 6 份：`evidence/02-cell-diff.json` 的 `unchanged_files` 块按 `read_bytes()` 逐字节比较，结果 **6/6 完全相同**（长度与 SHA256 都相同）；`evidence/03-determinism.json` 对双跑产物与仓库交付件三方比较 13/13 全等 ⇒ **6/6 逐字节相等**。`V02`、`D07–D10`、`A01–A08`、`B01–B08`、`font-license/` 按规格 §1.1 **未复制**。

## 7. keyspace proof：29 可对齐 / 7 不可对齐

做法（`evidence/04-keyspace-proof.py`）：用**真实** `ingestion.parsers.parse_document` 解析 v3 的 6 个 xlsx → 拿与入库一致的 `fields`；用**真实** `retrieval.index.analyze_fields` 求 `(entity_type, entity_key, entity_filters)`；用**真实** `retrieval.tokenize.normalize_value` 复算 id 段小写形态；target 声明取自出题计划 §5；版本窗口、上传集、逐 run `business_date` 取自 L1（脚本内重新读取）。

每条 target 检查 9 项：来源存在 / 该版本含该记录行 / 记录→unit 唯一 / 键含 `|id:` 且 id 段 = `normalize_value(标识)` / 实体类型与记录前缀一致 / 非 `document|`+uuid / filters 键 ⊆ 运行期角色键且含 id 键 / filters 值与运行期逐键逐值全等 / 该版本在本 run scenario 已上传 / 版本窗口按闭区间覆盖 run 日 / `raw_fields` 日期与 L1 逐字相等。

结果：

| 项 | 值 |
|---|---:|
| 声明 target 的题 | 30 / 30 |
| target 实例（含 6 道双 target） | 36 |
| **可对齐** | **29** |
| **不可对齐** | **7** |
| 受影响题 | 6（C09、C10、C15、C20、C29、C30） |
| 被用作 target 的记录 | 10（P01–P04、P07、P08、S01–S04） |

**不可对齐的 7 条全部集中在 `V05`（D01 v4）与 `V06`（D02 v2）**：`P08@D01v4`、`P07@D01v4`、`P08@D01v4`、`P07@D01v4`、`S02@D02v2`、`S03@D02v2`、`S02@D02v2`（按题序）。

反向探针（防止把不可对齐硬凑成可对齐，全部成立）：`备用物料表` 4 个 unit **全部非 id 型**（键含 `doc:`/`unit:`）；`旧草稿` 在 4 个文件里存在但**入库 0 条**（隐藏表被跳过）；`P05/P06` 出现在 target 声明里 **0** 次；`document|`/uuid 键 **0**；同一记录跨版本 `entity_key` 稳定 **12/12**（变化 0 条）。

### 7.1 根因（`evidence/08-header-detection-finding.json`）

`ingestion/parsers/excel.py:112-130 _find_header_index` 用「下一行占用数 ≥ 本行非空数」给候选表头加分。加了第 2 列后：

| 文件 | 真表头行非空数 | 数据行非空数 | 真表头得分 | 首数据行得分 | 解析器选中 | 结果 |
|---|---:|---:|---:|---:|---|---|
| D01 / V03 / V04 | 7 | 7（两列都有值） | 6 | 6（并列，先者胜） | 第 7 行 ✅ | 正常 |
| D02 | 8 | 8 | 6 | 6 | 第 4 行 ✅ | 正常 |
| **V05** | 7 | **6**（`失效日期` 空） | **4** | **6** | **第 8 行 ❌** | 无 `标识`、无日期 |
| **V06** | 8 | **7**（`失效日期` 空） | **4** | **6** | **第 5 行 ❌** | 无 `标识`、无日期 |

后果（实测）：V05/V06 的 unit `entity_key` 不是 id 型、`_effective_range` 退化为 `("none", None, None)`（日期检查整段失效），因此 runs 2/3 的 7 条 target 无法对齐。**其它 4 个 xlsx 与 6 个不变文件不受影响**。

### 7.2 两个可选处置（需裁定，本角色未实施）

1. **产品侧（首选）**：修 `_find_header_index`，让候选表头不被「数据行占用更多」反超（例如并列/后续行更宽时优先更早行，或要求候选表头行必须包含 `ID_HEADERS`）。改动产品解析行为，须走独立验收，且要注意它会改变所有 xlsx 的表头判定口径。
2. **语料侧（与规格字面冲突）**：把为 `null` 的 `失效日期` 写非日期占位文本（如 `未声明`），让该列非空。已**模拟验证**（临时副本，未落盘）：V05 表头恢复第 7 行、id 恢复 `P02–P08`；V06 恢复第 4 行、id 恢复 `S01–S04`；冻结分类器 `_effective_range` 返回 `("range", from, None)` —— 与留空**完全一致**（`_collect_dates` 只收可解析值，`p2_hard_evidence.py:1452-1474`）。但规格 §1.4 明确要求「留空」，故需主人/经理书面裁定后才能落。

## 8. 保全（`evidence/07-preservation.json` → `PRESERVED`）

| 项 | 值 |
|---|---|
| 分支 / HEAD | `codex/p2-e2e` / `97b00667…`（未变，0 commit） |
| 暂存区 | 空（未 `stage`/`commit`/`push`） |
| tracked modified | **15**，路径逐条不变 |
| untracked | 222 → **224**（新增仅 2 个顶层条目：`fixtures/acceptance-h2v3/`、`docs/evaluation/p2-holdout-v3.source-map.json`；本轮 evidence 目录位于本就 untracked 的父目录下，不新增顶层条目） |
| `fixtures/acceptance/**` | 35 个文件逐字节不变（v2 语料只读） |
| C 冻结 12 | 逐项与 `axes/evidence/04-protected-hashes-before.json` 相等（含 `p2_hard_evidence.py`、`retrieval/index.py`、`rag/chunking.py`） |
| 10 份只读输入件 | SHA256 不变（两份计划、判据 v1.1、L1、v2 source-map、v2 manifest、`p2_holdout_scenarios.py`、`retrieval/index.py`、`rag/chunking.py`、`retrieval/tokenize.py`） |
| 未读私有件 | 真实 H2 题面/标签/答案/密文/key/`.env`/保管会话/runbook **均未打开**；未写任何含题面值/目标值的临时明文 |

另跑了一次**只读回归子集**确认「新增兄弟目录」没有触发 v2 语料的断言：`backend/tests/acceptance/test_corpus.py -k "fixture_count or manifest_hashes or manifest_sources or d01_sheets"` → **4 passed / 23 deselected**（含「`fixtures/acceptance` 根目录无多余文件」「manifest 哈希与真实文件一致」「sources 指向真实位置」「D01 表头与首记录」）。未跑全量测试套件：本轮不涉及产品代码/测试改动。

## 9. 零调用（`evidence/09-zero-call.json` → `ZERO_EXTERNAL_CALLS`）

守卫（`evidence/netguard/`，`PYTHONPATH` + `sitecustomize` 进程级注入）拦 `socket.connect/connect_ex/create_connection/getaddrinfo`、`http.client` 与 `httpx` 传输层；回环放行。

- 9 次运行（正对照、生成器、02、03、04、05、06、08、07）守卫均落盘；**业务进程外部连接尝试 0**；
- 正对照：外部 `connect` 与外部 DNS **都被拦**（证明「0」不是「没装守卫」）；
- 全部脚本 `exit_code == 0`（唯一非 0 是 `04` 的 `exit=1`，它按设计在 `result != aligned` 时失败退出，属结论而非故障）。

## 10. 与规格的偏差 / 观察（逐条，供复核）

1. **不动的工作表实际是 8 张**（4 个 `备用物料表` + 4 个 `旧草稿`），规格 §7 写 6 张（4 + 2）。实测 4 个 D01 族工作簿各带 2 张非目标表（`D02`/`V06` 只有 `店家信息` 一张表）。manifest 记 8。
2. `manifest.json` **`questions_file` 设为 `null`**：语料根只放 12 源 + manifest（规格 §1.1），H2 题面属私有件不落盘；v2 的 `questions.json` 是另一套 64 题公共集，未复制。
3. `b0_initialization` 与 `boundary` 两块**未收入** v3 manifest（规格 §4.4 允许删除）：前者引用未复制的 D07–D10，后者是单文件边界样本集。`font` 块逐值沿用 v2（构建事实），`font-license/OFL.txt` 按 §1.1 未复制。
4. **L1 存在一处计数不一致（只读观察）**：`coverage_selfcheck.totals.records_rows = 2`，而 `records[]` 实为 **4** 行（r3 追加 P02/P08 后未同步）。L1 是设计事实，本角色不改，交回上游处置。
5. **`p2_holdout_scenarios.py:287` 的路径前缀校验会拒绝 v3 ingest plan（只读观察，未验证运行）**：`_require(path.is_relative_to((ROOT / 'fixtures/acceptance').resolve()) ...)`。v3 plan 的 `path` 指向 `fixtures/acceptance-h2v3/`，与「零改码」直接冲突；需在生成 plan 前裁定。
6. 生成器把 xlsx 统一重打包为 `ZIP_STORED`（体积变大、字节可复现），见 §5.1。

## 11. 事件记录（如实）

收尾阶段把整条流水线重跑时，`00-snapshot-before.py` 把真正的「开工前快照」覆盖成了「现在」。已做三件事：① 给 `00` 加「文件已存在即拒绝」的幂等保护；② 用 `00a-restore-baseline.py` 做**减法重建**（当前实测 − 本轮新增的 2 个顶层 untracked 条目，条数 224−2 = 222，与开工记录一致），重建依据写进 `00-snapshot-before.json` 的 `capture_note`/`reconstruction`；③ `07-preservation.json` 在重建后的基线上重跑，仍为 `PRESERVED`（`new_untracked = 2`）。受影响字段只有 untracked 列表，其余不变量均为收尾实测且等于开工值。

## 12. 残余与下一步（需要裁定，本角色不自行处置）

1. **V05/V06 表头误判**（§7.1）：选「改产品解析器」还是「改规格 §1.4」，决定 7 条 target 是否可对齐；在此之前 runs 2/3 的 6 道题（C09/C10/C15/C20/C29/C30）不可判。
2. **v3 ingest plan 路径校验**（§10.5）：`p2_holdout_scenarios.py` 的 `fixtures/acceptance` 前缀限制需裁定（新 loader 分支 / 新 schema / 或接受改码验收）。
3. **L1 `records_rows` 计数**（§10.4）：需上游确认是笔误还是另有口径。
4. 本报告不含任何题面/答案/目标值/密文；`evidence/` 下全部为公开件与本地复算结果，可随评审流转。

## 13. 复算入口（第三方照此可独立重跑）

```powershell
Set-Location -LiteralPath 'D:\GPT项目\市场部AI知识库'
$ev = 'docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\v3-corpus\evidence'
.\.venv\Scripts\python.exe -B "$ev\02-verify-cells.py"         # 逐格：原列投影矩阵，差异必须 0
.\.venv\Scripts\python.exe -B "$ev\03-reproduce-twice.py"      # 生成器双跑 + 与交付件比字节
.\.venv\Scripts\python.exe -B "$ev\04-keyspace-proof.py"       # keyspace：当前 29/36（exit 1 属预期）
.\.venv\Scripts\python.exe -B "$ev\05-normalized-digest.py"    # 规范化摘要（双人重算判据）
.\.venv\Scripts\python.exe -B "$ev\07-preservation.py"         # 保全核对
.\.venv\Scripts\python.exe -B "$ev\09-zero-call.py"            # 零调用 + 正对照
```

`00-snapshot-before.py` 只能采一次（已存在即拒绝）；重建用 `00a-restore-baseline.py`。
