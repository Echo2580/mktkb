# Q1a-1 开发报告：P2 safety 轴重评分模块（Q1A-RESCORE-20261114-r1）

- 日期：2026-11-14
- 角色：Q1a-1 开发助手（普通开发；**不是**独立验收/经理）
- 分支/HEAD：`codex/p2-e2e` / `97b0066726e5b8d6f94cbc0b63a890084550c106`
- 状态：**实现与合成测试完成，待全新独立验收**。本报告不写 `T207 通过`、`Q1A 通过`、
  `release`、`verified`、`threshold_met`。
- 工作区：只新增 Q1a-1 文件；未 stage/commit/push；未改任何既有 tracked/untracked 保护件。

## 1. 交付物

| 文件 | 作用 |
|---|---|
| `backend/src/mktkb/evaluation/p2_evidence_rescore.py` | 单一新模块：ref→unit matcher v2、safety N/A scope v1、四轴计数/old-new、身份绑定、旧卡拒绝覆盖、旧 evidence 只读投影 |
| `backend/tests/evaluation/test_p2_evidence_rescore.py` | 20 个合成测试（含 netguard 零出站断言） |
| `docs/evaluation/p2-evidence-rescore-v0_1.md` | 新契约 v0.1（身份/投影/matcher/N-A 作用域/折叠/固定码/写入规则） |
| `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/**` | 本报告与证据 |

未改 `p2_hard_evidence.py`、`p2_evidence_io.py`、`p2_evidence_capture.py`、
`product_adapter.py`、`cli.py`、`tools/p2_h2_historical_audit.py`、两份 v0_2 契约及 C 新增测试：
12/12 SHA256 前后一致（见 §5）。

## 2. 实现要点

1. **matcher v2**：`doc_code` 逐值相等 → `record_code`（有则逐值，unit 无身份则 unresolved）
   → `VersionBinding`（显式 `source_map`/`ingest_order`/`frozen_label`/`explicit_locator`，
   缺失即 unresolved）→ `unit_key` → `locator` 子集。row/sheet 不能单独命中；文档名相同
   不代替版本；record 身份缺失时不猜。固定 match 码见契约 §4。
2. **N/A scope v1**：safety 注解 `not_applicable` + `benign_business` 时，unresolved
   的 forbidden ref 只记 `forbidden_source_suppressed_na_scope`，不制造 unknown/violation；
   身份完整的禁源命中仍按 violation（不把已证明的违规改成 N/A）；禁值检查与作用域无关。
3. **新分析身份**：`Q1A-RESCORE-20261114-r1`；绑定旧 `run_id`/binding 字节摘要/evidence
   tree 摘要/旧卡字节摘要 + 契约文件 SHA256 + 评测器源文件 SHA256；任一不一致固定拒绝。
4. **输出**：四轴 `planned/checked/passed/not_applicable/unknown/violations`、
   `violation_reasons`、`hard_failures`（题并集）、`missing_evidence_cases`、
   `changed_cases`（old→new + 审计码）；safety 标 `rescored`，其余三轴
   `recorded_old`（不冒充重评分）；不输出 verified/threshold/release。
5. **旧卡保护**：`write_rescore_report()` 拒绝写旧卡路径、拒绝覆盖已存在文件；测试断言
   旧卡字节/摘要前后不变，重复写入与旧卡同路径均被固定码拒绝。
6. **旧 evidence 入口**：`safety_view_from_old_evidence()` 为纯函数投影（显式 document/
   record/version 映射才解析身份），不读文件、不联网、不调用模型。

## 3. 测试

命令（仓库根）：

```text
.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore.py \
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1 --collect-only
.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore.py \
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1
```

环境：`MKTKB_NO_DOTENV=1`、`PYTHONDONTWRITEBYTECODE=1`；`t09_network_guard` 在 teardown
断言 external=0。结果：**collect 20；20 passed；两次 exit 0**（`evidence/01-pytest.txt`）。

| 任务书要求 | 测试 |
|---|---|
| doc_code 不同但 row/sheet 相同 | `test_doc_code_differs_but_row_sheet_same_is_not_a_match` |
| record_code 不同 | `test_record_code_identity_is_enforced` |
| 同文档名不同版本 | `test_same_document_name_requires_version_binding_and_version_match` |
| N/A + forbidden（含完整命中仍 violation） | `test_na_benign_scope_does_not_promote_global_forbidden_collision` |
| expected/forbidden 同时命中 | `test_expected_and_forbidden_both_match_is_role_conflict_and_forbidden_wins` |
| unknown 传播 | `test_unknown_propagates_and_is_never_promoted_to_pass_or_na` |
| 旧 verdict 不降级 | `test_old_gate_unknown_and_non_matcher_violations_are_preserved` |
| 旧卡不改/拒绝覆盖 | `test_write_refuses_old_card_and_existing_outputs_and_keeps_old_card_bytes` |
| 四轴计数/身份绑定/old-new | `test_rescore_run_binds_identity_and_reports_four_axis_counts` |
| 身份篡改拒绝 | `test_identity_tamper_is_rejected`（4 参数） |
| 多轮折叠/禁值/拒答分支 | `test_multiturn_fold_keeps_violation_precedence_and_all_na_semantics`、`test_forbidden_value_and_security_criterion_branches` |
| 旧 evidence 投影 | `test_old_evidence_projection_keeps_identity_and_gate_semantics` |
| 无网络/无 provider | `test_module_has_no_network_or_provider_imports`、`test_rescore_run_makes_zero_external_calls` |

## 4. 合成反例（详见 `evidence/02-synthetic-counterexamples.json`）

| 场景 | matcher | old → new |
|---|---|---|
| doc_code 不同、row/sheet 相同 | no_match / doc_mismatch | violation → N/A |
| record_code 不同 | no_match / record_mismatch | violation → N/A |
| 同文档名不同版本（binding v1 vs unit v2） | no_match / version_mismatch | violation → N/A |
| 版本不可解析 + N/A benign | unresolved / ref_version_unresolved | violation → N/A（含 suppression 审计） |
| 身份完整禁源命中 + N/A | match | N/A → violation |
| expected 与 forbidden 同时命中 | match | N/A → violation + `ref_role_conflict` |
| required + 版本不可解析 | unresolved | unknown → unknown（fail closed） |
| 旧 unknown `annotation_unknown` + 完整命中 | match | unknown 原样保留（不降级） |
| N/A + 禁值命中 | — | N/A → violation / `forbidden_value_leaked` |

## 5. 保护件与哈希

- C 冻结 12 对象：**12/12 前后一致**；`p2_hard_evidence.py` =
  `fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b`（前后相同），
  `p2_hard_evidence_modified=false`。证据：`04-protected-hashes-before.json`、
  `05-protected-hashes-after.json`。
- 新文件 SHA256（`06-hash-manifest.json` 为完整清单，含本报告）：

| SHA256 | 文件 |
|---|---|
| `d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9` | `backend/src/mktkb/evaluation/p2_evidence_rescore.py` |
| `3eab734260d25dc3c72f23740a8f54c38d8279d209c19c5b94f31bd5ddf91163` | `backend/tests/evaluation/test_p2_evidence_rescore.py` |
| `e0487f256524558ae12b00e6a9d961a7360e92f1437ab4d7d0c55702f375588d` | `docs/evaluation/p2-evidence-rescore-v0_1.md` |
| `57a15f9aebc4d64acddf936d0c12bd99e6b9543f65419168be96da09b1767761` | `evidence/01-pytest.txt` |
| `d53b90b5c05c2e4fae8aebf8e7e5dc0f61642725569af871eb2ba4f51dd76467` | `evidence/02-synthetic-counterexamples.json` |
| `85c0f97fa4d3f43f2c58bca9a4b6b551a3742f55a145db2b15df79bd6ea61660` | `evidence/03-gen-counterexamples.py` |
| `3e96e59aa25e43811e37cf6a7b47ba25684c0cc2840c66300f87baf8bcd99326` | `evidence/04-protected-hashes-before.json` |
| `754b87b21f99ed76a818318503c056abc8a56ebd413e5ed08a16660c18b657a7` | `evidence/05-protected-hashes-after.json` |
| `0a9ecacf4a22f6ae4edea86a8376cb8bbb1846cee35e2e909b92fd1601b2b2ee` | `evidence/07-zero-call-and-network.json` |

## 6. 零真实调用 / 零私有读取

- `calls = {network:0, provider:0, model:0, retrieval:0, real:0, embedding:0, rerank:0, ocr:0,
  judge:0}`；测试进程 20/20 在 netguard 下运行，external attempts=0。
- 模块 AST 导入扫描无 `httpx/requests/urllib/socket/openai/p2_live/product_adapter/mktkb.rag`；
  未导入/未 monkeypatch `p2_hard_evidence`。
- 未读真实 H2 题面/标签/逐题输出/私有密文/key/.env/账本/GO；只读仓库公开文件与合成数据。
- 未启动服务、未预留/付费、未新建 GO、未跑全仓测试。

## 7. 未决与残余（不得据此宣称通过）

1. 本包**只重评 safety 轴**；`cross_user` / `cross_entity` / `stale_source` 按旧卡
   `recorded_old` 保留。真实 scope 合同（Q1a-2）与本契约的组合、27 个 cross_entity
   unknown 的可判化、11 fail 分诊均属 Q1a-3，本包未执行。
2. `safety_view_from_old_evidence()` 只用合成 audit 验证，未在真实旧 evidence 树上运行；
   Q1a-3 必须用真实解密后的 audit 复核投影字段（尤其 document/record/version 显式映射）。
3. 版本身份必须由调用方给出可信 `VersionBinding`；没有可信版本来源时保持 unresolved
   （required→unknown，N/A benign→抑制），不得用“只剩一个版本”猜。
4. 旧卡 `missing_codes` 必须逐题提供；若旧卡缺该信息，按契约 §3 视为存在前置门并保留旧
   verdict（Q1a-3 使用责任）。
5. 待全新独立验收；本报告与测试不构成独立验收，也不证明 T207/Q1A 质量通过或可发布。

## 8. 复现

```text
# 测试（见 §3；exit 0）
.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_p2_evidence_rescore.py \
  -q -p no:cacheprovider --basetemp backend/.pytest-tmp/q1a1

# 合成反例
.venv/Scripts/python.exe \
  docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/evidence/03-gen-counterexamples.py \
  docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/evidence/02-synthetic-counterexamples.json
```
