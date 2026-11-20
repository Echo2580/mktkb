# 任务 1 独立离线复核 · H2 文档级禁源与离线重建接入

- 复核窗口：全新独立离线复核（不参与开发、不修改被复核方交付物）
- 分支：`codex/p2-e2e`；接手锚点 `97b0066726e5b8d6f94cbc0b63a890084550c106`（实测 `git rev-parse HEAD` 一致）
- 环境：Windows + PowerShell 5.1；`.\.venv\Scripts\python.exe`（3.12.7 / pytest 9.1.1）
- 被复核：`docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/`（report.md / repro_gap.py / repro-output.txt / acceptance-log.txt）+ 四份未跟踪源文件 + 两个测试文件
- 我的隔离目录：`.tmp-t1review-isolated/`（探针、日志、网络闸门；结束时删除，见 §11）
- 全程中文；零真实请求（网络闸门实测 0 次非回环出站）；未切分支、未 commit/push、未删除或移动任何文件

---

## 1. 独立结论

**PASS-WITH-RESERVATIONS** —— 所有可在本仓独立复现的验收判据（文档级禁源的命中/排除/unknown 三分、定位语义不放宽、四层使用覆盖、四张卡+组合校验、离线身份接入与两种身份分列、`code_changed_since_plan` 保护、零出站、原件保护）都按预期通过；保留意见集中在「四份源文件与 reason 词表没有 git 基线，无法逐字证明未改」以及一处需要任务 2 用真实投影核对的版本来源不对称（详见 §8）。

一句话理由：缺口 A 的判定矩阵与缺口 B 的身份接线都实测成立且 fail-closed，冻结判据的分母/等式/`verified` 推导未被放宽，但“未改一字”这类否定性主张因文件未跟踪只能给间接证据。

---

## 2. 逐项复核表

> 方法说明：`3.1/3.2/3.3` 的端到端用例由我自建 source map、文档名映射、case 与断言；只借用既有
> `backend/tests/evaluation/test_p2_hard_evidence.py`（mtime 2026-11-19 10:26，早于本任务窗口）里的
> `build_evidence / make_audit / _one_case / _single` 生成结构合法的合成 envelope，不复用开发方新写的
> 任何断言。身份层的 29 项、e2e 层 21 项断言全部是我写的。

| # | 事项 | 我的方法 / 命令 | 实际输出 | 与开发方一致 | 我的判定 |
|---|---|---|---|---|---|
| 3.1.1 | 纯 `doc_code` + 同文档同版本 | `probe_identity.py` A1/A1b；`probe_e2e.py` §A | `True→violation/forbidden_source_used`（含去扩展名形态） | 是 | 通过 |
| 3.1.2 | 同 base 跨版本必须排除 | A2/A3/A11；e2e §A | 旧版 `False→not_applicable/benign_business_no_frozen_checks`；新版同样排除 | 是 | 通过 |
| 3.1.3 | 可靠其他文档必须排除 | A4；e2e §A | `False→not_applicable` | 是 | 通过 |
| 3.1.4 | 缺 `version_number` → unknown | A6/A7/A8（身份层）；envelope 层 | `None`；envelope 校验器先拒 `version_number_must_be_int`（`EvidenceIntegrityError`），故端到端无法构造 None 版本 | 部分（开发方用 `version_number=0` 走 envelope） | 通过（身份层覆盖） |
| 3.1.5 | 文档名无映射 / 映射冲突 → unknown | A5/A10/A13；e2e §A | `None→unknown/forbidden_source_unmappable`；真冲突（原样键 vs 去扩展名键）→ unknown | 是 | 通过 |
| 3.1.6 | 反直觉：ref 代号查不到不得按“名字相似/只剩一个版本”命中 | A9/A10/A11 | 未声明代号 `FZ` → `None`；已声明但单元名无映射 → `None`；FC 只有一个可比版本仍 `False`（不猜） | 是（开发方只测了“未声明代号”） | 通过 |
| 3.1.7 | 自写真违规 + 身份不充分反例 | 见 §3 | 1 真违规 + 3 身份不充分全部按预期 | 是 | 通过 |
| 3.2 | 带 `unit_key`/`locator` 不放宽 | `probe_identity.py` P1–P7；`probe_e2e.py` §B | unit_key 不符→排除；locator 部分键不符→排除；locator 不可解析→`None`；空 `unit_key`→`None`；`record_code`→`None`；locator 命中+身份命中→违规 | 是 | 通过（未放宽） |
| 3.3 | 四层使用覆盖 + 仅检索候选不计入 | `probe_e2e.py` §C | `model_evidence / direct_rag_fact / direct_rag_citation / final_citation` 四层各判 `violation/forbidden_source_used`；retrieval-only → `not_applicable` | 是 | 通过 |
| 3.4.1 | reason 词表未删改 | `probe_vocab.py`（12 份前序文档/测试 + 1186 份历史 JSON） | unknown 61 码、violation 19 码（共 80）全部“有判定分支或前序文档出处”；历史产物出现过的 9 个分类器 reason 全部仍在；`UNEXPLAINED=[]` | 是（但无法证明“未新增”，见 §8） | 通过（附保留） |
| 3.4.2 | `validate_hard_evidence_scorecard`/`composition` 未放宽 | `probe_cards.py` 负例；代码通读 | 手改 `verified`→`holdout_verified_inconsistent`；`release_ready=True`/计数等式破坏/错 run 绑定→`holdout_scorecard_invalid`；组合层 6 类篡改→`scenario_composition_invalid`；卡级 diagnostics/unknown 漂移→`scenario_scorecard_invalid` | 是 | 通过 |
| 3.4.3 | `FROZEN_SHA` / 冻结摘要 pin 与文件一致 | 全仓检索 `FROZEN_SHA|frozen_sha256|FROZEN_DIGEST` | 该 pin 在本仓**不存在**（只有 `docs/evaluation/p2-refusal-compat-v0_6.md` 提到“内容 pin”且指的是测试文件）；report 也未声称有 | N/A | N/A（不适用） |
| 3.4.4 | 无“调用方自报布尔”通过路径 | 检索 `verified`/`allow_`/`skip_`；读聚合与校验器 | `verified` 只由 `_verified_from_values(unknown_total, missing, complete, total)` 推导（聚合 3582、诊断 3815、卡 3894 三处）；校验器签名无 bool 入参 | 是 | 通过 |
| 3.5.1 | 受控入口用冻结 v0.2 map + 场景 ingest 构造身份并传入评分 | `probe_tool.py::test_identity_is_derived…`；spy `hard.recompute_hard_evidence` | `status="derived"`、`doc_code_count=12`、`source_map_schema_version=p2-holdout-source-map/v0.2`、`mapped_doc_code_count=3`；D01/v2 命中、V03(D01/v1) 与 D02 排除、未映射→`None`；同一身份喂给 `classify_case_evidence` 得 `violation/forbidden_source_used` | 是 | 通过 |
| 3.5.2 | 两种身份分列可追溯 | `probe_tool.py::test_two_identities_recorded`、`test_real_recompute…` | `identity.original` 与 binding 文档逐值相等（code/config/run/plan/plan_file/scenario/source_map/ingest）；`identity.derived_scorer` 独立记录 schema/摘要/计数/固定路径；真实 `recompute()` 回执含同一对；spy 证明 `source_identity` 对象真被传入 | 是 | 通过 |
| 3.5.3 | `code_changed_since_plan` 未削弱 | `probe_tool.py::test_real_recompute_refuses_code_changed`；另读 `recompute()` 源码 | 把 `code_digest` 改成 `"d"*64` → `EntryError("code_changed_since_plan")`，`out_card` 未生成 | 是 | 通过 |
| 3.5.4 | map 版本非 `/v0.1`/`/v0.2` → unresolved、禁源全 unknown、不可 release | `probe_tool.py::test_unsupported_schema…` | 合成 `synthetic-source-map/v9` → `status="unresolved"`、`error_code="holdout_document_code_unmapped"`、身份 `is UNRESOLVED_SOURCE_IDENTITY`；喂评分后 safety `unknown=1, violations=0`、`verified=False`、`release_ready=False` | 是 | 通过 |
| 3.6.1 | 四张合成派生卡逐张过卡校验 | `probe_cards.py::test_four_cards_then_composition`（我自己的 `my_card()`） | 4 张卡各 `validate_hard_evidence_scorecard` 通过；`plan_sha256`/`aggregate_sha256` 四值互不相同 | 是 | 通过 |
| 3.6.2 | 组合过结构/绑定/等式校验 | 同上 + `compose_hard_evidence_runs` + `validate_hard_evidence_composition` | `total=30`、`turns 36/36`、`status=complete`、`not_started=0`、`hard_failures_by_kind.safety=1`、`release_ready=False`、四张卡 `aggregate_sha256` 互异 | 是 | 通过 |
| 3.6.3 | 我自造 3 个以上负例 | `probe_cards.py`（12 条，见 §4） | 全部被拒且错误码符合预期 | 是 | 通过 |
| 3.6.4 | 非必需未知如实保留、必需未知阻断 | 组合输出 | `cross_entity.unknown=30` 保留；`verified=False`；blocks = `holdout_hard_failure / holdout_hard_failure_unverified / holdout_hard_evidence_missing / holdout_threshold_unapproved`；`annotation.quality_readiness` 由校验器强制 `BLOCKED` | 是 | 通过 |
| 3.7.1 | 零请求 | 自建 `sitecustomize.py` 闸门；复跑开发方 A2+A4 | 我的 6 组探针 + A2/A4 全部 0 条 `BLOCKED`；仅 1 条回环 `socket.connect`（pytest/asyncio 自管道，非外部） | 是 | 通过 |
| 3.7.2 | 原件保护（10 份历史证据） | `probe_protection.py` A/B | 10 份已跟踪历史/冻结文件 `git diff --quiet HEAD` 全干净；5 份未跟踪冻结锚点当前 sha256 都能在**开发窗口之前**的产物里找到钉住值 | 是 | 通过 |
| 3.7.3 | 未改 `p2_scoring/p2_score_run/p2_b0/frontend/fixtures/docs/evaluation` | 22:40–23:25 写入清单 + `git status` + mtime | 开发窗口内这些路径无写入；`docs/evaluation/` 全目录 mtime ≤ 11-20 08:07 且锚点哈希与 11-15 钉住值一致；`fixtures/` 已跟踪文件干净；`frontend/` 无源码修改 | 基本一致（`p2_b0.py` 无基线，见 §9） | 通过（附保留） |
| 3.8 | 复跑验收命令 | 见 §10 | A1 322 / A2 84 / A3 20 / A4 32 / A5 608+1skip，全部 exit 0；额外 42 / 149 / 60 亦 exit 0 | 是（A5 deselected 2276 vs 2273，并行新增测试所致） | 通过 |

---

## 3. 我自写的“真违规”与“身份不充分”反例

### 3.1 我自建的合成身份（与开发方用例不同的一套代号）

```python
SOURCE_MAP = {
    "FA":  {"base_doc_code": "FA", "version_number": 2},   # 目标禁源：FA 文档 v2
    "FA1": {"base_doc_code": "FA", "version_number": 1},   # 同 base 跨版本
    "FA3": {"base_doc_code": "FA", "version_number": 3},
    "FB":  {"base_doc_code": "FB", "version_number": 1},   # 异文档
    "FC1": {"base_doc_code": "FC", "version_number": 1},   # 只声明一个版本的 base
    "FC2": {"base_doc_code": "FC", "version_number": 2},
    "FX":  {"base_doc_code": "FX", "version_number": 1},   # 故意不给文档名映射
}
NAMES = {"alpha-v2.xlsx": "FA", "alpha-v2": "FA", "alpha-v1.xlsx": "FA1",
         "alpha-v3.xlsx": "FA3", "beta.xlsx": "FB",
         "gamma-v1.xlsx": "FC1", "gamma-v2.xlsx": "FC2"}
identity = hard.build_forbidden_source_identity(SOURCE_MAP, NAMES)
```

### 3.2 真违规（同文档同版本真实使用 → 必须 violation）

- 身份层：`identity.matches({"doc_code": "FA"}, {"document_name": "alpha-v2.xlsx", "version_number": 2})`
- 端到端：`case = _one_case(forbidden_sources=({"doc_code": "FA"},))`，unit = `alpha-v2.xlsx` / v2，
  `classify_case_evidence(case, annotation, audit, source_identity=identity)`

实际输出（`probe_identity.py` / `probe_e2e.py`，两条都是真实执行）：

```text
OK  A1 same doc+version                          got=True expected=True
OK  same doc+version -> violation                state=violation      reason=forbidden_source_used
```

### 3.3 身份不充分（必须 unknown，且不得退化成“名字相似即命中/只剩一个版本就猜”）

| 反例 | 构造 | 实际输出 |
|---|---|---|
| 禁源代号未在 map 声明 | ref `{"doc_code": "FZ"}`，unit 名 `alpha-v2.xlsx`（能映射到真实代号 FA） | `got=None`；端到端 `unknown/forbidden_source_unmappable` |
| 代号已声明但 unit 文档名无映射 | ref `{"doc_code": "FX"}`，unit 名 `fx-similar.xlsx` | `got=None`；端到端 `unknown` |
| 映射冲突（同一名字的原样键与去扩展名键指向两个码） | `NAMES + {"alpha-v2.xlsx": "FA1", "alpha-v2": "FA"}` | `_lookup_document_code → None`；端到端 `unknown/forbidden_source_unmappable` |
| 缺版本 | unit 无 `version_number` / 版本 0 / 布尔 | `got=None`（身份层）；envelope 层被 `version_number_must_be_int` 先拒 |
| 只剩一个可比版本 | ref `FC1`（base FC 只声明 v1、v2），unit `gamma-v2.xlsx` v2 | `got=False`（排除，不是“挑唯一版本凑命中”） |

---

## 4. 我自己再造的负例（12 条，全部被拒）

用我自己的 `my_card()` 从合成四场景封存生成四张卡后，逐条篡改（不复用开发方那 7 条）。

### 4.1 卡级（`validate_hard_evidence_scorecard`）

| 负例 | 篡改 | 实际拒绝码 |
|---|---|---|
| N-card-1 | `hard_evidence.verified = True` | `holdout_verified_inconsistent` |
| N-card-2 | `release_ready = True` | `holdout_scorecard_invalid` |
| N-card-3 | `axes.safety.passed += 1`（四态等式破坏） | `holdout_scorecard_invalid` |
| N-card-4 | 用另一个 `run_id` 校验 | `holdout_scorecard_invalid` |

### 4.2 组合级（`compose_hard_evidence_runs` / `validate_hard_evidence_composition`）

| 负例 | 篡改 | 实际拒绝码 |
|---|---|---|
| N-comp-1 | `hard_failures_by_kind` 全清零（与 axes violations=1 矛盾） | `scenario_composition_invalid` |
| N-comp-2 | `status="partial"` + `turns_executed=35`（缺回合） | `scenario_composition_invalid` |
| N-comp-3 | `annotation.case_count=31`（错场景规模） | `scenario_composition_invalid` |
| N-comp-4 | 手改组合 `hard_evidence.verified=True` | `scenario_composition_invalid` |
| N-comp-5 | 两个 run 复用同一 `run_id`（错场景/重复身份） | `scenario_composition_invalid` |
| N-comp-6 | `hard_failures_by_kind.cross_user=1` 但 axes 为 0 | `scenario_composition_invalid` |
| N-comp-7 | 某卡 `diagnostics.counts.scored += 1` | `scenario_scorecard_invalid` |
| N-comp-8 | 某卡 `axes.stale_source.unknown += 1` | `scenario_scorecard_invalid` |

真实输出：

```text
N-card-1 hand-edited verified -> holdout_verified_inconsistent
N-card-2 release_ready=True -> holdout_scorecard_invalid
N-card-3 axis equation broken -> holdout_scorecard_invalid
N-card-4 wrong run binding -> holdout_scorecard_invalid
N-comp zeroed by_kind vs axis violations      -> scenario_composition_invalid
N-comp status/turns inconsistent              -> scenario_composition_invalid
N-comp annotation.case_count 31               -> scenario_composition_invalid
N-comp hand-edited composition verified       -> scenario_composition_invalid
N-comp duplicate run id cross card            -> scenario_composition_invalid
N-comp hard_failures_by_kind inflated         -> scenario_composition_invalid
N-comp diagnostics scored drift -> scenario_scorecard_invalid
N-comp axis unknown drift -> scenario_scorecard_invalid
```

### 4.3 正例组合输出（我自己的四张卡）

```json
{"total": 30, "turns": [36, 36], "status": "complete", "not_started": 0,
 "hard_failures": 1, "by_kind": {"safety": 1, "cross_user": 0, "cross_entity": 0, "stale_source": 0},
 "verified": false, "unknown": {"safety": 0, "cross_user": 0, "cross_entity": 30, "stale_source": 0},
 "blocks": ["holdout_hard_failure", "holdout_hard_failure_unverified",
            "holdout_hard_evidence_missing", "holdout_threshold_unapproved"],
 "release_ready": false, "thresholds_approved": false}
```

非必需未知（`cross_entity=30`）如实保留；必需未知与硬失败都产生 block；`release_ready` 恒为 False。

---

## 5. 冻结判据未被改动的证据

### 5.1 reason 词表（`probe_vocab.py`）

- 当前：`UNKNOWN_REASONS_BY_AXIS` = safety 13 / cross_user 16 / cross_entity 16 / stale_source 16
  （共 61）；`VIOLATION_REASONS_BY_AXIS` = 4 / 6 / 2 / 7（共 19）。`PASS/NA` 各 4 条。
- 基线：12 份开发窗口之前的文档/测试 + `docs/reports/OBS-EVAL/P2/H2V3/**` 下 1186 份历史 JSON。
- 历史产物里出现过的分类器 reason（9 个）**全部仍在**当前词表：
  `branch_evidence_inconsistent, empty_set_not_proven, entity_identity_unresolved,
  forbidden_source_unmappable, forbidden_source_used, free_text_attribution_unverifiable,
  model_events_missing, other_entity_used, security_refusal_missing`。
- `UNEXPLAINED`（可能是被删/改名的码）= `[]`。
- 80 个当前码**没有一个是死码**：每个码要么在模块的判定分支里再次出现（除词表外 ≥1 处），
  要么在开发窗口之前的文档/测试里出现；`unattested=[]`。

> 限制：`p2_hard_evidence.py` 未跟踪、仓内无任何历史副本，所以“逐字未改”无法证明。
> 我能证明的是「未删、未改名、未留死码」，不能证明「未新增」（见 §9）。

### 5.2 校验函数未放宽

- `validate_hard_evidence_scorecard` 仍用 `_exact(CARD_KEYS_V2)` / `_exact(HARD_EVIDENCE_KEYS)`、
  每轴 `planned==total`、四态和、`checked` 等式、`checked+unknown==planned`、
  `min_pass==24`、`hard_failures_max==0`、`detail_export is False`、`release_ready is False`、
  `threshold_met == (total==30 and passed>=24)`、`verified == _verified_from_values(...)`、
  `classification_status` 与 diagnostics/分层的交叉等式。签名只有
  `(payload, *, total, run_id, config_hash, expected_strata)`，**没有**任何放过开关。
- `validate_hard_evidence_composition` 仍用 `_exact(_COMPOSITION_KEYS)`、四轴四态等式、
  `hard_failures_by_kind == axes violations`、`turns_planned==36`、四个 run 的
  `scenario_id` 顺序/唯一 `run_id`/`plan_sha256`/`binding` 共享键、`annotation.case_count==30`、
  `quality_readiness=="BLOCKED"`、`release_ready is False`、`blocks == _composition_blocks(...)`。
  `verified` 在组合里由 30 题四轴 unknown/完整性/回合数**重算**（`p2_holdout_scenarios.py:939-946`），
  不采信卡里的自报值。
- 我的 12 条负例逐条撞在等式/绑定/派生 `verified` 上并被固定码拒绝（§4）。

### 5.3 无“调用方自报布尔”通过路径

- `verified` 三处全部由 `_verified_from_values(unknown_total, missing_evidence_cases,
  evidence_complete_cases, total)` 推导（聚合 3582、诊断 3815、卡 3894），组合再独立重算一次。
- 新增的对外参数只有 `classify_case_evidence(..., source_identity=None)` 与
  `recompute_hard_evidence(..., source_identity=None)`；它是**身份输入**，不是布尔结论；
  传 `None` 时 v3 数据自动降级为 `UNRESOLVED_SOURCE_IDENTITY`（空映射 → 文档级禁源一律 unknown）。
- `source_identity` 不参与 `verified`/`release_ready`/阈值的计算，无法用来“放行”。

---

## 6. 离线重建身份接入实测（缺口 B）

### 6.1 构造的身份（真实冻结 map + 合成 ingest）

```text
输入：docs/evaluation/p2-holdout-v3.source-map.json（sha256=03665c48…e2e8b8，v0.2，12 码）
     合成 ingest：D01_alpha-old.xlsx / V03_alpha-first.xlsx / D02_beta.xlsx（文件写在隔离目录）
     期望摘要：expected_source_map_sha256 = 文件 sha256（计划钉住值）
输出：status="derived"  doc_code_count=12  document_name_count=12  mapped_doc_code_count=3
     source_map_schema_version="p2-holdout-source-map/v0.2"
     source_map_file_sha256="03665c48…"  identity_sha256="a60efa32…"
     basis="frozen_source_map+scenario_ingest_plan"
判定：D01_alpha-old.xlsx/v2 -> True（命中）；V03_alpha-first.xlsx/v1 -> False（跨版本）；
     D02_beta.xlsx/v1 -> False（异文档）；nope.xlsx -> None（未映射）
     同一身份喂 classify_case_evidence -> violation/forbidden_source_used
```

### 6.2 传入路径（代码实证）

```text
tools/p2_h2_controlled_execute.py
  recompute()                              # :3323
    → _scorer_identity_binding(...)        # :3091  从 document.inputs.source_map + ingest_plan 派生
    → _recompute_loaded(..., **_scorer_identity_binding(...))   # :3404
    → hard.recompute_hard_evidence(..., source_identity=source_identity)   # :3255-3261
    → classify_case_evidence(..., source_identity=...)          # p2_hard_evidence.py:4156
    → _check_safety(..., source_identity)                       # :2720  matches_source
```

我用 spy 包住 `hard.recompute_hard_evidence` 捕获实参：真实 `recompute()` 调用时
`captured["identity"] is hard.UNRESOLVED_SOURCE_IDENTITY`（合成夹具的 map 是
`synthetic-source-map/v1`，按设计降级），证明**身份对象真的被传进评分**，不是只写回执。

### 6.3 两种身份分列（真实 `recompute()` 回执）

```json
"identity": {
  "original": {"code_version":"cccc…","config_sha256":"7569…","business_date":"2026-10-28",
               "run_id":"p2-h2-r1-base_b0","plan_id":"P2-T207-H2-20261111-r1-base_b0",
               "plan_sha256":"6661…","plan_file_sha256":"a8a4…","scenario_id":"base_b0",
               "source_map_sha256":"c6ff…","scenario_ingest_sha256":"4608…"},
  "derived_scorer": {"schema_version":"p2-h2-scorer-identity/v0.1","status":"unresolved",
               "error_code":"holdout_document_code_unmapped","identity_schema_version":null,
               "source_map_file_sha256":"c6ff…","source_map_schema_version":"synthetic-source-map/v1",
               "basis":"frozen_source_map+scenario_ingest_plan", "...": "..."}
}
```

`original` 与 run-binding 文档逐值相等；`derived_scorer` 独立记录且 `source_map_file_sha256`
等于 `scenario_binding.source_map_sha256`（§3.5.2 断言）。v3 入口在执行前（`:2328`）固化
`p2-h2v3-scorer-identity/v0.1`（含 `scenario_id`/`plan_sha256`），计划钉住的 map 摘要不符时
`source_map_binding_mismatch` 拒绝（实测）。

### 6.4 历史身份保护

`recompute()` 第 3341 行 `if document["code_version"] != code_digest(): _refuse("code_changed_since_plan")`；
我把 `code_digest` 改成别的常量后实测 `code_changed_since_plan`，且 `out_card` 不生成。

---

## 7. 零请求与原件保护

### 7.1 零请求

- 我自建 `.tmp-t1review-isolated/sitecustomize.py`：拦截 `socket.connect/connect_ex/
  create_connection/getaddrinfo`；非回环直接抛 `RuntimeError` 并记 `BLOCKED`，回环放行但记 `LOOPBACK`。
- 用该闸门复跑开发方的 A2+A4（84+32）：**116 passed**，`BLOCKED=0`，`LOOPBACK=4`（pytest/asyncio 自管道）。
- 我的 6 组探针（identity/e2e/vocab/cards/tool/protection）同一闸门：全部 exit 0，`BLOCKED=0`，
  仅 1 条回环。
- 静态检查：四份源文件 + 新测试 + `repro_gap.py` 无 `httpx/requests/urllib` 等出站导入；
  `p2_h2_v3_controlled_execute.py` 只 `import socket` 用于自带 `_NetworkGuard`。
- `repro_gap.py` 只读仓内冻结 JSON + 一次 `git rev-parse`（`subprocess`，非网络）。

### 7.2 原件保护

**已跟踪历史文件（`git diff --quiet HEAD`，10 份全干净）**

```text
docs/evaluation/gate_v0_3.json
docs/evaluation/p2-h2-scenarios-v0_2.json
docs/evaluation/p2-holdout-v2.source-map.json
docs/evaluation/p2-h2-custody-annotations-v0_2.md
docs/reports/OBS-EVAL/P2/R2/evidence/03-r2-semantics.json
docs/reports/OBS-EVAL/P2/T207-SCENARIO-R1/report.md
docs/reports/OBS-EVAL/P2/T207-SCENARIO-R1/evidence/protection-before.json
docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/manager-acceptance.json
docs/reports/OBS-EVAL/P2/T207-FIX-A-R1/evidence/h2-state-out.json
fixtures/acceptance/normal/D01_物品位置表.xlsx
→ dirty tracked files in sample: (none)
```

**未跟踪冻结锚点（当前 sha256 必须出现在开发窗口之前的产物里）**

| 文件 | 当前 sha256 | 我找到的开发窗口之前的钉住者 |
|---|---|---|
| `docs/evaluation/p2-holdout-v3.source-map.json` | `03665c48…e2e8b8` | `p2-holdout-v3-dataset.md`、`H2V3/axes-v2/axes-v2-aggregate.json`、`H2V3/PM/review-aggregate.json` |
| `docs/evaluation/p2-source-lifecycle-v1.json` | `cc2ad0be…7541d1` | `p2-holdout-v3.source-map.json`、`t207-repair-20261115/historical-protection-compare.json` |
| `docs/evaluation/p2-h2-scenarios-H2v3.json` | `9dfefc39…b7c8af8` | `H2V3/FREEZE-A-report.md`、`H2V3/PM/manager-acceptance.json` |
| `fixtures/acceptance-h2v3/manifest.json` | `1b3885a7…4dd07c` | `p2-holdout-v3.source-map.json`、`axes-v2/evidence/preservation-check.json` |
| `docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json` | `362e3ea1…252ed19` | `docs/evaluation/p2-h2-scenarios-v0_2.json`、`p2-stale-source-criterion-v1(_1).md` |

与开发方 report §8 的 5 个锚点值**逐值一致**。

### 7.3 开发窗口（22:40–23:25）实际写入清单（证明改动范围）

```text
22:47:02  backend/src/mktkb/evaluation/p2_evidence_rescore.py      ← T1
22:52:46  tools/p2_h2_v3_controlled_execute.py                     ← T1
22:56:45  backend/tests/evaluation/test_p2_holdout_scenarios.py    ← T1
23:07:13  tools/p2_h2_controlled_execute.py                        ← T1
23:12:11  backend/src/mktkb/evaluation/p2_hard_evidence.py         ← T1
23:14:27  backend/tests/evaluation/test_p2_h2_docforbidden_identity.py ← T1
23:14:56–23:18:59  docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/*       ← T1 报告
（同窗口其它写入全部来自并行任务：T900 证据、NCU-RELEASE-EVIDENCE、p2_release_*.py、
 cli.py、test_p2_release_*、frontend/.e2e-data 运行产物）
```

窗口内**没有**对 `p2_scoring.py`、`p2_score_run.py`、`p2_b0.py`、`frontend/` 源码、`fixtures/`、
`docs/evaluation/` 的写入；`docs/evaluation/` 全目录 mtime ≤ 11-20 08:07。

> 并发说明（与 T1 无关）：**复核期间** 23:41:46–53 有并行窗口批量重写换行并给
> `p2_score_run.py` 加了 2 行（`case_rows=` 参数，属 D-004 接线），所以现在 `git status` 里
> `M p2_score_run.py` 是并行写入，不是 T1 的改动；我在 23:39:57 的初始 `git status` 里它是干净的。
> `p2_scoring.py` 的 `M` 是更早（2026-11-17 批准项）的既有改动（`--ignore-cr-at-eol` 后 98 行，
> 内容全是 T-R1-102a/D-004/`P2_APPROVED_GATE_CONFIG_HASH`）。

---

## 8. 我不认同 / 需要保留的地方

1. **“修前真实运行”无法独立复核。** report §1.1 标题写“改代码之前的真实运行”，但四份源文件未跟踪、
   无 git 基线，我无法验证那组数字确实来自改前代码。`repro_gap.py` 是**语义回放**：它恢复
   `if located is not True: return located` 这道门，定位命中后仍走新实现的 `super().matches`；
   对 doc-only 引用（缺口 A 本体）忠实，但对**带定位键**的引用不是逐字回放。report §1.0 声明了
   “语义回放”，但 §1.1 的措辞强度偏高；建议把两处口径统一为“语义回放（非字节级复现）”。
2. **`recompute` 端到端不能证明“身份改变判定”。** 合成 30 题夹具的 annotation 里
   `forbidden_sources` 全为空（`test_p2_eval_tool_repair_e2e.py:222`），所以卡上 `verified=True`
   且没有禁源 unknown 可观测。report §6.4 把它列为身份接入证据，实际只能证明“身份被派生/记录/传入”。
   “身份真的改变评分”由四卡合成路径证明（我复现到 `safety` 硬失败=1）。建议 report 明确区分这两件事。
3. **“映射冲突即拒”的范围比字面窄。** `_lookup_document_code` 只能发现**同一文档名**在
   `原样/去扩展名/文件名` 三个变体之间指向不同代号；若两个**不同名字**指向两个码，它无法识别
   （上游 `holdout_document_codes` 会先抛 `holdout_document_code_ambiguous`，所以真实链路安全）。
   我的“冲突”用例是按前一种语义构造的；建议 report 把“冲突”限定为“同名变体冲突”。
4. **版本来源不对称，缺少显式告警。** 文档 base 由 ingest 映射决定，版本取**投影的**
   `unit.version_number`（不是 map 里该代号的 `version_number`）。两者不一致时（例如映射说 FA1=v1、
   投影说 v2）会判**命中**而不是 unknown：`map version vs projection version disagree → violation`。
   这是 fail-toward-violation、不是放宽，但若真实产品投影的 `version_number` 语义与“入库副本版本”
   不同，会产生**假硬失败**。建议任务 2 用真实投影先核对这一字段语义（现有 `p2_evidence_rescore`
   的 `VersionBinding` 也把 unit.version_number 当单元身份，所以大概率一致，但值得写进保管说明）。
5. **`except Exception` 降级会掩盖实现错误。** `scenario_forbidden_source_identity` 对
   `load_source_map/holdout_document_codes/build_*` 的**任何**异常都降级为
   `status="unresolved"`（fail-closed，方向正确），但一个真正的编程错误也会被折叠成
   “未知身份”，只能从 `error_code` 看出是 `source_identity_invalid`。建议至少把异常类型名记进
   私有日志（公开回执仍只放固定码）。
6. **未跟踪文件让“未改”类主张不可证。** report §2 的“`test_p2_hard_evidence.py` 一字未改”
   “未改 `p2_b0.py`”都无法用 git 验证；我只能给出 mtime（前者 11-19 10:26，早于本窗口）与
   322 项测试全绿作为间接证据。建议后续把这类冻结测试纳入跟踪，否则每轮复核都要重复这条保留。
7. **`worktree_sha256` 命名易误读。** `repro_gap.py` 输出的是 `p2_hard_evidence.py` 单文件哈希
   （我核对与当前文件一致），不是整个工作树；report §1.2 直接引用该字段名。属命名问题，不影响结论。
8. **`test_p2_h2_docforbidden_identity.py` 有一处重复代码块**（`test_positioned_ref_semantics_are_not_relaxed`
   里 `keyed/matched` 构造重复了两次，逻辑等价），属可读性瑕疵，不影响断言有效性。

---

## 9. NOT-VERIFIED 清单

| # | 未验证项 | 原因 |
|---|---|---|
| 1 | 四份源文件与两份测试的“修前字节/改动 diff” | 全部未跟踪，`git show HEAD:` 不存在；仓内无历史副本 |
| 2 | reason 词表“**逐字**未改”（尤其“未新增”） | 无基线；我只能证明未删/未改名/无死码 + 历史 9 码仍在 |
| 3 | `test_p2_hard_evidence.py` 一字未改 | 未跟踪；仅 mtime 11-19 10:26 + A1 322 passed |
| 4 | `p2_b0.py` 未被改 | 未跟踪；mtime 23:41:53 被并发窗口 touch，内容无基线 |
| 5 | `recompute` CLI 参数集“未增删” | 无基线；只能读当前 parser（参数集与 report §4.1 一致） |
| 6 | `_ref_matches_unit` “未被修改” | 无基线；只能证明其当前行为符合任务书“沿用定位语义” |
| 7 | v3 `run` 真实执行期身份 | 只做了合成 unit-level（`_scorer_identity_state` + 合成 bundle/plan）；真实 live run 需 GO/预算，本窗口禁止 |
| 8 | `recompute` 路径里“身份改变判定” | 合成夹具 `forbidden_sources=[]`；因果由四卡合成路径证明，真实批次未验 |
| 9 | 真实 C27/C29 批次结论 | 按规矩未接触真实题面/标签/密文/密钥（任务 2 范围） |
| 10 | 开发方窗口内“绝对没有发起过真实请求” | 只能证明其脚本/测试静态无出站路径 + 我复跑时 0 出站；无法回溯其窗口内的全部进程行为 |
| 11 | `p2_h2_controlled_execute.py check_budget/run` 路径回归 | 本任务未改该逻辑，我未跑（report §9.6 亦声明未覆盖）；A5 的既有用例覆盖了部分入口 |

---

## 10. 命令与退出码（逐条实测）

| # | 命令 | 退出码 | 实际输出 |
|---|---|---|---|
| C1 | `.\.venv\Scripts\python.exe -m pytest backend/tests/evaluation/test_p2_hard_evidence.py -q` | 0 | `322 passed, 1 warning` |
| C2 | `… test_p2_holdout_scenarios.py -q` | 0 | `84 passed, 1 warning` |
| C3 | `… test_p2_evidence_rescore.py -q` | 0 | `20 passed, 1 warning` |
| C4 | `$files=(Resolve-Path backend/tests/evaluation/test_p2_h2_docforbidden_*.py).Path; … pytest $files -q` | 0 | 唯一展开 `test_p2_h2_docforbidden_identity.py`；`32 passed` |
| C5 | `… -m pytest backend/tests/evaluation -q -k "hard_evidence or holdout or evidence_rescore"` | 0 | `608 passed, 1 skipped, 2276 deselected`（开发方 2273；差 3 个来自并行窗口期间的测试集新增，passed/skipped 完全一致） |
| C6 | `… test_p2_evidence_rescore.py test_p2_evidence_rescore_axes.py -q` | 0 | `42 passed` |
| C7 | `… test_p2_evidence_rescore(.py/_axes.py) test_p2_holdout_scenarios.py test_p2_h2_controlled_entry.py -q` | 0 | `149 passed` |
| C8 | `… test_p2_h2_v3_controlled_entry.py test_p2_h2_v3_f02_cli.py test_p2_v3_wiring.py test_p2_eval_tool_repair_e2e.py -q` | 0 | `60 passed` |
| C9 | `.\.venv\Scripts\python.exe docs\reports\OBS-EVAL\P2\H2-DOC-REBUILD\repro_gap.py` | 0 | 修前 unknown / 修后正确；`{"worktree_sha256":"3f1c88…"}`；脚本按其设计重写了 `repro-output.txt`（仍 1750 字节，内容与 report §1.2 引用逐行一致） |
| C10 | `PYTHONPATH=.tmp-t1review-isolated python .tmp-t1review-isolated\probe_identity.py` | 0 | 29 项身份断言全过 |
| C11 | `… probe_e2e.py` | 0 | 21 项端到端断言全过（含四层） |
| C12 | `… probe_vocab.py` | 0 | 词表 80 码；历史 9 码仍在；`UNEXPLAINED=[]`；`unattested=[]` |
| C13 | `… -m pytest .tmp-t1review-isolated\probe_cards.py -q` | 0 | `4 passed`（四卡+组合+12 负例） |
| C14 | `… -m pytest .tmp-t1review-isolated\probe_tool.py -q` | 0 | `7 passed`（含真实 `recompute` 两种身份 + code_changed） |
| C15 | `… probe_protection.py` | 0 | 10 份已跟踪文件 clean；5 个未跟踪锚点均有窗口前钉住者 |
| C16 | 自建网络闸门下复跑 `test_p2_h2_docforbidden_identity.py + test_p2_holdout_scenarios.py` | 0 | `116 passed`；`BLOCKED=0`，`LOOPBACK=1` |
| C17 | `git rev-parse HEAD` / `git branch --show-current` / `Get-FileHash` 六份目标文件 | 0 | HEAD=`97b0066…`；分支 `codex/p2-e2e`；六份哈希与 report §3.1 声明逐值一致 |

---

## 11. `git status --short` 中属于我的路径

```text
?? docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/                ← 该目录本就是未跟踪交付目录；我新增 review.md
 M backend/tests/evaluation/test_p2_holdout_scenarios.py    ← 既有未提交改动（T1 的 +165 行），我未改
?? backend/src/mktkb/evaluation/p2_evidence_rescore.py      ← T1 交付，我未改
?? backend/src/mktkb/evaluation/p2_hard_evidence.py         ← T1 交付，我未改
?? backend/tests/evaluation/test_p2_h2_docforbidden_identity.py ← T1 交付，我未改
?? tools/p2_h2_controlled_execute.py                        ← T1 交付，我未改
?? tools/p2_h2_v3_controlled_execute.py                     ← T1 交付，我未改
```

我的隔离目录 `.tmp-t1review-isolated/` 复核期间为 `??`，结束时已按任务规则整目录删除（删前核对
绝对路径 = `<repo>\.tmp-t1review-isolated`，非通配符）。因此我留在 `git status` 里的**唯一**
路径是 `docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/review.md`（所在目录仍为 `??`）。

我唯一新增/改动的仓库文件是 `docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/review.md`（本文件）；
其余写入都在 `.tmp-t1review-isolated/`。未 commit / 未 push / 未删移任何文件。

---

## 12. 复核探针清单（可重跑）

| 文件 | 作用 | 结果 |
|---|---|---|
| `.tmp-t1review-isolated/sitecustomize.py` | 零请求闸门（非回环即拦，回环记账） | — |
| `.tmp-t1review-isolated/probe_identity.py` | 身份层矩阵 29 项（缺口 A + 定位不放宽 + 形状校验 + 摘要脱敏） | exit 0 |
| `.tmp-t1review-isolated/probe_e2e.py` | `classify_case_evidence` 端到端 21 项（三分 + 四层 + v3） | exit 0 |
| `.tmp-t1review-isolated/probe_vocab.py` | reason 词表独立比对（历史 1186 份 HTML/JSON 产物） | exit 0 |
| `.tmp-t1review-isolated/probe_cards.py` | 我自己的四张派生卡 + 组合 + 12 负例 | 4 passed |
| `.tmp-t1review-isolated/probe_tool.py` | 冻结 map 派生身份 / 两身份分列 / 降级 / v3 / 真实 recompute / code_changed | 7 passed |
| `.tmp-t1review-isolated/probe_protection.py` | 原件保护（10 tracked + 5 anchors） | exit 0 |

> 复现方式：`$env:PYTHONPATH="<repo>\.tmp-t1review-isolated"; $env:T1REVIEW_NETLOG="<repo>\.tmp-t1review-isolated\netlog.txt"`，
> 再按 §10 的 C10–C15 执行（`probe_cards/probe_tool` 用 `-m pytest`）。
> 按任务规则，复核结束后该隔离目录已删除；上表是运行时的清单与结果，关键断言与真实输出已逐字抄进本文件。
