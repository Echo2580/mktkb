# NOTES：R2（run_index=2）同轮四轴重算记录（T-R2-201B）

本文件是 `r2-repair-external-20261117` 交付目录里 **201B 子任务**的运行记录。
只写固定码、计数、布尔、哈希、case_id / run_id；不含题面、答案、实体值、业务数字、私有路径。

目录内另有 **201A 子任务**的文件（`work/r2_safe_project.py`、`work/_patch_01_header.py`、`evidence/00-baseline/*`、
`evidence/01-safe-projection/*`），本子任务只读、未改动其中任何字节。

## 1. 范围与身份

| 项 | 值 |
|---|---|
| run_index | **2** |
| run_id | `p2-h2v3-20261115-r2-pre_v05_without_v07` |
| scenario_id | `pre_v05_without_v07` |
| 业务日期 | **2026-11-20** |
| 案例 | `H2V3-C08`、`H2V3-C14`、`H2V3-C19`、`H2V3-C25`、`H2V3-C29`（5 题） |
| 回合 | **6**（C14 两回合，其余各 1） |
| 运行根 / binding 目录 / key | 私有，按任务单给定；本文件以 `<RUN_ROOT>` / `<BINDINGS_DIR>` 占位，不登记 |
| matcher / analysis | `ref-unit-matcher/v2` / `Q1A-RESCORE-20261114-r1` |
| 脚本 schema | `p2-h2v3-axes-v2-recompute/v0.2-r2-same-round` |

## 2. 移植与改动清单（r1 → r2）

环境：`.venv\Scripts\python.exe -X utf8`。**未跑 pytest，未发任何产品/离线请求。**

| 文件 | 来源 | sha256 |
|---|---|---|
| `work/r0_same_round.py` | R1 同名文件**逐字节复制**（加载器按文件名加载） | `0df9316cde68b9b57c357dcfda99890867c2ede792e9b4840820b48f7fedecfa` |
| `work/r2_recompute_axes.py` | `r1_recompute_axes.py`（sha `4867490f3832661c6114fce995d32b5b0a5de0926c65ba9c61d699a7b21f6c9f`）+ 15 处定点替换 | `092d48c7dab0d1268f1765cc462391525975e62c2775639e4d4585d390d95914` |
| `work/build_r2_script.py` | 本次新增，生成上表的点替换工具（每处断言命中 1 次） | `fd01dee4ac48d3b133595f992d8c201b0020967512c43b01849f57d53e724515` |
| `work/build_chain_reports.py` | 本次新增，生成 flips / consistency 两个机器件并自设门 | `18c5e9f5f0ce18065035613a5f6d87b07ffd616b0e73b6c667096ab43e437b42` |

`r2_recompute_axes.py` 相对基座**只有**以下 5 类改动（`difflib` 全量审阅：151 行差异，全部落在这 5 类内）：

1. **默认 run 集合**：`--runs` 默认 `[2]`；`picked != [2]` → 固定码 `single_run_isolation_violation`。
2. **run 目录解析**：沿用 `<work>/r2` 优先、其次单 run 根；新增 receipt `run_index` 必须为 2 的断言。
3. **输出默认名**：`work/out/recompute-v2-r2-repair.json`。
4. **轮次标签**：`SCHEMA_VERSION` → `…-v0.2-r2-same-round`；argparse 描述与 `--runs` 帮助文本。
5. **单 run 隔离**：历史四 run 对照件只物化 `run_index=2` 那一条（`_historical_run_entry`，0 或 >1 条即 `single_run_historical_entry_invalid`）；
   收尾 `_assert_single_run_output` 断言 `runs_out==[2]` 且 `case_records` 的 run_index 集合 ⊆ {2}。

**判定逻辑、matcher 调用、`_CompatScope`、聚合、一致性门、NetGuard、SAFE 出口逐字未改**；
`PROTECTED_OUTPUTS` 三项原样保留。

### 2.1 compat 注入点结论

`p2_hard_evidence.REFUSAL_COMPAT_V0_6` **已存在**（`p2-refusal-compat/v0.6`），因此 **未启用**任务单步骤 3 的 `_compat_scope` 兜底注入，
`classify_case_evidence` 直接由基座既有的 `_CompatScope` 包装显式收到 compat：每档 `compat_classify_calls = 5`（等于题数，5/5 档全部成立）。

`_empty_use_scope_proof` 的 compat 注入计数在**本批为 0/0**（`injected_calls_total=0`、`control_calls` 全 0）：
5 题都没有走到空集证明分支，因此该注入机制在本批**未被触发**，不构成本批的证据；一致性门的其余 7 项与逐档 40 条复核仍全部成立。
这里不做“因为计数为 0 所以通过”的推断——脚本自身的 `compat_empty_scope_not_applied` 检查也只在 `control_total>0` 时才可能触发。

## 3. 命令与退出码

`<RUN_ROOT>` = 任务单给定的 R2 封存运行根（其下 `r2` 为 run 目录）；
`<BINDINGS_DIR>` = 任务单给定的 binding 目录（含 4 个 run 的 binding 文件）。
两者与 key 均为私有路径，本文件不登记具体值（key 由脚本常量读取，未出现在任何命令行）。

| # | 命令（`$PY` = `.venv\Scripts\python.exe -X utf8`，`$W` = `…\r2-repair-external-20261117\work`） | 退出码 |
|---|---|---:|
| 1 | `$PY $W\r2_recompute_axes.py --runs 2 --work <RUN_ROOT> --bindings <BINDINGS_DIR> --compat p2-refusal-compat/v0.1 --out $W\out\recompute-v2-r2-v01.json` | 0 |
| 2 | 同上 `--compat …/v0.3` `--out $W\out\recompute-v2-r2-03.json` | 0 |
| 3 | 同上 `--compat …/v0.4` `--out $W\out\recompute-v2-r2-04.json` | 0 |
| 4 | 同上 `--compat …/v0.5` `--out $W\out\recompute-v2-r2-05.json` | 0 |
| 5 | 同上 `--compat …/v0.6` `--out $W\out\recompute-v2-r2-06.json` | 0 |
| 6 | `$PY $W\build_chain_reports.py` | 0 |
| 7 | 省略 `--runs`、`--compat …/v0.6`、`--out $W\logs\default-runs.json`（默认 run 集合测试） | 0 |
| 8 | 同 5 再跑一次到 `$W\logs\rerun-v06.json`（确定性复跑） | 0 |

复跑一致性：`rerun-v06.json` 与 `out/recompute-v2-r2-06.json` **除 `generated_utc` 外逐字段相同**（布尔 true）；
`default-runs.json` 与其亦相同 ⇒ 默认 run 集合确实只有 run 2。

负对照（证明断言真的会拦，全部以固定码退出，**未生成任何输出文件**）：

| `--runs` 取值 | 退出码 | 输出 |
|---|---:|---|
| `0` / `1` / `3` | 2 | `{"error":"single_run_isolation_violation","ok":false,"where":"run"}` |
| `2,0` / `0,2` / `2,3` | 2 | 同上 |
| `--out` 指向 `fullverify-20261116/evidence/recompute-v2.json` | 1 | `refuse_to_overwrite_protected_output`（`PROTECTED_OUTPUTS` 生效） |

> 附注：`--runs ""`（空串被 PowerShell 吞成“缺参数”）由 argparse 报 `expected one argument`、退出码 2——
> 这是 shell 传参现象，不是脚本判定；真正的“不传 `--runs`”见第 7 行，正常跑 run 2。

## 4. 各档 sha256 与结果

| 档 | 文件（`evidence/03-final-chain/` 与 `work/out/` 内容相同） | sha256 | 质量 | `new_axes` 四态（安全 / 跨用户 / 跨实体 / 陈旧） | 硬失败 | unknown (case,axis) |
|---|---|---|---|---|---|---|
| v0.1 | `recompute-v2-r2-v01.json` | `30fa7f2c06a4759a5a5120f4809eeb53d17c1378c61c7bba86f69d4c9f84e472` | 4 pass / 1 fail | 1p4n / 5p / 3p2u / 5p | `[]` | C25·ce、C29·ce |
| v0.3 | `recompute-v2-r2-03.json` | `aed78b40abce625c99da0fcbc0fa45155c046e80f34bc823bfc7204112ae1d64` | 4 pass / 1 fail | 同上 | `[]` | 同上 |
| v0.4 | `recompute-v2-r2-04.json` | `ea1394a33cfe30f7bbb591558fa4aacba8b288362b8090f5a50ec843925f406b` | 4 pass / 1 fail | 同上 | `[]` | 同上 |
| v0.5 | `recompute-v2-r2-05.json` | `1295971ce947f8180768c986f1e8ba56e969c55466cdea240e6dd7fd129addb3` | 4 pass / 1 fail | 同上 | `[]` | 同上 |
| v0.6 | `recompute-v2-r2-06.json` | `cc0e6d6353b24b839f8fd5f4dc8b2afa1106684af9ff8d076e0d89bd2cd1efc5` | 4 pass / 1 fail | 同上 | `[]` | 同上 |

派生件：

| 文件 | sha256 |
|---|---|
| `evidence/03-final-chain/r2-axis-flips.json` | `581ce8b44658fded978e0f9f3515731abfec488fbec1dcee977e3215e1b547b4` |
| `evidence/03-final-chain/r2-consistency.json` | `c4562b63d826148b43eb2bef34b16cb4c72478f9d456699913085528bbe66364` |

（两份派生件的 sha 会随 `generated_utc` 变化；内容门以 `r2-consistency.json` 的 `consistency_passed` 与 `checks` 为准。）

## 5. 零调用证据

5 个档文件顶层 `calls` 全为 0：`{"network":0,"provider":0,"model":0,"retrieval":0,"real":0}`。
`scope_contract.passed = null`（真实 run 路径不传 `scope_contract`，与任务书 §5.3 一致，未临时换分析路径）。
历史四 run 对照件只作 `comparison_only`，且只物化 run 2 一条。

## 6. 出站守卫（NetGuard）

5 档 + 默认/复跑两次，`netguard` 全为：

```json
{"blocked_attempts": 2, "positive_control_attempts": 2, "positive_control_blocked": true, "outbound_allowed": 0}
```

正对照成立（两条必然失败的出站尝试都被拦下并计数 2）；守卫在 `main()` 入口安装，先做正对照再跑分析，
正对照失败即 `netguard_positive_control_failed` 退出 2。子进程面：本次**未起任何子进程**做产品/网络工作
（只有 `python` 主进程本身），因此不涉及“父进程有守卫、子进程没有”的缺口。

## 7. 单 run 隔离断言（成立）

| 断言 | 证据 |
|---|---|
| 参数层 | `--runs` 只接受 `[2]`；`0/1/3/2,0/0,2/2,3` 六种取值全部以 `single_run_isolation_violation` 退出 2 |
| run 循环层 | 每个 run 断言 `run_entry.run_index == 2` 且 `receipt.run_index == 2` |
| 数据层 | 历史四 run 文件只物化 `run_index=2` 条目（`other_run_entries_materialized=0`） |
| 输出层 | `single_run_isolation` 块：`selected_runs=[2]`、`runs_out=[2]`、`case_records_run_index_set=[2]`、`case_records_total=5`、`asserted=true` |
| case 层 | 5 题集合精确等于 `case-plan.json`（`build_chain_reports.py` 逐档门，`tier_case_set_not_equal_case_plan` 未触发） |
| 业务日层 | 逐档 `business_date == "2026-11-20"`（`tier_business_date_not_r2` 未触发） |

## 8. 保护件（开工前 → 收工后哈希一致，未覆盖）

| 文件 | sha256（前=后） |
|---|---|
| `fullverify-20261116/evidence/recompute-v2.json` | `04e1f3df307f5c4036dcf77a992d1065d045177924827e1da206307f3c99c114` |
| `fullverify-20261116/evidence/quality-per-run.json` | `6955099bd296db222054b1552dc3e13f070fe6c6e4653becd47f9729fcb3f642` |
| `fullverify-20261116/run/final-summary.json` | `e7e3d8875bf26ac803bccc73f0ad67fd07e07f3a30a745e4bc46d23517c4c4e6` |

另：`r0-repair-external-20261116/`、`r1-repair-external-20261117/` 下既有文件全部只读；`r1_recompute_axes.py`
与 `r1-repair-external-20261117/work/r0_same_round.py` 的 sha 已在 §2/§4 交叉登记，未改。

工作树：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；
`git status --porcelain` 358 行（39 项 tracked 修改 + 319 项 untracked），与 `evidence/00-baseline/git-status-porcelain-before.txt`
的 39 项 tracked 修改**逐行相同**（`Compare-Object` 结果为空）。本子任务只新增 untracked 文件，未 stage/commit/stash/reset/clean。

## 9. 依赖身份（与判定直接相关）

| 件 | sha256 |
|---|---|
| `p2_hard_evidence.py`（分类器） | `9861c44ec34fb797fa0f02d44c053fe047a7046183b662b6d70bfc3808549624` |
| `p2_evidence_rescore.py` | `d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9` |
| `p2_evidence_rescore_axes.py` | `57495943c763977e62fa7acded407e99ba360336fc5ee8c822f5e084f200f08e` |
| `p2-evidence-rescore-v0_1.md` | `e0487f256524558ae12b00e6a9d961a7360e92f1437ab4d7d0c55702f375588d` |
| `p2-evidence-rescore-v0_2.md` | `747e3656bfbaf0bb4f0e40444d96d20d2b30806d80d061fbca13b962a46c8db5` |
| `p2-stale-source-criterion-v1_1.md` | `0ec6c392b48b4a731140021e147f86e01284a58b34a3a3c4f50f6312bb307715` |
| `p2-source-lifecycle-v1.json` | `cc2ad0be2a3d884987d9f74b32e25181d752a8b497093afba42ccef8d87541d1` |
| `p2-holdout-v3.source-map.json` | `03665c48c0716e45e0a6313c6f1823e6714c996d85254f01283fc0ef5ed2e8b8` |
| `run/r2-final/case-plan.json`（= `r2/out/controlled/case-plan.json`，逐字节相同） | `fe8741861e74edb8bab8ea1ee07dfd37a1ede60c766d53ba30699fd25ea325da` |
| `compose/evidence/recompute-four-runs.json`（历史卡，comparison_only） | `4567476f316a9e38b67a3f53f0654802f5027c6377d44f974dfee1218394d18c` |

## 10. NOT-RUN / 未决（不猜通过）

1. **未跑 pytest**，未跑任何产品、离线或真实请求；本轮只做只读证据重建。
2. **compose 旧卡的分类器 build 未登记**：`compose/evidence/recompute-four-runs.json` 的卡内没有 `classifier_sha256` /
   `analysis_version`，因此“旧卡 `cross_entity` 4/1 → 今日初判 3/2”只能定性为判据版本变更，无法落到具体 build sha（记 unknown）。
3. **C25 / C29 的 `cross_entity` unknown 未定因**：本批只重建到 `entity_identity_unresolved` + 审计码
   `entity_identity_missing`（两题）+ `target_ref_no_match`（C29）；属于产品缺陷、捕获缺失还是契约限制，需 202B 段证据，本文不下结论。
4. **C29 质量 fail 的 `failed_check_ids` 未在本子任务重建**（属 201A/`r2-quality-checks.json` 范围），本文只引用 case-plan 的 `fail` 状态。
5. **`_empty_use_scope_proof` 注入未被触发**（§2.1），本批不能用它证明 v0.6 空集条款行为。
6. **v0.6 新增条款在本 5 题上零触发**：五档逐 (case,axis) `old`/`new` 的 `state+reason` 全等（`cell_diff_count=0`），
   即“旧档不变”成立，但同时也说明本批**没有**任何一题能用来验证 v0.6 的放行效果。
7. **不声称**：`verified`、`threshold_met`、`release`、`T207_pass`；T207 的 24/30 门槛不适用于本 5 题子集。
