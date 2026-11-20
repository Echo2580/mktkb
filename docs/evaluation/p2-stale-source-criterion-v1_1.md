# `stale_source` 判据 v1.1：版本态优先、日期可选（`p2-stale-source-criterion/v1.1`）

- 状态：**已冻结为公开规范 v1.1 的文本**（2026-11-15 同版本澄清：新增 §3.4，区间语义与 21 码表不变）。**未生效**：它是一次**评分口径变更**（C1-1 回执 §5 选项 B），生效前置为「主人批准 + 独立验收」；本文件本身**不构成**执行授权、GO、阈值或发布批准。
- 角色：判据规范作者（普通角色；非验收、非经理、非保管）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0 项，0 commit。
- 上游裁定：经理 2026-11-15 两条裁定——**裁定 1**（本文件：区间语义统一为闭区间，升版 v1.1）、**裁定 2**（`as_of` 从逐题下发改为每 run 一个 `business_date`，落在出题计划侧，不改本判据）。
- 同版本澄清（2026-11-15）：**§3.4 裁定 v3 窗口唯一真相源 = 数据集 L1**；判据不内嵌 windows、不另存第二份窗口表。不升 v1.2，不改区间语义、不改 21 码表。
- 前版：`docs/evaluation/p2-stale-source-criterion-v1.md`（`p2-stale-source-criterion/v1`，SHA-256 `c34d08af3bc27f0f6d69bad200ce77c6db229622a204d5df1ebf7b010eaa9c7`）。**原 v1 文件原样保留为历史，本文件不改它一个字节。**
- 硬边界：本文件**只**冻结判据；零真实调用；未读真实 H2 题面/标签/答案/目标值/私有密文/key/`.env`/保管会话/runbook；未改任何 tracked 文件，v1 原文件未改；本次只对本文件做 §3.4 同版本澄清；未 stage/commit/push；未新建 worktree/切分支。
- 内容边界：本文件只含 schema、规则、枚举、固定码与**全虚构的合成示例**；不含题号、题面、答案、目标值、逐题派生表。

> ### 本升版的改动（必须逐字读）
>
> **相对 v1 的唯一语义改动仍是 `date_window` 区间开闭；`version_state` 模式与全部固定码不变。** v1.1 文本内另有一节**同版本澄清**（§3.4：SC-2 单一真相源 = 数据集 L1），它不改区间语义、不改 21 码表、不改变任何 verdict 路径。
>
> 具体地说：`date_window` 的覆盖判据从**左闭右开** `[effective_from, effective_to)` 改为**闭区间** `[effective_from, effective_to]`。
> **`as_of == effective_to` 仍有效**；**`as_of == effective_from` 有效**；`as_of == effective_to + 1 天` 过期；`as_of == effective_from - 1 天` 未生效。
> 除此之外 v1 的全部要点原样保留：两模式、21 个 determination 码（9 新 + 12 沿用）、14 个保留不产出码、18 码 annotation reason 表分层、四路冒充（X-1..X-4）、F-1..F-12、四状态与四条防误读。
>
> 因 2026-11-14 重算（`Q1A-RESCORE-20261114-r3`）使用 `version_state` 模式，本升版（含 §3.4 澄清）不影响其 11/30、0 硬失败、19 不可判的任何数值。

> **本判据不改变 30 题 / 标签 / 阈值 / 四状态 / 评分标准。** 它只改 `stale_source` 单轴"凭什么算通过"。
> **任何用本判据算出的数字与被替换的实现、与旧 19/30 均不可比**（见 §11）。

---

## 0. 一句话

`stale_source` 的判定对象从「**源侧日历区间 vs `as_of`**」改为「**产品实际使用的源身份 vs 该 case 所属 scenario 的 active 源身份**」。

日期不再是被比较的**主证据**，而是两种 grounding 模式之一（`date_window`）的全部依据，或在 `version_state` 模式下**可选的单向加严项**（只可能把 `passed` 抬成 `violation`，永不可能把 `violation`/`unknown` 抬成 `passed`）。

两种模式对"窗口是否覆盖 `as_of`"只允许**一种**读法：**闭区间**（§3.2 规则 2）。这是 v1.1 相对 v1 的唯一语义改动。

---

## 1. 为什么必须换口径（事实基础，非偏好）

### 1.1 旧口径在公开件范围内结构性不可判

`c1-1/p6/lifecycle-feasibility.md` 的实测结论（12/12）：

| 口径 | 计数 |
|---|---:|
| 能定出完整窗口（`published_at` + `effective_from` + `effective_to`） | **0 / 12** |
| 只能定出一端 | **0 / 12** |
| 无任何生命周期端点 | **12 / 12** |
| 唯一出现的日期值 | 常量 `2026-10-27`（"业务更新"页眉，与 `manifest.built_at` 逐字相同，对历史版与新版一视同仁） |

即：**被比较的另一侧（源侧区间）不存在**；`as_of` 一侧不缺。继续用旧口径只有两个结局，都不可接受：

- **fail-closed 到零可判**：P4 适配器对非空使用集无条件追加 `stale_lifecycle_evidence_missing`，`stale_source` 在真实数据上 100% unknown（IR-09 已记为设计后果）。
- **fail-open 到全假阳性**：把常量 `2026-10-27` 当 `effective_from`，12 源同时生效，"被后生效版本取代"在结构上永不可能成立 —— 这不是可判，是"全 not-stale"。

### 1.2 被否掉的三类冒充（外加第四类）

| # | 冒充物 | 为什么**不能**当日期证据 |
|---|---|---|
| X-1 | `manifest.built_at` / 语料页眉常量 `2026-10-27` | 语料**构建基线**，对被比较的全部历史版与新版取同值；无逐源区分力、无右端、与 `built_at` 逐字相同。 |
| X-2 | corpus-wide 常量 / 单值 `business_date` / addendum `business_date` | 单值业务日期既不能区分 12 源，也无区间右端；把单值当区间会制造"看似可判"的假证据。 |
| X-3 | active-version 断言（"V05 已是 v4 所以它生效于某日"） | 版本生效 ≠ 有日期证据；`p2-holdout-v2.source-map.json:12` 自述 `Mapping is historical identity, not an active-version assertion`。 |
| X-4 | 上传顺序 / 文件 mtime / OOXML core props / PDF `CreationDate` / ZIP epoch | 顺序只给全序、给不出日期，且 `source-map.json:11` 明示版本身份"follows upload order, **including unpublished uploads**"；元数据四者互相矛盾且均为构建产物。 |

> 这四类在任何模式下都**不得**进入 `effective_from` / `effective_to` / `as_of` 任一端。`date_window` 模式的窗口**只能**来自 §3.2 的冻结 fixture；H2 v3 走 §3.4 的 L1 唯一真相源（判据不内嵌、不另存第二份窗口表）。

**X-2 与 v1.1 的关系（防止把本升版读成"放开单值日期"）**：`business_date` 仍是**运行期基准日**，不是任何源的窗口值。裁定 2 允许的是「**每 run 一个** `business_date`」——即一个 run 内所有 case 共用同一基准日，**不是**允许把该单值当 `effective_from`/`effective_to`，也**不是**允许逐题改日期。四个 run 用四个不同的 `business_date`，正是 §1.2 X-2 所要求的"单值不足以区分 12 源"的合法处置方式（用 run 划分，而不是用单值冒充区间）。

### 1.3 改口径的代价（必须同时写清）

改口径会**让本期分数失去可比性**（C1-1 回执 §5 已列此代价，经理原建议是先下发权威生命周期表）。本规范把该代价固化为 §11 的不可比声明，而不是把它藏进"新口径更好"的叙事里。

---

## 2. 不变量（先钉死，再谈规则）

| id | 不变量 |
|---|---|
| I-1 | **数据集无关**：同一实现同时可跑 `version_state` 与 `date_window`；实现内**零**数据集字面量（见 §12.2）。 |
| I-2 | 四状态不变：`passed` / `not_applicable` / `unknown` / `violation`；不新增第五态。 |
| I-3 | 30 题 / 标签 / 阈值 / 评分标准 / 旧卡字节不变。 |
| I-4 | 冻结 annotation reason 表（**18 码**）不增、不删、不改义（见 §10.4）。 |
| I-5 | 输出不含 `verified` / `threshold` / `release` 字段与结论值。 |
| I-6 | 每个 case 的 `stale_source` **恰一个** state 与**恰一个** determination reason。 |
| I-7 | `unknown` 永不被降级为 `not_applicable`；本轴 `not_applicable` 恒为 0（§5.7）。 |
| I-8 | **区间只有一种读法**：任何模式、任何消费者都按闭区间 `[from, to]` 判覆盖；同一 `as_of` 在同一窗口上不得得出两种结论（v1.1 新增，v1 缺失）。 |

---

## 3. 两种 grounding 模式

一份规范、两种模式，由**数据集（或合同）顶层声明**，不得逐题切换。

### 3.1 `version_state`（2026-11-14 数据集使用本模式）

**定义**：`doc_code` 的 active 源身份**完全**由以下两项决定，**不读任何日期**：

1. **scenario 契约**的 `source_indices`（上传集与上传序，见 R-AV-3）；
2. **source map** 的 `version_number`（版本号标签，见 R-AV-5）。

必需输入（缺一即 §9 的对应 unknown，不得缺省补值）：

| 输入 | 本批公开件 | SHA-256（v1 冻结时实测） |
|---|---|---|
| scenario 契约 | `docs/evaluation/p2-h2-scenarios-v0_2.json` | `39c7e16103acdac52741a48d895b29ff5675ee97e5691955ccebe5b21a1274ad` |
| 12 源 ingest plan | `docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json` | `362e3ea10f673021d78c7a647305f04b8557b364a14482ebc2ba370d7752ed19` |
| source map | `docs/evaluation/p2-holdout-v2.source-map.json` | `86c86767ce5f4251ff52589cca9d02882aa7f47e23caf7cde654133b8ea821b5` |
| 数据集 manifest | `docs/evaluation/p2-holdout-v2.manifest.json` | `8874985ef8f4aacc5689d5dc4dc60db759c2620492d159171712f7a9b679ce4b` |

**禁止**：在本模式下读 `effective_from` / `effective_to` / `built_at` / `business_date` 来影响 verdict；把 `version_number` 的大小当作时间先后；把 scenario **名字**（如 `pre_v05` / `post_v05`）当作版本或时间。

> **本模式在 v1.1 中一字未改。** `2026-11-14` 的重算（`Q1A-RESCORE-20261114-r3`，`fixture_sha256=null`、`windows=null`）走的就是本模式，因此 §3.2 的区间开闭改动**进不到**那次重算的任何一步。

### 3.2 `date_window`（未来 H2 v3 使用本模式）

**定义**：每个源的生效区间 `[effective_from, effective_to]`（**闭区间，两端点均含**）由**冻结 fixture 显式编码**，逐源一条：

```json
{
  "schema_version": "p2-source-lifecycle-window/v1",
  "bindings": {"source_map_sha256": "<hex64>", "ingest_plan_sha256": "<hex64>"},
  "windows": {
    "<code>": {"effective_from": "YYYY-MM-DD", "effective_to": "YYYY-MM-DD"}
  },
  "open_ended": ["<code>", "..."],
  "basis": "owner_ruling | custodian_transcription",
  "evidence_ref": "<公开/受控记录定位，不含题面>"
}
```

规则：

1. `effective_from` **必填**；`effective_to` 可缺，缺则该源必须列进 `open_ended` 且 `basis` 必须存在 —— 否则 `stale_window_unresolved`。
2. **区间闭**：覆盖 ⇔ `effective_from <= as_of <= effective_to`。四条边界断言（**逐条必测**）：
   - `as_of == effective_from` → **有效**（有效首日）；
   - `as_of == effective_to` → **有效**（有效末日）；
   - `as_of == effective_to + 1 天` → **已过期**；
   - `as_of == effective_from - 1 天` → **未生效**。

   `effective_to` 缺失（open ended）⇔ `effective_from <= as_of`（右侧不设界，但见 §3.2 规则 4 对 null 的定性）。
3. 该 fixture 是**独立冻结件**，其 SHA-256 必须被数据集顶层 `stale_grounding.fixture_sha256` 绑定。不匹配或加载期可信度检查失败时**按模式分别处置**（见 §3.3）：`date_window` → `stale_window_unresolved` + `unknown`（整份不可用，不降级）；`version_state` → 丢弃 + audit，verdict 不变。
4. `basis` 只允许 `owner_ruling`（主人裁定）或 `custodian_transcription`（保管转述）；任何"从语料文本/元数据/行为反推"的来源一律拒收。
5. **`date_window` 模式下的 active 由窗口决定**（R-AV-3 的位置序在此模式下降级为一致性校验）：

   ```text
   covering(S, b, as_of) = { x ∈ groups(S)[b] : window(x) 覆盖 as_of }   # 覆盖 = 闭区间判定（规则 2）
   ```

   - `|covering| == 1` → 该源是 active；
   - `|covering| == 0` → 该 `base_doc_code` 在 `as_of` **无 active**；该组任何使用 → `violation` `stale_out_of_window`（不是 N/A、不是 unknown）；
   - `|covering| >= 2` → `unknown` `stale_active_version_ambiguous`；
   - 任何成员窗口缺失/半端 → `unknown` `stale_window_unresolved`（先于上述三条判定）。
6. **交叉校验**：若 `covering` 推出的 active 与 R-AV-3 的位置序 active 都存在且**不是同一源** → `unknown` `stale_active_version_ambiguous`（audit `stale_grounding_crosscheck_disagreement`），**不得择一**。
7. `version_state` 模式**不执行**本节 5–6：窗口只按 §5.4 单向加严，绝不参与 active 推导。

**本升版的依据（只对齐区间，不改任何其它语义）**：闭区间不是本判据的新发明，它已经是 v3 冻结面里唯一实现的读法 ——

| 面 | 证据（当前工作树实测） | 读法 |
|---|---|---|
| 冻结分类器 | `backend/src/mktkb/evaluation/p2_hard_evidence.py:1726-1732`：`actual_date < start` → `future_source_as_current`；`actual_date > end` → `source_expired` | 两端点均**不算**违规 ⇒ 闭区间 |
| 产品检索过滤 | `backend/src/mktkb/rag/retrieval.py:205-211`：`effective_from <= plan.as_of`、`effective_to >= plan.as_of` | 两端点均**保留** ⇒ 闭区间 |
| 设计规格 | `2026-11-14-h2-v3-design-spec.md` §3.4 `S1`（闭区间）与 `S4`（`== from` / `== to` 均有效） | 闭区间 |

> 行号说明：v1 原文引用的 `:1803-1808` 是同一段代码在更早工作树下的行号，当前工作树漂移到 `:1726-1732`。**代码语义未变**，本升版只是让判据文本与它一致。

**禁止**（与前节 X-1..X-4 一一对应，且**在加载期就拒收**，不是判定期才判 unknown）：

- 任何窗口值等于 `manifest.built_at` 或语料页眉常量 → 拒收该条；
- 任何"全 corpus 同一值"的窗口集合（12/12 同值）→ 拒收整份 fixture；
- 任何窗口由 active-version 断言推导（无独立 `evidence_ref`）→ 拒收该条；
- 任何窗口由上传顺序 / 文件时间戳 / core props 推导 → 拒收该条。

> **边界日的处置（v1.1 后）**：v1 曾把 `2026-10-31` / `2026-05-01` 这类边界日集中在"同日边界"题里隔离两种读法（v1 版 fixture 的 SC-1）。v1.1 之后两读法已统一，**不需要**再隔离；边界日可以出现在任何题上，只要该题期望的方向按闭区间计算。反过来，**任何按半开区间写的实现都会在边界日系统性错一天**，这是 v1.1 明令禁止的。

### 3.3 模式声明

```json
{"stale_grounding": {"mode": "version_state" | "date_window",
                     "fixture_sha256": "<hex64|null>",
                     "criterion_version": "p2-stale-source-criterion/v1.1"}}
```

- 缺失 / 值不在枚举 / 同时声明两种 / `criterion_version` 不符 → `stale_grounding_mode_invalid` + `unknown`。
- **不得**按 case 或按题组切换模式；**不得**"两种都跑、取较好者"（择优即 reverse-engineering，禁止）。
- `fixture_sha256` 的必需性**按模式不同**：
  - `date_window`：**必须**非 null。窗口是必需输入，缺/不符 → `stale_window_unresolved` + `unknown`。
  - `version_state`：**可为 null**（不启用日期检查，`evidence_grade=version_only`）**或**非 null（启用 §5.4 的单向加严）。非 null 而绑定不符 / 加载期可信度检查失败 → **丢弃该 fixture、记 audit `stale_date_fixture_rejected`、`evidence_grade` 固定为 `version_only`，verdict 不变**；理由是可选输入不得决定判决，否则等于把"日期"重新变成必需证据。

### 3.4 SC-2 裁定：`date_window` 的窗口单一真相源 = 数据集 L1（2026-11-15，同一版本澄清）

> 本节是 v1.1 的**同版本澄清**（不升 v1.2），不改变 §3.2 规则 1–7 的区间语义，不改变 §10 的 21 码表，也不改变 §12.3 的 G-1..G-11 编号。它只钉死一件事：**窗口从哪来、谁是真相、消费方怎么证明自己拿到的窗口就是真相**。

**裁定（写死）**：H2 v3 的 `date_window` 窗口**唯一真相源**是数据集生命周期件 `docs/evaluation/p2-source-lifecycle-v1.json`（schema `p2-source-lifecycle/v1`，`declaration.kind = design_fixture`，`interval = closed`，下称 **L1**）。本判据**不内嵌任何窗口值**；v3 不得再存在第二份可独立编辑的窗口表。§3.2 的 `windows` / `open_ended` 形状只在「数据集自带独立窗口 fixture」时使用；v3 不实例化该文件。若某个消费方在内存中把 L1 投影成 §3.2 形状，该投影是**派生只读量**，不是冻结件、不得落盘为可编辑真相、不得与 L1 并列被引用。

**L1 的权威对象（逐类）**：

| L1 对象 | 在判据里的地位 | 消费方式 |
|---|---|---|
| `sources[]`（v3 快照 12 行；`effective_from`/`effective_to`） | **版本级窗口的唯一真值** | 逐 `(source_id, doc_code, version_number)` 读；`effective_to = null` ⇒ `open_ended`（`not_asserted`） |
| `records[]`（v3 快照 4 行；记录级窗口） | **记录级窗口的唯一真值** | 逐 `(doc_code, version_number, record_code)` 覆盖版本窗口；不在 §3.2 的 `windows` 形状内，按记录级消费 |
| `interval` / `interval_rule` | 本判据 §3.2 规则 2 的**同一闭区间** | 加载期断言 `interval == "closed"`；不一致即整份拒收 |
| `declaration.kind = design_fixture` | L1 的 `basis`，不得改写 | 见下「basis 澄清」 |

版本级 active 仍按 §3.2 规则 5 的版本窗口推导；记录级窗口只用于该记录行自身的日期子检查（由冻结分类器/证据侧执行），**不参与**版本 active 推导，也不得用来把某个版本判成「未生效」。

**basis 澄清（SC-2 的核心）**：§3.2 规则 4 的 `owner_ruling` / `custodian_transcription` 枚举，只适用于**独立 `p2-source-lifecycle-window/v1` fixture**（窗口事实直接由裁定/转述写入该 fixture 的情形）。v3 走 L1，而 L1 的 `declaration.basis_enum` 只有 `design_fixture`，语义是「出题时合成设定」——不是主人裁定、不是保管转述、不是从语料文本/元数据/行为反推。因此：

- L1 派生视图的 `basis` **必须**是 `design_fixture`；
- 把 L1 派生视图标成 `owner_ruling` / `custodian_transcription` = **伪造来源** → `stale_window_unresolved` + `unknown`；
- 把非 L1 派生的独立 fixture 标成 `design_fixture` = **冒充设计事实** → 同样 `stale_window_unresolved` + `unknown`；
- `design_fixture` 不是「可信度更低」的同义词：它的可信度来自 L1 的冻结/绑定与逐值复算，不来自任何自然人的口头裁定。

**读取规则（v3 消费方必须这样做）**：

1. `grounding.mode = date_window`；`grounding.fixture_sha256` **必须非 null**，且等于 L1 原始字节的 SHA-256（§3.3 对 `date_window` 的要求不变）。
2. 直接读 L1；**不得**再读一份 `windows` JSON 作为并列真相。若传输层必须携带投影，`grounding.windows` 只能是**进程内重算值**，并在审计里记 `window_source = "p2-source-lifecycle/v1"` + `lifecycle_sha256`；持久化副本一律视为不可信输入。
3. 对每个 used unit：先按 `(doc_code, version_number, record_code)` 查 `records[]`，命中则用记录级窗口；未命中则用 `sources[]` 版本窗口。`effective_to = null` ⇒ 右侧不设界（`not_asserted`），按 §3.2 规则 2 的 open-ended 读法。
4. 任何一侧窗口缺失 / 解析失败 / `records[]` 命中但字段不全 → `stale_window_unresolved` + `unknown`（不降级、不猜）。

**校验算法（消费方证明「L1 与判据一致」；逐值重算 + SHA 绑定，六步，任一失败即 fail-closed）**：

| # | 步骤 | 失败结果 |
|---:|---|---|
| V-1 | **字节绑定**：`sha256(L1 bytes) == grounding.fixture_sha256`，且（若 run 回执带 bindings）`== bindings.lifecycle_sha256` | `stale_window_unresolved` + `unknown` |
| V-2 | **模式绑定**：`schema_version == "p2-source-lifecycle/v1"`、`interval == "closed"`、`declaration.kind == "design_fixture"`、`declaration.basis_enum == ["design_fixture"]` | 同上 |
| V-3 | **形状**：`sources[]` 非空且 `(source_id, doc_code, version_number)` 唯一；每行 `effective_from` 可解析为 `YYYY-MM-DD`，`effective_to` 为 `YYYY-MM-DD` 或 null；`records[]` 每行 `(doc_code, version_number, record_code)` 唯一 | 同上 |
| V-4 | **逐值重算**：按上面的读取规则，对**每个** used unit 重算窗口，并与消费方实际使用的窗口**逐字段字符串相等**比较；不得容差、不得「取一方」、不得用 `published_at`/`built_at`/`business_date` 补值 | 同上 |
| V-5 | **不变量**：同槽位后继 `effective_from == 前驱 effective_to + 1`；槽位最大版本 `effective_to == null`；`records[]` 窗口 ⊆ 同版本窗口；无窗口等于 `manifest.built_at`/语料页眉常量；版本窗口不全同值 | 同上（整份 L1 拒收） |
| V-6 | **冲突处置**：L1 与内存投影/历史副本不一致 → **以 L1 为准**，投影/副本整份拒收；禁止「取较宽/较窄」、禁止按题择优、禁止回退到 `version_state` 掩盖窗口缺失 | 同上 |

> 这六步与 §3.2 规则 3/5 的关系：规则 3 的「fixture SHA 必须绑定」在 v3 就是 V-1；规则 5 的 `covering` 在 v3 就是对 L1 窗口逐值重算后的闭区间判断。两者不是第二套规则，而是同一规则在 L1 上的落地。

**与冻结分类器的关系（防止把本节读成「判据取代分类器」）**：H2 v3 的**判定权威仍是冻结分类器** `backend/src/mktkb/evaluation/p2_hard_evidence.py`（classification v0.2 不变）。分类器消费的是 L0 语料行里的 `生效日期`/`失效日期` 两列；这两列由语料改动规格逐行抄 L1（`sources[]` 默认、`records[]` 覆盖）。本节管的是**窗口来源与一致性证明**，不改变任何 verdict 的判定路径。

**冲突时的单一真相源**：任何「判据内嵌 windows」与 L1 不一致的场合，一律以 L1 为准；内嵌值没有独立权威，必须整份拒收，不得进入判定。SC-2 的状态从「开放」改为「已裁定（L1 唯一真源）」。

---

## 4. active 版本推导（R-AV-1 … R-AV-6）

给定 `case.scenario_id`，按下列顺序**确定性**算出每个 `base_doc_code` 的 active 源。全部步骤都是纯函数、无自由参数、可逐条复算。

### 4.1 符号

| 符号 | 定义 |
|---|---|
| `plan.sources[0..n-1]` | ingest plan 的**有序**数组；下标即上传位置 `pos`（位置越小＝越早上传）。 |
| `code(entry)` | `basename(entry.path)` 在**第一个 `_` 之前**的前缀（如 `V03` / `D01` / `V01`）。 |
| `slot(entry)` | `entry.document_ref`，否则 `entry.name`，否则 `basename(entry.path)`。 |
| `aliases` | source map 的 `sources`：`变体码 → base_doc_code`。 |
| `version_numbers` | source map 的 `sources`：`变体码 → version_number`。 |
| `base_doc_code(c)` | `aliases[c]`（若 `c ∈ aliases`），否则 `c`。 |

> `slot` / `code` 的区别是刻意的：`slot` 只用于**分组语义**的可读性核对，`code` + `base_doc_code` 才是判定身份。本批公开件中 `slot` 的 doc-code 前缀与 `base_doc_code(code)` 逐条一致；**不一致即 `stale_active_version_ambiguous`**（说明 ingest plan 与 source map 冲突，不得择一）。

### 4.2 R-AV-1 上传集与上传序

```text
upload(S) = [ (pos=idx, plan.sources[idx]) for idx in scenario(S).source_indices ]   # 按 idx 升序
```

`source_indices` **必须**是整数数组、无重复、每个 idx 落在 `[0, n)`；违反 → `stale_scenario_undeclared` + `unknown`。

`ingest_batches` 的地位：**不参与排序，也不参与判定**。它只作为不透明的一致性声明原样记入 provenance（audit `stale_batch_count_opaque`）。

> 本批公开件观测到 `ingest_batches == len(source_indices) + 1`（四 scenario 全部成立）。该关系**不得**被写成常量或用于推导 —— 它是本数据集的观测巧合，不是契约。

### 4.3 R-AV-2 分组

```text
groups(S) = { base_doc_code(code(entry)) : [(pos, entry), ...] }   # 按 base_doc_code 分组
```

### 4.4 R-AV-3 active 选择

```text
active(S, b) = entry with max pos among groups(S)[b]
```

即「**同一槽位内最后上传者胜**」。这与 source map `basis` 的 "ordered uploads … in D01 slot"、"V06 replaces D02 as v2" 同向，也与四个 scenario 命名自洽（`pre_v05` 恰排除 V05、`post_v05` 恰含 V05）。

> **与 `business_date` 的关系（v1.1 明确）**：`active` 由**该 run 的上传集**决定，与该 run 声明的 `business_date` **无关**。同一 upload 集在不同 `business_date` 下 active 不变。因此「每 run 一个 `business_date`」不会动摇 R-AV-3，也不需要请求级入参。

### 4.5 R-AV-4 版本号标签

```text
version_number(code) = version_numbers[code] if code in version_numbers else UNDECLARED
```

- `UNDECLARED` **不是 `1`**，也**不是** `null` 可选项；它是显式第三值，输出为 `null` + audit `stale_version_number_undeclared`。
- `UNDECLARED` **不阻止** `version_state` 判定（身份是 `code`，不是号），但会阻止任何"用版本号大小做否决"的推理。

### 4.6 R-AV-5 声明一致性校验

若组内**全部**成员都有声明版本号，则必须满足：

```text
version_number(active(S,b)) == max(version_number(x) for x in groups(S)[b])
```

不满足 → `stale_active_version_ambiguous` + `unknown`（位置序与声明号冲突，**不得**择一）。组内存在 `UNDECLARED` 成员时本校验**跳过**（audit `stale_active_version_from_position`），因为无从比较。

### 4.7 R-AV-6 歧义与零 active

| 情形 | 触发条件 | 结果 |
|---|---|---|
| **多 active** | 组内 `max pos` 不唯一（位置并列 / 数据集只给 `batch_membership` 且同批含同类多源 / `source_indices` 有重复） | `stale_active_version_ambiguous` + `unknown` |
| **0 active** | 某个 `base_doc_code` 出现在**使用集**里，但不在 `groups(S)` 中 | `stale_active_version_ambiguous` + `unknown`（audit `stale_usage_source_not_in_scenario`） |

**0 active 为什么是 unknown 而不是 violation**：使用集里出现本 scenario 从未上传的源，最可能是**证据归属错误**（运行期身份错配），而不是产品真的用了不存在的源。把它判 violation 会把量具缺陷记成产品失败。故 fail-closed 到 unknown。

### 4.8 输出

```json
{"active_versions": {"<base_doc_code>": {"code": "V05", "version_number": 4,
                                         "basis": "position_max",
                                         "position": 3}}}
```

键集 = `groups(S)` 的键集，一个不多一个不少（0 active 的情形不进入此表，只在 audit 里记）。

---

## 5. 判定规则（逐轴、逐回合、再折叠）

### 5.1 前置（按序，先命中先返回）

| # | 条件 | 结果 |
|---|---|---|
| P-1 | 注解缺失 / 缺字段 / 坏枚举 / 不可信来源 | `unknown` `annotation_unknown` |
| P-2 | 注解 `applicability != required` 或 `criterion != lifecycle_dates` | `unknown` `annotation_unknown`（audit `scope_mode_mismatch`） |
| P-3 | §3.3 模式声明缺失/非法/双声明 | `unknown` `stale_grounding_mode_invalid` |
| P-4 | `case.scenario_id` 缺失 / 不在 scenario 契约 / 契约缺 `source_indices` | `unknown` `stale_scenario_undeclared` |
| P-5 | ref → 记录身份不可解析（`record_code` 或 `code` 缺） | `unknown` `source_unresolved` |

### 5.2 使用集

| # | 条件 | 结果 |
|---|---|---|
| R-J-1 | 使用层**有观测**且 `units == []`，且空集闭包证明**成立** | `passed` `stale_empty_use_scope_proven` |
| R-J-2 | 使用层有观测且 `units == []`，闭包证明**不成立** | `unknown` `empty_set_not_proven` |
| R-J-3 | 使用层**零观测**（无 `units` 字段 / 未观测 / 回合未完成 / 回合 `partial`） | `unknown` `stale_usage_set_missing`（沿用码 `turn_not_executed` / `turn_error` / `replay_without_original` / `evidence_incomplete` 优先） |

> 闭包证明的**判定输入**沿用既有口径：逐层 `observed/count` + 检索观测 `observed/count/refs/truncated` + 回合完成状态；**不读** `empty_set_candidate` 之类派生布尔（P4 §3.2 已实测该函数不读它们）。

### 5.3 源身份比对（两种模式都跑；`date_window` 的 active 见 §3.2 规则 5）

比对顺序**必须**是：先 R-J-7（能否解析）→ R-J-6（是否在册）→ R-J-4 / R-J-5（是否 active）。顺序颠倒会让"未在册"的源被当成"未取代"。

对每个使用 unit：

| # | 条件 | 结果 |
|---|---|---|
| R-J-4 | `code(u)` 等于其 `base_doc_code` 的 active（active 的定义按模式，见 §3.2 规则 5 / §4.4） | 该 unit **合规** |
| R-J-5 | （**仅 `version_state`**）`code(u)` 属于同组、但**不是** active（被后上传取代） | `violation` `stale_superseded_version_used` |
| R-J-6 | `base_doc_code(code(u))` 不在 `active_versions`（本 scenario 未上传该槽位） | `unknown` `stale_active_version_ambiguous`（audit `stale_usage_source_not_in_scenario`） |
| R-J-7 | `code(u)` 无法解析成任何已知源 | `unknown` `version_unresolved` |

> `date_window` 模式下，used ≠ active 的情形**不**落 `stale_superseded_version_used`，一律落 §5.4 的 `stale_out_of_window`（该模式下"不 active"的语义就是"不在窗口内"）。两个码不得互相借用。

- **一律按身份精确相等**比对（`code` 字面相等 + `base_doc_code` 相等）。禁止前缀、包含、大小写折叠、模糊匹配、名称相似度（IR-04/IR-08 的历史教训）。
- **为什么比 `code` 而不比 `version_number`**：`code` 唯一标识一个源版本（一文件一码），而 `version_number` 可缺失（`UNDECLARED`）、可因数据集不同而从 0 或 1 起算、也可能在跨槽位时重复。故 `code` 是身份，`version_number` 只是标签；**禁止**把判定退化成"号相等即通过"。
- 一个 unit 命中 R-J-5 即记一条 violation；多条不合并、不去重成"1 个问题"。

### 5.4 汇总与日期叠加

| # | 条件 | 结果 |
|---|---|---|
| R-J-8 | 无 violation、无 unknown，**且**全部 unit 合规 | 进入 R-J-9 / R-J-10 决定最终 state 与 pass 码 |
| R-J-9 | 有 violation（任一） | `violation`（`stale_superseded_version_used` 或 `stale_out_of_window`；reason 取回合序最小的第一条 violation） |
| R-J-10 | 有 unknown 无 violation | `unknown`（reason 取 P-1..P-5、R-J-6/R-J-7 中序最前的一条） |

R-J-8 之后的日期叠加（**单向加严**；"覆盖"一律按 §3.2 规则 2 的**闭区间**）：

| 模式 | 窗口状态 | 结果 |
|---|---|---|
| `version_state` | 未提供 fixture（`fixture_sha256 == null`） | `passed` `stale_active_version_used`，`evidence_grade=version_only` |
| `version_state` | 附带窗口且**覆盖** `as_of`（含 `as_of == from` / `== to`） | `passed` `stale_active_version_used`，`evidence_grade=version_plus_date` |
| `version_state` | 附带窗口且**不覆盖** `as_of`，且 `as_of` 与窗口均完整可解析 | `violation` `stale_out_of_window`，`evidence_grade=version_plus_date` |
| `version_state` | 附带窗口损毁/半端/不可解析，或 fixture 被拒收/绑定不符 | 忽略窗口（不出 unknown，不改 verdict），`evidence_grade=version_only`，audit `stale_date_check_skipped_unresolved` / `stale_date_fixture_rejected` |
| `date_window` | 窗口覆盖 `as_of`（含 `as_of == from` / `== to`） | `passed` `stale_source_dates_ok`，`evidence_grade=version_plus_date` |
| `date_window` | 窗口**不覆盖** `as_of`（完整） | `violation` `stale_out_of_window` |
| `date_window` | 窗口缺失/损毁/半端 | `unknown` `stale_window_unresolved` |
| `date_window` | `as_of` 缺失或非法 | `unknown` `as_of_missing` |

**关键语义**：`version_state` 模式下"窗口不覆盖"是**唯一**能让 `passed` 变 `violation` 的附加通道；"窗口损毁"**不得**制造 unknown（否则等于把可选证据变成必需证据，回退到第 5 缺口的老问题）。

**v1.1 补充（边界口径的唯一性）**：上表每一行的"覆盖"都必须是闭区间。若同一 case 的同一 `as_of` 在两个消费者（如判据与检索过滤）上得出不同覆盖结论，则**不是**判据歧义，而是实现缺陷，按 I-8 处理。

### 5.5 citation 层一致性（与版本态正交，沿用）

| # | 条件 | 结果 |
|---|---|---|
| R-J-11 | 存在 `final_citation` 层，其 `document_id` / `version_id` 与对应 unit 不一致 | `violation` `citation_version_mismatch` |
| R-J-12 | 存在 `final_citation` 层但投影行缺失 | `unknown` `source_unresolved`（旧码 `citation_source_unresolved` 已退役，见 §10.3） |
| R-J-13 | 注解 `as_of` 与运行期 `as_of` 不等（两者都非空） | `violation` `date_intent_conflict` |

> R-J-13 是**产品侧一致性**检查（注解声明的基准日 vs 运行期实际基准日），**不是**源侧日历比较，故保留。它的存在与否**不得**改变 R-J-4..R-J-10 的结论。
> **裁定 2 的落点**：v3 采用「每 run 一个 `business_date`」，因此同一 run 内所有 case 的注解 `as_of` 必须**逐字等于**该 run 的 `business_date`；不同 run 的 `business_date` 不同，彼此不比较。R-J-13 只比较同一 case 的注解值与同一 run 的运行期值，**不需要**请求级入参。

### 5.6 多轮折叠

```text
case.state = max_priority(turn.state for turn in case.turns)
priority   = violation(3) > unknown(2) > not_applicable(1) > passed(0)
case.reason = reason of the turn with the highest priority, ties broken by smallest turn index
```

- 折叠后 `state` 唯一、`reason` 唯一（I-6）。
- **所有**被折叠掉的较低优先级回合的码必须留在 `provenance.per_turn[].reason` 与 `audit` 里，不得静默丢弃（否则"某回合其实缺证据"会被 violation 掩盖）。
- 禁止拼接不同回合的分数、禁止用后一回合"洗掉"前一回合的 violation。
- 同一 case 的所有回合同属一个 run，故共享同一个 `business_date`；跨轮不得改日期。

### 5.7 `not_applicable` 在本轴**不可达**（写清是哪种）

明确答案：**空使用集且证明成立 → `passed`（`stale_empty_use_scope_proven`），不是 `not_applicable`。**

理由链（三条独立依据）：

1. `stale_source` 对 30 题**全部 required**（C1-1 回执 §2：`stale_source` 是全部 required 轴，它不可判则任何题都不能判合格）。
2. 冻结口径要求：注解 `applicability=not_applicable` → `unknown`（`annotation_unknown`，audit `scope_mode_mismatch`），**绝不 N/A**。
3. 空集是**可证成的通过**而不是"不适用"：产品确实被要求处理这批源，它只是没用到任何一个；这属于"用对了（空集）"，不是"这一轴对它不适用"。

因此：

- `no_dated_sources_lifecycle_checked`（冻结词表里唯一的 stale N/A 码）**保留在词表、本判据一律不产出**；产出即 non-conformant。
- 计数字段 `not_applicable` **恒为 0**，且必须在 `verify()` 里作为**额外硬不变量**断言（`counts.not_applicable == 0`，否则 `axis_counts_inconsistent`）。
- 四状态枚举本身不变（I-2）：`not_applicable` 仍是合法 state，只是本轴在本判据下走不到。

---

## 6. "日期为可选加分"的严格定义

术语：`evidence_grade ∈ {none, version_only, version_plus_date}`。

| 值 | 含义 |
|---|---|
| `none` | 无可用结论（unknown / violation 之外的退化情形，不给 grade） |
| `version_only` | 仅版本态已 grounding（`version_state` 模式常态） |
| `version_plus_date` | 版本态 + **完整**窗口且与 `as_of` 一致（即"加了日期分"） |

硬约束：

1. `evidence_grade` **不是分数**：不参与阈值、权重、排序、求和、均值、tie-break；**不得**与 `passed` 计数相加或做加权。
2. 它改变的是**证据强度标注**，不是 verdict；唯一例外是 §5.4 明确列出的"窗口不覆盖 → violation"单向通道。
3. 一旦 `state != passed`，`evidence_grade` 必须是 `none`（不允许给失败者打"日期分"）。
4. 报告必须**分列**：`passed_version_only` 与 `passed_version_plus_date` 两个计数单列，且都计入 `passed`（不得重复计数）。

反例（明确禁止的写法）：「stale 13 pass + 4 date bonus = 17」——这是把 grade 当分数的典型误用。

---

## 7. 合成示例表（**全部虚构**，不含真实题面/答案/目标值）

虚构 scenario `S_syn`（`source_indices = [0,1,2,5]`，`ingest_batches = 99` 为不透明值）：

| pos | path（虚构） | `document_ref` | `code` | `base_doc_code` | 声明 `version_number` |
|---:|---|---|---|---|---:|
| 0 | `variants/V20_d10_a.xlsx` | —（`name: D10_d10.xlsx`） | `V20` | `D10` | 1 |
| 1 | `normal/D10_d10.xlsx` | — | `D10` | `D10` | UNDECLARED |
| 2 | `variants/V21_d10_b.xlsx` | `D10_d10.xlsx` | `V21` | `D10` | 3 |
| 5 | `normal/D11_d11.pdf` | — | `D11` | `D11` | UNDECLARED |
| 9 | `variants/V30_d12.pdf` | — | `V30` | `V30` | —（不在 `S_syn` 上传集） |

推导结果：`active(D10) = V21 (v3, pos 2)`；`active(D11) = D11 (UNDECLARED, pos 5)`；`V30` 无 active。
R-AV-5 校验：`D10` 组含 `UNDECLARED` 成员 → 校验跳过（audit `stale_active_version_from_position`）。

| # | 使用集（虚构） | 模式 | 窗口（虚构） | 期望 state | 期望 reason |
|---:|---|---|---|---|---|
| 1 | `[V21]` | `version_state` | 无 | `passed` | `stale_active_version_used` |
| 2 | `[V20]` | `version_state` | 无 | `violation` | `stale_superseded_version_used` |
| 3 | `[D10]` | `version_state` | 无 | `violation` | `stale_superseded_version_used`（pos 1 < 2） |
| 4 | `[D11]` | `version_state` | 无 | `passed` | `stale_active_version_used` |
| 5 | `[V30]` | `version_state` | 无 | `unknown` | `stale_active_version_ambiguous`（0 active） |
| 6 | `[]`，闭包证明成立 | `version_state` | 无 | `passed` | `stale_empty_use_scope_proven` |
| 7 | `[]`，闭包未证 | `version_state` | 无 | `unknown` | `empty_set_not_proven` |
| 8 | 未观测 | 任意 | 任意 | `unknown` | `stale_usage_set_missing` |
| 9 | `[V21]` | `version_state` | `[2026-01-01, 2026-06-30]`，`as_of=2026-03-01` | `passed` | `stale_active_version_used`（grade=`version_plus_date`） |
| 10 | `[V21]` | `version_state` | `[2026-01-01, 2026-02-01]`，`as_of=2026-03-01` | `violation` | `stale_out_of_window` |
| 11 | `[V21]` | `version_state` | 半端（只有 `effective_from`、且未列 `open_ended`） | `passed` | `stale_active_version_used`（grade=`version_only`，窗口忽略） |
| 12 | `[V21]` | `date_window` | 窗口缺失 | `unknown` | `stale_window_unresolved` |
| 13 | `[V21]` | `date_window` | `[2026-01-01, 2026-02-01]`，`as_of=2026-03-01` | `violation` | `stale_out_of_window` |
| 14 | `[V21, V20]`（多回合：t1 pass、t2 用 V20） | `version_state` | 无 | `violation` | `stale_superseded_version_used`（t2），且 t1 记录保留 |

上表 14 行是**一致性测试的最小语料**（§12.3）。全部代码、路径、日期均为虚构。

### 7.1 边界四断言（v1.1 新增；全部虚构）

窗口一律虚构为 `[2026-01-01, 2026-02-01]`，`date_window` 模式，使用集 `[V21]`：

| # | `as_of` | 相对窗口 | 期望 state | 期望 reason |
|---:|---|---|---|---|
| B-1 | `2026-01-01` | == `effective_from`（首日） | `passed` | `stale_source_dates_ok` |
| B-2 | `2026-02-01` | == `effective_to`（末日） | `passed` | `stale_source_dates_ok` |
| B-3 | `2026-02-02` | == `effective_to + 1 天` | `violation` | `stale_out_of_window` |
| B-4 | `2025-12-31` | == `effective_from - 1 天` | `violation` | `stale_out_of_window` |

> 这四行是 v1.1 的**升版断言**：任何实现若在 B-2 或 B-1 上给出 `violation`，就是仍按半开区间实现，判 non-conformant。

---

## 8. 输入 / 输出形状

### 8.1 输入（单 case，逐 case 调用；同 run 内全部 case 共享一个 `business_date`）

```json
{
  "criterion_version": "p2-stale-source-criterion/v1.1",
  "grounding": {
    "mode": "version_state",
    "fixture_sha256": null,
    "scenario": {"scenario_id": "S_syn", "source_indices": [0,1,2,5], "ingest_batches": 99},
    "ingest_plan": {"schema_version": "p2-ingest-plan/v0.1",
                    "sources": [{"path": "...", "document_ref": "...|absent", "name": "...|absent"}]},
    "source_map": {"sources": {"<code>": {"base_doc_code": "...", "version_number": 1}}},
    "windows": null
  },
  "evidence": {
    "as_of": "YYYY-MM-DD|null",
    "usage": {"observed": true,
              "units": [{"unit_id": "...", "code": "...", "record_code": "..."}],
              "closure_proven": false,
              "closure_audit": ["..."]},
    "citations": [{"unit_id": "...", "document_id": "...", "version_id": "..."}],
    "annotation": {"applicability": "required", "criterion": "lifecycle_dates",
                   "reason": "<18 码之一>", "as_of": "YYYY-MM-DD|null",
                   "temporal_intent": "<TEMPORAL_INTENTS 之一>"},
    "turns": [{"turn_index": 0, "state_inputs": {}}]
  }
}
```

- 未知键一律拒绝（`criterion_field_invalid`）；缺失必需键 → 对应固定码 + unknown，**不补默认值**。
- 输入内**不得**含答案文本、目标值、真实记录键（本判据不需要它们）。
- `evidence.as_of` 是**该 case 所属 run 的 `business_date`**，不是逐题自由变量；`annotation.as_of` 必须与它逐字相等（§5.5 R-J-13）。
- v3 的 `date_window` 输入：`windows` 不落第二份可编辑文件；`fixture_sha256` = L1 原始字节 SHA-256；读取与一致性证明按 §3.4 的 V-1..V-6 执行。

### 8.2 输出

```json
{
  "criterion_version": "p2-stale-source-criterion/v1.1",
  "cases": [{
    "case_id": "...",
    "scenario_id": "...",
    "state": "passed|unknown|violation|not_applicable",
    "reason": "<§10 的 21 码之一>",
    "evidence_grade": "none|version_only|version_plus_date",
    "per_turn": [{"turn_index": 0, "state": "...", "reason": "..."}],
    "provenance": {
      "grounding_mode": "version_state|date_window",
      "active_versions": {"<base_doc_code>": {"code": "...", "version_number": 1,
                                              "basis": "position_max", "position": 2}},
      "audit": ["stale_active_version_from_position", "..."]
    }
  }],
  "counts": {"planned": 0, "passed": 0, "not_applicable": 0,
             "unknown": 0, "violations": 0, "checked": 0,
             "passed_version_only": 0, "passed_version_plus_date": 0},
  "axes_provenance": "rescored"
}
```

硬不变量（`verify()` 必须断言）：

```text
planned   == passed + not_applicable + unknown + violations
checked   == passed + not_applicable + violations
planned   == checked + unknown
not_applicable == 0                                   # 本判据额外不变量（§5.7）
passed    == passed_version_only + passed_version_plus_date
```

输出禁令：不含 `verified` / `threshold` / `release` / 分数 / 均值 / 加权；不含真实日期值、unit 标识、记录键（这些只在私有明细）；不含题面/答案片段。

---

## 9. 不可判边界与 fail-closed 清单（12 条）

每一条都必须在实现里有一个反例测试；任一条退化为 pass 或 N/A 即 non-conformant。

| # | 情形 | 必须结果 | 明确禁止的替代 |
|---:|---|---|---|
| F-1 | 产品使用了某源，但该源在 scenario 中**无版本号**（`UNDECLARED`）且同组还有其它在册源 | 按 R-AV-3 位置序判定；若它非 active → `stale_superseded_version_used` | ❌ 因"号缺失"判 `version_unresolved`（位置序已足够）；❌ 把 `UNDECLARED` 当 `1` |
| F-2 | **同一 `base_doc_code` 两个 active**（位置并列 / 同批含同类多源 / `source_indices` 重复） | `stale_active_version_ambiguous` + `unknown` | ❌ 取第一个；❌ 取版本号最大者；❌ 判 N/A |
| F-3 | **0 active**（使用集含本 scenario 未上传的 `base_doc_code`） | `stale_active_version_ambiguous` + `unknown`（audit `stale_usage_source_not_in_scenario`） | ❌ 判 `stale_superseded_version_used`（那是把量具缺陷记成产品失败）；❌ 回退到"全部 12 源" |
| F-4 | `as_of` **晚于全部窗口**（`date_window` 模式，即 §3.2 规则 5 的 `covering` 基数为 0，且全部窗口完整） | `violation` `stale_out_of_window` | ❌ "全部源都过期 → 该轴不适用 → N/A"；❌ 放宽成"任一端缺失就算覆盖"（那应走 `stale_window_unresolved`） |
| F-5 | 数据集**未声明** grounding mode / 双声明 / 声明未知值 / `criterion_version` 不符 | `stale_grounding_mode_invalid` + `unknown` | ❌ 默认成 `version_state`；❌ 两模式都跑取较优 |
| F-6 | `scenario_id` **不在** scenario 契约 / 契约缺 `source_indices` / `source_indices` 非法 | `stale_scenario_undeclared` + `unknown` | ❌ 回退到"全集"或"最后使用的 scenario"；❌ 用 `ingest_batches` 反推集合 |
| F-7 | **证据缺使用集**（有回答但使用层零观测） | `stale_usage_set_missing` + `unknown` | ❌ "没观测到使用" ⇒ "没用过" ⇒ pass；❌ 判 N/A |
| F-8 | 空使用集但**闭包证明不成立**（某层未观测 / 候选被截断 / 回合未完成） | `empty_set_not_proven` + `unknown` | ❌ 用 `empty_set_candidate=true` 冒充已证；❌ 判 N/A |
| F-9 | `source map` 声明号与上传位置序**冲突**（argmax 位置的号 ≠ 组内最大号） | `stale_active_version_ambiguous` + `unknown` | ❌ 择一；❌ 以号为准覆盖位置序 |
| F-10 | `date_window` 模式下 fixture 的窗口值等于 `built_at` / 语料常量 / 由 active-version 断言推导 / 全 corpus 同值 | 拒收：`stale_window_unresolved` + `unknown`（整份 fixture 不可用） | ❌ 加载后"尽力比较"；❌ 只挑有效的几条用；❌ 在 `version_state` 下把被拒 fixture 当 violation 依据（该情形只丢弃，见 §3.3） |
| F-11 | 注解 `applicability=not_applicable`（或缺 `criterion=lifecycle_dates`） | `annotation_unknown` + `unknown` | ❌ 判 N/A；❌ 用 `no_dated_sources_lifecycle_checked` 收口 |
| F-12 | 一回合 violation、另一回合 unknown | `violation`（优先级），但 unknown 必须留在 `per_turn` + `audit` | ❌ 只报 violation 让缺证据消失；❌ 把两回合并成一回合重算 |

补充说明（不单独编号，但同属 fail-closed）：

- 运行期实体/记录身份不可解析 → `source_unresolved` + `unknown`（沿用）。
- `date_window` 模式 `as_of` 缺失/非法 → `as_of_missing` + `unknown`（沿用）。
- `date_window` 模式 `fixture_sha256` 为 `null`（窗口是必需输入却未提供）→ `stale_window_unresolved` + `unknown`，**不是** `stale_grounding_mode_invalid`（模式本身合法）。
- 任何非标量枚举值（数组/对象）→ 必须收敛为固定码 + unknown，**不得抛裸异常**（C1-P4 `IR-01` 的教训：11 个站点曾以 `TypeError` 逃出 `determine_case`）。
- **v1.1 新增**：同一窗口在同一 `as_of` 上被判"覆盖"又判"不覆盖"（例如判据按闭区间、检索过滤按半开区间）→ 属实现违规（I-8），必须在验收里被抓住；**不得**以"两种读法都说得通"收口。

---

## 10. 固定码表

**版本声明**：本表属于 `p2-stale-source-criterion/v1.1`，只在 v1.1 的消费实现里有效。总码数 **21**（新增 **9** / 沿用 **12**），另有 **14** 个旧码**保留不产出**（§10.3）。**码集与 v1 逐字相同**：本升版不新增、不删除、不改义任何码。

### 10.1 新增码（9，必须单独列并声明版本）

| 码 | 类别 | 触发 |
|---|---|---|
| `stale_active_version_used` | pass | 全部使用 unit 的 `code` 等于其 `base_doc_code` 的 active（`version_state` 模式） |
| `stale_empty_use_scope_proven` | pass | 使用集为空且闭包证明成立（**取代** P4 复用 `stale_source_dates_ok` 的写法） |
| `stale_superseded_version_used` | violation | 使用了同组内被后上传取代的已知源（含"同 `base_doc_code` 的旧版本"） |
| `stale_out_of_window` | violation | active 源已确认，但完整窗口不覆盖 `as_of`（两种模式共用；覆盖按闭区间） |
| `stale_active_version_ambiguous` | unknown | 多 active（位置并列/同批多源/重复索引）**或** 0 active |
| `stale_scenario_undeclared` | unknown | `scenario_id` 缺失/未知/`source_indices` 非法 |
| `stale_usage_set_missing` | unknown | 使用层零观测（含回合未完成/partial） |
| `stale_window_unresolved` | unknown | `date_window` 模式窗口缺失/半端/不可解析，或 fixture 被拒收 |
| `stale_grounding_mode_invalid` | unknown | 模式声明缺失/非法/双声明/fixture 绑定不符 |

### 10.2 沿用码（12，语义不变或显式收窄）

| 码 | 类别 | 沿用自 | 语义 |
|---|---|---|---|
| `stale_source_dates_ok` | pass | C1-P4 适配器 `PASS_CODES` | **收窄**：只在 `date_window` 模式产出（"active 源 + 窗口覆盖"），不再用于空集 pass |
| `annotation_unknown` | unknown | C 冻结 `UNKNOWN_REASONS_BY_AXIS["stale_source"]` | 注解缺/坏/与 required 冲突 |
| `source_unresolved` | unknown | 同上 | ref → 记录/源身份不可解析 |
| `version_unresolved` | unknown | C1-P4 `SEMANTIC_UNKNOWN_CODES` | `code` 无法解析成任何已知源 |
| `empty_set_not_proven` | unknown | C 冻结 | 空集闭合不可证 |
| `as_of_missing` | unknown | C 冻结 | `date_window` 模式下 `as_of` 缺失/非法 |
| `citation_version_mismatch` | violation | C 冻结 `VIOLATION_REASONS_BY_AXIS["stale_source"]` | citation 层 document/version 与 unit 不一致 |
| `date_intent_conflict` | violation | C 冻结 | 注解 `as_of` ≠ 运行期 `as_of`（产品侧一致性，非源侧日历） |
| `turn_not_executed` | unknown | C 冻结 | 该回合未执行（无使用集可读） |
| `turn_error` | unknown | C 冻结 | 该回合执行出错 |
| `replay_without_original` | unknown | C 冻结 | 重放缺原始记录 |
| `evidence_incomplete` | unknown | C 冻结 | 采集不完整（使用集/引用层不全） |

### 10.3 保留不产出（14；词表保留、本判据一律不得产出）

| 码 | 原类别 | 退役理由 |
|---|---|---|
| `no_dated_sources_lifecycle_checked` | N/A | 本轴 `not_applicable` 不可达（§5.7） |
| `source_deleted` | violation | 依赖源侧 lifecycle 字段；公开件不存在（第 5 缺口） |
| `source_not_published` | violation | 同上 |
| `source_not_active` | violation | 语义被 `stale_superseded_version_used` 取代（旧码比较运行期 active 标志，本判据比较**推导出的** active 身份） |
| `source_expired` | violation | 旧"日历比较"的产物；本判据由 `stale_out_of_window` 取代 |
| `future_source_as_current` | violation | 同上 |
| `lifecycle_unavailable` | unknown | 旧口径把"无 lifecycle"记为 unknown；本判据不再需要 lifecycle |
| `date_unresolved` | unknown | 窗口不可解析改由 `stale_window_unresolved` 表达 |
| `citation_source_unresolved` | unknown | 并入 `source_unresolved`（同一失败模式，避免两个码同义） |
| `stale_lifecycle_evidence_missing` | unknown | **正是本判据要消灭的码**；无条件追加它即 non-conformant |
| `version_mismatch` | unknown | 旧码比较"运行期号 vs 产品号"；本判据用 `stale_superseded_version_used` / `version_unresolved` |
| `stale_source_unresolved` | unknown | 并入 `source_unresolved` / `version_unresolved` |
| `stale_no_positive_refs` | unknown | 该码描述的是**合同投影**失败，不是判定失败；不进 verdict |
| `stale_positive_ref_not_record_level` | unknown | 同上 |

> **禁止同名改义**：任何码一旦进入本表，其语义不得在后续版本里悄悄改变；要改语义就换新码 + 升 `criterion_version`。

### 10.4 与既有 **18 码 reason 表**的关系（必须读懂的一节）

这是两套**不同层**的码，**不得混用、不得互相扩充**：

| | annotation reason 表 | determination reason 表（本文件 §10） |
|---|---|---|
| 字段 | `axis.reason`（`AxisAnnotation.reason`） | `case.reason` / 每轴判定结果 |
| 权威 | C 冻结件 `p2_hard_evidence.py` 的 `REASONS`，**恰 18 码**：`explicit_security` `explicit_privacy` `prompt_injection` `explicit_forbidden` `benign_business` `all_user_contexts` `explicit_single_target` `explicit_multi_target` `shared_policy` `no_entity_scope` `published_lifecycle` `explicit_temporal` `business_date_default` `ambiguous_semantics` `unresolved_target` `source_state_conflict` `third_state_required` `insufficient_annotation` | 本文件 §10（21 码 = 9 新 + 12 沿用） |
| 本判据的处置 | **不增、不删、不改义**。stale 轴可出现的注解 reason 仍是原集合的子集（`published_lifecycle` / `explicit_temporal` / `business_date_default` / `ambiguous_semantics` / `unresolved_target` / `source_state_conflict` / `third_state_required` / `insufficient_annotation`），**不新增第 19 码** | 新增 9 / 沿用 12，全部在 determination 层 |

四条硬规则：

1. **新增码不是新增 annotation reason**：把 `stale_superseded_version_used` 之类写进 `axis.reason` 会被冻结 loader 以 `annotation_axis_invalid` 拒绝 —— 这是**预期行为**，不得为了"能跑"去扩 18 码表。
2. 历史笔误纠偏：公开 schema 曾把该表写成"19 码"，实测枚举实数 **18**（`R-Q1A2-01` 已裁定按 18 码校验）。本判据沿用该裁定，**不**借机改数。
3. **不得写回 C 冻结件**：`backend/src/mktkb/evaluation/p2_hard_evidence.py` 是 C 冻结 12 对象之一（`fba6e606…3529b`），**不得原地修改**。本判据的码只活在新模块 / 新分析身份里。
4. 新码进入任何消费者前，必须同时落一份本表的机器可读副本 + 该副本的 SHA-256 绑定；无绑定的新码一律视为 `criterion_field_invalid`。

---

## 11. 与旧结果的关系（不可比声明）

1. **旧 `19/30` 与本口径不可比。** 旧数是"日历比较 + locator-only 匹配"的产物；本判据换掉了被比较对象本身（源日历 → 源身份）。两者不是同一把尺子，差值不表示产品变好或变坏。
2. **同样不可比的还有**：Q1a-3 新口径 `1/30`（29 unknown）、`cross_entity` 可判 `1 → 13/30`、C1-1 的"stale 可判 **0/30**"、以及 P4 下"stale 100% unknown"的预期。以上任何数字都**不得**与本判据的 pass 数并列成"改进曲线"。
3. **本判据不追溯解释 19/30。** 它不证明任何一题是产品失败，也不证明任何一题是量具缺陷；它只定义"从今往后 stale 轴怎么算"。
4. **不改变既有冻结面**：30 题 / 题集身份 / 标签 / 阈值 / 四状态 / 评分标准 / 旧卡字节 / 旧 evidence / 账本 / 预算 / GO **全部不变**（I-3）。
5. **不构成执行授权**：本判据是口径文本。真正按本判据重算需要（a）主人批准口径变更，（b）独立验收，（c）若涉及真实运行期证据还需新计划 + 新 GO。三者任一缺失即 `NOT-RUN`。
6. **不得据此声称**：T207 通过、质量放行、release / threshold / baseline 批准、P2 完成、分数提升。
7. **v1.1 专属**：`Q1A-RESCORE-20261114-r3` 的任何数值（11/30、0 硬失败、19 不可判；逐轴 stale 24 pass / 6 unknown）**不受本升版影响**，因为该重算显式使用 `version_state` 模式且 `fixture_sha256=null`、`windows=null`（见 `rescore-report-r3.md` §1–§4）。**报告里不得把 v1.1 说成"重算结果变了"。**

---

## 12. 实现契约：同一实现跑两种模式

### 12.1 单一入口

```python
determine_stale_case(
    criterion_version: str,      # 必须等于 "p2-stale-source-criterion/v1.1"
    grounding: Mapping,          # §8.1 grounding
    evidence: Mapping,           # §8.1 evidence
) -> CaseDetermination           # §8.2 单 case
```

- 一个函数、一条代码路径、`mode` 只影响 §5.4 的窗口分支与 pass 码选择。
- 任何固定码都以**等值比较**断言，禁止 `in FIXED_CODES` 之类弱断言（C1-P4 §7.3 的口径）。
- 任何非标量/不可哈希枚举值必须收敛成固定码 + unknown，禁止抛裸异常（`IR-01`）。

### 12.2 零数据集常量（grep 可查）

实现与测试里**不得**出现：`D01`…`D06`、`V01`…`V07` 字面量；`base_b0` / `pre_v05_without_v07` 等 scenario id 字面量；`2026-10-27` / `2026-10-28` 字面量；`version_number` 的期望值字面量；`ingest_batches == len+1` 这类关系常量。全部通过输入注入。

### 12.3 必测（合成语料，对应 §7 的 14 行 + §7.1 的 4 行）

| 组 | 覆盖 |
|---|---|
| G-1 双模式同一路径 | 同一 case 在 `version_state` / `date_window` 下分别产出 §7 第 1 与第 12/13 行的结果 |
| G-2 active 推导 | §7 的 1/2/3/4 行 + `UNDECLARED` 情形 + 位置并列情形 |
| G-3 歧义与零 active | §7 第 5 行 + F-2 + F-9 |
| G-4 使用集 | §7 第 6/7/8 行 |
| G-5 单向加严与窗口 active | §7 第 9/10/11 行（含"窗口损毁不制造 unknown"）+ §3.2 规则 5 的 `covering` 基数三态 + 规则 6 的 crosscheck 不一致 → `stale_active_version_ambiguous` + §3.4 的 V-1..V-6（L1 逐值重算；SHA 不符 / 投影冲突 → `stale_window_unresolved`） |
| G-6 折叠 | §7 第 14 行 + F-12（低优先级码不得丢失） |
| G-7 N/A 不可达 | 注解 N/A → `annotation_unknown`；任何路径 `not_applicable == 0` |
| G-8 码覆盖 | §10 的 21 码逐个至少一条断言；14 个保留码逐个断言"不产出" |
| G-9 形状 | 三式计数 + `passed == version_only + version_plus_date` + `NA == 0` |
| G-10 边界（v1.1 新增） | §7.1 的 B-1..B-4 逐条断言；任一按半开区间实现必须在此组失败 |
| G-11 边界 | 零网络 / 零 provider / 旧卡不改 / 无真实值输出 |

### 12.4 与既有消费者的关系

- 本判据**不复用** `p2_hard_evidence.py`（C 冻结）的 `_check_stale_source`；也不得把它改成 v1.1 语义。两者在区间语义上已对齐（闭区间），但**码集与规则仍不同**，不得互相替代。
- 本判据与 C1-P4 适配器 v2 的关系是**替换**关系：P4 现行无条件 `stale_lifecycle_evidence_missing` 的写法在本判据下属于 non-conformant。切换需新分析身份 + 独立验收，不得就地改 P4 产物。
- `cross_entity` / `cross_user` / `safety` 三轴**完全不受本文件影响**。
- **现有实现只认 v1，不得就地升版**：`backend/src/mktkb/evaluation/p2_stale_version_state.py` 的 `CRITERION_VERSION = "p2-stale-source-criterion/v1"`（`:118`），且 `:1312` 对不等的 `criterion_version` 直接拒绝。该文件的 SHA-256 已被 `Q1A-RESCORE-20261114-r3` 绑定为 `fed191446ed261873acd81d6b0fea0adcfd317aff4cc41bf8b60e0cb61fdcf59`，因此：
  - **不得**改它的 `CRITERION_VERSION` 或任何字节（会同时破坏 r3 的字节绑定与"历史件不可改"）；
  - 若要跑 v1.1，必须**新模块 + 新分析身份 + 独立验收**（`date_window` 分支本来也只在 v1.1 下才有意义）；
  - 由于 r3 走的是 `version_state`、`fixture_sha256=null`、`windows=null`，v1 → v1.1 的区间改动**进不到**它的任何一行判定，所以"没升版"不是缺陷，是正确状态。

---

## 13. 易被误读的四条（防 reverse-engineering）

| # | 误读 | 为什么错 |
|---:|---|---|
| M-1 | "本判据更容易 pass，所以选它" | pass 通道只有两条（active 身份一致 / 空集已证）；`stale_source` 仍全部 required，题级判定仍受其余三轴约束。选型理由是 §1 的**数据不存在**，不是分数。 |
| M-2 | "版本态过了，日期就不用管" | `date_window` 模式下日期是**必需** grounding；`version_state` 模式下附带窗口可单向加严。两种模式都不允许"跳过日期就宣称更强"。 |
| M-3 | "0 violations = 干净" | `unknown` 不是 0。任何"干净"结论必须同时给 reason 直方图（C1-P4 §4.4-1 的教训）。 |
| M-4 | "空集 pass 等于该题一定合格" | 空集 pass 只说明 stale 轴通过；题级仍需四轴折叠，且 `cross_user`/`cross_entity` 可能未知。 |
| M-5 | "v1.1 改了区间，所以 v1 的结论都作废" | 只有 `date_window` 模式的边界日结论受影响，且该模式**从未在任何已完成的重算里启用**（§11.7）。`version_state` 的结论逐条不变。 |

---

## 14. 保全与零调用（本轮）

| 项 | 结果 |
|---|---|
| HEAD / 分支 | `97b0066726e5b8d6f94cbc0b63a890084550c106` / `codex/p2-e2e`（未变） |
| 暂存区 | 0 项；commit 0；未 push；未新建 worktree / 未切分支 |
| 15 个 tracked modified | 15/15 路径逐条不变 |
| untracked 文件数 | 2370 → 2370（本轮只更新既有未跟踪文件，不新增文件） |
| 既有文件 | **零 tracked 修改**；本轮更新 4 个既有未跟踪文件（本文件 + 出题计划 + 语料改动规格 + L1）；v1 原文件原样保留 |
| 零真实调用 | 未调用产品 / 模型 / embedding / rerank / OCR / 裁判 / 检索 / 鉴权 / 余额；未启动服务；未建 GO |
| 零出站 | 本轮只做本地文件读取、哈希与本地 Python 复算；脚本内无 socket / http / requests / httpx 路径 |
| 私有边界 | 未读真实 H2 题面 / 标签 / 答案 / 目标值 / 私有密文 / key / `.env` / 保管会话 / runbook |

> 如实说明：本轮**未**运行 netguard 正对照。理由：本轮为纯文档写作 + 本地只读复算，未创建任何判定进程，也未新增 `evidence/` 目录。若复核要求形式化拦截回执，需另派并沿用既有 `evidence/netguard/` 逻辑。

---

## 15. 结论

1. `stale_source` 的被比较对象从**源侧日历**改为**源身份（doc_code + version）**；数据集按声明选择 `version_state` 或 `date_window`，同一实现两模式通用。
2. active 版本由 `scenario.source_indices` 的上传序（位置大者胜）确定，`version_number` 是标签与一致性校验，**不是**日期、不是排序依据；任何歧义（多 active / 0 active / 号序冲突）→ `stale_active_version_ambiguous` + `unknown`。
3. 判定：active 一致 → `passed`；被取代 → `stale_superseded_version_used`；active 但窗口不覆盖 → `stale_out_of_window`；空集已证 → `passed`（**不是** N/A）；版本/窗口不可解析 → `unknown`。**N/A 在本轴不可达**。
4. 固定码 21 个（新增 9 / 沿用 12），另 14 个旧码保留不产出；与 18 码 annotation reason 表**分层不混用**。**v1.1 的码集与 v1 逐字相同。**
5. **区间只有一种读法：闭区间**（`as_of == from` 与 `as_of == to` 均有效）。这是 v1.1 相对 v1 的唯一语义改动，且它与冻结分类器、产品检索过滤、设计规格 S1/S4 完全一致。
6. 12 条 fail-closed 边界 + 5 条防误读；与旧 19/30 **不可比**；不改 30 题 / 标签 / 阈值 / 四状态。
7. **本判据不改变 `Q1A-RESCORE-20261114-r3` 的任何数值**（该重算走 `version_state`）。
8. 本文件**不**构成通过、放行、发布或执行授权。生效需主人批准口径变更 + 独立验收。
9. **SC-2 已裁定（2026-11-15，同一版本澄清）**：v3 的 `date_window` 窗口唯一真相源是 L1（`p2-source-lifecycle/v1`）；判据不内嵌 windows、不另存第二份窗口表；消费方按 §3.4 的 V-1..V-6 做逐值重算 + SHA 绑定。版本仍 v1.1，区间语义与 21 码表不变。

---

## 附录 A：v1 → v1.1 变更记录（逐条，可核）

| # | 位置 | v1 | v1.1 | 性质 |
|---:|---|---|---|---|
| 1 | 标题 / 全篇版本号 | `p2-stale-source-criterion/v1` | `p2-stale-source-criterion/v1.1` | 版本号 |
| 2 | §3.2 规则 2 | `effective_from <= as_of < effective_to`（左闭右开） | `effective_from <= as_of <= effective_to`（闭区间）+ 四条边界断言 | **唯一语义改动** |
| 3 | §3.2 规则 5 的 `covering` | 引用规则 2（半开） | 引用规则 2（闭），并注明"覆盖 = 闭区间判定" | 随之对齐 |
| 4 | §5.4 日期叠加表 | "覆盖"未标开闭 | 三处显式写"含 `as_of == from` / `== to`" + I-8 补充段 | 随之对齐 |
| 5 | §7 示例 9/10/13 | 窗口写作 `[a, b)` | 窗口写作 `[a, b]` | 随之对齐 |
| 6 | §7.1 边界四断言 B-1..B-4 | 无 | 新增 4 行 | 新增（升版断言） |
| 7 | §8 / §12.1 / §3.3 | `criterion_version` = `/v1` | `/v1.1` | 版本号 |
| 8 | §2 I-8 | 无 | 新增"区间只有一种读法" | 新增不变量 |
| 9 | §13 M-5 | 无 | 新增"v1.1 改了区间不等于 v1 结论作废" | 新增防误读 |
| 10 | §11.7 | 无 | 新增"r3 数值不受影响" | 新增不可比条款 |
| 11 | §12.3 G-10/G-11 | G-10 边界 | G-10 = 边界四断言；G-11 = 原 G-10 | 重编号 |
| 12 | §14 保全 | v1 那一轮的数 | 本轮的实测数 | 逐轮更新 |
| 13 | §3.4（新增） | 无 | SC-2 裁定：v3 窗口唯一真相源 = L1；判据不内嵌 windows；V-1..V-6 校验算法 | **同版本澄清**（不改区间/码表） |

**明确未改**：§1（X-1..X-4）、§2 I-1..I-7、§3.1（`version_state` 全文）、§3.2 规则 1–7 的正文、§4（R-AV-1..R-AV-6）、§5.1–§5.3、§5.5–§5.7、§6、§9（F-1..F-12）、§10（21 码 / 14 保留码 / 18 码分层）、§11.1–§11.6、§12.1/§12.2/§12.4、§13 M-1..M-4、§15 的 1–4 与 6–8 条。§12.3 只在 G-5 内追加 §3.4 的测试项，未增删分组或固定码。
