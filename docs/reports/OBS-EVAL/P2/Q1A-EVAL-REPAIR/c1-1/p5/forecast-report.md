# C1-P5 零调用复跑收益预判（forecast）

- 角色：**保管执行**（2026-11-12 批准的两个隔离保管角色之一的新上下文）。非开发、非验收、非经理。
- 基线：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`、暂存区 0 项、0 commit。
- 工作区：`D:\GPT项目\市场部AI知识库`。
- 边界：**零真实调用**（netguard 正对照 4/4 拦截，见 §8）；只读旧证据与冻结件；不改 C 冻结 12、旧卡/账本/GO、合同 v1/v2、Q1a-1/1b 与 P3/P4 模块与契约、30 题/标签/阈值；不 stage/commit/push；不新建 worktree/切分支；不派子助手。
- 读取边界：题面/原标签/保管附件只在进程内解密用于确定性计算；**不呈现、不落盘、不回传**题面/答案/目标值/key；本报告与聚合不含题号（轴一律用不透明标签 `Nnn`；按 `SHA256(case_id)` 升序编号，映射不落盘，复跑脚本可复现）。
- 结论：**`COMPLETE`**（本包范围内；不是验收、不是 GO）。

## 0. 硬结论

**`C1-2 不值得签 GO（应转 C2）`**。

一句话理由：按 P4 交付的消费侧适配 v2 同时接管两轴时，`cross_entity` 的现实可判/通过为 **13/30**，但 `stale_source` 是 **0/30**（12 条被固定的 `stale_lifecycle_evidence_missing` 拦下、15 条 ref 身份不可解析、3 条空集无法证明）；**题级 pass 现实值 0、理论上界 3**，都远低于 24/30。花约 108 次真实请求换不到可用干净分数，且 `cross_entity` 的 1→13 收益用旧证据**零调用**即可复现（§5.3），复跑不增加可判化。

## 1. 输入与身份

| 输入 | 实测 |
|---|---|
| 合同 v2 密文 | `7ed0bf41…e260` / **99128 B**（与任务给定一致） |
| 合同 v2 schema | `b98f9f4a…ce25`（与 P4 钉住值一致） |
| 旧 run binding payload | `291cfec9…65d4`（与 R2 身份一致） |
| 旧证据 | 4 run / **36 回合** / **30 题全执行**；全部 `p2-hard-evidence-capture/v0.2-live`；per-run card、seal tree、逐文件 SHA 与 R2 记录一致（§8.2） |
| 公开语料投影 | 4 份公开件 SHA 与 R2 输入一致；产品名→文档槽 **11/11** 可映射、0 歧义；记录索引无冲突 |
| 旧逐题使用单元 | 按 P3 九层口径**逐题去重 86 个**（按回合口径 92 个；R2 报告 91 用的是 Q1a-3 `_used_layers`，口径差 ±1，不影响本包计数） |

## 2. 方法（零调用、可复算）

旧证据是 v0.2 回合 envelope，**没有** v0.3 快照。本包不伪造 v0.3 快照，而是按 P3 采集器的公开/只读语义，把每个旧回合**确定性重建**为 v0.3 风格的 `record_identities` / `effective_temporal` / `empty_use_scope_input`：

- 使用层：只读调用 `p2_evidence_snapshot_v03._extract_use_layers` / `_extract_candidate_layers`（9 使用层 + 3 候选层，与 v0.3 契约 §2.1 同源）。
- 记录身份：只读调用 P3 的 `_locator_kind` / `_doc_code_for` / `_base_doc_code` / `_normalize_record_index`，按 R-RC-1..5 用公开语料 `(base_doc_code, sheet, row)` 反查 `record_code`。
- 日期/版本：`plan_observed.as_of`（36/36 回合唯一）+ `db_projection.units.version_number`；v0.2 无 `runtime_snapshot`，故 `product_version_number` 恒空、`retrieval_use.availability` 无法重建（见 §7 残余）。
- 判定：只读调用 `p2_evidence_axes_adapter_v2.determine_cross_entity` / `determine_stale_source`，输入合同 v2 视图 + 重建快照视图；不改适配器、不绕过其固定码。
- 独立复核：另写一版**不 import 适配器**的键空间检查（合同角色 filters + `chunking.normalize_field`），16 轴结论与适配器逐轴一致（13/3/0/0）。

所有明文只在进程内存；输出只含计数、固定码、层名、不透明轴标签。

## 3. 键空间判定（16 个「具可匹配目标」的 cross_entity 轴）

匹配目标按合同 v2 §3.4 独立重算：`entity_type ∈ {item,store,record}` ∧ `entity_key` 非空 ∧ `filters` 键全为 6 个角色名。共 **16** 轴（与公开聚合 `axes_has_matchable_target = 16` 一致）。

| 轴 | criterion | 可匹配目标 | 使用单元 | 键空间结论 | cross_entity（v0.3 模型） | stale_source（v0.3 模型） |
|---|---|---:|---:|---|---|---|
| N14 | structured_target | 1 | 1 | `aligned` | passed | unknown / lifecycle |
| N07 | structured_target | 1 | 1 | `aligned` | passed | unknown / lifecycle |
| N16 | structured_target | 1 | 1 | `aligned` | passed | unknown / lifecycle |
| N13 | structured_target | 1 | 1 | `aligned` | passed | unknown / lifecycle |
| N04 | structured_target | 1 | 1 | `aligned` | passed | unknown / lifecycle |
| N12 | multi_target | 2 | 2 | `aligned` | passed | unknown / lifecycle |
| N26 | structured_target | 1 | 1 | `aligned` | passed | unknown / lifecycle |
| N08 | structured_target | 1 | 1 | `aligned` | passed | unknown / lifecycle |
| N30 | structured_target | 1 | 1 | `aligned` | passed | unknown / no_positive_refs |
| N09 | structured_target | 1 | 0 | `missing_v03_field` | unknown / empty_set_not_proven | unknown / empty_set_not_proven |
| N20 | structured_target | 1 | 1 | `aligned` | passed | unknown / lifecycle |
| N24 | structured_target | 1 | 0 | `missing_v03_field` | unknown / empty_set_not_proven | unknown / empty_set_not_proven |
| N18 | structured_target | 1 | 1 | `aligned` | passed | unknown / lifecycle |
| N10 | multi_target | 2 | 1 | `aligned` | passed | unknown / lifecycle |
| N05 | multi_target | 2 | 0 | `missing_v03_field` | unknown / empty_set_not_proven | unknown / empty_set_not_proven |
| N02 | structured_target | 1 | 1 | `aligned` | passed | unknown / lifecycle |

**三个计数（16 轴）**

| 结论 | 计数 | 含义 |
|---|---:|---|
| `aligned` | **13** | 运行期 id 型键 + 角色值，按 canonical 规则逐值对齐到合同名称型目标；13 轴全部 `key_space_aligned_by_role_filters` |
| `entity_key_space_incompatible` | **0** | 无“两侧同空间但逐值不同”的失配；也无“只有 `*_id` 缺角色值”的不可对齐 |
| `missing_v03_field` | **3** | 该轴没有任何使用单元；唯一可判路径是 v0.3 空使用集输入，而这三题连 model/direct-RAG 事件都没有（9 层里 6 层未观测） |
| `other_fixed_code` | **0** | — |

补充事实：13 个 `aligned` 轴的运行期行**不是**名称型键，而是 `…|id:…`；合同目标是名称型 canonical 键。能对齐完全依赖 P4 §5.3 的“角色值复算 canonical key”规则，**不是**前缀/包含/模糊匹配。独立复核（不 import 适配器）得到完全相同的 13/3/0/0。

## 4. v0.3 字段依赖度

旧 v0.2 证据没有 `request_owner` / `record_code` / 实际 `as_of` / `runtime_snapshot.retrieval_use`。逐项：

| 字段 | 旧证据 | 影响面 | 结论 |
|---|---|---|---|
| `request_owner` | 无该块（`turn.authenticated_user_id` 在） | 两轴判定都不读它 | **不影响** |
| `record_code`（v0.3 派生） | 无 | `stale_source` ref 解析；`cross_entity` 的 doc_code 级降级 | cross_entity：**0 轴依赖**；stale：15 轴 ref 可解析依赖它 |
| 实际 `as_of` / `effective_temporal` | 可由 `plan_observed` 确定性重建（36/36） | stale 日期意图 | 12 条 matched-record 轴依赖它；补齐后仍被 lifecycle 拦下 |
| `runtime_snapshot.retrieval_use` | v0.2 无 | 空使用集 `turn_status` | 3 条空集轴依赖它；**即使补成 complete，6 个使用层仍未观测**，证明仍失败 |
| `document_versions` | 可由 `unit.version_number` 重建 | stale 版本一致性 | 可重建；不改变结论 |

**计数**

- `cross_entity`：**13 轴不依赖任何 v0.3 字段即可判**；**3 轴**依赖 v0.3 空使用集输入（`missing_v03_field`）；**0 轴**依赖 `record_code`/doc_code。
- `stale_source`：**30/30 轴在 v0.2 下不可判**。其中 **15 轴** ref 身份可解析（12 条 matched-record + 3 条空集）、依赖 `record_code` + `as_of`；**15 轴**是结构性不可解析（10 条 ref 非记录级、5 条无正向 ref），补 v0.3 也救不回。
- 关键：**即使 v0.3 字段全补齐，stale 可判仍为 0**——12 条 matched-record 轴被适配器**无条件**追加 `stale_lifecycle_evidence_missing`（P4 §8.2 刻意 fail-closed，v0.3 不含逐源 lifecycle）；3 条空集轴的 6 个使用层不观测。**v0.3 不是 stale 的解锁键。**

## 5. C1-2 预判区间

### 5.1 现实（v0.3 采集可用；产品行为与旧运行同构）

| 项 | 数值 | 推导 |
|---|---:|---|
| cross_entity 可判 | **13/30** | 16 个可匹配轴中 13 轴键空间 `aligned` 且全部使用行 `matched`；3 轴空集无法证明 |
| cross_entity 通过 | **13/30** | 13 轴均 `cross_entity_targets_match_ok`；0 violation |
| stale_source 可判 | **0/30** | 12 lifecycle + 3 empty + 10 非记录级 + 5 无 refs，全部 unknown |
| stale_source 通过 | **0/30** | 无空集证明、无日期冲突 |
| **题级 pass（两轴都 pass）** | **0/30** | 交集为空 |

题级口径说明：本表的“题级 pass”是**两轴交集**（cross_entity 与 stale_source 都 pass），是四轴题级 pass 的**必要条件**；再叠加 safety / cross_user 只会更低，不会更高。

其余 17 条 cross_entity unknown 的固定码：`shared_background_runtime_identity_unavailable` 7、`targets_missing` 4、`targets_unresolved` 2、`target_granularity_incomparable` 1、`empty_set_not_proven` 3。这些是**合同/模式/产品粒度**问题，不是 v0.3 采集能解决的。

### 5.2 乐观（v0.3 采集补齐 + 所有非键空间问题解决；合同/适配器不变）

| 项 | 数值 | 推导 |
|---|---:|---|
| cross_entity 可判 | **16/30** | 全部 16 个可匹配轴；假设 3 个空集轴在复跑中实际使用实体单元（行为假设） |
| cross_entity 通过上界 | **16/30** | 键空间已证明可对齐；通过取决于产品是否用对实体 |
| stale_source 可判 | **3/30** | 只有 3 个空集轴有 pass 通道；12 条 matched-record 轴被 lifecycle 固定码封死 |
| stale_source 通过上界 | **3/30** | 需这 3 题在复跑中发出完整 9 层事件且计数全 0（当前 6/9 层未观测） |
| **题级 pass 上界** | **3/30** | 3 个空集轴同时满足 cross 与 stale 才可能 |

若“乐观”只补 v0.3 字段、不假设产品事件链变化，则 stale 仍为 **0**、题级 pass 仍为 **0**；cross 为 13（或 16，取决于复跑是否使用实体单元）。**没有任何乐观口径能接近 24/30。**

### 5.3 与已接收基线对比

| 口径 | cross_entity pass | stale_source pass | 题级 pass |
|---|---:|---:|---:|
| Q1a-3 R2（Q1a-1b 判据，已接收基线） | 1 | 13 | **1** |
| C1-2 现实（P4 适配器接管两轴） | **13** | **0** | **0** |
| C1-2 乐观上界 | 16 | 3 | 3 |

两个要点：

1. **cross_entity 的 1→13 是量具收益，不是复跑收益**：本预判本身就用旧证据 + 合同 v2 + 适配器 v2 零调用算出 13 个 pass。C1-2 复跑不会让 13 变多，只会用新回答替换旧回答。
2. **stale_source 从 13 掉到 0 是判据替换的后果**：Q1a-1b 的 `lifecycle_dates_ok` 在适配器 v2 里被更严的 fail-closed 取代。于是 C1-2 按设计会把干净分数从 1 拉到 **0**——不是产品变差，是判据变严且 v0.3 补不上 lifecycle 证据。

## 6. 决策与替代

### 6.1 硬结论

**`C1-2 不值得签 GO（应转 C2）`**。

依据（按强度）：

1. 现实题级 pass **0**、乐观上界 **3/30**，24/30 门槛在两种口径下都不可达；按经理回执 §11 的门槛，不应先用 ~108 请求试错。
2. `stale_source` 在适配器 v2 下**没有非空 pass 通道**：12 条 matched-record 轴被 `stale_lifecycle_evidence_missing` 无条件封死；这是判据/证据契约缺口，不是采集缺口，v0.3 补不了。
3. `cross_entity` 的收益已零调用兑现（本包即证明），复跑只刷新产品行为，不增加可判化。
4. 唯一可能值得复跑的变体：**保留 Q1a-1b 的 stale 判据（13 pass）+ 适配器 v2 只接管 cross_entity（13 pass）**。此时题级 pass 取决于两套 13 条的交集；R2 未持久化逐题值（`detail_export=false`），**交集无法从公开聚合推出**（只能界定在 0..13），必须先做一次零调用交集测量再谈 GO。这属于判据分叉决策，是 C2 范围，不是本包能签的。

### 6.2 建议的 C2 入口（不改任何冻结件）

- 先做 **零调用交集测量**：用 Q1a-1b 的 stale 逐题状态与适配器 v2 的 cross_entity 逐题状态做交集，得到“混合口径”的真实题级 pass 上界；若交集 ≤3，C2 也无需真实调用即可否掉。
- 若要走“stale 可判”的正路，需要**新契约版本**补逐源 lifecycle（deleted/published/active/生效区间）并明确“空集/未走分支”的观测语义（适配器空集证明 vs 冻结原语的 2 条 proven 差异，见 §7）。这属于 C2 的新计划 + 新 GO，不是 C1-2。

## 7. 残余与未决（如实，不覆盖）

1. **多回合组合未定义**：适配器一次只吃一个 case 的建议快照；本批 4 题 2 回合、1 题 3 回合。本包按“同题各回合使用单元并集”组合；C1-2 必须显式定义组合规则，否则逐题值可能与本预判不同（影响面：5 题）。
2. **1 条 stale 轴是 forbidden-only**：适配器把 `target_refs` 里的 forbidden ref 也当正向 ref，得到 15 条 ref 可解析；公开覆盖口径是 14 条 positive-ref-resolved + 6 条 no-positive-refs。定义差异，不改变 stale=unknown 的结论。
3. **空集证明口径分叉**：冻结原语判 2 回合 proven（其中 1 回合属于可匹配 cross 轴 N09），适配器 v2 判 0（要求 9 层全 observed + retrieval 观测为空）。这是判据差异，需经理裁决；本包不表决。
4. **v0.2 没有 `runtime_snapshot`**：`retrieval_use.availability` 无法重建；本包在 v0.3 模型里假设 `complete`，但它不能凭空造出缺失的 model/direct-RAG 层，故不改变空集结论。
5. **doc/record 索引是公开规则重建**：产品名→文档槽 11/11、记录反查无冲突；但没有真实 v0.3 快照可交叉核对，`record_code` 相关结论只用于 stale（且 stale 仍 unknown）。
6. **本包不产生真实 H2 分数**：13/13 是对旧证据的确定性重判，不是 C1-2 的复跑结果；产品在新一轮的实际行为未知。

## 8. 零调用与保全

### 8.1 零真实调用

- 进程级出站守卫（`evidence/netguard/`，逻辑同已接收的 C1-P4 守卫）随 `PYTHONPATH` 注入；主计算进程退出回执：`socket_connect_external=0`、`connect_ex=0`、`create_connection=0`、`dns_getaddrinfo=0`、`http_client=0`、`httpx=0`、`loopback=0`、`blocked=0`（`04-forecast-zero-call.json`）。
- 正对照 4/4 拦截：外部 DNS、`create_connection`、裸 `socket.connect`、`http.client.connect` 全部 `OSError`（`03-netguard-positive-control.json`，`all_blocked=true`）。
- 未跑真实 H2、未跑 C1-2、未调用产品/模型/embedding/rerank/OCR/裁判/检索/鉴权/余额、未新建 GO、未启动服务。

### 8.2 保全（终态实测，`06-preservation-check.out.json`）

| 项 | 结果 |
|---|---|
| HEAD / 分支 / 暂存 | `97b00667…` / `codex/p2-e2e` / **0 项** |
| C 冻结 12 | **12/12 哈希全等** |
| 15 个 tracked modified | **15/15 哈希全等**（与 P4 接收态一致） |
| 合同 v1 密文/schema | 哈希等于 R2 记录 |
| 合同 v2 | `7ed0bf41…e260` / 99128 B / schema `b98f9f4a…ce25`（只读） |
| 旧 run | binding 文件+payload 哈希等于 R2；4 卡 SHA、4 个 seal tree、逐 evidence 文件 SHA 全等 |
| Q1a-1 / Q1a-1b 模块与契约 | 4 个哈希全等于 R2 |
| P3/P4 模块与契约 | 只读；mtime 均早于本会话开始 |
| 本包新增 | 仅 `c1-1/p5/` 下文件；未 stage/commit/push |

### 8.3 隐私

`05-privacy-scan.out.json`：对 p5 全部交付物做进程内 needle 扫描（题面/参考答/expected/forbidden/目标 entity_key/filter 值/记录键/key 材料 + Fernet key 形态），`clean=true`、0 hit。报告与聚合不含题号（轴用 `Nnn`）、题面、答案、目标值、key、日期值。

## 9. 交付清单

| 文件 | 说明 |
|---|---|
| `c1-1/p5/forecast-report.md` | 本报告 |
| `c1-1/p5/forecast-aggregate.json` | 仅计数/分布/固定码；无题号/题面/答案/目标值 |
| `c1-1/p5/evidence/00-probe-shape.{py,out.json}` | 合同/旧证据形状普查 |
| `c1-1/p5/evidence/01-forecast.{py,out.json}` | 主预判（P3 语义重建 + 适配器只读） |
| `c1-1/p5/evidence/02-independent-keycheck.{py,out.json}` | 不 import 适配器的独立键空间复核 |
| `c1-1/p5/evidence/03-netguard-positive-control.{py,json}` | 守卫正对照 |
| `c1-1/p5/evidence/04-forecast-{stdout.json,stderr.txt,zero-call.json}` | 主计算的 stdout/stderr/出站回执 |
| `c1-1/p5/evidence/05-privacy-scan.{py,out.json}` | 敏感串扫描 |
| `c1-1/p5/evidence/06-preservation-check.{py,out.json}` | 保全比对 |
| `c1-1/p5/evidence/07-build-aggregate.{py}` | 聚合构建（白名单） |
| `c1-1/p5/evidence/netguard/` | 进程级守卫（P4 逻辑，前缀改为 c1p5） |

复算（零调用）：

```bash
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p5/evidence/00-probe-shape.py
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p5/evidence/01-forecast.py
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p5/evidence/02-independent-keycheck.py
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p5/evidence/05-privacy-scan.py
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p5/evidence/06-preservation-check.py
.venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p5/evidence/07-build-aggregate.py
```
