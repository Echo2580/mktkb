# C1-P4 全新独立验收报告（消费侧适配 v2：合同 v2 + 运行期身份快照 v0.3）

- 角色：C1-P4 **全新独立验收**（非开发、非经理）；不参与实现、不代签 GO、不改开发文件、不改冻结件。
- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存区 **0**；commit **0**。
- 被验收对象：
  - `backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py`（2262 行）
  - `backend/tests/evaluation/test_p2_evidence_axes_adapter_v2.py`（43 项）
  - `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/**`（开发报告与证据）
- 独立方法：**不采信开发自报数字**。自建合成 v2 合同 / v0.3 快照构建器（`independent/synth.py`），
  自建 9 支探针（`probe_01..09`）与零出站守卫（`independent/netguard.py`）；
  全部数字由本目录 `independent/out/*.json` 重算。共 **312 条探针断言**，其中 **4 条失败**，
  同一缺陷的 4 个观察面（见 §5.2 / IR-01）。
- 未读真实 H2 题面/标签/答案/私有密文/key/`.env`/保管会话；未打开任何仓外合同密文。

## 0. 结论

> **`PASS_WITH_DISAGREEMENTS`**
>
> - **两条经理红线的实质均未被越过**：document 粒度目标与携带 doc/unit uuid 的运行期键**不会**产出 violation
>   （3 类自建反例全部 `unknown`、violation=0）；class C（`not_observed` + `candidates=[]`）在 6 种形状下
>   **一律** `empty_set_not_proven`，P3 的 `empty_set_candidate=true` 不足以 proven。
> - **版本分派成立**：v1 合同被固定码拒绝；v2 合同（6 顶层键）被旧 v1 消费者以 `contract_schema_invalid` 拒绝；
>   但 **schema sha 只是“声明字符串 ↔ 常量”的标签钉扎，不是内容钉扎**（改载荷一个字节仍通过，IR-05）。
> - **键空间规则确定性成立、无前缀/包含/模糊匹配残留**；R-ENT-1 复算与合同规则源 9/9 逐值一致；
>   但存在 **target 顺序依赖**（假 unknown，IR-02）与 **自相矛盾行可被判 pass**（假 pass，IR-03）。
> - **fail-closed 在非标量枚举值上崩塌**：11 条路径以 `TypeError` 逃出 `determine_case`，
>   与模块自述“不抛裸异常”矛盾（IR-01，medium）。其余 fail-closed 类别（缺合同/缺轴/缺快照字段/
>   身份不可解析/未知键/unknown→N/A）**全数固定码 + unknown**。
> - 冻结与保全 **12/12、15/15、38/38、2/2**，2086 个外来 untracked 基线 **0 改动 / 0 缺失**（34 个敏感名文件按边界跳过）；
>   暂存 0、commit 0、HEAD/分支不变。零调用正负对照成立；43 项测试 0 skip/xfail，66 处固定码断言全部为等值比较。
>
> **不得据此声称**：T207 通过、质量放行、release/threshold、C1-2 授权、分数提升。
> **若经理把“fail-closed 必须全量”作为硬门**，则本包在“fail-closed”单项上应记为 **FAIL**；
> 我按“红线 + 核心判据”给出 `PASS_WITH_DISAGREEMENTS`，并把该分歧与修复建议写在 §5.2、§9。

## 1. 逐项结果

| # | 必测项 | 结果 | 关键实测（可复算） |
|---|---|---|---|
| 1 | 版本分派与 schema sha 钉扎 | **PASS（有分歧）** | 27 条断言 0 失败。v1 最小/完整载荷 → `contract_version_v1_rejected_by_v2_adapter`；v2（6 键）→ 旧 v1 消费者 `contract_schema_invalid`；`schema_version` 未知 → `contract_version_unsupported`。**声明摘要改 1 个 hex → 立即拒绝；载荷改 1 字节（目标键值）→ 照收**（IR-05）。v1/v2 常量与公开 schema 文件字节 **逐值一致**（`cb1257fa…` / `b98f9f4a…`）。 |
| 2 | M-C1P1-01（document 级目标不得判 violation） | **PASS（有分歧）** | 41 条断言 0 失败；**3 类自建反例**（document\|uuid 目标、运行期键含 doc/unit uuid、运行期文档粒度行）**全部 unknown、violation=0**。唯一 violation 通道要求 `document` 型目标带**语料 doc_code 形键**且运行期有另一文档的记录级行（合同 §4.3 产不出这种目标，IR-08）。 |
| 3 | M-C1P2-01（class C 不得 proven） | **PASS** | 23 条断言 0 失败。class C 的 6 种形状（标准/候选层观测/截断/非空候选/使用层未观测/回合未完成）**没有任何一轴**落 passed 或 N/A；真空集（9 层观测 + 检索观测且空候选、未截断）才 pass。P3 布尔自相矛盾载荷被结构拒绝。 |
| 4 | 键空间规则可执行性 | **PASS（有分歧）** | 41 条断言 0 失败。静态：0 个模糊库、1 处 `startswith`（仅 document 分类）、7 处键比较全为精确等值/集合成员；运行时：11 个形状矩阵、3× 重复完全一致、前缀相似键不匹配。R-ENT-1 复算 **9/9**、归一化 **5/5** 与 `chunking._entity` 一致。**顺序依赖**（同键两条 target 顺序不同 → unknown vs passed，IR-02）、**矛盾键/过滤器可 pass**（IR-03）。 |
| 5 | fail-closed（固定码 + unknown） | **PASS（有缺陷，建议硬条件）** | 93 条断言，**4 条失败**：66 条结构化反例全数命中期望码；51 个 unknown 码逐码验证 `unknown→N/A` 必被 `unknown_to_not_applicable_forbidden` 拦；800 次确定性变异中 **626 次被固定码拒绝**（合同 317 + 快照 309）、**164 次改的是模块声明不消费的块**（合同 74 + 快照 90）；**10 次裸 `TypeError` 逃逸（11 个站点，IR-01）**。 |
| 6 | 计数自洽 / basis / 输出边界 | **PASS** | 33 条断言 0 失败。4 题样例：`planned 4 / checked 3 / passed 1 / NA 1 / unknown 1 / violations 1`，三条公式逐条成立（`verify()` 强制）。4 个 basis 变体状态/原因逐值不变、只 provenance 变。输出无 verified/threshold/release **字段与结论值**；合同 `axis_codes` 不进输出；provenance 无 uuid/记录键/日期值。 |
| 7 | 冻结与保全 | **PASS** | 27 条断言 0 失败。C 冻结 **12/12** 逐字节不变；15 tracked modified **15/15**；Q1a-1 保护 **38/38**；R2 **28**（24 校验一致 + 4 敏感名跳过）；P3 模块与契约 **2/2** 与 P3 轮记录值一致；合同 v2 三件公开产物 **3/3** 与 P1 接收值一致；外来 untracked **2086**（2052 一致 + 34 敏感名跳过，0 改动 / 0 缺失）。暂存 0、commit **172 不变**、HEAD/分支不变。 |
| 8 | 零调用（正负对照） | **PASS** | 13 条断言 0 失败。干净段（合同加载 + 3 类判定）`external=0`；正对照 **7 层**（socket connect/connect_ex/create_connection/getaddrinfo/gethostbyname、http.client、httpx 传输层）**全部被拦并逐笔记账**；**不清账 `assert_clean()` 必报错**，清账后通过；43 项测试进程内 `external=0`。 |
| 9 | 测试质量 | **PASS（覆盖残余）** | 14 条断言 0 失败。独立执行 **43 passed / 0 failed / 0 skipped**（`out/09-pytest.txt`，仓外 basetemp、`-p no:cacheprovider`）；0 skip/xfail marker、0 恒真断言、0 monkeypatch 被测模块；**133 条 assert**，**66 处固定码字面量全部位于 `==/!=` 比较**（0 处仅 `in FIXED_CODES` 的弱断言），**66/66 都是真实固定码**；覆盖 **44/58** 码族（14 个未被开发测试断言，见 IR-10）。 |

## 2. 版本分派与 schema sha 钉扎（要求 1）

### 2.1 v1 必被拒 / v2 不得被裸 v1 常量收下

| 实验 | 结果 |
|---|---|
| v1 最小载荷 `{schema_version: .../v1}` → v2 适配器 | `contract_version_v1_rejected_by_v2_adapter` |
| v1 完整 5 键载荷 → v2 适配器 | 同上（版本判定先于结构校验，`:641`） |
| 未知版本（`/v3`） | `contract_version_unsupported` |
| 真实 v2 载荷（6 顶层键）→ 旧 v1 消费者 `load_q1a2_contract_view` | `contract_schema_invalid`（`p2_evidence_rescore_axes.py:3094-3102`） |
| v2 去掉 `projection`（5 键）但保留 v2 版本 → v1 消费者 | `contract_schema_invalid`（版本字符串不等） |
| **v2 去掉 `projection` 并把版本改回 v1 → v1 消费者** | **ACCEPTED**（旧消费者只钉“版本字符串 + 5 键集”，不钉 `contract_schema_sha256`）→ **IR-06** |
| 同一“改名载荷” → v2 适配器 | 仍 `contract_version_v1_rejected_by_v2_adapter` |

**结论**：合同 §12.1 的“v2 会被 v1 常量拒绝”对**未改动的 v2 载荷**成立；对“删 projection + 改名”的
冒充载荷，**冻结的 v1 消费者无法识别**（它没有 schema sha 钉扎）。这不是 P4 引入的，P4 自己也拒绝该载荷，
但 C1-2 若走旧 v1 路径则存在该口子，必须由经理知悉（IR-06，跨包）。

### 2.2 schema sha 是否“改一个字节应拒”

实测三种“改一个字节”：

| 改动位置 | 结果 | 说明 |
|---|---|---|
| 载荷里 `contract_schema_sha256` 改 1 个 hex | **拒绝** `contract_schema_binding_mismatch` | 钉的是“声明值 == 常量” |
| 载荷里任意**其它**字段改 1 字节（目标键 `item|storea|itema` → `item|storea|itemB`） | **通过**，且判定随之改变 | 模块没有载荷内容摘要 |
| 公开 schema 文件改 1 字节 | **无消费者反应** | 模块 AST 中 **0 个文件读取调用**、**0 处引用 `docs/evaluation`** |

另外：调用方显式传 `expected_schema_sha256="0"*64` 且载荷声明同值 → **通过**（`_load_bindings:493-500`）。
即默认严格（只认 b98f9f4a…），但**调用方可自行放宽**。

**裁决**：`contract_schema_sha256` 是**版本标签钉扎**，不是内容钉扎。真实内容完整性依赖合同 §11 第 1 步
（密文 SHA256）与保管侧解密校验，不在本模块职责内；但开发报告称“双保险”**夸大了**本模块的能力（IR-05）。

## 3. 两条经理红线

### 3.1 M-C1P1-01：document 级目标不得判 violation

自建 3 类反例（`probe_02`，41 条断言 0 失败）：

| 类 | 形状 | 实测 |
|---|---|---|
| **A** | 目标只有 `document\|<uuid>`；运行期分别为文本行 / 记录级 item 行 | `unknown` / `target_granularity_incomparable` / violation=0（A、A2） |
| **B** | 目标可匹配；运行期 `entity_key` 携带 `doc:<uuid>` + `unit:<uuid>` | `unknown` / `target_granularity_incomparable`；`record_key_spaces={"document":1}`；violation=0 |
| **B2** | 键看起来干净，但 `entity_filters.store` 是 uuid | `unknown` / `identity_unresolved`；violation=0 |
| **C** | 可匹配目标 + 运行期出现 `entity_type=document` 行（单独 / 与命中行并存） | 均 `unknown` / `target_granularity_incomparable`；**命中行不会把整轴抬成 pass** |
| **D** | 目标自身携带运行期 id（`entity_type=item`、键 `document\|<uuid>`） | `unknown` / `entity_key_space_incompatible`；violation=0 |

**唯一 violation 通道**（`probe_02` E/E3）：`entity_type="document"` + **语料 doc_code 形键**（如 `S01`）+ 空 filters，
且运行期存在**另一文档**的记录级行 → `other_entity_used`。同文档记录 → **passed**。
该通道有两个前提：
1. 目标必须由合同 §4.3 R-ENT-1 产出——而 R-ENT-1 的 document 分支固定产出 `document|doc_id`（运行期 uuid），
   **产不出 doc_code 形键**（合同 §4.4 自己写明 document 不可投影）。因此该通道在真实合同数据上**不可达**；
2. 它把 document 型目标按 doc_code 级身份比较，**符合**经理裁决的“要么保持 unknown，要么改用 doc_code 级身份”，
   但**与开发报告 §8.7 的“不要把它当成 document 目标可通过的通道”自相矛盾**：实测同文档记录**就是** pass。

**裁决**：红线**实质成立**——合同数据域内 document 粒度目标/身份**绝不产 violation**。
保留分歧：doc_code 通道在合同数据域内不可达，一旦未来合同新增 doc_code 型 document 目标，
它会同时产生 **pass** 与 **violation** 两条文档级判定路径，语义未经经理批准（IR-08，low）。

`criterion=no_entity_claim` 另有护栏：合同声明 N/A 但运行期出现任何实体身份 → `unknown` / `entity_scope_conflict`，
不会被静默判 N/A（实测）。

### 3.2 M-C1P2-01：class C 必须保持 unknown

`probe_03` 23 条断言 0 失败。6 种形状：

| 形状 | cross_entity | stale_source |
|---|---|---|
| class C：9 层 observed+计数 0、`empty_set_candidate=true`、`retrieval_observed.observed=false`、`candidates=[]` | `unknown` / `empty_set_not_proven` | `unknown` / `empty_set_not_proven` |
| class C + query/projection 候选均“观测且空” | 同上 | 同上 |
| 检索观测但候选被截断（`truncated=true`） | 同上（audit `retrieval_candidates_truncated`） | 同上 |
| 检索观测到非空候选 | 同上 | 同上 |
| 使用层 `entity_inheritance` 未观测 | 同上 | 同上 |
| 回合 `partial` | 同上 | 同上 |
| **真空集**（9 层观测+0、检索观测且空、未截断、回合完成） | **passed** / `cross_entity_empty_use_scope_ok` | **passed** / `stale_source_dates_ok` |

证明函数（`:1354-1377`）**不读** `empty_set_candidate` / `all_use_layers_observed`，而是逐层读
`use_layers[*].observed/count` + `retrieval_observed.observed/count/refs/truncated`；
P3 的两个派生布尔只用于结构自洽校验（`empty_set_candidate` 与 `all_observed & total==0` 不符 → 整份快照 `snapshot_field_invalid`）。
**结论**：M-C1P2-01 落实。

## 4. 键空间规则的可执行性判断（必给节）

### 4.1 规则形态（实现事实）

`_match_entity_row`（`:1468-1499`）是三步：

1. 同 `(entity_type, entity_key)` 且 `target.filters ⊆ runtime.entity_filters` → **matched**；
   同键但 filters 矛盾 → **立即** `incompatible/identity_unresolved`；
2. 目标键本身是 canonical 名称型时，用运行期**角色值**复算 canonical key，逐值相等且 filters 满足 → **matched**
   （audit `key_space_aligned_by_role_filters`）；
3. 只有“运行期键可复算为 canonical（corpus_name）且全部可匹配目标也是 corpus_name”才允许 `mismatch`（violation 候选）；
   其余 → `incompatible/entity_key_space_incompatible`（unknown）。

### 4.2 确定性与“无前缀/包含/模糊”

- **确定性**：11 个形状 × 3 次重复，`(state, reason)` 逐次相同；无随机/时间/字典序依赖（`probe_04`）。
- **前缀/包含**：AST 全量扫描 `entity_key` 相关行——1 处 `startswith("document|")` 仅做**分类**；
  7 处键比较全部是 `==`/`!=` 或**集合成员**（`target.entity_key in known_doc_codes` 等）；0 个 `fnmatch/difflib/rapidfuzz/Levenshtein`。
- **运行时探针**：目标 `item|storea|itema` vs 运行期 `item|storea|itema|x`（filters 不指向目标）→ `unknown/entity_key_space_incompatible`；
  前缀相似键**不会**被判 matched。
- **归一化保真**：对合同规则源 `chunking._entity` 做逐例差分，**9/9** 非 document 分支的
  canonical key 与复算值逐字符相等（含 `product|奶茶|none|none` 这类缺 channel 的退化形状）；
  大小写/首尾空白/全角/中文括号 **5/5** 一致。**规则实现是 R-ENT-1 的忠实复刻**，不是另一套归一化。

### 4.3 真实数据上是否可执行

**可执行的部分**：P3 公开 fixture（`c1-1/p3/independent/out/08b-public-fixture-entity-shape.json`，公开 D01）
实测运行期 `entity_key="item|id:p01"`、`entity_filters={"item":"宣传海报","item_id":"P01","store":"城东店"}`。
适配器用角色值复算得到 `item|城东店|宣传海报`——正是 R-ENT-1 在语料侧产出名称型键的形状。
因此 **item/store 型目标（P1 报告 v2 新增的 16 条）在对齐规则下可执行**，且**不需要**解释 id 型键；
`item_id` 这类非角色键会被忽略，不造成噪音。

**不可执行/高风险的部分**：
- `record` 型目标（`record|norm(identifier)`）要求运行期 filters 带 `identifier` 角色值；公开 fixture 只有 `item_id`。
  实测 `record` 目标 + `{item_id}` filters → `unknown/identity_unresolved`（`probe_04` 矩阵）。
  若 P3 的真实采集同样不给 `identifier`，**所有 record 型目标系统性不可对齐**（IR-04，跨包）。
- `product` 型目标在合同 §3.4 下**不是可匹配目标**（`MATCHABLE_ENTITY_TYPES = item/store/record`），
  实测 `unknown/targets_unresolved`——不是缺陷，但会消耗“看起来有目标”的轴。

### 4.4 我最担心的失败模式（按严重度）

1. **系统性 unknown 被读成“干净”**。角色值缺失（文档/段落单元、只有 id 表头、产品侧表头同义词漂移）时，
   每一行都落 `entity_key_space_incompatible`，轴是 unknown，**violation 计数为 0**。
   报告若只看“0 violations”，会把“没判”当“没问题”。**缓解**：任何“0 violations”结论必须同时给
   `reason_histogram(determinations, "cross_entity")` 的完整直方图。
2. **一行坏数据翻转整轴**。判定顺序是 `violations` 先于 `unknowns`（`:1804-1829`）：
   一条按名称空间逐值失配的记录级行 → 整轴 `other_entity_used`，即使其余行都不可对齐。
   而名称空间只做 NFKC+大小写+空白折叠，**不统一标点/后缀**（如“折叠凳-蓝” vs “折叠凳（蓝）”）——
   这正是“粗粒度匹配造成假阳性”的旧病新装。**缓解**：violation 必须带 audit 行与 `target_codes` 逐条复核，
   且 C1-2 报告必须把 violation 与 unknown 分列，不得只报净分。
3. **顺序依赖静默吃掉 pass**。同一 `(type, key)` 的两条 target，若“更严 filters”的那条排在前面，
   函数在第一条就返回 `identity_unresolved`，后面本可匹配的 target 永远到不了（IR-02）。
   v2 的 R-T-5 会在 v1 目标之后**追加**同键的干净目标；若 v1 目标本身是 matchable（role-only filters）且更严，
   追加目标就永远失效——这会直接压低 C1-2 的 pass 数。
4. **自相矛盾行被规则②“救活”**。运行期 `entity_key` 指向 A、`filters` 指向 B 时，规则②按 filters 复算并判 pass（IR-03）。
   干净数据不会出现，但**坏快照会**；它是假通过，比假 unknown 更危险。

## 5. fail-closed：覆盖与缺陷

### 5.1 已成立的部分

- **66 条结构化反例**逐条固定码：合同结构/轴/target/basis/projection/runs/case 数与重复 id、未知顶层键、
  绑定缺键与 dataset_version、快照缺字段/未知键/类型/枚举/fixture 绑定/跨 run/跨场景/跨回合/来源不完整/重放/
  公开边界/摘要不符/记录级与 locator 矛盾/使用层缺层与计数不符/候选层计数不符/时间字段矛盾/版本行矛盾。
- **51 个 unknown 码逐码验证**：任何 unknown reason 配 `not_applicable` → `unknown_to_not_applicable_forbidden`；
  只有 `cross_entity + not_applicable + no_entity_claim + no_entity_scope_verified` 放行。
- **800 次确定性变异**（400 合同 + 400 快照）：**0 条**产生未知固定码。被接受的 164 次变异全部落在模块
  **声明不消费**的块（`turn_ref`/`runtime_identity`/`projection` 语义子结构），与开发报告 §3.1 的口径一致。
- 静态：`getattr`/`hasattr` **0**、裸 `except` **0**、`pass` **0**、`.get(默认值)` **1 处**且只用于
  `projection["target_provenance"].get(key, [])`（不影响 verdict）。

### 5.2 缺陷 IR-01（medium）：非标量枚举值 → `TypeError` 逃出

`determine_case` 只捕 `AdapterError`（`:2093-2123`）；而多处枚举校验是 `value in frozenset`，
遇到 JSON 数组/对象（不可哈希）即抛 `TypeError`。**11 个站点全部实测复现**（`out/05-failclosed.json#non_scalar_enum_sites`）：

| 侧 | 路径 | 抛点 |
|---|---|---|
| 合同 | `cases[i].axes.*.criterion` | `_load_axis:568`（`criterion in Q1A2_AXIS_CRITERIA[...]`） |
| 合同 | `cases[i].axes.*.reason` | `_load_axis:569`（`reason in ANNOTATION_REASONS`） |
| 合同 | `cases[i].basis.*` | `load_contract_v2:672`（`value in Q1A2_BASIS_CODES`） |
| 快照 | `effective_temporal.availability` | `_load_temporal:936` |
| 快照 | `effective_temporal.as_of_source` | `:940` |
| 快照 | `effective_temporal.observed_from` | `:942` |
| 快照 | `effective_temporal.code` | `:949` |
| 快照 | `effective_temporal.document_versions[i].code` | `:977` |
| 快照 | `empty_use_scope_input.code` | `_load_empty_use:1080` |
| 快照 | `empty_use_scope_input.turn_status` | `:1092` |
| 快照 | `source_evidence.completeness_status` | `load_snapshot_v03:1159` |

对照：**同一字段给 hashable 的错值**（`criterion="bogus"`、`availability="bogus"`）→ 正常固定码
（`contract_axis_invalid` / `snapshot_enum_invalid`）。所以不是“未知键不拒”，而是**类型面漏了一条**。
影响：一份被篡改/损坏的合同或快照会让整次判定抛 `TypeError`（调用方未捕获则整轮 rescor 死掉），
与模块 docstring“不抛裸异常”、开发报告“所有错误收敛为固定码”**直接矛盾**。
修复成本极低：成员判断前加 `isinstance(value, str)`（或 `determine_case` 额外捕 `TypeError` → `*_invalid:<path>`）。

### 5.3 其他 fail-closed 边界（已被开发报告声明为“只校验被消费块”，我确认一致）

`projection` 的内部语义（lineage/entity_rule/coverage）、`runtime_identity`、`request_owner` 的内部枚举、
`turn_ref` 的额外字段只做存在性/类型检查；一次变异到这些位置会被接受。这不改变 verdict，因为判定不读它们；
但它们进入 `provenance` 的只有固定几项——**复核方不应把“快照被接受”理解为“快照全字段合法”**（残余，非缺陷）。

## 6. 计数、basis 与输出边界（要求 6）

- **三公式**：`planned == passed + NA + unknown + violations`、`checked == passed + NA + violations`、
  `planned == checked + unknown`；`AxisCounts.verify()` 强制，冲突 → `axis_counts_inconsistent`（实测）。
  4 题样例：cross_entity `4/3/1/1/1/1`，stale_source `4/0/0/0/4/0`（本题组无 stale 正例）。
- **`basis` 不进 verdict**：4 个合法 basis 变体（frozen_label_target / public_corpus_structure /
  frozen_question_scope / case_business_date_baseline）→ 状态与原因**逐值不变**，只有 `provenance.basis` 变。
- **输出边界**：`CaseDetermination.as_dict()` 键集恰 6；轴对象键集恰 7；无 `verified`/`threshold`/`release`
  字段或结论值；合同 `projection.axis_codes`（含 `record_code_verified`）**不进输出**；
  `target_provenance` 进输出且必须是固定码形态。
  残余：固定码 `no_entity_scope_verified` 含 “verified” 子串——是 v1 词汇，不是结论字段（IR-11，low）。
- **provenance 不泄露运行期身份**：无 uuid、无记录键值（`W01`）、无日期值（`2026-10-28`）、无题面文本。

## 7. 冻结、保全、零调用、测试质量

### 7.1 冻结与保全（27 条断言 0 失败）

| 组 | 结果 |
|---|---|
| C 冻结 12（`axes/evidence/04-protected-hashes-before.json`） | **12/12** 逐字节一致 |
| 15 tracked modified | **15/15** 一致（路径与 SHA 均不变） |
| Q1a-1 保护 38 | **38/38** 一致 |
| R2 保护 28 | 24 校验一致 + **4 敏感名跳过**（custody/holdout 私有件，本会话不读） |
| readonly references 2 | **2/2 跳过**（custody 注释文档，按边界不读） |
| P3 模块 + 契约 | **2/2** 等于 P3 轮记录值 `63ca7ecf…` / `67f6d534…` |
| 合同 v2 schema / aggregate / report | **3/3** 等于 P1 接收值 `b98f9f4a…` / `745f9c71…` / `ce9116c3…` |
| 外来 untracked（R2 基线 2086） | **2052 一致 + 34 敏感名跳过；0 改动 / 0 缺失** |
| git | 分支 `codex/p2-e2e`、HEAD 不变、暂存 **0**、commit **172**、status 229 行、tracked modified 15 |
| 新增 untracked | 218 个，全部落在允许前缀内（C1-1 交付物 / rescore 前轮 / 任务书 / 合同 v2），**0 个越界** |

### 7.2 零调用（13 条断言 0 失败）

- 干净段：合同加载 + 三类判定 → `external=0`。
- 正对照：7 层（`socket.connect` / `connect_ex` / `create_connection` / `getaddrinfo` / `gethostbyname` /
  `http.client.connect` / `httpx.HTTPTransport.handle_request`）**全部被拦并逐笔记账**。
- 负对照：账未清时 `assert_clean()` **必报错**；`clear()` 后通过；清账后再跑同一 workload 结果逐值相同。
- 环境注记：本机存在代理环境变量；守卫在 connect/getaddrinfo/httpx 三层拦截，httpx 显式 `trust_env=False`。

### 7.3 测试质量（14 条断言 0 失败）

- 独立执行：**43 passed / 0 failed / 0 skipped**，exit 0；仓外 basetemp、无缓存文件、仓内无 `__pycache__`/`.pytest_cache`。
- 静态：43 个 `test_*`、0 skip/xfail、0 恒真断言、0 monkeypatch 被测模块、133 条 assert、
  **66 个固定码字面量全部在 `==/!=` 比较中**、66/66 均为真实固定码、0 处 `in FIXED_CODES` 弱断言。
- 覆盖：开发测试断言到 **44/58** 码族；未断言的 14 个（`axis_not_adapted`、`citation_entity_mismatch`、
  `contract_binding_mismatch`、`contract_case_missing`、`contract_run_missing`、`entity_scope_conflict`、
  `snapshot_contract_version_invalid`、`snapshot_enum_invalid`、`snapshot_field_invalid`、
  `snapshot_fixture_kind_invalid`、`snapshot_missing`、`snapshot_schema_version_invalid`、
  `stale_no_positive_refs`、`targets_missing`）**全部由我的探针独立覆盖**（IR-10 仅指测试套件未强制覆盖）。

## 8. 对 C1-2 可判化上界的含义（不作收益承诺）

1. **stale_source 在真实数据上不会因 P4 变 pass**：非空使用集一律 `unknown` + `stale_lifecycle_evidence_missing`
   （快照 v0.3 无逐源 lifecycle）；唯一 pass 通道是“已证明的空使用集”，而 P3 builder 产不出该形状（P3 R-11）。
   因此 **C1-2 的 stale 轴预期 100% unknown**，P4 只把它从“不可判”变成“有理由的不可判”。
2. **cross_entity 的 pass/violation 依赖运行期角色值**：item/store 型目标在公开 fixture 形状下可执行；
   record 型可能系统性不可对齐（IR-04）。真实可判轴数必须用 `reason_histogram(determinations, "cross_entity")`
   的实跑计数回答，本包只能给规则与合成证据。
3. **不得把“0 violations”当作干净**（见 §4.4-1）。

## 9. 发现、分歧与残余

### 9.1 本次发现（按严重度）

| id | 级别 | 内容 | 归属/建议 |
|---|---|---|---|
| **IR-01** | **medium** | 非标量枚举值 → `TypeError` 逃出 `determine_case`，**11 个站点**（§5.2）。与“不抛裸异常”矛盾。 | P4 实现。建议作为 **M-C1P4-01 硬条件**：成员判断前 `isinstance(str)`，或 `determine_case` 增捕 `TypeError` → `*_field_invalid:<path>` + unknown。C1-2 前修复。 |
| **IR-02** | **medium** | `_match_entity_row` 同键 filters 不符时**立即返回** `identity_unresolved`，后面的同键 target 永远到不了 → **顺序依赖**（[严, 松] unknown / [松, 严] passed）。违反合同 §3.4(3)“任一条匹配即匹配”。只造成假 unknown，不造成假 violation。 | P4 实现。建议：同键循环继续而非提前返回；或按 filters 更宽者优先。 |
| **IR-03** | **medium** | 规则②按 `entity_filters` 复算 canonical key，**不校验** `entity_key` 与 filters 是否一致：键指向 StoreB/ItemB、filters 指向 StoreA/ItemA 的运行期行 → **pass**（`record_key_spaces={"opaque":1}`）。坏快照可产生假通过。 | P4 实现。建议：`entity_key` 不属于 {canonical(filters), id 型, document/ uuid 型} 时记 `entity_key_space_incompatible`。 |
| **IR-04** | medium | `record` 型目标需要运行期 `identifier` 角色值；公开 fixture 只有 `item_id`。实测 → `identity_unresolved`。若 P3 真实采集不给 `identifier`，record 目标系统性不可对齐。 | 跨包 P3/P4。需 P3 字段映射或合同侧归一规则；**不得**用前缀/包含硬凑。 |
| **IR-05** | medium | `contract_schema_sha256` 是声明字符串 ↔ 常量的标签钉扎；无载荷内容摘要、模块不读 schema 文件；调用方可自带 `expected_schema_sha256` 放宽。改载荷 1 字节仍通过。 | P4/合同消费口径。要么在 P4 加“载荷摘要绑定”（需合同先给载荷摘要），要么在文档/接收口径里**改写“双保险”表述**。 |
| **IR-06** | medium | 冻结 v1 消费者只钉版本字符串 + 5 键集，不钉 `contract_schema_sha256`：v2 去 `projection` 改名 v1 → **被接受**。 | 跨包（旧消费者，冻结不可改）。C1-2 若走旧路径需经理知悉；P4 自身拒绝该载荷。 |
| **IR-07** | low | `_target_view` 把“`entity_type=item` 但键是 `document\|<uuid>`”的目标标成 `matchable=True`/`granularity=record`；匹配阶段才被判 `runtime_id` 不可比。verdict 安全，但 provenance 的 `matchable_target_count` 会虚高。 | P4。建议在 `_target_view` 加键形态判定。 |
| **IR-08** | low | doc_code 降级通道在合同 §4.3 数据域内不可达；一旦可达到，会同时产生 document 型目标的 **pass**（同文档）与 **violation**（异文档）。开发报告 §8.7 的“不是可通过通道”与实测相反。 | P4/经理口径。若未来合同出 doc_code 目标，需单独验收。 |
| **IR-09** | low | 真空集 pass 路径依赖 P3 产不出的形状（P3 R-11）→ 真实数据上 stale 轴 100% unknown。 | 设计后果，非缺陷；影响 C1-2 收益预期。 |
| **IR-10** | low | 开发测试覆盖 44/58 码族；14 个码族无断言（列表见 §7.3）。无断言强制码族覆盖。 | 测试。建议补一个“码族覆盖清单”断言（像 P3 R-10 的建议）。 |
| **IR-11** | low | 输出固定码 `no_entity_scope_verified` 含 “verified” 子串；粗 grep 会命中，但无结论字段。 | 词汇遗留，记为上轮词表约束。 |
| **IR-12** | low | `determine_case(case_id=None)` 抛 `AdapterError`（`adapter_invariant_violation`）而非返回 unknown。调用方误用；固定码但以异常形式逃出。 | P4。可接受，建议 `case_id` 非 str 时直接 `_unknown_case(str(case_id))` 或拒参。 |
| **IR-13** | info | `.get(默认值)` 仅 1 处（projection 查找）；无 getattr/hasattr/裸 except/pass。 | 与开发报告一致。 |

### 9.2 与开发报告的分歧（保留，不表决）

1. **“schema sha 双保险”** → 实测是“标签双保险”，不是内容钉扎（IR-05）。
2. **“匹配顺序 ①→②→③”** → 未披露①的提前返回造成的顺序依赖（IR-02）。
3. **“唯一可比降级链路有正例”** → 该链路在合同数据域内不可达；且它对同文档记录**会判 pass**，
   与 §8.7“不要把它当成 document 目标可通过的通道”矛盾（IR-08）。
4. **“所有错误在 `determine_case` 收敛为两轴 unknown + 固定码，不抛裸异常”** → 非标量枚举下半句不成立（IR-01）。
5. **“反例矩阵 22 类 / 66 处固定码断言”** → 66 处**核实**且全为等值比较；22 类为开发自报口径，
   我的独立矩阵是 **66 条结构化反例**（不逐一对应其 22 类）。
6. **“键空间受影响 1/2”** → 合成探针口径成立；但真实受影响轴数仍未知，且存在 IR-02/IR-03 两个合成探针未覆盖的形状。

## 10. 边界声明

- 本验收**只读**被验收文件与冻结件；未改任何开发文件/冻结件/合同/旧卡/账本/GO；未 stage/commit/push；
  未新建 worktree/切分支。新增文件仅 `c1-1/p4/independent/**` 与本报告 + `review-aggregate.json`。
- 只使用**合成数据 + 仓库内公开契约文本 + 公开 fixture 形状证据**；未读真实 H2 题面/标签/答案/私有密文/key/
  `.env`/保管会话；未打开任何仓外私有路径。
- 仓外账本/预算/GO/30 题/标签/密文**未触碰**：我只能声明“本会话未打开”，不能声明其字节未变（不在可读范围）。
- 冻结/保全里 **4 个 R2 保护件 + 2 个 readonly 引用 + 34 个外来 untracked** 因命中 custody/`.fernet`/holdout-private
  命名模式被**跳过未读**，已在 `out/07-preservation.json` 逐个列出——这些条目的“未变”**不由本会话证明**。
- 零真实调用：干净段 `external=0`；正对照 7 层全拦并记账；负对照不清账必报错。

## 11. 证据索引（`c1-1/p4/independent/`）

| 文件 | 内容 |
|---|---|
| `synth.py` | 自建 v2 合同 / v0.3 快照构建器（不依赖开发 fixture） |
| `harness.py` / `netguard.py` | 记录器 / 自建零出站守卫 |
| `probe_01_version_dispatch.py` → `out/01-version-dispatch.json` | 27 检查：版本分派 + schema 钉扎 + 文件常量 |
| `probe_02_redline_document.py` → `out/02-redline-document.json` | 41 检查：M-C1P1-01 三类反例 + doc_code 通道 |
| `probe_03_class_c.py` → `out/03-class-c.json` | 23 检查：M-C1P2-01 六形状 + 真空集 |
| `probe_04_key_space.py` → `out/04-key-space.json` | 41 检查：静态扫描 + 矩阵 + 确定性 + R-ENT-1 差分 |
| `probe_05_failclosed.py` → `out/05-failclosed.json` | 93 检查：66 反例 + 全码 N/A 门 + 800 变异 + 11 崩溃站点 |
| `probe_06_counts_output.py` → `out/06-counts-and-output.json` | 33 检查：三公式 / basis / 输出边界 |
| `probe_07_preservation.py` → `out/07-preservation.json` | 27 检查：冻结/保全/git/新增前缀 |
| `probe_08_zero_call.py` → `out/08-zero-call.json` | 13 检查：零调用正负对照 |
| `probe_09_tests.py` → `out/09-test-quality.json`、`out/09-pytest.txt` | 14 检查：43 项执行 + AST 质量 |
| `README.md` | 运行方式与边界 |
