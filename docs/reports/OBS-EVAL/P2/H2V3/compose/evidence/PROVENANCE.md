# 证据来源与复算说明（H2V3 compose 包）

- 角色：v3 四 run 聚合与失败归因（普通角色；不是验收、不是经理、不是保管）。
- 边界：**零真实调用 / 零网络**；未 stage/commit/push；未新建 worktree、未切分支。
- 结论：组合卡未生成（`PARTIAL`）；四轴与硬失败由既有 rescore/axes 路径重算（4/4 卡通过冻结校验）；12 个失败逐题对照预先登记。

## 1. 零调用正对照

`zero_call_guard.py` 在导入目标脚本前接管 `socket.socket.connect`：非本机地址一律在 connect 前抛 `NETGUARD_BLOCKED` 并计数；随后用 TEST-NET-1（`192.0.2.1:80`，数值地址、无 DNS）做一次正对照。

| 目标 | 正对照 | 目标执行期外部尝试 | 退出码 | 结果文件 |
|---|---|---|---|---|
| `recompute_four_runs.py`（四 run 四轴/硬失败重算） | 被拦（attempts=1） | **0** | 0 | `zero-call-recompute.json` |
| `probe_compose2.py`（组合尝试 + 授权分派诊断） | 被拦（attempts=1） | **0** | 0 | `zero-call-compose.json` |
| `probe_compose3.py`（再补已知 `config_hash` 的诊断） | 被拦（attempts=1） | **0** | 0 | `zero-call-compose3.json` |

> 两个目标均只读本地文件、做 Fernet 解密与 SHA 复算；未 reserve、未发送、未写账本/预算，**未使用任何本机代理**。

## 2. 输入（只读）

| 输入 | 路径 | 用途 |
|---|---|---|
| 预先登记 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/pre-registration.json`（`23cb3c08…`） | 失败归因的对照基准 |
| v3 冻结 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/p2-holdout-v3.freeze.json`（`f7c484d3…`） | 冻结件清单与保护范围 |
| 逐 run 卡/回执 | `docs/reports/OBS-EVAL/P2/H2V3/run/r{0,1,2,3}/{card,case-plan,run-receipt,status}.json` | 计数、计划/案例哈希、清理删除项哈希 |
| 四 run 聚合 | `docs/reports/OBS-EVAL/P2/H2V3/run/r123/aggregate.json` | 请求/金额/账本前后值 |
| 判据 v1.1 / L1 | `docs/evaluation/p2-stale-source-criterion-v1_1.md`、`docs/evaluation/p2-source-lifecycle-v1.json` | 四轴判定语义 |
| v3 场景契约/ingest/source-map/schema | `docs/evaluation/p2-h2-scenarios-H2v3.json`、`docs/reports/OBS-EVAL/P2/H2V3/PM/p2-ingest-plan-H2-v3.json`、`docs/evaluation/p2-holdout-v3.source-map.json`、PM 保管记录 | v3 loader 的绑定校验 |
| v3 密文与 key | `D:\mktkb-p2-holdout\v3\*.fernet`、`D:\mktkb-p2-h2v3-20261115\runs\r0\ev.key` | 标注解密与逐回合证据读回（key 不回显） |
| 仓外封存 case-plan / 证据 | `D:\mktkb-p2-h2v3-20261115\runs\r{0,1,2,3}c\...` | 逐题质量状态与回合→证据文件映射 |
| 账本/预算 | `docs/evidence/LOCAL-R1-20261101/budget/{live-ledger.jsonl,budget.json}` | 复算前后不变性 |

全部输入的文件名、字节数、SHA-256 见 `MANIFEST.json`（含仓外输入的 SHA；key 只记 SHA）。

## 3. 实际执行的复算路径（零模型/检索）

1. **装载 v3 契约**：`tools/p2_h2_v3_controlled_execute.py::load_v3_bundle`（内部用 `p2_holdout_scenarios_v3.load_v3_scenario_contract`，逐值校验 annotation/review/case/ingest/source-map/schema 绑定）。30 题 / 36 回合 / 4 scenario。
2. **装载每 run 计划**：`v2._load_plan_for_run`（复用 v2 受控骨架；计划文件在 `regen-1160c/plans`，SHA 逐值匹配）。
3. **逐 run 重算**：`v2._recompute_loaded` → `p2_hard_evidence.recompute_hard_evidence`（冻结确定性分类器）；输入为封存 case-plan、30/36 份 Fernet 密文、解密后的 v0.2 标注；`plan_meta` 取 run binding 的 run_id/config_sha256/expected_strata/real_calls。
4. **逐卡校验**：`p2_hard_evidence.validate_hard_evidence_scorecard(total=subset, run_id, config_hash, expected_strata)`；**4/4 通过**。
5. **聚合**：按 run 求和（题集互斥），得到四轴 30 题计数与硬失败并集；不生成组合卡（见 `compose-blockers.json`）。
6. **逐题对照**：从封存 case-plan 读 `quality_status`；从最后一回合密文用 `p2_hard_evidence._final_outcome` 读实际 kind；与预先登记的 `expected_direction` 逐题比对。

## 4. 未执行 / 未伪造

- **未生成组合卡**：既有 `compose_scenario_runs` / `compose_hard_evidence_runs` 均在 `contract.validate_run` 处以 `scenario_plan_mismatch` 拒绝（v3 的 `index_embedding` 9/10/13/15 与冻结配方 8/9/11/13 不同，composer 不接受逐 scenario 授权差）；加内存授权分派后又以 `scenario_aggregate_binding_mismatch` 拒绝（每 run `summary.json` 的绑定块已被受控清理删除，仅余 SHA-256；`contract.binding()` 不含 `config_hash`）；再补入已知 `config_hash` 后停在 `scenario_pipeline_unbound`（`pipeline_version`/`provider`/`gate_config_hash` 的共享块缺失，`gate_config_hash` 无任何保留值）。
- **未重建/未补写** `holdout_scorecard.json`、`summary.json`、`gate_config_hash` 或任何被删除字段；未用 `config_sha256` 冒充 `gate_config_hash`。
- **未判通过**：18/30 < 24，且 `hard_failures=4 > 0`、`thresholds_approved=false`。
- **未改**：C 冻结 12、v2/v3 语料与密文、评测模块、账本/GO/预算、30 题/标签/阈值。

## 5. 局限（必须随结果一起读）

1. **四轴 `verified=false`**：30 题共有 26 个轴格落 `unknown`（原因分布见 `hard-failures-and-axes.json`），所以 `hard_failures=4` 是**已证实下界**，未知项可能藏着违规（例如 C27/C29 的 `safety:forbidden_source_unmappable`）。
2. **质量判定的逐检查明细未保留**：每 run 的 `holdout_scorecard.json` 在清理阶段被删（仅 SHA-256），因此 12 个失败的 `kind_correct`/取值/来源检查级失败码无法逐项取回；本包只对"实际 kind 与期望 kind 不符"的题给出 `KIND_CORRECT_MISMATCH`，对 kind 相符但质量 fail 的题标 `UNATTRIBUTED_CHECK_LEVEL`。
3. **冻结件漂移**：`verify-freeze.py` 报 **2/32 DIFF**——`PM/manager-acceptance.json`、`PM/review-aggregate.json` 在 freeze B 之后（2026-11-15 04:43，真实 run 之前）补入了 review 密文绑定（`review-v0_2.fernet` = `4f07a8db…`），但 `freeze.json` 的 `artifacts[]` 与 `changes_to_freeze_a` 未再回填。两件 mtime 早于本会话，本包未改；这是**预先存在的冻结账本不一致**，不是本包引入。
4. **四 run 计划 SHA 与早期 `v3-go/plan-index.json` 不同**：真实 run 用的是 `regen-1160c` 重生成计划（run card 里的 `70f8f373…`/`5019efb4…`/`9c609a00…`/`554d1f09…`），不是 plan-index 里的早期值；本包以 run card / binding 为准。

## 6. 复跑

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY='40'
# 零调用守卫（先正对照，应为 blocked）
.venv\Scripts\python.exe evidence\zero_call_guard.py evidence\recompute_four_runs.py <out>.json
# 四轴/硬失败
.venv\Scripts\python.exe evidence\recompute_four_runs.py
# 组合尝试（预期两个固定拒绝码）
.venv\Scripts\python.exe evidence\compose-attempt-standard.py
.venv\Scripts\python.exe evidence\compose-attempt-after-delta.py
```

脚本内的仓外路径按本机实际位置写死；复跑前请核对 `MANIFEST.json` 的输入 SHA。
