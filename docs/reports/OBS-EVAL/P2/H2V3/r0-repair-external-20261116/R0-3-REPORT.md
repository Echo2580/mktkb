# R0-3 报告：拒答跨层兼容 v0.3 版本开关

日期：2026-11-16（Asia/Shanghai）。任务：R0-3（`REFUSAL-COMPATIBILITY-PROPOSAL.md` §5 冻结兼容增量）。
授权：主人 2026-11-16 明确批准；实现严格等于提案范围，未扩大。

## 1. 结论

- 已按提案 §5 在 `p2_hard_evidence.py` 加入**版本开关**的两条兼容修订：默认 `p2-refusal-compat/v0.1` 行为逐字不变；只有调用方**显式**传 `p2-refusal-compat/v0.3` 才放行「`no_answer→not_found` 跨层映射」与「`SECURITY_RESTRICTED_CONTACT` 模板键」。
- 新契约文档 `docs/evaluation/p2-refusal-compat-v0_3.md` 已新增；冻结的 `p2-evidence-rescore-v0_1.md` 未动。
- 新增 `backend/tests/evaluation/test_r0_repair_refusal_compat.py`：62 项断言全绿，覆盖提案 §7 全部反例。
- 冻结行为未破坏：`test_p2_hard_evidence.py` **整文件 312 passed**（另跑定向子集 113 passed 交叉确认）；`test_p2_evidence_rescore.py` 20 passed。
- **一个预期内的外部影响**：`test_p2_empty_scope_proof.py` 把 `p2_hard_evidence.py` 的字节 hash 钉成 `FROZEN_SHA`，文件一改该 pin 必失败（2 项：`test_frozen_module_sha_is_expected`、`test_differential_against_frozen_primitive` 的 gate）。该文件不在本任务授权改动范围，**未改**；需由其所有者重新 pin（见 §6）。

## 2. 改动清单

只改 3 个文件（其余零改动）：

| 文件 | 性质 | 净增行数 |
|---|---|---|
| `backend/src/mktkb/evaluation/p2_hard_evidence.py` | 修改 | **+49**（3855 → 3904 行） |
| `docs/evaluation/p2-refusal-compat-v0_3.md` | 新增 | 新文件 |
| `backend/tests/evaluation/test_r0_repair_refusal_compat.py` | 新增 | 810 行 |

`p2_hard_evidence.py` 改动点（全部为追加/等价替换）：

1. `NO_FACT_TEMPLATE_KEYS` 之后新增 `REFUSAL_COMPAT_V0_1`、`REFUSAL_COMPAT_V0_3`、`REFUSAL_KIND_CROSS_LAYER_MAP`、`REFUSAL_TEMPLATE_KEYS_EXTRA`（+17 行，含注释）。
2. `_matches_product_no_fact_template(kind, text, *, compat=…)`：模板键 = 原族 + 登记额外键；匹配方式仍是 `_template_pattern(...).fullmatch(...)`。
3. `_empty_use_scope_proof(evidence, *, compat=…)`：签名 + docstring 语义说明；section G 增 `kind_ok`（字面相等 **或** 已登记映射 + 两侧 kind ∈ `NO_FACT_KINDS`，文本仍须逐字相等）；section H 透传 `compat`。
4. 线程透传（keyword-only `compat`，默认 v0.1）：`classify_case_evidence` → `_classify_turn` → `_check_stale_source`（call site `:1732`）/ `_check_cross_entity`（call site `:2044`，并透传给 `_check_cross_entity_v02`，call site `:2140`）。
5. **未改**：`_check_safety`（无 `compat` 参数，测试固化）、`NO_FACT_TEMPLATE_KEYS` 本体、`NO_FACT_KINDS`、`MATCHER_VERSION`、任何阈值/词表/评分口径、`recompute_hard_evidence`/CLI 默认。

## 3. 受保护件哈希（实测）

| 对象 | 改前 | 改后 |
|---|---|---|
| `p2_hard_evidence.py` | `fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b` | `84f53a517e4c2e5eeb50cd4319462ef7d966f2d946083794c406cd2605bd485b` |
| `p2_evidence_rescore.py` | `d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9` | 同前（未变） |
| `docs/evaluation/p2-evidence-rescore-v0_1.md` | `e0487f256524558ae12b00e6a9d961a7360e92f1437ab4d7d0c55702f375588d` | 同前（未变） |

## 4. 红 → 绿证据（实测命令与统计）

环境：`$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`；`.\.venv\Scripts\python.exe -B -m pytest … -p no:cacheprovider`。

红（实现前，59 项版本）：

```
pytest backend/tests/evaluation/test_r0_repair_refusal_compat.py -q --basetemp backend\.pytest-tmp\r0-3
→ 58 failed, 1 passed, 1 warning in 0.99s
→ 代表红因：TypeError: _empty_use_scope_proof() got an unexpected keyword argument 'compat'
```

（唯一通过项是 `test_safety_check_does_not_gain_compat_parameter`：它断言 `_check_safety` **不**带 `compat`，实现前后都应成立。当前 62 项中的另外 3 项——模板注册表增量、36 组 kind 矩阵 ×2——在 green 阶段补强，红因与上述同源：缺 `REFUSAL_*` 常量/`compat` 关键字。）

绿（实现后）：

```
pytest backend/tests/evaluation/test_r0_repair_refusal_compat.py -q --basetemp backend\.pytest-tmp\r0-3
→ 62 passed, 1 warning in 0.43s

pytest backend/tests/evaluation/test_p2_hard_evidence.py -q --basetemp %TEMP%\mktkb-r03-full
→ 312 passed, 1 warning in 22.23s   # 仓外 basetemp；整文件全绿

pytest backend/tests/evaluation/test_p2_hard_evidence.py -q --basetemp %TEMP%\mktkb-r03-hardsubset \
  -k "empty_scope or no_fact_template or no_fact_kind or clarification_template or
  branch_evidence_gaps or no_model_events or true_template_full_empty or kept_unknown or
  branch_matrix or branch_x_model_purpose or duplicate_model_events or required_key_and_type_gaps or
  duplicate_answer_model_input or cross_entity or stale_source or safety or template or
  rag_direct or legacy_branch"
→ 113 passed, 199 deselected, 1 warning in 0.65s

pytest backend/tests/evaluation/test_p2_evidence_rescore.py -q --basetemp %TEMP%\mktkb-r03-rescore
→ 20 passed, 1 warning in 0.13s
```

关键绿点（对应提案 §7）：

- 同一份 C26 形状 envelope：默认/显式 v0.1 → `(False, "branch_evidence_inconsistent")`；显式 v0.3 → `(True, "empty_use_scope_ok")`；`cross_entity`/`stale_source` 由 `unknown/branch_evidence_inconsistent` 变为 passed。
- 6×6=36 组 kind 组合 × 2 个 compat，对逐个组合按"独立推导的冻结规则"断言（不调用被测函数）：v0.1 严格等于字面相等；v0.3 只在 `no_answer→not_found` 上多放行。
- 模板注册表逐 `COPY` 键枚举：v0.3 相对 v0.1 的增量**恰好** `{SECURITY_RESTRICTED_CONTACT}`，且只在 `not_found`/`no_answer` 两族；`clarification`/`knowledge_changed` 无增量、无减量。

## 5. 旧版不变的自证

1. **代数退化（结构性）**：`compat == V0_1` 时两张登记表都取到 `{}` → `mapped_kind is None`、模板键元组等于原 `NO_FACT_TEMPLATE_KEYS.get(kind, ())`，两个新表达式与原表达式**逐字等价**；没有删除/重排任何既有分支。
2. **同值断言**：`test_default_compat_is_value_identical_to_explicit_v0_1` 对 25 份合成 envelope 断言「默认 == 显式 v0.1」——`_empty_use_scope_proof` 返回值与 `classify_case_evidence().as_dict()` 全等。
3. **唯一翻转点**：`test_v0_3_only_flips_the_registered_pair` 断言在 25 份 envelope 中 v0.3 相对 v0.1 的翻转集合恰为 `{"c26_security"}`，其余 24 份 proof 与分类输出全等。
4. **冻结件差分（无 hash gate 手工复跑）**：`test_p2_empty_scope_proof.py` 的 72 例语料上，`prove_empty_use_scope` vs 冻结 `_empty_use_scope_proof` 的分歧画像 = 60 equal / 1 extension / 11 stricter，且默认、显式 v0.1、显式 v0.3 三者对该语料**零翻转**（该语料不含"已登记映射 + 安全模板"组合）。
5. **冻结测试**：`test_p2_hard_evidence.py` 整文件 312 项、`test_p2_evidence_rescore.py` 20 项全绿。

## 6. 未验证项 / 需他人处理

1. **需重 pin（不在本任务授权范围）**：`backend/tests/evaluation/test_p2_empty_scope_proof.py:54` 的 `FROZEN_SHA` 仍钉改前字节 → 该文件 2 项失败（`2 failed, 123 passed`）。这是**预期**的防篡改 pin，不是行为回归；其差分语义已用 §5.4 手工复跑证明未变。是否改 pin 由该文件所有者决定。
2. **未做真实评分**：未跑真实请求、未在真实重评分上启用 v0_3、未改 CLI/`recompute_hard_evidence` 默认；因此"C26 真实回合是否首先命中该行"仍未经真实证据确认（提案 §1 已要求由 R0-2 受控 SAFE 投影归因）。
3. **未跑全仓测试**：仅定向子集 + 相邻两个文件（`test_p2_empty_scope_proof.py`、`test_p2_cross_entity_scope_v02.py`）+ rescore。
4. **未做 lint/格式化**：环境无 `ruff`，且禁止安装依赖；改动按既有风格手写。
5. **未验证历史探针脚本**：`docs/reports/**` 下的旧 probe 以默认 `compat` 调用，按 §5.1 行为不变，但未逐个复跑（`docs/reports/**/bi_contract_loader.py` 曾 `inspect.signature(classify_case_evidence)`，新增 keyword-only 默认参数不改变既有调用，但未实测）。
6. **未改**：`tools/p2_h2_v3_controlled_execute.py`、`rag/budget.py`、`p2_authorization.py`、`backend/tests/evaluation/test_p2_authorization.py`（另一助手并行改动，未触碰）；未 `git add/commit/stash/reset/checkout/clean`。
