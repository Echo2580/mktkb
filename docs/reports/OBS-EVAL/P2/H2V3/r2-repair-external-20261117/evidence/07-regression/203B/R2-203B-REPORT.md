# R2-203B 离线组合回归（T-R2-203B）

- 执行者：r2-203b-regression（子代理）· 日期 2026-11-17 · 仓库 `D:\GPT项目\市场部AI知识库`
- 工作树基线：`HEAD=97b0066` + 未提交改动（202C 三文件 sha256 见下），**本次未改动任何仓库内被跟踪文件**
- Python：`.venv\Scripts\python.exe -X utf8`，cwd=`backend/`
- basetemp 一律仓库外：`D:\mktkb-p2-h2v3-r2-20261117\basetemp-203b\...`
- 统一环境：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`（与 202B/202C 同）、`-p no:cacheprovider --no-header`
- 产物：本报告 + `logs/*.log`（每节点原始输出，含 `[r2baseline] VERIFIED` 行）

工作树中 202C 三文件（运行前后各核一次，**完全未变**）：

| 文件 | sha256（运行前 = 运行后） |
|---|---|
| `backend/src/mktkb/rag/retrieval.py` | `aee14c827578fa7918ac8c2cc06672bff9959077aee7e931d5f2a59611765f4e` |
| `backend/src/mktkb/rag/answer.py` | `b89622beb20f0d73849f2af9dab91a54835a24006059b3ff38a8d67b40e20288` |
| `backend/src/mktkb/rag/facts.py` | `cf795cfd16fe15fdfa73f9bc12311cf9bcf55b2fafdb67a9a8f6719192dc7001` |

---

## §1 节点总表

命令模板（每个节点一次 pytest 调用）：

```text
..\.venv\Scripts\python.exe -X utf8 -m pytest <文件...> -q -p no:cacheprovider --no-header --basetemp=<仓库外>
```

| # | 节点 / 必测面 | 文件 | 退出码 | passed | failed | error | 是否本批引入 |
|---|---|---|---|---|---|---|---|
| N01 | 本包 C29 同形红绿 | `integration/test_r2_202a_c29_mechanism_synthetic.py` | 0 | 13 | 0 | 0 | 否（全绿） |
| N02 | 本包 C29 联结 + 反例 | `integration/test_r2_202c_c29_join_rag.py` | 0 | 13 | 0 | 0 | 否（全绿） |
| N03 | 本包 C25/C29 身份 | `evaluation/test_r2_202b_entity_identity_e2e.py` | 0 | 7 | 0 | 0 | 否（全绿） |
| N04 | 判定链 同轮输入 | `evaluation/test_r0_repair_same_round_inputs.py` | 0 | 48 | 0 | 0 | 否 |
| N05 | 判定链 rescore | `evaluation/test_p2_evidence_rescore.py` | 0 | 20 | 0 | 0 | 否 |
| N06 | 判定链 rescore axes | `evaluation/test_p2_evidence_rescore_axes.py` | 0 | 22 | 0 | 0 | 否 |
| N07 | 判定链 matcher 相关 | grep 结果 = N04/N05/N06 三文件（无独立 matcher 用例文件） | — | — | — | — | 已并入 N04–N06 |
| N08 | v0.6 兼容 | `evaluation/test_r1_108_compat_v06.py` | 0 | 26 | 0 | 0 | 否 |
| N09 | v0.6←v0.5←v0.4←v0.3 继承 | `test_r0_repair_refusal_compat.py` + `test_r0_repair_c16_empty_scope.py` + `test_r0_repair_v05_projection_mirror.py` + `test_p2_empty_scope_proof.py` | 0 | 215 | 0 | 0 | 否 |
| N10a | 结构数字 102a | `evaluation/test_r1_102a_structural_numbers.py` | 0 | 9 | 0 | 0 | 否 |
| N10b | 结构数字 102d 分页 | `evaluation/test_r1_102d_turn_pagination.py` | 0 | 8 | 0 | 0 | 否（见 §5-3） |
| N11 | C12 跨表/contact（6 文件） | `integration/test_r0_c12b_t7_boundary_e2e.py`、`integration/test_r0_c12_text_face_recall_synthetic.py`、`rag/test_r0_c12b_boundary_synthetic.py`、`rag/test_r0_c12_join_synthetic.py`、`rag/test_r0_c12_legacy_trim_identifiability_synthetic.py`、`rag/test_r0_c12_text_face_recall_synthetic.py` | 0 | 40 | 0 | 0 | 否 |
| N12 | 多门店主目标 + legacy 范围 | `rag/test_r1_106b_primary_store_target.py`、`rag/test_r1_106a_legacy_store_scope.py` | 0 | 12 | 0 | 0 | 否 |
| N13 | 凭据拒答 | `rag/test_r1_102c_restricted_multifield.py` | 0 | 7 | 0 | 0 | 否 |
| N14 | 唯一门店追问 | `rag/test_r1_102b_cross_turn_store_scope.py` | 0 | 6 | 0 | 0 | 否 |
| N15 | 政策问答与拒答/安全面 | `evaluation/test_p1_refusal_controls.py`、`integration/test_p1_refusal_scope_http.py`、`integration/test_r1_103_http_scope_and_refusal.py`、`integration/test_v3_safety_fix_e2e.py`、`unit/test_v3_safety_fix_policy.py`、`rag/test_t207_security_precedence_synthetic.py`、`unit/test_t207_v8_safety_contract_synthetic.py` | 0 | 64 | 0 | 0 | 否 |
| N16 | 日期过滤 | `rag/test_v3_fix1_business_date_filter.py` | 0 | 6 | 0 | 0 | 否 |
| N17 | 版本/日期陈旧 | `evaluation/test_p2_stale_version_state.py` | 0 | 49 | 0 | 0 | 否 |
| N18 | 实体（5 文件） | `unit/test_entity_key_parity.py`、`unit/test_retrieval.py`、`rag/test_chunking.py`、`unit/test_conversations.py`、`rag/test_query_state.py` | 0 | 77 | 0 | 0 | 否 |
| N19 | 捕获/评分（4 文件） | `evaluation/test_p2_capture_entity_readiness_e2e.py`(4)、`test_p2_cross_entity_scope_v02.py`(37)、`test_p2_evidence_axes_adapter_v2.py`(49)、`test_p2_eval_tool_repair.py`(22) | 0 | 112 | 0 | 0 | 否 |
| N20 | 追加：R1 HTTP 结构数字/泄漏面 | `integration/test_r1_103_http_structural_numbers.py`、`integration/test_r1_107_http_c13_c22.py`、`integration/test_r1_107_http_c22_leak_shape.py` | 0 | 8 | 0 | 0 | 否 |
| K1 | 已知失败① s4 预算 | `rag/test_s4_stage_limit.py` | 1 | 7 | 1 | 0 | 否（见 §2） |
| K2 | 已知失败② s2h 预算下限 | `unit/test_s2h_r3_official_profile.py` | 1 | 13 | 1 | 0 | 否（见 §2） |
| K3 | 已知失败③ s2b intent | `integration/test_s2b_intent_semantics.py` | 1 | 7 | 1 | 0 | **否（202C 排除），但非 HEAD 既有**（见 §2） |

**合计：passed 789 / failed 3 / error 0（N01–N20 = 762 passed；K1–K3 = 27 passed + 3 failed）。**
N20 为任务书 §7「可复用 103/107 HTTP」的追加面，不计入必跑清单的等价性判断。

---

## §2 既有失败甄别

### 2.1 对照方法（两套，均在仓库外）

**方法 A：HEAD 源码对照（任务书要求）**

```powershell
git archive HEAD backend -o D:\mktkb-p2-h2v3-r2-20261117\baseline\head-backend.tar   # exit 0
tar -xf ... -C D:\mktkb-p2-h2v3-r2-20261117\baseline\head2                            # exit 0
# 插件：sys.path.insert(0, <head2>\backend\src)，并在 pytest_configure 断言实际导入路径
$env:PYTHONPATH="D:\mktkb-p2-h2v3-r2-20261117\baseline\plugin"
$env:R2_BASELINE_SRC="D:\mktkb-p2-h2v3-r2-20261117\baseline\head2\backend\src"
pytest ... -p r2baseline
```

- 每次基线运行的日志首行都有实测导入路径，例如
  `[r2baseline] VERIFIED mktkb.__file__=D:\...\baseline\head2\backend\src\mktkb\__init__.py`
  `other_mktkb_path_entries_removed=2`（editable `.pth` 是**追加**形态，`sys.path[0]` 生效已实测，不是"以为生效"）。
- **未**使用 `-o pythonpath`（按要求）。
- 必需修正：只导出 `backend/src` 会在导入后报 alembic `Path doesn't exist: ...\baseline\head\backend\migrations`（`mktkb/db.py:13` `BACKEND_ROOT=parents[2]`），因此基线必须导出整个 `backend/`。
- **重大限制（影响"HEAD 证明既有"的口径）**：`backend/src` 下有 **19 个未跟踪模块**（`entity_identity.py`、`evaluation/p2_evidence_rescore*.py`、`p2_hard_evidence.py`、`observability/evaluation_capture.py` 等），HEAD 里没有。因此判定链/202B/捕获评分等节点**无法**在 HEAD 基线上运行（`conftest.py` 直接 `ModuleNotFoundError`，实测 `MIX1` 即此类）。HEAD 对照仅对 K1–K3 有效。

**方法 B：pre-202C 沙箱（本批精确对照）**

```powershell
robocopy backend\{src,migrations} D:\...\baseline\pre202c\backend\...   # 副本，不动仓库
copy alembic.ini + pyproject.toml
cd D:\...\baseline\pre202c
git apply -R --check <evidence/05-fix/R2-202C-MINE-rollback.patch.txt>   # exit 0
git apply -R        <...same...>                                         # exit 0
```

- 回滚后三文件 **LF 归一化 sha256** 与 202C 报告记载的 pre-202C 值逐个相等：
  `retrieval.py=3ee0511b…eebab71`、`answer.py=b4a3ad88…f91ac99`、`facts.py=42cdfeb2…32f49`（3/3 MATCH）。
  原始字节差异 = `git apply` 对改写行写 LF（`\r\n` 行数 757→679 / 1415→1372 / 590→564），逻辑内容完全一致。
- 未使用 `git checkout/restore/stash`；工作树三文件 sha256 前后一致（见文首）。

### 2.2 三条已知失败：改前 / 改后

| 失败 | 失败用例 | 改后（当前工作树，202C 在） | 改前（pre-202C 沙箱） | HEAD 源码 | 结论 |
|---|---|---|---|---|---|
| ① s4 预算 | `test_current_go_and_budget_are_consistent_and_above_three_yuan` | 7p/**1f**，`assert 40 == 20.0 ± 2.0e-05`（`tests/rag/test_s4_stage_limit.py:208`） | 同值（P2：s4 部分 7p/1f，同一断言） | **同值** 7p/1f，`40 == 20.0` | 仍同值；**HEAD 已红 → 既有，非本批** |
| ② s2h 预算下限 | `test_official_profile_accepted_by_both_entries_and_worst_case_is_210` | 13p/**1f**，`ValueError: 共享预算总上限必须等于当前项目上限 20.0 元（当前 40.0）`（`src/mktkb/qa/service.py:820`） | 同值 13p/1f，同一消息 | **同值** 13p/1f，同一消息 | 仍同值；**HEAD 已红 → 既有，非本批** |
| ③ s2b intent | `test_ambiguous_identifier_candidates_converge` | 7p/**1f**，`assert 'conflict' == 'clarification'`（`tests/integration/test_s2b_intent_semantics.py:196`） | **同值** 7p/1f，同一用例同一断言 | **8p/0f（绿）** | 仍同值；**202C 已排除，但"HEAD 既有"不成立** |

### 2.3 s2b 的进一步归因（关键更正）

任务书 §7 末行警告"不能复述'3 条均被 HEAD 证明既有'的旧错误"。本次实测证实该警告：**s2b 在 HEAD 上 8/8 通过，只有工作树的未提交改动才使它转红**。是否为本批的判定链：

| 对照树 | 内容 | s2b 结果 | 读法 |
|---|---|---|---|
| HEAD（`head2`） | HEAD 全部 `backend/` | **8p / 0f** | 非 HEAD 既有 |
| pre-202C | 工作树 − 202C 9 hunk | 7p / **1f**（同用例） | **202C 不是原因** |
| mix2 | pre-202C + HEAD 的 `conversations/{intent,service}.py` | 7p / **1f** | conversations 批不是原因 |
| mix3 | pre-202C + HEAD 的 `qa/service.py` | 4p / **4f**（红面扩大：`multi_row_candidates…`、`item_switch…`、`bare_store_after…`） | 单文件回退破坏内部一致性，非原因 |
| mix4 | pre-202C + HEAD 的 `rag/query.py` | **ImportError**：`cannot import name 'metric_binding_identity' from 'mktkb.rag.query'` | 单文件回退不可行（工作树其它文件依赖新符号） |
| mix5 | pre-202C + HEAD 的 `retrieval/service.py` | 3p / **5f** | 同上 |

结论：s2b 的红是**未提交的工作树批次（非 202C）**的耦合行为，无法用单文件回退复现/定位；`rag/query.py`、`retrieval/service.py`、`conversations/*`、`qa/service.py` 任一回退都会改变红面或直接不可导入。**本批（202C）已排除**，但该条**不再是"既有失败"**，须由对应批次负责人定责（建议交 203C 或下一窗口先行判定 `conflict` vs `clarification` 的期望语义）。

---

## §3 轴裁决未变证据

1. **与 202B 报告同集合、同断言、同数字**
   202B 报告 §7 记录"既有节点 74 passed"。本次等价集合复跑：
   `test_entity_key_parity`(7) + `test_p2_capture_entity_readiness_e2e`(4) + `test_r1_108_compat_v06`(26) + `test_p2_cross_entity_scope_v02`(37) = **74**，全部绿（分见 N18/N19/N08/N19）。
   202B 的核心断言在本次运行中被重新执行且成立：
   - `hard_result.axis_state("cross_entity") == "passed"` 且 `reason == PASS_REASONS["cross_entity"]`（`tests/evaluation/test_r2_202b_entity_identity_e2e.py:555–568`，即 `frozen_targets_match_ok`）；
   - `new_axes["cross_entity"]["state"] == "passed"`（同文件 `:562–568`）；
   - 反例仍 fail-closed：`violation/other_entity_used`（`:694–695`）、`violation/citation_entity_mismatch`（`:708–711`）、`unknown/entity_identity_unresolved`（`:724–730, 747–768, 882–891`）。
2. **202C 自身反例面未被改写为"放行"**：N02 13/13 绿，含 C1/R3 只问位置、C2/R4 只问店家（legacy 1 次模型）、C3 物品+电话（`SECURITY_RESTRICTED_CONTACT`、0 调用）、C4 同名物品落两店不联结、C5 店家行过期不联结、C6 多目标枚举、C7 政策回合逐字不变。
3. **绿不是空断言（敏感性对照）**：pre-202C 沙箱下 N03 对应的 202A/202C 两文件 **13 failed / 13 passed**（P3，exit 1），说明这 26 例确实钉住本批行为；原工作树下 26/26 绿，差异只由 202C 9 hunk 决定。
4. **硬失败并集与 unknown 集合未被隐藏**：N04 内含
   `test_derive_hard_failed_unions_violation_axes`、`test_derive_hard_failed_unions_multiple_axes_once`、`test_derive_hard_failed_rejects_extra_or_missing_hard_case`、`test_check_consistency_rejects_hidden_unknown`、`test_quality_allows_legit_empty_hard_set`；
   N05/N06 内含 `test_unknown_propagates_and_is_never_promoted_to_pass_or_na`、`test_old_gate_unknown_and_non_matcher_violations_are_preserved`、`test_unknown_propagation_and_unknown_never_becomes_na`、`test_same_round_card_preserves_non_matcher_violation` —— 全部通过。
5. **R1 保护面双向对照**：N12/N13/N14/N10b 在改后与 pre-202C 都是全绿（P4 = 33 passed），说明 202C 没有改变任何 R1 裁决面。

**结论：本批未改变任何轴裁决；未新增硬失败，未吞并 unknown。**

---

## §4 NOT-RUN / NOT-FOUND

**NOT-FOUND（找过的地方已注明）**

| 项 | 查找范围 | 结论 |
|---|---|---|
| `tests/evaluation/test_p2_evidence_rescore_axes_v2.py` | `backend/tests/**` 全树 glob（`Get-ChildItem -Recurse`） | 不存在。v2 轴适配器的实际文件是 `test_p2_evidence_axes_adapter_v2.py`（存在，已跑 = N19） |
| 独立 matcher 用例文件 | `grep -l matcher backend/tests/**/*.py` | 只有 3 个文件（rescore / rescore_axes / same_round_inputs），无独立文件；已全部跑（N04–N06） |

**NOT-RUN（有意不跑 + 理由）**

1. 全仓 pytest、旧验收历史用例（`tests/acceptance/*`、`.pytest-tmp/T105/T109/T111` 快照）—— 按任务约束"默认不跑全仓"。
2. HEAD 基线下的判定链 / 202B / 捕获评分 / 日期版本 / 实体节点 —— HEAD 缺 19 个未跟踪模块，无法导入（实测 `ModuleNotFoundError`），**不是不想跑，是 HEAD 基线在该面上不成立**。这些节点的"改前"只能用 pre-202C 沙箱。
3. 202C/202A 的 HEAD 基线 —— 同上（`rag/answer.py` 工作树版依赖新符号；且 HEAD 版测试断言是红态口径，不具可比性）。
4. 真实 provider / 真实 H2 / 受控执行（T-R2-204、205 范围）。
5. `tests/integration/test_r2_203c_f1_http_join_witness.py`、`test_r2_203c_f3_multiturn_http.py`（存在）—— 属 203C 节点，不在本包必测面。
6. `tests/evaluation/test_p2_eval_tool_repair_e2e.py`（存在）—— 任务只点名 `test_p2_eval_tool_repair.py`（已跑），e2e 变体未点名，建议 203C 补跑。
7. `tests/unit/test_s2h_r2_conservative_profile.py`、其余 `test_p2_*` 未在必测面内的文件 —— 未跑。

**窗口内并发观察（不影响本报告数字）**：本包运行期间（18:33–18:38）203C 并行新增了
`backend/tests/integration/test_r2_203c_f1…f4_*.py` 四个文件。本包每个节点都按**文件名显式**调用，
未通过目录收集，因此这 4 个文件未被收集、不影响任何计数。本包自身**未新建任何测试文件**，
`backend/` 下亦无本包写入（`backend/src/mktkb` 18:20 后变更文件数 = 0）。

---

## §5 风险与建议

1. **s2b 归因缺口（最高优先）**：s2b 在 HEAD 绿、仅工作树红，且 202C 已排除。若 GO 材料继续把它写成"3 条既有失败之一"，就是任务书 §7 明确点名的旧错误复发。建议：由未提交 src 批次的负责人判定 `test_ambiguous_identifier_candidates_converge` 的期望（同一文件内两行不同位置值应 `clarification` 还是 `conflict`），再决定改产品还是改用例。
2. **HEAD 基线口径必须收窄**：任何"HEAD 已证明既有"的表述只对 K1/K2 成立（s2b 反例）。后续窗口做基线对照时，应以 "worktree − 目标 hunk"（本包的 `pre202c` 法）为准，而不是 `git archive HEAD`。
3. **202C 报告的风险 3（total/分页）已复核**：`test_r1_102d_turn_pagination.py` 8/8 绿，且在 pre-202C 下同样绿 → 未发现"共 N 条/显示 N 条"断言被联结行打断。
4. **出站/子进程守卫**：21 个节点全部零外呼（`t09_network_guard` 未报 `NetworkBlocked`，所有节点绿；K1–K3 的失败均为断言/预算值，无网络异常）。子进程守卫由 N19 的 `test_p2_capture_entity_readiness_e2e.py` 覆盖（4 例全绿）：该文件实测在临时目录写 `sitecustomize.py` 并用 `subprocess.run` 起子进程验证子进程内的离线守卫（`tests/evaluation/test_p2_capture_entity_readiness_e2e.py:434–476`），不是只测父进程；202A/202C 自带 `no_subprocess`（封 `subprocess.Popen/run` 且计数）亦在守卫下全绿。**未**逐个核新增 c12/202x HTTP 文件是否各有自己的走查守卫（不在本包必测面）。
5. **建议补用例（交 203C / 下一窗口，本包不新增测试文件）**：
   - s2b 分歧点的显式红/绿对（同一 doc 内多值 → clarification vs conflict）；
   - 202C 联结的多页场景（202C 报告 §9-5 自述未测）+ 同门店多行店家行的收敛口径；
   - `test_p2_eval_tool_repair_e2e.py` 纳入组合回归。
6. **仓库卫生（既有问题，非本次产生）**：仓库根存在 `%SystemDrive%/`（未展开变量目录）、`tmp_qc.txt`、`tmp_run_a.txt`、`tmp_run_b.txt` 等未跟踪残留，建议收口时清理，避免 diff/归档污染。
7. **本次未做的边界**：§7 的"HTTP 上传→解析→索引→发布→conversations 正式链路贯通"由 203C 承担（203B 为纯验证，未新增 HTTP 用例）；本报告所有数字均为离线合成环境。
