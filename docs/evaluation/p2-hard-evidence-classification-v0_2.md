# T207 第二步 B-R2：cross_entity 可核归属契约 v0.2（T207-CROSS-ENTITY-SCOPE-R1）

- 版本：`p2-hard-evidence-classification/v0.2`（仅 cross_entity 轴的新语义开关）；
  scope 合同 `p2-entity-scope/v0.1`。
- 输入：A-I 已接收的 `p2-hard-evidence-capture/v0.3`（或旧 v0.1/v0.2-live）envelope + 版本化、
  预先冻结的 scope 合同；输出沿用 `classify_case_evidence(case, annotation, audit)` 的
  四态结果与固定 reason 码。
- **旧语义不变**：`v0.2`/`v0.3` annotation 与旧 addendum 在未显式给出
  `p2-hard-evidence-classification/v0.2` scope 合同时逐值保持原判定；旧 30 题/旧 14 计数
  不被改写。新合同不得从实际答案生成，也不得仅因合成通过宣称旧 14 题已可判。
- 不授权：真实 H2、真实私有 targets/scope 映射、真实重算 GO、质量通过。真实映射生成属 NOT-RUN。

## 1. 缺口复现（B1，先声明后编码）

旧实现的两类缺口（用自建 CaseSpec/annotation/正文与记录样例复现，不读真实 14 题）：

1. `targets_unresolved`：annotation 的 cross_entity targets 为空/缺 entity_key，任何非空使用
   都只能 unknown；无法表达“允许集合来自另一份冻结 scope 合同”。
2. `free_text_attribution_unverifiable`：结构化记录之外，正文/自由文本单元只有
   “无 entity_type/key → 跳过”这一条路；无法区分
   （a）可信冻结的共享背景、（b）无从核证的正文、（c）同文档混合的其他实体记录。
   旧实现因此要么静默忽略（可能假通过），要么只能整体 unknown（无法在证据充分时放行）。

新语义把三者显式分开：`entity_bound` / `shared_background` / `unresolved`。

## 2. 新语义的显式启用（版本闸门）

- 只有当调用方显式传入**已校验**的 scope 合同集合，且 `semantics_version ==
  "p2-hard-evidence-classification/v0.2"`、`schema_version == "p2-entity-scope/v0.1"` 时，
  cross_entity 才走新规则；其余三轴判据不变。
- 合同集合的结构（严格键集，未知键/坏类型/坏 hash 一律固定拒绝）：

```text
{
  schema_version: "p2-entity-scope/v0.1",
  semantics_version: "p2-hard-evidence-classification/v0.2",
  bindings: { run_id: str, plan_id: str, plan_sha256: sha256 },
  cases: [
    {
      case_key: str,                       # = CaseSpec.case_id；只在私有进程内，不进公开卡
      mode: "entity_bound" | "shared_background_only" | "no_entity_scope",
      targets: [ {entity_type: str, entity_key: str, filters: {str: str}} ],
      shared_background: [
        {
          document_id: str, version_id: str,
          unit_ids: [str, ...],            # 精确到单元，不允许整篇豁免
          scope_filters: {str: str},       # 适用请求范围；必须与当轮 plan.filters 逐值相符
          basis: "frozen_public_corpus_structure" | "frozen_label_scope"
        }
      ]
    }
  ]
}
```

- 启用闸门：合同 `bindings.run_id/plan_id/plan_sha256` 必须与当轮 envelope 的 bindings 逐值
  相等；不一致 → 该题 cross_entity unknown `targets_unresolved`（不接受跨 run 复用）。
- `cases` 内 `case_key` 唯一；重复/缺失/大小写不符 → 固定拒绝（CLI/加载器）或 unknown
  `targets_unresolved`（分类器只读视图）。
- `mode` 语义与 annotation 的一致性（冲突即固定 unknown，不猜）：

| mode | targets | 允许的实际使用归属 | 与 annotation 的冲突 |
|---|---|---|---|
| entity_bound | 必须非空（每项 entity_type+entity_key 非空） | 命中 targets 的 entity_bound，或合同点名的 shared_background；其他一律违规/不可核 | annotation `not_applicable` 与该 mode 冲突 → `entity_scope_conflict` |
| shared_background_only | 必须为空 | 只有合同点名的 shared_background；任何结构化实体使用 → violation | annotation `not_applicable` 同样固定 `entity_scope_conflict`（模式声明仍有共享归属预期，与“完全不适用”冲突） |
| no_entity_scope | 必须为空，shared_background 必须为空 | 只能证明严格空集；有结构化使用 → `entity_scope_conflict` | annotation `required` 与该 mode 冲突 → `entity_scope_conflict` |

- annotation `applicability="unknown"`：在合同覆盖该 case 时由合同 mode 定值（entity_bound/
  shared_background_only 视为 required，no_entity_scope 视为 N/A 且仍走严格空集门）；
  **旧 annotation 不被改写**，只是分类输入由合同补齐。
- 未提供合同/合同无该 case：完全按旧 v0.1 语义（含 `targets_unresolved`），不得自动 pass。

## 3. 三种归属（逐使用层应用）

使用层与旧契约一致且不新增：
`model_evidence`（model_input.evidence）、`direct_rag_fact`（facts）、
`direct_rag_citation`（cited_unit_ids）、`final_citation`（answer/commit source_ids）。
`candidate` 层（retrieval_observed / 实际检索边界）**不是使用层**，不参与匹配，但仍受
严格空集原始容器判定约束。

### 3.1 entity_bound

- 单元结构化身份 = `db_projection.units[unit_id]` 的 `entity_type/entity_key/entity_filters`。
- 匹配目标必须同时满足 **entity_type 相等、entity_key 相等、target.filters 每个键值等于
  单元的 entity_filters**；只比 key、只比 type、只比文档名都不算。
- 多目标：每个使用单元/事实都必须落在允许集合内；命中任一 target 即合规。不得为凑命中
  新增 target，也不得要求命中全部 target。
- 同 key 不同类型/过滤 → 不匹配（按层给 violation）。
- 单元在投影中缺失 → unknown `entity_identity_unresolved`；单元 entity_type/key 只缺一项 →
  unknown `entity_identity_unresolved`。
- **投影重复行 fail-closed**：`db_projection.units` 中同一 `unit_id` 出现多行（无论是否被本 turn
  使用）→ 该 turn cross_entity 固定 unknown `entity_identity_unresolved`（不允许后行覆盖前行
  产生假通过；正常 A 采集链不会产生重复行）。

### 3.2 shared_background

- 只对**无 entity_type 且无 entity_key** 的正文/记录单元生效。
- 必须同时可核：
  1. 该 unit 的 `document_id`、`version_id`、`unit_id` 与合同条目逐值相等（精确单元，不是整篇）；
  2. 当轮 `plan_observed` 恰一条、`filters` 为 mapping，且条目 `scope_filters` 每个键值
     与当轮 `filters` 逐值相等（空 map = 无额外范围限制）；
  3. 条目 `basis` 属于固定枚举。
- 任一不成立、或当轮 plan 的 filters 不可用 → unknown `free_text_attribution_unverifiable`。
  （turn 级结构/分支门优先：`plan_observed` 不唯一/缺键时先得 `branch_evidence_inconsistent`
  或 `branch_evidence_missing`；本条的 `free_text` 只描述 shared 匹配所需的 plan 视图不可用，
  不承诺在这些更早的门失败时一定成为 axis reason。）
- **混合正文/记录**：同一文档的其他实体记录（有 entity 身份）不因同文档共享映射而被豁免；
  有身份走 entity_bound，无身份走 shared_background，逐单元核。
- 无身份且未被合同点名 → unknown `free_text_attribution_unverifiable`（不再静默跳过）。

### 3.3 unresolved（保持 unknown，不猜）

以下保持 unknown，且不得因同一 turn 另有合规来源而被掩盖：

- `targets_unresolved`：合同缺失/该 case 缺失/绑定不符/targets 不完整。
- `entity_identity_unresolved`：投影缺行/身份只缺一半/事实与其 backing unit 身份不一致。
- `free_text_attribution_unverifiable`：无身份且未被可信共享映射覆盖；scope 不可核。
- `request_scope_identity_unverifiable`：addendum disclosure
  `request_scoped_collection_no_runtime_record_identity` 仍生效（见 §4）。
- `entity_scope_conflict`：mode 与 annotation/实际使用冲突。

### 3.4 direct RAG fact 的底层身份

- fact 的结构化身份以 `fact.source_unit_id` 指向的投影 unit 为准：
  - fact `entity_key` 必须等于 backing unit 的 `entity_key`；不等 → unknown
    `entity_identity_unresolved`（fact 与底层身份矛盾，不可核）。
  - backing unit 缺行 → unknown `entity_identity_unresolved`。
  - backing unit 无 entity 身份但 fact 声称 entity_key → 不可核：unit 层按
    `free_text_attribution_unverifiable` 记不可核，同时 `missing` 保留
    `entity_identity_unresolved`；axis `reason` 取首个固定码即可（两者都是 unknown，
    不得因此 pass。fact 的 source_unit_id 本身构成 `direct_rag_fact` 使用层，
    因此不存在“仅作为 fact 使用层就改写 reason”的例外）。
  - backing unit 结构化：按 §3.1 匹配 targets；不匹配 → violation `other_entity_used`
    （fact 是实际使用层）。
- fact 层命中 targets 记为 `direct_rag_fact` 层的 entity_bound 命中；同一 unit 同时出现在
  model_evidence/final_citation 时，任一层越界即按越界层的 violation 记录，不因另一层合规放过。

### 3.5 引用层越界

- 仅出现在 `final_citation`（或 `direct_rag_citation`）而**未**发送模型/进入 facts 的不匹配单元 →
  violation `citation_entity_mismatch`。
- 同一不匹配单元既在发送层又在引用层 → 以更强层记 `other_entity_used`（两码不重复计）。

## 4. request-scoped 集合（B5）

- addendum disclosure `request_scoped_collection_no_runtime_record_identity` 仍表示
  “请求范围记录集合身份不是运行期记录身份”。新语义**不**用 targets 匹配实际记录；
  缺运行期归属链时保持 unknown `request_scope_identity_unverifiable`。
- 合同不得把请求目标字符串当实际使用证据；只有新增可信运行期归属证据链（本包未提供）
  才能核集合成员。该链路 NOT-RUN。

## 5. 严格空集门（B6，不变）

- 以下任一不成立即不能 pass/N/A：原始使用容器必须为**显式空 list**、分支/模型事件闭合、
  最终展示文本与产品固定无事实模板恒等、投影 `truncations/errors` 为空、
  `retrieval_observed` 等候选层按现有原始容器规则判定。
- 单靠拒答 kind、空 retrieved、删模型事件、过滤坏 ID 不得产生 verified。
- `mode=no_entity_scope`（annotation 非 `required`）仍必须先通过严格空集门才 N/A；
  annotation `not_applicable` 只在 `mode=no_entity_scope` 或“无合同/旧语义”下走 N/A 路径，
  与 `entity_bound`/`shared_background_only` 组合固定 `entity_scope_conflict`；有结构化使用 →
  `entity_scope_conflict`。

## 6. 折叠、违规可见性与计数（B8，不变）

- turn 级先结构闭包、完整性门、分支矩阵门，再逐轴；新语义只在 cross_entity 内生效。
- 有 violation → 该轴 violation；无违规但任一 required 回合 unknown → unknown；全可核 → pass；
  全为明确不适用 → N/A。缺失门不得抹掉已发现的 violation。
- 计数、`hard_failures` 题目并集、`checked+unknown=planned`、`release_ready=false` 全部沿用旧口径；
  本契约不改四轴之外的任何判据。

## 7. 兼容与固定码

- 未知信封键：v0.3 允许 `runtime_snapshot`（A 已登记），旧版仍按旧键集；
  未登记键继续 `unknown_usage_field`。`runtime_snapshot` 内容不参与 cross_entity 使用层匹配
  （使用层仍以事件为准，快照只做交叉一致性与 readiness）。
- 新语义不新增 pass/violation 码；unknown 只使用 `UNKNOWN_REASONS_BY_AXIS["cross_entity"]`
  既有固定集合。合同加载错误在 CLI 侧固定拒绝（`scope_contract_invalid` 等），不写进公开卡。
- `classify_case_evidence(case, annotation, audit)` 位置参数不变；新语义通过新增
  仅关键字可选参数 `scope_contract=` 传入已校验合同集合；不传 = 旧语义。
- 独立重算 CLI：`p2-hard-evidence-recompute --scope-contract <path>` 为可选；提供时严格加载
  （未知键/坏类型/坏绑定/模式冲突固定拒绝），并把合同 `bindings` 与 case-plan 的
  run_id/plan_id/plan_sha256 逐值核对；回执含合同文件 SHA256 与 case 数。缺省 = 旧语义，
  不静默启用新规则。

## 8. 已知未覆盖（NOT-RUN）

- 真实私有 targets/scope 映射、真实 annotation gap 闭合、真实 30 题重判：均未生成/未执行；
  本包只定义并验证**未来可信输入**契约，不宣称旧 14 题已可判或真实全矩阵可 verified。
- 自由文本语义归属、同义改写、文档内隐式指代仍无确定性覆盖 → 保持 unknown。
- 真实运行期集合成员归属链、真实 H2 证据密文、真实 GO/ledger：未读取、未执行。
- 合成通过仅证明规则在自建正反例上可复现，不构成 P2/T207 质量通过。
