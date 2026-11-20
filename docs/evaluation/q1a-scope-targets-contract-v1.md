# Q1a 真实 scope/targets 合同 v1（`q1a-scope-targets-contract/v1`）

- 状态：私有密文明细已生成，**待保管 B 独立复核**；本文件只是公开 schema/枚举/校验与消费规则，不含任何逐题内容、题号、题面、答案、目标值或逐题 hash。
- 目的：把 2026-11-12 冻结的 H2 四轴保管标注（v0.2 基线 + v0.3 gap addendum）**原样投影**为 Q1a-1b / Q1a-3 可消费的 scope/targets 合同；只补“可消费结构 + 固定 basis 来源码”，**不新增、不改变、不重判任何冻结标签语义**。
- 非目标：不产生运行期 `checked` / `passed` / `violations`；不证明真实产品通过；不读、不反推真实产品回答/输出/分数/trace；不修改 30 题/标签/阈值/四状态/评分标准；不覆盖 v0.2/v0.3 密文与已接收报告；不授权真实调用。

## 1. 证据来源与语义基线

只允许以下输入作为投影依据：

1. 冻结 H2 题面与参考答案/标签（`P2-HOLDOUT-v2`，label `p2-holdout-v2-2026-11-10`）。
2. 公开语料 `fixtures/acceptance/**` 与原 12-source 配方 `T207-ingest-plan-H2.json`。
3. source map `p2-holdout-v2.source-map.json`。
4. 冻结 `CaseSpec.business_date`（本批为 `2026-10-28`）作为“产品应使用的业务基准日”，不是产品实际使用该日期的证明。
5. 既有冻结四轴标注：v0.2 密文（基础 120 轴）与 v0.3 gap addendum（仅整体替换 4 个 gap 轴）。

禁止：从产品回答/最终输出/评分/分数反推；因难判而选 `not_applicable`；把 `unknown` 改成 `not_applicable`；用运行期结果回填语义；新增第三状态或扩展固定词表。

## 2. 私有明文载荷精确 schema

明文是一个 JSON 对象，**顶层键恰为 5 个且仅这 5 个**：

```json
{
  "schema_version": "q1a-scope-targets-contract/v1",
  "bindings": { "...": "..." },
  "runs": [ "... 4 项 ..." ],
  "case_count": 30,
  "cases": [ "... 30 项 ..." ]
}
```

- `schema_version`：固定字符串 `q1a-scope-targets-contract/v1`。
- `bindings`：见 §2.1。
- `runs`：长度恰 4 的有序数组，见 §2.2。
- `case_count`：整数，必须等于 `30` 且等于 `len(cases)`。
- `cases`：长度恰 30 的有序数组，见 §2.3。

### 2.1 `bindings`（恰 17 键）

| 键 | 类型 | 含义 |
|---|---|---|
| `old_run_binding_sha256` | 64 位小写 hex | 旧 run binding 文档去掉 `binding_sha256` 字段后的 canonical JSON SHA256；必须等于文档内记录的 `binding_sha256` |
| `old_run_binding_file_sha256` | 64 hex | 旧 run binding 文件原始字节 SHA256 |
| `dataset_version` | 非空 str | 必须为 `P2-HOLDOUT-v2` |
| `label_version` | 非空 str | 必须为 `p2-holdout-v2-2026-11-10` |
| `manifest_sha256` | 64 hex | 封存 manifest |
| `cases_sha256` | 64 hex | 冻结 30 题按加载序的 canonical JSONL SHA256 |
| `source_map_sha256` | 64 hex | source map 原字节 |
| `ingest_plan_sha256` | 64 hex | 原 12-source ingest plan 原字节 |
| `scenario_contract_sha256` | 64 hex | `p2-h2-scenarios-v0_2.json` 原字节 |
| `annotation_v0_2_ciphertext_sha256` | 64 hex | v0.2 标注密文 |
| `annotation_review_v0_2_ciphertext_sha256` | 64 hex | v0.2 独立复核密文 |
| `annotation_v0_3_ciphertext_sha256` | 64 hex | v0.3 gap addendum 密文 |
| `annotation_schema_sha256` | 64 hex | `p2-h2-custody-annotations-v0_2.md` 原字节 |
| `annotation_manager_acceptance_v2_sha256` | 64 hex | T207-CUSTODY-V2 manager acceptance 原字节 |
| `annotation_review_aggregate_v2_sha256` | 64 hex | T207-CUSTODY-V2 review aggregate 原字节 |
| `addendum_acceptance_v3_sha256` | 64 hex | T207-CUSTODY-V3 manager acceptance 原字节 |
| `contract_schema_sha256` | 64 hex | 本 schema 文档原字节 |

所有 hex 键必须能由复核方从对应输入重算并逐值相等；不一致即 `contract_binding_mismatch`，fail closed。

### 2.2 `runs`（恰 4 项，按 `run_index` 升序）

每项**恰 5 键**：

| 键 | 类型 | 约束 |
|---|---|---|
| `run_index` | int | `0..3`，数组下标必须等于该值 |
| `scenario_id` | str | 依次为 `base_b0`、`base_b0_plus_v01`、`pre_v05_without_v07`、`post_v05_without_v01` |
| `run_id` | 非空 str ≤96 | 旧 run binding 中的 run_id，逐值相等 |
| `plan_id` | 非空 str ≤96 | 旧 run binding 中的 plan_id，逐值相等 |
| `plan_sha256` | 64 hex | 旧 run binding 中的 plan_sha256，逐值相等 |

`runs` 只绑定旧 run 的题集/计划/场景归属；不得改写、重算或替换旧 binding。

### 2.3 `cases`（恰 30 项，冻结加载序）

每项**恰 5 键**：

| 键 | 类型 | 约束 |
|---|---|---|
| `case_id` | 非空 str | 必须等于冻结 dataset 同一下标的 `case_id`；30 个唯一 |
| `case_index` | int | `0..29`，数组下标必须等于该值 |
| `scenario_id` | str | 必须等于冻结标注同题的 `scenario_id`；枚举见 §2.2 |
| `axes` | object | 恰 4 键：`safety` / `cross_user` / `cross_entity` / `stale_source` |
| `basis` | object | 恰 4 键，与 `axes` 同键集；每值为 §4 的固定 basis code |

`case_id` / `scenario_id` / `axes` 只存在于私有密文；公开聚合不得出现题号、题面、答案、目标值或逐题 hash。

### 2.4 轴对象（每轴恰 7 字段）

每个轴对象**字段集恰为**：

```json
{
  "applicability": "required | not_applicable | unknown",
  "criterion": "按轴固定枚举，见 §3.1",
  "reason": "固定 19 码之一，见 §3.2",
  "target_refs": [ {"collection": "expected_sources | relevant_units | forbidden_sources", "index": 0} ],
  "targets": [ {"entity_type": "...", "entity_key": "...", "filters": {"k": "v"}} ],
  "as_of": "YYYY-MM-DD 或 null",
  "temporal_intent": "current | historical | future_explicit | not_applicable | unknown"
}
```

严格约束：

- `applicability` 只允许 `required` / `not_applicable` / `unknown`。
- `criterion` / `reason` / `temporal_intent` 只允许 §3 的冻结词表；不得出现自由文本。
- `target_refs`：数组；每项恰 `collection` + `index` 两键；`collection` 只允许三枚举；`index` 为非负整数且必须落在**同题**对应冻结集合边界内；同题同轴不得重复 `(collection,index)`；不得重写原 ref。
- `targets`：数组；每项恰 `entity_type` + `entity_key` + `filters` 三键；`entity_type` 非空 str ≤256；`entity_key` str ≤256；`filters` 为 str→str/int/float/bool/null 的映射；不得创造不存在的 `record_code` 字段或实体实例。
- `as_of`：`null` 或严格 ISO 日期（`date.fromisoformat` 回写必须逐字相等）。
- 七个字段必须**逐值等于**合并后的冻结标注轴值（v0.2 原值，若该轴在 v0.3 addendum 中 `resolution=resolved` 则等于 v0.3 `axis_value`）；不得增删字段、不得改写、不得用默认值补齐。任何差异即 `contract_semantics_changed`。

## 3. 冻结枚举

### 3.1 `criterion`（按轴）

| 轴 | 允许值 |
|---|---|
| `safety` | `must_refuse_security` / `forbidden_content` / `benign_business` / `unknown` |
| `cross_user` | `owner_context` / `unknown` |
| `cross_entity` | `structured_target` / `multi_target` / `shared_background` / `no_entity_claim` / `unknown` |
| `stale_source` | `lifecycle_dates` / `unknown` |

### 3.2 `reason`（19 码，全局）

`explicit_security`、`explicit_privacy`、`prompt_injection`、`explicit_forbidden`、`benign_business`、`all_user_contexts`、`explicit_single_target`、`explicit_multi_target`、`shared_policy`、`no_entity_scope`、`published_lifecycle`、`explicit_temporal`、`business_date_default`、`ambiguous_semantics`、`unresolved_target`、`source_state_conflict`、`third_state_required`、`insufficient_annotation`。

### 3.3 `applicability` 与轴级硬规则

- `cross_user`、`stale_source`：全部题必须 `required`；不得 N/A。
- `safety`：确有安全/保密/越权/注入契约才 `required`；明确良性业务问答可 `not_applicable`，但不取消全局禁值/禁源检查；语义不明 `unknown`。
- `cross_entity`：明确目标/比较集合 `required`；只有冻结语义明确无业务实体约束才 `not_applicable`；解析器没识别、正文 document key、来源失败都不能当 N/A 证据。
- 任一轴 `unknown` 必须保留；本冻结合并后 `unknown` 总数为 0，合同不得新增 unknown，也不得把任何 unknown 改写为 N/A。

## 4. 固定 `basis` code 与确定性映射

`basis` 每个轴恰一个值，枚举**只有**：

| code | 含义 |
|---|---|
| `frozen_label_target` | 目标/禁值/禁源身份由冻结标签（参考答案、expected/forbidden 值或来源）决定 |
| `frozen_question_scope` | 适用性/范围/owner/无实体声明由冻结题面语义决定 |
| `public_corpus_structure` | 目标/共享背景/生命周期身份由公开语料结构（文档/版本/单元）决定 |
| `case_business_date_baseline` | 日期锚点取冻结 `CaseSpec.business_date`（业务基准日，不是产品实际使用证明） |
| `no_provable_basis_keep_unknown` | 无可证依据，保留 `unknown` |

### 4.1 赋值优先级（逐轴，首个命中即止）

1. **v0.3 gap 轴例外**：若 `(case_index, axis)` 在 v0.3 addendum 中且 `resolution=resolved`，`basis` 必须逐值等于该 gap 的 `basis`（本批 4 轴：2×`case_business_date_baseline`、1×`frozen_label_target`、1×`frozen_question_scope`）。不得用本规则重算覆盖。
2. `applicability == "unknown"` → `no_provable_basis_keep_unknown`。
3. `safety`：
   - `required` → `frozen_label_target`；
   - `not_applicable` → `frozen_question_scope`。
4. `cross_user`：一律 `frozen_question_scope`。
5. `cross_entity`：
   - `shared_background` → `public_corpus_structure`；
   - `no_entity_claim` → `frozen_question_scope`；
   - `structured_target` / `multi_target`：`target_refs` 非空 → `frozen_label_target`；否则 `targets` 非空 → `frozen_question_scope`；两者都空 → `no_provable_basis_keep_unknown`。
6. `stale_source`：`target_refs` 非空 → `public_corpus_structure`；否则 `as_of` 非空且等于冻结 `CaseSpec.business_date` → `case_business_date_baseline`；否则 → `frozen_label_target`。

`basis` 只是**来源分类**，不是适用性判定、不是运行期结论、不得参与 pass/fail 折叠。

## 5. 校验算法（消费者与复核方必须逐项执行）

1. 读取密文原始字节，重算 SHA256，必须等于公开聚合记录的 `private_ciphertext.sha256`；不一致 → `contract_ciphertext_sha_mismatch`。
2. 只通过受控 loader（既有 H2 custody key 容器；明文只在进程内存）解密；解密失败 → `contract_decrypt_failed`。
3. 严格 JSON 解析：拒绝重复键、非对象顶层、非 UTF-8；拒绝未知/缺失键。
4. 校验 `schema_version`、`bindings` 17 键、`runs` 4 项、`case_count=30`、`cases` 30 项。
5. 重算 §2.1 的全部 binding；验证 v0.2 密文/复核密文/v0.3 密文/acceptance/schema/scenario/manifest/cases/source_map/ingest 的 SHA256；验证旧 run binding 的 `binding_sha256` 与文件 SHA256。
6. 按冻结 dataset 加载序逐题比较 `case_id`；按合并后标注逐题比较 `scenario_id`；验证 30 唯一、无缺失/额外/重复。
7. 逐题逐轴比较 7 字段与合并标注轴值**深度相等**；验证 refs 边界、targets 类型、日期规范、枚举。
8. 逐题逐轴验证 `basis` 属于 §4 枚举；对 v0.3 gap 轴验证与 addendum `basis` 逐值相等；对其余轴按 §4.1 复算；任何不符 → `contract_basis_mismatch`。
9. 验证没有 `unknown`→`not_applicable`、没有新增/删除轴、没有改动 120 轴的任何非投影字段。
10. 任何校验失败以固定码拒绝，不降级、不“尽力消费”。

固定错误码：`contract_ciphertext_missing`、`contract_ciphertext_sha_mismatch`、`contract_decrypt_failed`、`contract_schema_invalid`、`contract_binding_mismatch`、`contract_coverage_invalid`、`contract_axis_invalid`、`contract_basis_invalid`、`contract_semantics_changed`、`contract_unknown_downgraded`。

## 6. 序列化与加密

- 明文序列化：`json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",",":"))` 的 UTF-8 字节，无尾随换行。
- 加密：Fernet 认证加密；key 只用既有 H2 custody key 容器（`MKTKB_P2_HOLDOUT_KEY_FILE`），只在受控进程内存由 loader 读取，不打印、不复制、不落盘、不写入报告。
- 密文写到仓外新目录，独占创建，不覆盖任何既有文件；明文只在内存，不写明文脚本/日志/JSON/临时文件/数据库。
- 公开只允许：密文绝对路径、密文 SHA256/字节数、计数、basis 分布、unknown 计数、binding 摘要、输入前后 hash、零真实调用计数；不得出现逐题内容。

## 7. 消费方式

### 7.1 Q1a-1b（其余三轴重评分模块）

- 输入适配器只接受已通过 §5 校验的合同视图：`case_id -> {axes, basis}`。
- `cross_user` / `cross_entity` / `stale_source` 的 `applicability` 决定该轴 planned；`required` 轴必须按运行时证据重算，不得直接继承冻结标注为 pass。
- `target_refs` / `targets` / `as_of` / `temporal_intent` 是 scope/targets 的**唯一**合同输入；不得用产品回答/输出/分数补目标或日期。
- `basis` 只进入 provenance 报告；不得参与 verdict 折叠。
- 合同缺失某题/某轴/某 basis，或该轴 `unknown` → 该轴 `unknown` / `blocked`；不得默认 N/A、不得 fail-open。
- 合同版本只接受 `q1a-scope-targets-contract/v1`；其他版本 → `contract_schema_invalid`。

### 7.2 Q1a-3（私有重评分 + 11 fail 分诊）

- 把合同密文 SHA256 与合同 schema SHA256 写入新分析身份 `Q1A-RESCORE-20261114-r1` 的绑定；旧 run binding / 旧 evidence / 旧卡只读。
- 按 `case_id` 与旧 evidence/旧卡对齐；按 `scenario_id` 与旧 run 的 `runs` 绑定对齐。
- `applicability=required` 只表示“该轴应被检查”，不是“已通过”；`checked`/`passed`/`violations` 仍必须来自运行时真实 context/source/date/entity 快照与确定性分类。
- 合同本身不产生运行期四轴结论；不得用合同替代缺失的 owner/实体/日期证据；无法核的轴保留 `unknown`，不得改 N/A。
- 分诊时 `basis` 可作为“该轴语义来源”的固定 code 记录；不得把 `basis` 当成产品行为正确/错误的证据。

### 7.3 保管 B 独立复核

- 用同一既有 key 容器与受控 loader 独立解密；独立重算 30 题覆盖、120 轴 7 字段、basis 分布、binding 与密文 SHA256。
- 逐轴对照合并后的 v0.2+v0.3 冻结标注；任何 7 字段差异、basis 差异、覆盖差异、绑定差异都保留为分歧，不表决、不择优。
- 复核只写独立聚合/报告，不覆盖本合同的密文或公开文件；复核前不得把本合同当作质量通过或真实运行依据。

## 8. 版本与边界

- 本合同版本固定 `q1a-scope-targets-contract/v1`；新版本必须新文件、新版本号、新密文，不覆盖本件。
- 本合同只补语义归属与可消费结构，不证明真实产品通过，不产生 `verified` / `threshold_met` / `release_ready`，不进入 T208/T209/T900。
- 任何 schema/绑定/覆盖/复核不一致即阻断；失败如实记 NOT-RUN/BLOCKED，不猜、不冒充。
