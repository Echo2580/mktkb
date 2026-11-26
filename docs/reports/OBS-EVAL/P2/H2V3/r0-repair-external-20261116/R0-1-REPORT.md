# R0-1 报告：跨轮初判输入与逐题报告错误修复（合成验证）

日期：2026-11-16（Asia/Shanghai）。角色：R0-1 开发助手（只读私有材料、未真实调用）。
任务单：`docs/superpowers/plans/2026-11-16-r0-external-ai-repair-taskbook.md` §三。

## 结论

- 三处已证实错误（D1 历史卡当本轮初判、D2 逐题质量字段取旧卡、D3 `hard_failed` 错层级）已在**适配/聚合层**修复；冻结评分器、契约、fixture、旧证据零改动。
- 新分析链的初判卡只来自本轮真实 run 路径：`tools/p2_h2_controlled_execute.py::_recompute_loaded → p2_hard_evidence.recompute_hard_evidence → classify_case_evidence`；历史 compose 结果只保留为 `historical_*` 对照，不进入本轮门状态。
- 新增 48 条合成测试（红→绿、五类跨轮拒绝、质量/硬失败/unknown 一致性、词表兼容、离线守卫），全部通过；既有冻结测试定向回归通过。
- **未执行受控同轮重算**（无私有输入权限）：真实 r0 重算、C26 本轮 safety、20/30 是否变化、v2 脚本在真实 run 上的可运行性均**未验证**；旧产物哈希未变。

## 已证实根因（本次复核）

- **D1**：`fullverify-20261116/work/recompute_axes_fullverify.py:69-71,786-791,867-872` 把历史 compose 卡当本轮初判；`:962-976` 又把历史卡字节/哈希与本轮 run_id/binding/evidence-tree 放进同一个 `RescoreIdentity`。哈希只证明字节未变，不证明来源轮次。冻结 `p2_evidence_rescore.py:823-855` 按合同保留非 matcher 旧 violation，于是旧 fail 无法反映本轮改动。
- **D2**：同文件 `:1035-1037` 输出 `old.quality_status / old.evidence_complete / old.missing_codes`，与本轮 case-plan 质量（8/12 vs 7/12）不一致。
- **D3**：`build_fullverify_artifacts.py:95-96` 读顶层 `axes.get("new_hard_failures", [])`；实际硬失败在 `aggregate.hard_failures`，导致 30 条逐题 `hard_failed` 全 false。
- **调用路径核对（修正任务单假设）**：真实 run 路径**没有**构造/传入 `scope_contract`：`tools/p2_h2_controlled_execute.py:3125-3127`、`p2_hard_evidence.py:3681,3688`，历史生产路径 `compose/evidence/recompute_four_runs.py:64-74` 同样只经 `_recompute_loaded`。因此 v2 **不**从 annotation 另造 scope contract（否则 cross_entity 判据漂移），并在捕获到非 None 时以 `current_round_scope_contract_unexpected` 停止。

## 改动文件（全部为新增；未改任何既有文件）

| 文件 | 行数 | SHA-256 |
|---|---|---|
| `work/r0_same_round.py` | 672 | `0df9316cde68b9b57c357dcfda99890867c2ede792e9b4840820b48f7fedecfa` |
| `work/recompute_axes_fullverify_v2.py` | 869 | `9ecb8f46e2fcff9190bf5107cda9b33c8c930622208e9a91f3b956caa128611f` |
| `work/build_fullverify_artifacts_v2.py` | 299 | `583a5f50c43dd026ed2e86c9da759e0d64bd7c14a26df6011834d07b08b1f80b` |
| `backend/tests/evaluation/test_r0_repair_same_round_inputs.py` | 959 | `2cf39ca3a333294bd0fb2a5b9a91ba4f560d8ab156211d3431162c36dbc79aeb` |
| `work/out/r0-1-test-evidence.txt` | 命令与输出留档 | — |

`r0_same_round.py` 只做纯函数：`build_current_card`（本轮结果→`OldCardCase`）、`card_origin_record`/`assert_same_round`（值+来源对象+轮次+sha，五类拒绝）、`derive_hard_failed`/`check_consistency`（逐题四轴→并集，双向核对）、`build_quality_payload`（D3 修复 + D2 交叉核）。导入期零文件 IO（有测试固化）。

## 红 / 绿证据（实际命令与末尾统计）

- 新合成套件：`pytest backend/tests/evaluation/test_r0_repair_same_round_inputs.py -q -p no:cacheprovider --basetemp backend\.pytest-tmp\r0-1` → **48 passed, exit 0**。
- 红→绿 1（D1）：`test_historical_card_passes_structural_identity_but_same_round_rejects` 先断言历史卡字节+本轮 identity 能被冻结 `RescoreIdentity` 结构接受（旧适配会放行），再断言 `assert_same_round` 以 `same_round_origin_not_current` 拒绝。
- 红→绿 2（D3）：`test_quality_hard_failed_derives_from_axes_not_missing_top_level_field` 先复现旧公式 `axes.get("new_hard_failures", [])` → 空集，再断言新派生 C02=true、计数=1。
- 五类拒绝：run_id / plan_id / plan_sha256 / evidence_tree / 缺失来源证明（字段 source、classifier sha、card sha）各有固定码断言；另含 case 缺失/重复/多余、card sha 篡改。
- 旧判隔离：旧 fail→本轮 pass、旧 error/缺证据→本轮不同状态；本轮 error→`unknown/turn_error`、本轮 evidence_complete=false→`unknown/evidence_incomplete`，均拒绝假通过。
- 同轮限定重评分：本轮卡的非 matcher violation（`security_refusal_missing`）仍按原合同保留（`preserved_old_verdict`），未被 matcher v2 洗白。
- 一致性：新增/重复/缺失 case、硬失败存在但 flag=false、缺 aggregate、run 质量不等、每轴计数不等、unknown 被隐去均抛固定码；合法空硬失败集合在逐题证据完整时允许。
- 既有回归：`test_p2_evidence_rescore.py` 全文件 **20 passed**；`test_old_gate_unknown_and_non_matcher_violations_are_preserved` **1 passed**；`test_p2_hard_evidence.py` 定向子集（safety/strict_empty/branch_evidence/branch_x/duplicate）**86 passed**。
- 离线守卫：autouse fixture 阻断 socket/`create_connection`/urllib/httpx 与私有路径读取，并有正对照自证；另有“导入期除模块源码外不打开文件”测试。
- 如实披露：把 `--basetemp` 放进仓内跑**整个** `test_p2_hard_evidence.py` 时出现 27 个 setup error（`scenario_private_path_inside_workspace`）与 2 个 failure（`evidence_root_inside_forbidden`），均为 basetemp 位置导致的环境拒绝；换仓外 basetemp 的定向子集 86 passed。未改任何断言或冻结源码来消除该现象。

## 新分析 schema 与来源说明

- `p2-h2v3-axes-v2-recompute/v0.2-r0-same-round`：逐题 `initial_axes`（本轮初判）、`new_axes`（matcher v2）、`historical_axes`（compose 对照）；`quality_status/evidence_complete/missing_codes` 取本轮卡，历史值只出现在 `historical_*`。
- 来源：`runs[].card_origin` 为 8 个身份字段逐个记录 `{value, source.object, source.field, round}`，逐卡记录 `{case_id, sha256, source.classifier_sha256, round}`；`runs[].identity_provenance` 为 `RescoreIdentity` 每个哈希记录来源对象；`historical_card.role=comparison_only`。
- 硬失败：`hard_failed_source = validated_per_case_axes.new_axes[*].state==violation`；`aggregate.hard_failures`、逐题 `hard_failed`、每轴 `violations`、`case_count` 四向核对后才落盘；`check_consistency` 通过后才写 `consistency.passed=true`。
- 产物：v2 默认写 `work/out/recompute-v2-r0-repair.json` 与 `work/out/artifacts-v2/{quality-per-run-v2.json,final-summary-v2.json}`；`--out/--out-dir` 可改到仓外，显式拒绝覆盖旧 `recompute-v2.json/quality-per-run.json/final-summary.json`。

## 未验证项（没有受控同轮重算，不得读成通过）

- v2 两个脚本未在真实 run 上执行：未生成新的四轴/质量/汇总产物，未验证 r0 是否 12/12、硬失败是否 0、unknown 是否收敛、C26 本轮 safety 与 D4/D5 兼容缺口的实际触发点。
- `recompute_axes_fullverify_v2.py` 走真实 `_recompute_loaded`，因此依赖 binding 文档的 `plan_file/plan_file_sha256`、`business_date`、`config_sha256`、`runs[0].evidence_bindings` 与回执 `run_binding`。fullverify 的 binding 是否逐项具备未核；缺失时脚本 fail closed（如 `plan_file_missing`/`case_plan_binding_mismatch`），不会伪造身份。
- `evidence_tree_sha256` 取自同一 run 回执并记录来源，但本脚本未独立重算整棵证据树；该核对留给受控执行/保管复核。
- 未做真实请求、未联网、未读私有题面/答案/计划/binding/密钥/.env；合成测试不能替代真实 H2。

## 保护件前后哈希（Get-FileHash SHA-256，19/19 SAME）

| 对象 | before = after |
|---|---|
| `p2_hard_evidence.py` | `fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b` |
| `p2_evidence_rescore.py` | `d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9` |
| `p2_contracts.py` | `3341ea79066b089e91e701fdff1b4713fe451044f4555bc0576425358bdd2fca` |
| `recompute_axes_fullverify.py` | `8952a5ce4fc2a804d6b91aa8199f5478fa3ca0223e8dc5c4c4206d15e5455d2e` |
| `build_fullverify_artifacts.py` | `3f2090691ba81331375e4eb165d1249dc3574b81289bca0df32dcee229c3af25` |
| `quality-per-run.json` | `6955099bd296db222054b1552dc3e13f070fe6c6e4653becd47f9729fcb3f642` |
| `recompute-v2.json` | `04e1f3df307f5c4036dcf77a992d1065d045177924827e1da206307f3c99c114` |
| `final-summary.json` | `e7e3d8875bf26ac803bccc73f0ad67fd07e07f3a30a745e4bc46d23517c4c4e6` |

Git：`git diff --name-status` before=29 / after=29 / differences=0；`git status --porcelain` 的 tracked ` M` 计数仍为 29；未 stage/commit/stash/reset/clean，未新建分支/worktree。基线快照见 `evidence/00-baseline/`，本次 after 快照见 `work/out/`。

## 交接停止点

R0-1 的代码、合成测试与红/绿证据已交付；真实同轮重算与 r0 结论需由有权限角色在受控环境执行 v2 脚本后另行报告。未做受控重算前，本报告不主张 r0 进展。
