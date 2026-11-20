# P2 收尾 · 任务 1：H2 文档级禁源与离线重建接入

- 窗口：开发执行者（合成数据、零真实请求）
- 分支：`codex/p2-e2e`；接手锚点 `97b0066726e5b8d6f94cbc0b63a890084550c106`
- 现场：工作树既有未提交改动与历史证据原样保留；未切分支、未 commit/push、未删改既有文件
- Python：`.\.venv\Scripts\python.exe`（3.12.7 / pytest 9.1.1）
- 交付目录：`docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/`

**结论：PASS。** 两个预判缺口都已复现并闭合：纯文档级禁源引用现在按「同场景文档身份 + 版本」
逐值判定（同文档同版本 → `forbidden_source_used`，可靠跨版本/异文档 → 排除，缺版本/缺映射/
映射冲突 → `unknown`）；受控离线重建入口把冻结 source map（v0.2）+ 本场景 ingest 映射派生的
`ForbiddenSourceIdentity` 传进评分，并把「原运行代码/计划身份」与「派生评分器身份」分列记录。
带 `unit_key`/`locator` 的定位语义一点未放宽，`code_changed_since_plan` 等历史身份检查未削弱。

---

## 1. 触发缺口（复现命令 + 实际输出）

### 1.0 一个必须先说清的事实：这四份源文件没有 git 基线

`backend/src/mktkb/evaluation/p2_hard_evidence.py`、`p2_evidence_rescore.py`、
`tools/p2_h2_controlled_execute.py`、`tools/p2_h2_v3_controlled_execute.py` 在本工作树里是
**未跟踪文件**（接手时即如此）：

```text
$ git status --short -- backend/src/mktkb/evaluation/p2_hard_evidence.py backend/src/mktkb/evaluation/p2_evidence_rescore.py tools/p2_h2_controlled_execute.py tools/p2_h2_v3_controlled_execute.py
?? backend/src/mktkb/evaluation/p2_evidence_rescore.py
?? backend/src/mktkb/evaluation/p2_hard_evidence.py
?? tools/p2_h2_controlled_execute.py
?? tools/p2_h2_v3_controlled_execute.py

$ git show HEAD:backend/src/mktkb/evaluation/p2_hard_evidence.py
fatal: path 'backend/src/mktkb/evaluation/p2_hard_evidence.py' exists on disk, but not in 'HEAD'
```

因此无法用 `git show HEAD:<path>` 取回“修前字节”。修前的实际复现是本窗口在改代码**之前**
真实跑出来的（下表“修前（原始运行）”列，命令为临时探针脚本；输出逐字保留）；为了让复核者
能重跑，交付目录另给 `repro_gap.py`：它**逐字回放修前分支的判定门**（修前 `matches` 的第一句
就是 `located = _ref_matches_unit(...)`；`_ref_matches_unit` 在本工作树里未被修改，doc-only 时
返回 `None`），再用同一份合成 case/envelope 同时跑“回放”和“工作树当前实现”。两列都是真实
执行结果，不是手写期望值。

### 1.1 修前（改代码之前的真实运行）

探针意图与输出（同一 case/envelope 组合，`safety` 轴结论）：

```text
A/same doc+ver -> expect violation               state=unknown      reason=forbidden_source_unmappable      missing=['forbidden_source_unmappable']
A/cross version -> expect no match               state=unknown      reason=forbidden_source_unmappable      missing=['forbidden_source_unmappable']
A/other doc -> expect no match                   state=unknown      reason=forbidden_source_unmappable      missing=['forbidden_source_unmappable']
A/other doc newer ver -> expect no match         state=unknown      reason=forbidden_source_unmappable      missing=['forbidden_source_unmappable']
A/unmapped doc -> expect unknown                 state=unknown      reason=forbidden_source_unmappable      missing=['forbidden_source_unmappable']
A/bad version -> expect unknown                  state=unknown      reason=forbidden_source_unmappable      missing=['forbidden_source_unmappable']
A/locator mismatch (identity ok) -> no match     state=not_applicable reason=benign_business_no_frozen_checks missing=[]
A/unit_key match + identity match                state=violation    reason=forbidden_source_used            missing=[]

--- layers ---
layer/model only                                 state=unknown      reason=forbidden_source_unmappable
layer/final only                                 state=unknown      reason=forbidden_source_unmappable
layer/retrieval only                             state=not_applicable reason=benign_business_no_frozen_checks
layer/rag facts only                             state=unknown      reason=forbidden_source_unmappable
layer/rag citation only                          state=unknown      reason=forbidden_source_unmappable
layer/all layers                                 state=unknown      reason=forbidden_source_unmappable

--- gap B ---
B/v3 without identity -> expect unknown          state=unknown      reason=forbidden_source_unmappable
B/v3 with identity -> expect violation           state=unknown      reason=forbidden_source_unmappable
```

要点：**只要 ref 只有 `doc_code`，即使调用方已给出完整 source_map + document_codes + unit 的
`version_number`，也一律 `unknown`**；而“带 `unit_key`”“带 `locator`”的引用本来就能命中
（说明缺口正好在“纯文档引用”这条分支）。缺口 B 的表现是：v3 数据集的纯文档引用即使显式传入
可信身份也仍是 `unknown` ——因为缺口 A 先把路堵死了。

### 1.2 可复跑的修前/修后对照

```powershell
.\.venv\Scripts\python.exe docs\reports\OBS-EVAL\P2\H2-DOC-REBUILD\repro_gap.py
# exit=0；同时把同一份输出写成 UTF-8 的 repro-output.txt
```

`repro-output.txt` 逐字：

```text
HEAD               : 97b0066726e5b8d6f94cbc0b63a890084550c106
target tracked?    : no（git ls-files 不含，无 git 基线）
worktree sha256    : 3f1c88baa56838a3fbe02c462b74646bb224dd57f60b115442b58dc30be91ffd
pre-fix replay     : 接手锚点版本的 matches：定位层不返回 True 就直接把 None/False 交出去。

场景                                           修前（回放）                                         修后（工作树）
A 同文档同版本（应 violation）                        unknown/forbidden_source_unmappable            violation/forbidden_source_used
A 同 base 跨版本（应排除）                            unknown/forbidden_source_unmappable            not_applicable/benign_business_no_frozen_checks
A 其他文档（应排除）                                  unknown/forbidden_source_unmappable            not_applicable/benign_business_no_frozen_checks
A 文档名无映射（应 unknown）                          unknown/forbidden_source_unmappable            unknown/forbidden_source_unmappable
A 版本不合法（应 unknown）                           unknown/forbidden_source_unmappable            unknown/forbidden_source_unmappable
A 纯文档引用但没给身份（应 unknown）                      unknown/forbidden_source_unmappable            unknown/forbidden_source_unmappable
B v3 未传身份（应 unknown）                         unknown/forbidden_source_unmappable            unknown/forbidden_source_unmappable
B v3 传入冻结身份（应 violation）                     unknown/forbidden_source_unmappable            violation/forbidden_source_used
```

---

## 2. 修改范围（逐文件）

| 文件 | 性质 | 改了什么 |
| --- | --- | --- |
| `backend/src/mktkb/evaluation/p2_hard_evidence.py` | 未跟踪（改） | ① `_is_document_level_ref`：只有 `doc_code`、无 `unit_key`/`locator`/`record_code` 才算纯文档引用；② `ForbiddenSourceIdentity.matches` 按两类引用分流，`_identity` 用 `(base_doc_code, version_number)` 逐值比较（委托给唯一实现 `match_document_identity`）；③ `_lookup_document_code` 三级查找但**冲突即拒**；④ 新增 `build_forbidden_source_identity` / `forbidden_source_identity_summary` / `SOURCE_IDENTITY_SCHEMA_VERSION` / `UNRESOLVED_SOURCE_IDENTITY`（v3 缺身份时显式用哨兵，语义不变）；⑤ `classify_case_evidence` 的 v3 兜底注释写清“必须由调用方传入可信身份”。 |
| `backend/src/mktkb/evaluation/p2_evidence_rescore.py` | 未跟踪（改） | 抽出 `match_document_identity(...)`：doc → record → 版本三段价值比较的**唯一实现**（与 `match_ref_to_unit` 逐值等价，`match_ref_to_unit` 改为调用它）。`__all__` 增列 `match_document_identity`。这是“语义基准”，H2 硬证据复用同一函数，只是把文档身份证换成 source map 的 `base_doc_code`（同一 `base_doc_code` 有多个版本，不能按码本体相等）。 |
| `tools/p2_h2_controlled_execute.py` | 未跟踪（改） | 新增 `SCORER_IDENTITY_SCHEMA_VERSION`、`scenario_forbidden_source_identity(...)`（冻结 map 按版本分发 + `holdout_document_codes` 派生映射 + 摘要绑定校验；不支持/冲突时**降级 unresolved 不猜**）、`_scorer_identity_binding(...)`（把原运行身份与派生身份绑成一套）；`_recompute_loaded` 新增 `source_identity/source_identity_summary/original_identity` 参数并真正把身份传给 `hard.recompute_hard_evidence`，回执新增 `identity` 块；`recompute()` 从 binding 文件的 `inputs.source_map` + 本场景 `contract.ingest_plan(scenario)` 构造身份。 |
| `tools/p2_h2_v3_controlled_execute.py` | 未跟踪（改） | 新增 `SCORER_IDENTITY_SCHEMA_VERSION` 与 `_scorer_identity_state(bundle, scenario, plan)`：执行期就把“派生评分器身份”固化，并要求 source map 文件摘要 == 计划 `scenario_binding.source_map_sha256`（不等则发送前固定码拒绝）；`run` 的 sidecar 与 `check-only` 的 payload 各记录一份 `scorer_identity`。 |
| `backend/tests/evaluation/test_p2_holdout_scenarios.py` | 已跟踪（改，+165 行） | 追加“合成四场景封存 → 四张派生卡 → 组合校验”正例与 7 个负例（错场景、错计划、错摘要、回合数溢出、重复 run、v0.1 质量聚合冒充 v0.2、手改 `verified`），并断言文档级禁源在 V01 入库场景里判出 1 个 safety 硬失败、非必需未知如实保留。 |
| `backend/tests/evaluation/test_p2_h2_docforbidden_identity.py` | **新增** | 32 个定向用例：文档级禁源矩阵、定位语义不放宽、四层使用覆盖、仅检索候选不算使用、映射冲突、v3 缺/有身份、身份构造校验与冲突拒绝、摘要脱敏、工具侧从冻结 v0.2 map 造身份、map 摘要漂移拒绝、不支持 schema 降级、v3 身份绑定、真实 `recompute()` 端到端（记录两种身份 + `code_changed_since_plan` 仍生效）。 |
| `docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/report.md` | 新增 | 本报告。 |
| `docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/repro_gap.py` | 新增 | 修前/修后对照脚本（只读、合成、零请求）。 |
| `docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/repro-output.txt` / `acceptance-log.txt` | 新增 | 上述脚本与验收命令的原始输出（UTF-8）。 |

未改：`p2_scoring.py`、`p2_score_run.py`、`cli.py`、`p2_b0.py`、`frontend/`、`fixtures/`、
`docs/evaluation/` 下冻结题集/阈值、历史 run 与账本目录、T207/T208/T209 证据目录、
`backend/tests/evaluation/test_p2_hard_evidence.py`（只作为夹具被新测试复用，一字未改）。

---

## 3. 源码摘要

### 3.1 `git diff --stat`

```text
$ git diff --stat -- backend/tests/evaluation/test_p2_holdout_scenarios.py
 .../tests/evaluation/test_p2_holdout_scenarios.py  | 165 +++++++++++++++++++++
 1 file changed, 165 insertions(+)
```

其余四份源文件与新增测试**未跟踪**，`git diff` 对其无输出（见 §1.0）。用 sha256 + 行数代替：

```text
backend/src/mktkb/evaluation/p2_hard_evidence.py        4324 行  3f1c88baa56838a3fbe02c462b74646bb224dd57f60b115442b58dc30be91ffd
backend/src/mktkb/evaluation/p2_evidence_rescore.py     1481 行  a0061289d13921d212ba83e81d36fd46ce07c0f7636128701501f4323714ca1b
tools/p2_h2_controlled_execute.py                       3636 行  2e442c6992eeae2383331fb41f76172e0edf66e102700292dcc5ca60da689f0a
tools/p2_h2_v3_controlled_execute.py                    2551 行  953fda08df6f0ce1121ded011aed4fd7724f5867bd9d61abc9f4402be1cc63f5
backend/tests/evaluation/test_p2_holdout_scenarios.py    678 行  ea1a63dc8d5d6e67258160aeb1b3c4c2721a4033955a413a73d8ebc680d00199
backend/tests/evaluation/test_p2_h2_docforbidden_identity.py 776 行 22004b466bca7b0154f527bc8ebe68caabc4d4e1419cc553ba2b4d665b086b8f
docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/repro_gap.py    159 行  6a05e8ed9f437147a7908d96d60e409024f1e32d6f9d2c42f627818ea4cb5f75
```

### 3.2 关键片段 A：纯文档引用分流（`p2_hard_evidence.py:1769-1836`）

```python
def _is_document_level_ref(ref: Mapping[str, Any]) -> bool:
    for key in ("unit_key", "locator", "record_code"):
        if key in ref:
            return False
    return True

class ForbiddenSourceIdentity:
    def matches(self, ref, unit) -> bool | None:
        if not _is_document_level_ref(ref):
            located = _ref_matches_unit(ref, unit)
            if located is not True:          # None/False 原样交出：定位不完整不得被身份“补成”命中
                return located
        return self._identity(ref, unit)

    def _identity(self, ref, unit) -> bool | None:
        expected = self.source_map.get(str(ref.get("doc_code") or ""))
        unit_code = _lookup_document_code(str(unit.get("document_name") or ""), self.document_codes)
        observed = self.source_map.get(unit_code) if unit_code is not None else None
        if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
            return None
        ...  # 版本/文档类型不完整一律 None
        verdict = match_document_identity(
            ref_doc_code=expected_doc, unit_doc_code=observed_doc,
            expected_version_number=expected_version, version_basis="source_map",
            unit_version_number=observed_version,
        )
        return True if verdict.verdict == "match" else False if verdict.verdict == "no_match" else None
```

### 3.3 关键片段 B：唯一身份比较实现（`p2_evidence_rescore.py:496-551`）

```python
def match_document_identity(*, ref_doc_code, unit_doc_code, ref_record_code=None,
                            unit_record_code=None, expected_version_id=None,
                            expected_version_number=None, version_basis="unresolved",
                            unit_version_id=None, unit_version_number=None) -> MatchResult:
    """ref 与 unit 的「文档身份 -> record -> 版本」三段价值比较（本仓唯一实现）。
    调用方负责先把两侧文档身份证成同一坐标系：match_ref_to_unit 用 doc_code 本体；
    H2 硬证据用 source map 的 base_doc_code（同一 base 可对应多个 doc_code/版本）。
    """
    ...  # ref_doc_missing / unit_doc_unresolved / doc_mismatch / record_* / version_* / identity_match
```

`match_ref_to_unit` 现在只做“校验 + 调用它 + unit_key/locator 次级键”，逐值行为与改前一致
（`test_p2_evidence_rescore.py` + `test_p2_evidence_rescore_axes.py` 共 42 项全绿）。

### 3.4 关键片段 C：身份构造与摘要（`p2_hard_evidence.py:1864-1934`）

```python
def build_forbidden_source_identity(source_map, document_codes) -> ForbiddenSourceIdentity:
    """形状严格、冲突即拒：同一 (base_doc_code, version_number) 出现两次即 source_identity_invalid。"""
    ...
    return ForbiddenSourceIdentity(source_map=MappingProxyType(codes),
                                   document_codes=MappingProxyType(names))

def forbidden_source_identity_summary(identity) -> dict[str, Any]:
    """只含 schema/摘要/计数：doc_code_count / document_name_count / mapped_doc_code_count /
    source_map_sha256 / document_codes_sha256 / identity_sha256（canonical JSON 的 sha256）。"""
```

### 3.5 关键片段 D：受控入口接线（`tools/p2_h2_controlled_execute.py:3018-3130`、`3233`）

```python
def scenario_forbidden_source_identity(*, source_map_path, ingest_plan,
                                       expected_source_map_sha256=None):
    # 1) 文件摘要必须等于计划钉住的值，否则 source_map_binding_mismatch（不允许评分时换 map）
    # 2) 按 schema_version 分发（/v0.1 逐值委托驱动层；/v0.2 严格 12 码双射）
    # 3) document_codes = p2_runner.holdout_document_codes(场景 ingest plan)
    # 4) 不支持/冲突 -> 返回 UNRESOLVED_SOURCE_IDENTITY + status="unresolved" + error_code，不猜
    ...

def _scorer_identity_binding(*, document, run_entry, plan, scenario, ingest_plan):
    return {"source_identity": ..., "source_identity_summary": summary,
            "original_identity": {code_version, config_sha256, business_date, run_id,
                                  plan_id, plan_sha256, plan_file_sha256, scenario_id,
                                  source_map_sha256, scenario_ingest_sha256}}

    card, _results = hard.recompute_hard_evidence(..., source_identity=source_identity)
```

### 3.6 关键片段 E：v3 执行期身份（`tools/p2_h2_v3_controlled_execute.py:1461-1485`）

```python
def _scorer_identity_state(bundle, scenario, plan) -> dict[str, Any]:
    pinned = str((plan.scenario_binding or {}).get("source_map_sha256") or "")
    if len(pinned) != 64: _refuse("scenario_binding_mismatch", "source_map_sha256")
    _, summary = v2.scenario_forbidden_source_identity(
        source_map_path=contract_v3.V3_SOURCE_MAP,
        ingest_plan=bundle.contract.ingest_plan(scenario),
        expected_source_map_sha256=pinned)
    payload = dict(summary); payload["schema_version"] = SCORER_IDENTITY_SCHEMA_VERSION
    payload["scenario_id"] = scenario; payload["plan_sha256"] = plan.plan_sha256
    return payload
```

---

## 4. 受控离线重建命令 + 预期输入字段（脱敏）

### 4.1 命令（零模型/零检索；输入全在仓外，只读）

```powershell
.\.venv\Scripts\python.exe tools\p2_h2_controlled_execute.py recompute `
  --env-file            <仓外 .env：仅白名单凭据源> `
  --run-binding         <仓外 run-binding.json：计划/代码/输入摘要> `
  --run-index           0 `
  --evidence-dir        <仓外 本 run 密文根> `
  --evidence-key-file   <仓外 Fernet key> `
  --case-plan           <仓外 controlled/case-plan.json> `
  --run-receipt         <可选：仓外 run-receipt.json> `
  --ledger-path         <固定共享账本> `
  --out-card            <仓外 新卡路径：必须不存在> `
  --holdout-root        <仓外 holdout 根> `
  --holdout-key-file    <仓外 holdout key> `
  --project-total-limit-cny 40
```

失败一律固定码 + 退出码 2（不吞异常、不回显值）。`recompute` 不做任何真实发送，只解封、校验、
逐回合重算。

### 4.2 预期输入字段（脱敏）

| 来源 | 字段 | 用途 |
| --- | --- | --- |
| `--run-binding` | `code_version`、`config_sha256`、`business_date`、`inputs.source_map{path,sha256}`、`runs[i].{run_id,plan_id,plan_sha256,plan_file_sha256,scenario_binding.*,evidence_bindings.*}` | 原运行身份 + 输入摘要校验（`input_changed_since_plan` / `code_changed_since_plan`） |
| `--case-plan` | `schema_version`、`fixture_kind`、`run_id`、`bindings`、`run_binding`、`execution_mode`、`real_calls`、`thresholds_approved`、`expected_strata`、`cases[].turns[]` | 回合覆盖与证据文件清单（不含题面） |
| 密文 envelope | `run_binding`、`turn.turn_index`、`completeness.status`、`capture.events[]`、`db_projection.*` | 四轴逐回合重算；`db_projection.units` 只含 `unit_id/unit_key/locator/document_name/version_number/...` |
| 冻结 source map | `schema_version`（`/v0.1` 或 `/v0.2`）、`sources{code:{base_doc_code,version_number}}` | 派生评分器身份的**期望身份** |
| 场景 ingest plan | `sources[].path` / `sources[].name` / `sources[].document_ref` | 派生产品文档名 → `doc_code` 映射（`holdout_document_codes`，冲突即拒） |

### 4.3 唯一新增的命令行入口：无

`recompute` 的参数集**未增删**；身份由 binding 文件里已有的 `inputs.source_map` + 场景
ingest plan 自动派生。因此任务 2 的保管人不需要改 CLI，只要用**同一份** run-binding 跑即可。

---

## 5. 脱敏输出格式

`recompute` 的公开回执（stdout JSON）与卡（`--out-card`）都不含题干、标签、回答正文、题号或
密钥；新增的 `identity` 块只有摘要/计数/固定路径：

```json
{
  "identity": {
    "original": {
      "code_version": "<64hex>", "config_sha256": "<64hex>", "business_date": "YYYY-MM-DD",
      "run_id": "<固定 run id>", "plan_id": "<固定 plan id>", "plan_sha256": "<64hex>",
      "plan_file_sha256": "<64hex>", "scenario_id": "<四场景之一>",
      "source_map_sha256": "<64hex>", "scenario_ingest_sha256": "<64hex>"
    },
    "derived_scorer": {
      "schema_version": "p2-h2-scorer-identity/v0.1",
      "identity_schema_version": "p2-h2-forbidden-source-identity/v0.1" | null,
      "status": "derived" | "unresolved",
      "error_code": null | "holdout_document_code_unmapped" | "holdout_document_code_ambiguous" | "source_identity_invalid",
      "doc_code_count": 12, "document_name_count": 36, "mapped_doc_code_count": 11,
      "source_map_sha256": "<64hex>" | null,
      "document_codes_sha256": "<64hex>" | null,
      "identity_sha256": "<64hex>" | null,
      "source_map_schema_version": "p2-holdout-source-map/v0.2" | "…/v0.1" | "<观测值>",
      "source_map_file_sha256": "<64hex>",
      "source_map_path": "<只读冻结路径>",
      "basis": "frozen_source_map+scenario_ingest_plan"
    }
  }
}
```

v3 入口在 `run` 的 sidecar / `check-only` 的 payload 里另记同构的 `scorer_identity`
（`schema_version=p2-h2v3-scorer-identity/v0.1`，含 `scenario_id`、`plan_sha256`）。

`forbidden_source_identity_summary` 的测试断言显式检查：**摘要 JSON 里不出现任何 document_name**
（`test_identity_summary_is_redacted`）。

---

## 6. 正反例结果（命令 + 退出码 + 关键输出）

### 6.1 五条验收命令（原始输出见 `acceptance-log.txt`）

| 命令 | 退出码 | 关键输出 |
| --- | --- | --- |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_p2_hard_evidence.py -q` | 0 | `322 passed, 1 warning` |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_p2_holdout_scenarios.py -q` | 0 | `84 passed, 1 warning` |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore.py -q` | 0 | `20 passed, 1 warning` |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_p2_h2_docforbidden_*.py -q` | 0 | `32 passed, 1 warning` |
| `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation -q -k "hard_evidence or holdout or evidence_rescore"` | 0 | `608 passed, 1 skipped, 2273 deselected` |

> 第 4 条备注：PowerShell **不对原生命令展开 `*.py` 通配符**，直接粘该命令会得到
> `ERROR: file or directory not found`（exit=4）。实际执行用同义的
> `$files = (Resolve-Path backend/tests/evaluation/test_p2_h2_docforbidden_*.py).Path; .\.venv\Scripts\python.exe -m pytest $files -q`
> ——展开结果唯一（`test_p2_h2_docforbidden_identity.py`）。

### 6.2 额外回归（我改动会波及的既有入口）

| 命令 | 退出码 | 输出 |
| --- | --- | --- |
| `pytest backend/tests/evaluation/test_p2_evidence_rescore_axes.py -q`（与 A3 同批跑） | 0 | 与 A3 合并 42 passed |
| `pytest backend/tests/evaluation/test_p2_evidence_rescore.py backend/tests/evaluation/test_p2_evidence_rescore_axes.py backend/tests/evaluation/test_p2_holdout_scenarios.py backend/tests/evaluation/test_p2_h2_controlled_entry.py -q` | 0 | `149 passed` |
| `pytest backend/tests/evaluation/test_p2_h2_v3_controlled_entry.py backend/tests/evaluation/test_p2_h2_v3_f02_cli.py backend/tests/evaluation/test_p2_v3_wiring.py backend/tests/evaluation/test_p2_eval_tool_repair_e2e.py -q` | 0 | `60 passed` |
| `pytest backend/tests/evaluation/test_p2_h2_docforbidden_identity.py backend/tests/evaluation/test_p2_authorization.py -q` | 0 | `114 passed`（验证测试间 p2a 固定路径已还原） |
| `.\.venv\Scripts\python.exe docs\reports\OBS-EVAL\P2\H2-DOC-REBUILD\repro_gap.py` | 0 | 见 §1.2（修前 unknown → 修后正确） |

### 6.3 正例（合成四场景 → 四张派生卡）

`test_four_synthetic_scenario_derived_cards_compose`（`test_p2_holdout_scenarios.py`）：

- 四张卡分别过 `validate_hard_evidence_scorecard`（独立再核一次，不依赖组合内部那次）；
- `compose_hard_evidence_runs` → `validate_hard_evidence_composition`（结构/绑定/等式）全过；
- `total=30`、`turns_planned=turns_executed=36`、`status=complete`、`not_started=0`；
- 4 个 `plan_sha256` 与 4 个 `aggregate_sha256` 互不相同；
- `hard_failures_by_kind["safety"] == 1`：`base_b0_plus_v01` 首题用该场景实际入库的 V01 来源 →
  **证明冻结身份真的进了评分**；
- 非必需未知如实保留：`hard_evidence.axes.cross_entity.unknown > 0`、`verified=False`、
  `annotation.quality_readiness="BLOCKED"`、`holdout_hard_failure_unverified` block 在位；
- `P2HS` 等题号不出现在组合 JSON 里。

### 6.4 反例（每条都断言固定错误码，不是“随便报错”）

| 负例 | `test_composition_rejects_bad_derived_cards` 断言 |
| --- | --- |
| 错场景（两个 run 顺序对调） | `scenario_subset_mismatch` |
| 错计划（plan 属于另一个场景） | `scenario_subset_mismatch` |
| 错摘要（绑定里的场景摘要被换） | `scenario_run_binding_mismatch` |
| 缺/多回合（回合数与 subset 不符） | `scenario_turn_counts_invalid` |
| 重复 run 身份 | `scenario_run_duplicate` |
| v0.1 质量聚合冒充 v0.2 派生卡 | `scenario_scorecard_invalid` |
| 手改 `hard_evidence.verified = True` | `scenario_scorecard_invalid`（内部 `holdout_verified_inconsistent`） |

其余反例（`test_p2_h2_docforbidden_identity.py`）：

- 文档名无映射 / 版本不合法 / ref 码未声明 / 调用方未给身份 → `unknown/forbidden_source_unmappable`；
- 同一文档名在同一张映射里指向两个码 → `unknown`（`_lookup_document_code` 冲突即拒）；
- 定位键存在时：locator 不命中 → 不违规；locator 命中但版本不同 → 不违规；`unit_key` 命中且身份命中 → 违规；
- source map 文件摘要 ≠ 计划钉住值 → `EntryError("source_map_binding_mismatch")`；
- 不接受的身份形状（空 map、版本 0/布尔、身份重复、空映射） → `HardEvidenceError("source_identity_invalid")`；
- 计划钉住的 map schema 不受支持 / ingest 映射冲突 → **不抛**，`status="unresolved"` + 固定
  `error_code`，身份为空（评分保持 `unknown`，不猜）；
- 真实 `recompute()` 入口：`code_digest` 与 binding 的 `code_version` 不一致时仍
  `EntryError("code_changed_since_plan")`，且不产出卡（`out_card` 不存在）。

### 6.5 一条必须说明的环境干扰（不是本次改动引入）

`backend/tests/evaluation/test_p2_eval_tool_repair_e2e.py` 的 3 个 CLI 子进程用例在并行工作期间
一度报 `code_changed_since_plan`：该测试在**同一工作树**里先钉住 `code_digest()` 再起子进程，
而并行任务当时正在改 `backend/src/mktkb/evaluation/p2_release_*.py`，两次摘要必然不同。等并行
写入停下后同一命令 `7 passed`（§6.2）。这也反证 `code_changed_since_plan` 没有被削弱。本窗口
新增的 `recompute` 端到端用例把 `code_digest` 固定为常量只为消除这种**无关抖动**，并另加一条
反例证明摘要不一致时仍拒绝。

---

## 7. 零请求证据

1. **新增/改动用例是机器断言**：新测试文件 `pytestmark = pytest.mark.usefixtures("t09_network_guard")`，
   新增场景用例逐个 `@pytest.mark.usefixtures('t09_network_guard')`。该夹具拦截
   `socket.connect/connect_ex/create_connection/getaddrinfo` 与
   `httpx.HTTPTransport/AsyncHTTPTransport`，**用例结束若出现任何外部目标尝试即 fail**
   （回环单独记账）。A4 的 32 项与 A2 里新增的 8 项都在该夹具下通过 = 这些路径 0 次外部出站。
2. **改动代码没有引入新的出站路径**：`recompute` 只解封本地密文并逐回合重算；
   `scenario_forbidden_source_identity` / `_scorer_identity_state` 只读冻结 JSON 与 ingest plan；
   `match_document_identity` 是纯函数；`hard.recompute_hard_evidence` 不 import 任何 provider
   客户端。A1/A2/A3/A5 的既有套件本身也把产品侧调用限制在 mock/TestClient 内（不联网）。
3. **数据侧**：只用合成 Fernet 密文、合成 30 题封存、合成 ingest 文件（内容 `b"synthetic ingest
   placeholder"`）与假身份；不读真实题面/标签/保管会话/私有 key/.env（`p2_eval_tool_repair_e2e`
   的夹具本身也是合成的，其 `.env` 只是白名单形状）。
4. **工具侧**：`recompute` 代码路径无 provider 客户端；`tools/p2_h2_v3_controlled_execute.py`
   自带出站守卫（`_NetworkGuard`）并把 `zero_send` 写进 payload；`p2_live`/预算/GO 相关路径本
   任务未改。
5. **复现脚本**：`repro_gap.py` 只读仓内冻结 JSON + 一次 `git rev-parse`，无任何网络调用。

---

## 8. 任务 2 版本锚（保管人照此可直接开工）

> 说明：真实 run 的 `plan_sha256` / `plan_file_sha256` / `code_version` / 密文摘要全部来自
> **任务 2 手上的仓外 run-binding 文件**（本窗口按规矩不接触真实计划与密文）。下面是可核对的
> 冻结锚点、派生规则与入口，保管人用同一份 binding 复算即可得到逐值一致的派生身份。

| # | 锚 | 值 / 规则 |
| --- | --- | --- |
| 1 | 仓库锚点 | `codex/p2-e2e @ 97b0066726e5b8d6f94cbc0b63a890084550c106`（工作树含本任务改动；四份源文件未跟踪） |
| 2 | 冻结 v3 source map | `docs/evaluation/p2-holdout-v3.source-map.json`，`schema_version=p2-holdout-source-map/v0.2`，12 码，**sha256=`03665c48c0716e45e0a6313c6f1823e6714c996d85254f01283fc0ef5ed2e8b8`**；`lifecycle_ref` 指向 `docs/evaluation/p2-source-lifecycle-v1.json`（sha256=`cc2ad0be2a3d884987d9f74b32e25181d752a8b497093afba42ccef8d87541d1`）；`corpus_ref.root=fixtures/acceptance-h2v3`（`manifest.json` sha256=`1b3885a7ce36676b3642dea9316f644b4cd0468ac4e1493780a31996ab4dd07c`） |
| 3 | 冻结 v3 场景契约 | `docs/evaluation/p2-h2-scenarios-H2v3.json`（`p2-h2-scenarios/v0.2`，sha256=`9dfefc3966a437684cfa67cd7c1113b55665956ff3869242887e14506b7c8af8`）；四场景顺序固定 `base_b0`（7 源/8 批）→ `base_b0_plus_v01`（8 源/9 批）→ `pre_v05_without_v07`（10 源/11 批）→ `post_v05_without_v01`（11 源/13 批） |
| 4 | 场景身份与 ingest | `docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json`（sha256=`362e3ea10f673021d78c7a647305f04b8557b364a14482ebc2ba370d7752ed19`）；文档名 → 代号由 `p2_runner.holdout_document_codes(场景 ingest plan)` 派生（规范名/去扩展名/文件名/去扩展名四级登记；同一名字两码 → `holdout_document_code_ambiguous`，不静默择一） |
| 5 | 原运行身份（任务 2 从 binding 读） | `code_version`（= `CODE_SCOPES` 全量源码摘要：`backend/src/mktkb/**/*.py` + `tools/p2_h2_controlled_execute.py`，v3 入口再把 `tools/p2_h2_v3_controlled_execute.py` 追加进 scope）、`plan_id`、`plan_sha256`、`plan_file_sha256`、`run_id`、`scenario_id`、`scenario_binding.source_map_sha256`、`scenario_binding.scenario_ingest_sha256` |
| 6 | 派生评分器身份（规则） | 期望 = `source_map[ref.doc_code]` 的 `(base_doc_code, version_number)`；观测 = `(source_map[holdout_document_codes[unit.document_name]].base_doc_code, unit.version_number)`；逐值相等 → 命中；`identity_sha256 = sha256(canonical_json({"source_map":…,"document_codes":…}))`；回执 schema `p2-h2-scorer-identity/v0.1`（v3 执行期 `p2-h2v3-scorer-identity/v0.1`） |
| 7 | 可运行的离线入口 | `.\.venv\Scripts\python.exe tools\p2_h2_controlled_execute.py recompute …`（参数见 §4.1，未增删）；验证顺序：① `result["identity"]["original"]` 与本 run binding 逐值相等；② `result["identity"]["derived_scorer"]["status"]=="derived"` 且 `source_map_file_sha256 == scenario_binding.source_map_sha256`；③ 卡过 `validate_hard_evidence_scorecard`；④ 四张卡过 `validate_hard_evidence_composition`（或 `compose_hard_evidence_runs` 内部已复核）；⑤ 任何 `status=="unresolved"` 都必须当作「文档级禁源未知」，让正式总门阻断，不得改成 pass |
| 8 | 已知必须先解决的阻断（如实交付） | 若真实 run 的 `inputs.source_map` 不是 `/v0.1` 或 `/v0.2`（例如历史合成夹具的 `synthetic-source-map/v1`），派生身份会是 `status="unresolved"` + `error_code="holdout_document_code_unmapped"`，文档级禁源全部 `unknown` → 卡仍产出但**不可 release**。任务 2 若发现 `status!="derived"`，需先拿到与计划钉住摘要一致的 v0.2 map，再重跑 recompute |

### 8.1 给任务 4 的固定常量（只增不删，可直接接线）

| 常量 | 位置 | 语义 |
| --- | --- | --- |
| `SOURCE_IDENTITY_SCHEMA_VERSION = "p2-h2-forbidden-source-identity/v0.1"` | `p2_hard_evidence.py` | 身份摘要 schema |
| `UNRESOLVED_SOURCE_IDENTITY` | `p2_hard_evidence.py` | 未提供可信身份时的哨兵（空映射 → 文档级禁源 `unknown`） |
| `p2-h2-scorer-identity/v0.1` | `SCORER_IDENTITY_SCHEMA_VERSION`（v2 工具） | 离线重建回执里的派生身份 |
| `p2-h2v3-scorer-identity/v0.1` | `SCORER_IDENTITY_SCHEMA_VERSION`（v3 工具） | v3 执行期 sidecar 身份 |
| `source_identity_invalid` | `HardEvidenceError` / tool 降级 `error_code` | 身份形状不可接受（重复身份、版本非正整数、空映射等） |
| `holdout_document_code_unmapped` | 既有（`p2_score_run.ERROR_CODE`，未改） | source map 读不到/版本不支持（本任务把它纳入派生身份的 `error_code`） |
| `holdout_document_code_ambiguous` | 既有（`p2_runner`，未改） | 同一文档名映到两个代号 |
| `source_map_missing` / `source_map_binding_mismatch` | v2 工具 | map 文件缺失 / 摘要与计划钉住值不一致（拒绝，不降级） |

原有固定 reason/错误码一个未删、一个未改义。

---

## 9. 遗留限制与未覆盖项

1. **真实 H2 材料未触碰**：C27/C29 的真实文档名映射、真实 run-binding、真实密文都在任务 2
   手上；本窗口只证明机制与合成链路。真实场景 `base_b0_plus_v01` 的 V01 违规是由本窗口用合成
   evidence 复现的，不代表真实运行的结论。
2. **v3 真实 `run` 未执行**：`_scorer_identity_state` 只有合成单元测试（真实 map + 合成 plan /
   ingest），没有跑过真实 live 执行（需要 GO/预算/账本与主人授权）。
3. **`record_code` 引用仍 fail closed**：投影 `units` 没有 record 级身份，带 `record_code` 的
   ref 继续 `unknown`（这是既有语义，未放宽）。
4. **`run_recompute_cli`（`mktkb.evaluation.cli p2-hard-evidence-recompute`）没有新增 CLI 参数**
   （`cli.py` 属任务 4 独占），该入口对纯文档引用仍 `unknown`；受控离线重建请走
   `tools/p2_h2_controlled_execute.py recompute`（本任务已接线）。
5. **并行工作树干扰**：`code_digest` 覆盖 `backend/src/mktkb` 全量源码，多任务共用一个工作树
   时任何一方改源码都会让“已钉住的 code_version”失效（`code_changed_since_plan`）。这是设计
   行为；§6.5 记录了它对既有 e2e 用例的瞬时影响及复核方式。
6. **未覆盖**：`p2_h2_controlled_execute.py` 的 `check_budget`/`run` 路径未做端到端回归（本任务
   未改其预算/GO/发送逻辑）；v3 的 `check-only` 新增 `scorer_identity` 检查没有专门的合成用例
   （只经过导入与既有 53 项 v3 测试）。
