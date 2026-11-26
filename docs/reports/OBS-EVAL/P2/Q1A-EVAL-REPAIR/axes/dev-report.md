# Q1a-1b 开发报告：P2 其余三轴重评分模块（Q1A-RESCORE-20261114-r1 / axes-v0.1）

- 日期：2026-11-14
- 角色：Q1a-1b 开发助手（普通开发；**不是**独立验收/经理）
- 分支/HEAD：`codex/p2-e2e` / `97b0066726e5b8d6f94cbc0b63a890084550c106`
- 状态：**实现、适配层与合成测试完成，待全新独立验收**。本报告不写 `T207 通过`、
  `Q1A 通过`、`release`、`verified`、`threshold_met`。
- 工作区：只新增本包允许文件；未 stage/commit/push；未改任何既有 tracked/untracked
  保护件；暂存区为空。

## 1. 交付物

| 文件 | 作用 |
|---|---|
| `backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py` | 三轴重评模块：cross_user / cross_entity / stale_source、四轴计数、provenance、Q1a-2 v1 薄适配层 |
| `backend/tests/evaluation/test_p2_evidence_rescore_axes.py` | 22 个合成测试（含 netguard 零出站断言、Q1a-2 适配层形状/拒绝码） |
| `docs/evaluation/p2-evidence-rescore-v0_2.md` | 契约 v0.2（三轴语义、输入 schema、固定码、优先级、unknown 传播、v0.1 兼容、R-06/R-07、适配层、禁止项） |
| `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/**` | 本报告与证据 |
| `docs/evaluation/q1a-scope-targets-contract-v1.md` | **只读**公开 schema；未修改，未读仓外私有密文 |

未改 `p2_hard_evidence.py`、`p2_evidence_rescore.py`、`test_p2_evidence_rescore.py`、
`p2-evidence-rescore-v0_1.md`、`Q1A-EVAL-REPAIR/evaluator/**`、C 冻结 12 对象及
2026-11-14 旧卡/case-plan/回执/seal/密文/账本/预算/GO。

## 2. 实现要点

1. **复用 matcher v2**：直接 import `p2_evidence_rescore.match_ref_to_unit()`/
   `VersionBinding`/`UnitView`/`ref_key`；不复制、不改写 Q1a-1 模块。`target_refs`
   与 `stale_source` 版本约束都用 matcher v2 核对 `doc_code`/`record_code`/版本/
   `unit_key`/`locator` 身份。
2. **三轴语义**：
   - `cross_user`：owner/claim/request/context/QueryState/实体继承/结果消息的确定性
     归属核对；全部 required，N/A 非法。
   - `cross_entity`：显式合同 mode（entity_bound / shared_background_only /
     no_entity_scope）、targets、shared_background、targets_refs、facts；目标/scope
     缺失一律 unknown，不猜。
   - `stale_source`：lifecycle、版本约束、`as_of`/`temporal_intent`、最终引用 FK；
     `document_deleted`/`version_state`/`active` 缺失一律 unknown，不把缺失当
     violation，也不当 pass。
3. **fail closed**：缺合同、缺字段、坏枚举、身份不完整、来源标记不可信一律
   `unknown`；缺合同不降级为 N/A/pass；旧 `unknown` 不得改 N/A（审计码
   `unknown_to_na_blocked`）；旧 `violation` 命中前置门时保留旧 verdict。
4. **basis 只进 provenance**：`AxisAnnotation.basis` / Q1a-2 `cases[i].basis` 只写入
   `AxesCaseResult.axis_basis`、报告 `axes_basis_counts` 与 `changed_cases[].basis`，
   **不参与 verdict 折叠**；`no_provable_basis_keep_unknown` 本身不改变 pass/unknown。
5. **四轴输出**：`planned`/`checked`/`passed`/`not_applicable`/`unknown`/`violations`
   逐轴自洽；`axes_provenance` safety=`recorded_old`、三轴=`rescored`；
   `axes_provenance_counts` 另给逐案 `preserved_old_verdict`；
   `changed_cases` 逐条 old→new + audit codes；old/new 分列；不输出
   `verified`/`threshold_met`/`release_ready`/`release`/`T207_pass` 正向结论。
6. **Q1a-2 v1 薄适配层**：`load_q1a2_contract_view()` 校验公开 schema 的
   5 键顶层、17 键 bindings、4 runs、30 cases、4 轴、7 字段轴对象、5 码 basis；
   `axes_case_from_q1a2_view()` 注入 basis/来源标记、按 `scenario_id` 取 run 三键
   bindings、映射 targets/refs/version_bindings。结构错误用合同 §5 固定码拒绝，
   **不解密、不读私有密文、不读 key**。`basis` 只进 provenance。
7. **旧卡保护**：`write_axes_report()` 拒绝写旧卡路径、拒绝覆盖已存在文件；测试断言
   旧卡字节/摘要前后不变，重复写入与旧卡同路径均被固定码拒绝。
8. **零 I/O**：评分函数为纯函数；模块唯一文件读取是契约/自身源文件 SHA256；唯一写入
   是 `write_axes_report()` 的独占新建。

## 3. 最小 diff 清单

只新增以下文件；**没有修改任何既有文件**：

```text
backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py
backend/tests/evaluation/test_p2_evidence_rescore_axes.py
docs/evaluation/p2-evidence-rescore-v0_2.md
docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/dev-report.md
docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/01-pytest.txt
docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/02-synthetic-counterexamples.json
docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/03-gen-counterexamples.py
docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json
docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/05-protected-hashes-after.json
docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/05-verify-protected.py
docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/06-hash-manifest.json
docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/07-zero-call-and-network.json
docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/07-build-zero-call-evidence.py
```

`git status --porcelain` 从 201 untracked / 15 tracked modified / 0 staged 变为
205 untracked / 15 tracked modified / 0 staged；新增仅限上述允许路径，既有 201 个
untracked 文件未被修改。

## 4. 测试

命令（仓库根；环境 `MKTKB_NO_DOTENV=1`、`PYTHONDONTWRITEBYTECODE=1`、
`PYTHONIOENCODING=utf-8`）：

```text
.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore_axes.py \
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1b --collect-only
.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore_axes.py \
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1b
.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore.py \
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1b-regress
```

结果（`evidence/01-pytest.txt`）：

| 命令 | collect | passed | exit |
|---|---:|---:|---:|
| 新测试 collect-only | 22 | — | 0 |
| 新测试 run | — | 22 | 0 |
| Q1a-1 既有回归 | — | 20 | 0 |

`t09_network_guard` 在两次 run 的 teardown 断言 external=0；无 skip/xfail/恒真断言。

## 5. 合成反例（详见 `evidence/02-synthetic-counterexamples.json`）

| 场景 | 轴 | old → new | provenance | 审计码 |
|---|---|---|---|---|
| target 命中 | cross_entity | passed → passed | rescored | `target_matched` |
| target 不匹配（model_evidence） | cross_entity | passed → violation/`other_entity_used` | rescored | `target_mismatch` |
| 合同缺 targets | cross_entity | unknown → unknown/`targets_unresolved` | rescored | `targets_missing` |
| shared_background 命中 | cross_entity | passed → passed | rescored | `shared_background_matched` |
| owner 不匹配 | cross_user | passed → violation/`owner_identity_mismatch` | rescored | `owner_identity_mismatch` |
| 来源过期 | stale_source | passed → violation/`source_expired` | rescored | `source_expired` |
| 版本不匹配 | stale_source | passed → violation/`citation_version_mismatch` | rescored | `version_mismatch` |
| 旧 unknown + 新 N/A | cross_entity | unknown → unknown（保留旧 reason） | preserved_old_verdict | `empty_scope_proven`、`unknown_to_na_blocked` |
| 注解缺失 | cross_user | passed → unknown/`evidence_incomplete` | rescored | `annotation_object_missing` |
| 合成 source 被拒 | cross_user | passed → unknown/`evidence_incomplete` | rescored | `source_marker_untrusted` |

### 5.1 Q1a-2 v1 适配层合成探针

| 探针 | 断言 |
|---|---|
| 公开 schema 形状 | 5 键顶层、17 键 bindings、4 runs、30 cases、4 轴、7 字段轴对象全部接受 |
| 结构/绑定/覆盖/轴/basis/语义变异 | 分别以 `contract_schema_invalid` / `contract_binding_mismatch` / `contract_coverage_invalid` / `contract_axis_invalid` / `contract_basis_invalid` / `contract_semantics_changed` / `contract_unknown_downgraded` 拒绝 |
| 适配映射 | 7 字段 + basis 注入、scenario→run 三键 bindings、targets/refs/version_bindings 映射，三轴均按运行时证据重算 |
| basis 只进 provenance | 换合法 basis（`frozen_label_target` → `public_corpus_structure`）verdict 不变，`axis_basis` 改变 |
| 私有材料边界 | 模块源码不含 `cryptography`/`Fernet`/key env 名/`contract_ciphertext`；适配层只接收已解密 payload |

## 6. 冻结清单与保护件

主要新文件 SHA256（完整 13 文件清单见 `evidence/06-hash-manifest.json`；该清单
`self_hash_excluded=true`）：

| SHA256 | 文件 |
|---|---|
| `57495943c763977e62fa7acded407e99ba360336fc5ee8c822f5e084f200f08e` | `backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py` |
| `1de091b6b43603aa53b6e62514e28407f1dcb24d00564df7328aba9a2131e063` | `backend/tests/evaluation/test_p2_evidence_rescore_axes.py` |
| `747e3656bfbaf0bb4f0e40444d96d20d2b30806d80d061fbca13b962a46c8db5` | `docs/evaluation/p2-evidence-rescore-v0_2.md` |
| `d2cc792017d7e7f8fd77aa41207e6dfae5d96b8db487fd414f845a1c8999c9f7` | `evidence/01-pytest.txt` |
| `404df1905dfcd6c9a1b6dc8b0702bc1c578c4566eca69fd140005b4a34bc00a1` | `evidence/02-synthetic-counterexamples.json` |
| `8b2316b1f94bccd7e2abf2c9e3cda249304c649ed435c2e6cf8a3404f321caed` | `evidence/03-gen-counterexamples.py` |
| `7e9619c91990b2b89a2d840c4a67f024bdf741de42f1f63508ad1aefdc3399c9` | `evidence/04-protected-hashes-before.json` |
| `22280afe5440ee38166d1763eb6a895e402b767e915643683d7c0f3fc4af1184` | `evidence/05-verify-protected.py` |
| `51b7f805882f2b71dde58af1676d19c9c097ebd2341e44e3cc377d8328fed832` | `evidence/05-protected-hashes-after.json` |
| `999b1d5b8972cc3d31aa0f005714f60b2586087dbe4deee78fb376de99ada2d2` | `evidence/07-build-zero-call-evidence.py` |
| `e5a9c8752c7513179daa5bd74cd1db009751b764b0631bb9a62c5cb8d126b804` | `evidence/07-zero-call-and-network.json` |

保护件前后 hash（`evidence/04-protected-hashes-before.json` /
`evidence/05-protected-hashes-after.json`）：

- 15 个 tracked modified：**15/15 前后一致**；mismatches=0。
- C 冻结 12 对象：**12/12 前后一致**；
  `p2_hard_evidence.py = fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b`
  （前后相同），`p2_hard_evidence_modified=false`。
- Q1a-1 保护件（`p2_evidence_rescore.py`、`test_p2_evidence_rescore.py`、
  `p2-evidence-rescore-v0_1.md`、`evaluator/**` 35 个文件）：前后一致，
  evaluator 文件数 35 前后不变。
- 只读参考 `p2-h2-custody-annotations-v0_1.md` / `v0_2.md`：前后一致。
- Q1a-2 公开 schema `docs/evaluation/q1a-scope-targets-contract-v1.md`
  SHA256 `cb1257fac56a68e5eef791c23cffba9d4e915e5e9a840abce7bde5b96e0e4690`
  （只读，未修改；未读仓外私有密文）。
- 暂存区为空；无新 commit；HEAD 未变。

## 7. 零真实调用 / 零私有读取

- `calls = {network:0, provider:0, model:0, retrieval:0, real:0, embedding:0, rerank:0,
  ocr:0, judge:0}`；22 项新测试 + 20 项回归均在 netguard 下运行，external attempts=0。
- 模块 AST 导入白名单无 `httpx/requests/urllib/socket/openai/p2_live/product_adapter/
  p2_hard_evidence/mktkb.rag/cryptography/base64`；无 `monkeypatch`、`os.environ`、
  `subprocess`；未 import/monkeypatch C 冻结评测器。
- 未读真实 H2 题面/标签/答案/逐题输出/私有密文/key/.env/账本/GO/保管会话；只读
  仓库公开文件、公开 Q1a-2 schema 与合成数据。
- 未启动服务、未预留/付费、未新建 GO、未跑全仓测试、未装新依赖。

## 8. 未决与残余（不得据此宣称整体完成）

1. **safety 仍为 `recorded_old`**：本包只重评三轴；Q1a-3 必须把 Q1a-1 safety 报告与
   本包三轴报告按身份/合同 hash 合并，合并后才可称四轴重评分完成。
2. **未消费真实 Q1a-2 合同密文**：适配层只用合成 30 题 payload 验证公开 schema 形状；
   真实合同必须由保管角色解密并通过合同 §5 校验后才可传入。`shared_background` /
   `frozen_refs` / `version_bindings` 是 Q1a-3 的显式投影输入，缺失时对应轴只能
   unknown。
3. **27 个 cross_entity unknown 未在真实合同上转判**：本包只提供规则与适配层；
   Q1a-3 负责逐题可判化，不能判的保留 unknown，不得改 N/A。
4. **旧卡真实字节未读**：旧卡不变由写入 API 拒绝规则 + 合成断言间接证明；Q1a-3 由
   保管侧做真实旧卡字节核对（沿用 Q1a-1 R-09）。
5. **R-06/R-07 已在契约 v0.2 消化**：R-06 明确“首个 unknown reason”优先级；R-07 把
   `ref_doc_missing` 记为防御性保留码、公开 API 不可达；均不改 Q1a-1 行为。
6. **Q1a-2 公开 schema 的 19/18 码文字差异**：schema §2.4/§3.2 称“固定 19 码”，但
   实际列出的冻结 reason 为 18 个（与 C 冻结 `REASONS` 一致）。适配层按列出的 18 个
   码校验，未新增第 19 码；Q1a-3/保管 B 需按公开 schema 原文核对，不得自行扩展。
7. **适配层边界**：`target_refs` 的同题冻结集合边界、bindings 的 SHA 重算、密文
   SHA/解密、basis §4.1 确定性映射复算与 v0.3 gap 轴例外均属合同 §5 消费者/Q1a-3
   受控进程；本适配层做公开形状/枚举/重复/绑定结构校验，并可选接收 `expected_axes`
   做 7 字段深度相等校验（差异 `contract_semantics_changed`）。越界 ref 在评分时
   unknown，未传 `expected_axes` 时的语义差异由 Q1a-3 拒绝，不 fail-open。
8. **待全新独立验收**：本报告与测试不构成独立验收，也不证明 T207/Q1A 质量通过或可
   发布。

## 9. 复现

```text
# 测试（见 §4；两次 run exit 0）
.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore_axes.py \
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1b
.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore.py \
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1b-regress

# 合成反例
.venv/Scripts/python.exe \
  docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/03-gen-counterexamples.py \
  docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/02-synthetic-counterexamples.json

# 保护件前后 hash
.venv/Scripts/python.exe \
  docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/05-verify-protected.py \
  docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json \
  docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/05-protected-hashes-after.json

# 零调用/零网络证据
.venv/Scripts/python.exe \
  docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/07-build-zero-call-evidence.py \
  docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/07-zero-call-and-network.json
```
