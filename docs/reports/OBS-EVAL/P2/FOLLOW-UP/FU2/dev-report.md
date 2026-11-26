# FU-2 开发报告：正式 H2 工具支持 v3 单 run 离线派生

- 日期：2026-11-21（Asia/Shanghai）
- 分支 / HEAD（开工核对）：`codex/p2-e2e` / `93486b6590c6542f34dd70d20a19b792c659f416`
- 范围：任务书 §3（FU-2）；与 FU-4 共用同一名开发者（CLI 错误出口同写）
- 零真实调用：本轮真实模型调用 **0**、OCR **0**、外网请求 **0**、新增费用 **0**
- 私有限制件：**未读取** env 文件、未打开任何私有密文内容、未写入/复制任何受限批次

> 路径书写约定：本报告及全部新公开产物中，仓外开发目录记作 `<DEV>`、pytest 临时目录记作
> `<TMP>`，受限 holdout / 批次根的名称与密钥、密文文件后缀一律不写（它们的检测字面量只存在于
> `FU4/evidence/scripts/audit_public_paths.py`，该目录在设计上被扫描排除）。

---

## 1. 结论（先看这段）

1. **旧入口确实不能派生 v3 单 run**：合成 v3 单 run binding 交给正式 v2 `recompute`，固定码
   `run_binding_invalid`、退出码 `2`、`real_sends=0`（可复现脚本见 §3）。
2. 正式 v3 入口新增 `derive-cards` 子命令：单 run 出卡，四 run 自动追加四场景合成；
   **五道校验独立**（历史计划与原执行身份 / 派生评分身份 / 场景与语料绑定 / 封存状态 /
   回合完整性），全部复用既有实现，**没有新增或放宽任何阈值**。
3. **确定性**：同输入重复运行，卡与证明逐字节相同（两次 `SHA-256` 逐值比对，见 §6）。
4. **v2 兼容**：v2 命令集合、v2 拒绝码、`code_changed_since_plan` 防护、既有评分口径全部未动；
   160 条既有受测定向用例 100% 通过（§7）。
5. **写入拒绝**：仓库根、`var`、原批次根、绑定声明的冻结 holdout 根内一律拒绝；覆盖 `..`、
   大小写、尾斜杠、`.\`、链接（junction）与"已存在且非空"（§8）。
6. 本轮 `NOT-RUN`：真实 v3 批次的端到端派生（无授权真件）；`_validate_dataset_shape` /
   `_verify_axis_counts` 两个 live 契约闸在合成夹具里被显式置空（§10）。

---

## 2. 改动清单（含行数量级）

| 文件 | 动作 | 行数 | SHA-256（改前 → 改后） |
| --- | --- | --- | --- |
| `tools/p2_h2_v3_controlled_execute.py` | 改（正式入口 + `derive-cards`） | 3421（原 2551，**+870**） | `953fda08df6f0ce1…` → `b5a20caf32f12f0b…` |
| `tools/p2_h2_controlled_execute.py` | 改（仅公开出口脱敏，13 行） | 3649（原 3636，**+13**） | `2e442c6992eeae23…` → `6cfcb724da366912…` |
| `backend/src/mktkb/evaluation/p2_safe_output.py` | **新建**（FU-4 共用） | 331 | 不存在 → `1d3b29bd5104e70f…` |
| `backend/tests/evaluation/test_p2_fu2_derive_cards.py` | **新建** | 1133 | 不存在 → `bc55fcf7ae5f68e7…` |
| `backend/tests/evaluation/test_p2_fu4_safe_output.py` | **新建**（FU-4） | 363 | 不存在 → `ab6007617654ab50…` |

> **并发工作树声明**：本工作树同时有 FU-1 / FU-3 的开发者在改文件。`git status` 里
> `backend/src/mktkb/evaluation/p2_runner.py`、`product_adapter.py`、`p2_release_gate.py`、
> `backend/tests/evaluation/test_p2_runner.py`、`test_p2_live_wiring.py`、`.claude/handoffs/_index.md`
> 的 tracked 改动**不是本项的**（本项只写下方 5 个文件 + `FOLLOW-UP/FU2`）。本项未对这些文件做任何
> 写入，也未执行 `git add/commit/stash/reset/clean`。
未改动的禁止区：`p2_runner.py`、`product_adapter.py`、`p2_b0.py`、`p2_release_public.py`、
`evaluation/cli.py`、`gate.py`、`docs/reports/OBS-EVAL/P2/**` 既有文件、`candidate-freeze.json`、
`var/**`、env 文件系列。全仓 `git status` 显示 `docs/reports/OBS-EVAL/P2` 下**唯一**的 tracked 改动
`T207-QUALITY-REPAIR/manager.md` 属开工前既有的在途改动，本轮未触碰（本报告全部证据另存
`FOLLOW-UP/FU2`）。

### 2.1 `derive-cards` 做了什么

```
derive-cards
  --binding B（可重复）        v3 单 run binding（仓外）
  --run-index N（可重复）      0..3，与 --binding 逐位对应
  --evidence-dir D（可重复）   该 run 的封存密文根（仓外）
  --case-plan P（可重复）      该 run 的 case-plan.json（仓外）
  --run-receipt R（可选、可重复）封存回执
  --evidence-key-file K       该批证据 Fernet key（仓外）
  --out-dir OUT               独立输出目录（受限根外、不存在或为空）
  --batch-root BR（可重复）    原批次根（禁止写入集合）
  --gate-config G             记录原始运行身份用（默认 `docs/evaluation/gate_v0_3.json`）
  --compat C                  拒答兼容版本（默认 `p2-refusal-compat/v0.6`，与已封存批次同值）
  --compose {auto,always,never}
  --ledger-path L（可选）      只读账本核对
```

输出（全部为聚合件，无题面/答案/逐题哈希）：

```
OUT/cards/run{i}-{scenario}.v0.2.card.json
OUT/proofs/run{i}-{scenario}.proof.json
OUT/composition/h2-composition.v0.2.json         # 四 run 时
OUT/composition/composition-proof.json            # 四 run 时
```

复用（未复制、未改写）：`v2.load_run_binding`（v3 校验器已在导入期替换为单 run 形状）、
`_records_from_document`、`v2._load_plan_for_run` / `v2._verify_plan_binding`、
`v2._scorer_identity_binding`（其内复用 `scenario_forbidden_source_identity`）、
`v2._validate_case_plan_document`、`v2.read_encrypted_evidence`、`assert_private_path`、
`tree_digest`；分类/聚合/校验 `hard.classify_case_evidence` /
`aggregate_hard_evidence` / `validate_hard_evidence_scorecard`；四场景合成
`compose_hard_evidence_runs` / `validate_hard_evidence_composition`。

### 2.2 五道校验与拒绝码

| 校验 | 复用实现 | 代表拒绝码（固定码） |
| --- | --- | --- |
| 历史计划与原执行身份 | v3 绑定校验器 + `_records_from_document` + `_load_plan_for_run` + `_verify_plan_binding` | `run_binding_invalid`、`input_changed_since_plan`、`plan_file_changed`、`plan_identity_mismatch`、`evidence_binding_mismatch`、`pipeline_changed` |
| 派生评分身份 | `_scorer_identity_binding` | `source_map_binding_mismatch`；失败降级为 `unresolved`（fail closed） |
| 场景与语料绑定 | `contract.binding/subset/ingest_plan` + 逐题 business_date | `scenario_binding_changed`、`scenario_subset_changed`、`business_date_case_mismatch` |
| 封存状态 | `_read_seal_state`（回执或封存 manifest） | `run_receipt_binding_mismatch`、`run_receipt_unsealed`、`run_receipt_not_succeeded`、`evidence_seal_missing` |
| 回合完整性 | `_validate_case_plan_document` + 密文逐回合回读 + manifest 对账 | `case_plan_invalid`、`case_plan_coverage_invalid`、`case_plan_turn_order_invalid`、`case_plan_evidence_file_duplicate`、`evidence_turn_index_mismatch`、`evidence_manifest_turn_count_mismatch` |

`code_changed_since_plan` 防护**保持**在真实入口（v2 `recompute` / v3 `run`）不变；派生是
"用新分类器重算历史证据"，因此按 D-010 的受控口径在证明里**同时显式记录**两套身份：
`identity.original.*`（原运行计划/代码）与 `identity.derived_scorer.*` +
`identity.derived_scorer_impl.classifier_source_sha256`（本轮真正执行的评分器源码摘要）。

---

## 3. 先复现（改前观测，原样记录）

### 3.1 正式入口当时没有派生能力

```
.venv\Scripts\python.exe tools\p2_h2_v3_controlled_execute.py derive-cards --help
```

- 观测（改前，2026-11-21 02:26）：`exit=2`，stderr：
  `argument command: invalid choice: 'derive-cards' (choose from 'plan-private', 'check-only', 'run')`
- 观测（改前，同一时刻）：`.venv\Scripts\python.exe tools\p2_h2_controlled_execute.py derive-cards --help`
  → `exit=3`，stdout `{"error_code": "usage_invalid", ...}`（`choose from 'plan-private','preflight','run','recompute'`）
- 结论：两个正式入口**都没有** v3 单 run 派生入口，与 D-010「仓外包装器」的事实一致。

### 3.2 旧入口拒绝 v3 单 run binding（可复现）

```
.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P2\FOLLOW-UP\FU2\evidence\scripts\repro_v3_reject.py --out docs\reports\OBS-EVAL\P2\FOLLOW-UP\FU2\evidence\reproduction.json
```

实测（本机）：

| 项 | 值 |
| --- | --- |
| 退出码 | `2`（`EXIT_REFUSED`） |
| `error_code` | `run_binding_invalid` |
| `real_sends` | `0` |
| stdout 行数 / stderr 行数 | 1 / 0 |
| 读取仓库 env 文件 | **否**（凭据源被重定向到合成 env；脚本不引用仓库 env 文件） |
| 真实模型调用 / 出站 | 0 / 0 |

原因（代码定位）：v2 `_validate_binding_document` 要求键集合恰为 14 键的 v2 形状（四 run、
26/1/2/1 计数、ingest 8/9/11/13），v3 单 run binding 是另一种 schema（`holdout_root` 等
v3 键 + `runs` 仅 1 条），因此在键集合处即被固定码拒绝，任何私有材料都没有被加载。
证据：`FU2/evidence/reproduction.json`（只含固定码/退出码/计数，命令已按角色脱敏）。

---

## 4. 验收用例与结果

命令（仓库根；`cd backend` 会破坏个别既有用例的相对语料路径，见 §10）：

```
.venv\Scripts\python.exe -m pytest backend\tests\evaluation\test_p2_fu2_derive_cards.py backend\tests\evaluation\test_p2_fu4_safe_output.py -q
→ 43 passed, 0 failed, 1 warning, exit 0        # FU-2 19 条 + FU-4 24 条
```

FU-2 覆盖矩阵（19 条）：

| 要求 | 用例 | 结果 |
| --- | --- | --- |
| 先复现旧入口拒绝 v3 单 run | `test_old_recompute_still_refuses_a_v3_single_run_binding`（**独立导入** v2 入口，避免 v3 导入期替换校验器） | PASS：码 `run_binding_invalid`、exit 2 |
| 正式入口注册派生命令且保留 live 命令 | `test_v3_parser_registers_derive_cards_and_keeps_live_commands` | PASS |
| v2 命令集合未被改动 | `test_v2_entry_still_refuses_derive_cards_subcommand` | PASS（恰为原四命令） |
| 错误绑定（binding_sha / 旧 schema） | `test_synthetic_binding_passes_the_real_v3_validator_and_tamper_is_refused` | PASS：合法件通过真校验器；篡改与旧 schema 均 `run_binding_invalid` |
| 历史计划与原执行身份 | `test_plan_identity_and_plan_tamper_are_refused` | PASS：合法通过；改计划字节 `plan_file_changed`；改 plan_id `plan_identity_mismatch` |
| 派生评分身份 | `test_derived_scoring_identity_is_derived_from_frozen_source_map_and_refuses_map_swap` | PASS：派生 `status=derived`；换 map 摘要 `source_map_binding_mismatch` |
| 回合完整性：完整 / 缺回合 / 重复回合 / 旧 schema | `test_case_plan_accepts_complete_turns_and_refuses_missing_duplicate_and_old_schema` | PASS：`case_plan_coverage_invalid` / `case_plan_turn_order_invalid`（或 coverage）/ `case_plan_invalid` |
| 派生编排：卡 + 证明 + path-safe | `test_derive_cards_writes_card_and_proof_path_safe` | PASS：卡过官方 `validate_hard_evidence_scorecard`；证明 `card_sha256` 逐值对得上；公开件扫描 0 命中 |
| 确定性 | `test_derive_cards_is_deterministic_for_the_same_input` | PASS（见 §6） |
| 错误绑定 / 错场景 / 错计数 / 旧 schema / 缺回合 / 重复证据文件（编排级 6 连负例） | `test_derive_cards_refuses_broken_bindings[...]`（6 参数） | PASS：`run_binding_invalid`、`scenario_binding_changed`、`scenario_subset_changed`、`case_plan_invalid`、`case_plan_coverage_invalid`、`case_plan_evidence_file_duplicate` |
| 封存状态 | `test_derive_cards_refuses_seal_missing` | PASS：`evidence_seal_missing` |
| 非法输出路径（8 个归一化负例 + 链接 + 非空） | `test_derive_cards_refuses_forbidden_and_normalized_output_paths` | PASS（§8） |
| 四场景合成（官方 compose + 官方组合校验） | `test_four_synthetic_derived_runs_compose_with_official_validators` | PASS：`total=30`、`turns 36/36`、`status=complete`；重复场景 `derive_composition_scenario_duplicate`；错序 `derive_composition_invalid: scenario_subset_mismatch` |
| 阈值中立 + 核心确定性 | `test_derive_card_core_is_threshold_neutral_and_deterministic` | PASS：两次派生逐值同；`thresholds_approved=False`、`hard_evidence.verified=False`（不放宽） |

---

## 5. 确定性

口径：卡用**唯一**序列化函数写盘并计算摘要（`indent=2, sort_keys=True, ensure_ascii=False`，
尾换行）；证明/摘要不含时间戳与随机盐，路径一律是角色记号 + 摘要前缀。

实测（`-k deterministic -s`）：

```
FU2-DETERMINISM {"files": {"cards/run0-base_b0.v0.2.card.json": "06196b2c1a3bfa0193c524ac0242cf4ef71584150486b306dd74634ebd328e81",
                           "proofs/run0-base_b0.proof.json": "50cdf364296aa7cf4715a5642e59e2a5af755a73610083a9a591946dbf18d9df"},
                 "summary_sha256": "3497d94a591e976499a44ff2c5fe3214ba22913f3e21db6a570f31072afd7e67"}
```

做法：同一输出目录连跑两次（中间清空），逐文件 SHA-256 全等 + 摘要 JSON 全等；再换一个
**不同**输出目录跑第三次，卡文件仍逐字节相同（证明卡内容与输出位置无关）。

---

## 6. 兼容

| 项 | 结论 | 证据 |
| --- | --- | --- |
| v2 命令集合 | 未变（plan-private / preflight / run / recompute） | `test_v2_entry_still_refuses_derive_cards_subcommand` |
| v2 拒绝码 | 未变（含 `run_binding_invalid`、`usage_invalid` …） | 复现脚本 + 既有 23 条 v2 入口用例 |
| 真实入口 `code_changed_since_plan` | 未改（v2 `recompute` / v3 `run` 原样） | diff 仅新增 `derive-cards` 与公开出口脱敏 |
| 既有评分口径 | 未改：`min_pass=24`、`hard_failures_max=0` 等阈值全部走官方默认；卡/组合校验器原样调用 | `_derive_card_core` 只调官方函数；§4 断言 |
| 既有受测定向用例 | **160 passed / 0 failed**（6 个文件，见 §7） | 下方命令 |

```
.venv\Scripts\python.exe -m pytest backend\tests\evaluation\test_p2_h2_v3_f02_cli.py backend\tests\evaluation\test_p2_h2_v3_controlled_entry.py backend\tests\evaluation\test_p2_h2_controlled_entry.py backend\tests\evaluation\test_p2_eval_tool_repair_e2e.py backend\tests\evaluation\test_p2_h2_docforbidden_identity.py backend\tests\evaluation\test_p2_holdout_scenarios.py -q
→ 160 passed, 0 failed, 1 warning, exit 0（45.83s）
```

---

## 7. 输出目录防护（实测负例）

`derive-cards` 的写入口只接受：受限根之外、且**不存在或为空**的目录；`..`、`.\`、大小写、
尾斜杠均先归一化再判定；链接按真实目标判定。

| 负例 | 实测拒绝码 | 目录是否被创建 |
| --- | --- | --- |
| 仓库根内 `<REPO>/tmp-fu2-derive-out` | `derive_output_in_forbidden_root` | 否 |
| `<REPO>/tmp-x/../tmp-y`（`..`） | `derive_output_in_forbidden_root` | 否 |
| 仓库根**大写**变体 | `derive_output_in_forbidden_root` | 否 |
| 尾斜杠 `<REPO>/tmp-fu2-derive-out/` | `derive_output_in_forbidden_root` | 否 |
| `.\`（`<REPO>/./tmp-fu2-derive-out`） | `derive_output_in_forbidden_root` | 否 |
| 仓库 `var` 目录内 | `derive_output_in_forbidden_root` | 否 |
| 原批次根内 | `derive_output_in_forbidden_root` | 否 |
| 绑定声明的冻结 holdout 根内 | `derive_output_in_forbidden_root` | 否 |
| 链接/junction 指向仓库（`<TMP>/link-into-repo/derived`） | `derive_output_in_forbidden_root` | 否 |
| 已存在且非空目录 | `output_not_empty` | 不写入 |

链接可用性实测：本机 **symlink 不可用**（"You do not have sufficient privilege"），
**junction 可用**并已实际用于负例；因此"链接负例"是**真跑过**的，不是声明。
输入侧同样只读校验：binding / case-plan / 回执 / key 文件都必须仓外（`path_inside_forbidden_root`）。

---

## 8. 证据索引

| 证据 | 路径 | SHA-256 |
| --- | --- | --- |
| 旧入口拒绝复现（机件） | `docs/reports/OBS-EVAL/P2/FOLLOW-UP/FU2/evidence/reproduction.json` | `4465225b0e8b95aa8191783f8ee496d661fbf55759ab2800244fb91e4d7d7125`（1082 B） |
| 复现脚本 | `.../FU2/evidence/scripts/repro_v3_reject.py` | `c9d67899fceab24678f540ef4892699002b9dd098cf56f8df4c0165f63481f15`（8834 B） |
| 派生入口观测/拒绝/sha 台账 | `.../FU2/evidence/derive-cards-evidence.json` | `d7582d0cd7c01fc2912ca3ac0f156cb8d0443b4fc1ac1f33f4961ba7ac2cc28a`（7749 B） |
| 本报告 | `.../FU2/dev-report.md` | 自指不列（交付窗口统一复算） |
| 测试日志 | `<DEV>/fu2/pytest-fu2-fu4.log`、`<DEV>/fu2/pytest-existing.log` | — |

---

## 9. 未覆盖 / 阻断 / 待经理决定

| 编号 | 事项 | 状态 |
| --- | --- | --- |
| B-1 | **真实 v3 批次端到端派生**（24 + 36 回合的受限封存） | `NOT-RUN`：无授权真件，且本轮硬约束禁止打开私有密文。合成夹具已覆盖五道校验的编排与拒绝分支；真实批次派生须由获授权保管人在既有权限内办理。 |
| B-2 | `_validate_dataset_shape` / `_verify_axis_counts` 在合成夹具中被显式置空 | 它们在**真实批次**上仍照常执行（代码未改、未绕过）；合成 12 题夹具无法满足"30 题/36 回合/逐场景 14-10-6-6"的 live 契约，故编排级用例只验派生自身五道校验。建议独立验收时用真件补一次正例。 |
| B-3 | `derive-cards` 的**多 run 组合**只在核心函数级验证（4 条合成 run），未跑 4 份真 binding 的 CLI | 同上（缺真件）。CLI 的 4-run 分支代码与单 run 共用同一循环 + `_derive_composition`，风险已登记为遗留 R-3。 |
| B-4 | 任务书 §7 的 `FOLLOW-UP/report.md` / `review.md` / 亲验交接 | 非本项交付物；`FOLLOW-UP/FU1`、`FU3` 已在同目录由其他开发者并行产出，本轮**未触碰**其文件。 |
| 决策请求 | 是否允许在**合成**层面把 `_validate_dataset_shape` 的 live 常量参数化（供夹具复用） | 待经理决定。默认**不改**：那会触碰"不放宽校验"的红线；本轮选择显式登记 NOT-RUN。 |

## 10. 遗留风险

- **R-1**：`derive-cards` 依赖 `v2` 模块的私有函数名（`_load_plan_for_run` 等）。v2 文件一旦
  重构，派生入口会立刻以 `internal_error` 失败（fail closed，不会静默出错，但需要同步改）。
- **R-2**：`--compat` 默认 `p2-refusal-compat/v0.6` 与已封存批次一致；若未来批次换 compat
  版本，必须显式传参，否则会以旧口径重算（会被官方卡校验/组合校验的 block 码显式标出）。
- **R-3**：四 run CLI 组合分支未在真件上跑过（B-3）；建议独立验收时补一条真件正例。
- **R-4**：派生输出目录的"为空"判定与写入之间存在 TOCTOU 窗口（同一机器并发写同一目录）。
  既有入口（`require_new_or_empty_dir`）本就是同一约定，未额外加固。
- **R-5**：`cd backend` 下跑这批用例会有既有用例因相对语料路径失败（与本项无关，见下）；本轮
  统一在**仓库根**执行并在报告里注明命令与 cwd。

## 11. 附：最终摘要（落盘后复算）

```
tools/p2_h2_v3_controlled_execute.py   3421 lines  b5a20caf32f12f0b6d1d170a75bbd39b2a3f0cf4a088b635f6d121fc587f94cf
tools/p2_h2_controlled_execute.py      3649 lines  6cfcb724da366912130d398f66c92423615de031653a3a183d1e80b952cfad86
backend/src/mktkb/evaluation/p2_safe_output.py  331 lines  1d3b29bd5104e70fa530d8de3982f0baf706a4ce31f84e897d6ec98ed63207f9
backend/tests/evaluation/test_p2_fu2_derive_cards.py 1133 lines bc55fcf7ae5f68e709355153aaa01ceb73b5e2e622cabaeb25a5dd6186fbae03
backend/tests/evaluation/test_p2_fu4_safe_output.py  363 lines ab6007617654ab500459f649876abcb1302e11a83d3964609a957ca2e5d09f9e
```
