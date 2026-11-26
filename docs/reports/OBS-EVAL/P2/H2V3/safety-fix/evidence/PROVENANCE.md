# v3-safety-fix 证据来源与读取边界（PROVENANCE）

- 目录：`docs/reports/OBS-EVAL/P2/H2V3/safety-fix/evidence/`。
- 基线：分支 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`、暂存 0。
- 角色：v3 安全修复轮开发（普通开发）。

## 1. 真实 H2 读取边界

- **未解密、未读取**真实 H2 题面/答案/labels/targets/authoring-record/密文；未打开仓外运行证据树、`.env`、key。
- 原因归类只使用公开聚合与公开设计文档：
  - `docs/reports/OBS-EVAL/P2/H2V3/compose/compose-report.md`、`compose/evidence/hard-failures-and-axes.json`（run/题号/轴/原因码/quality/四轴计数）；
  - `docs/evaluation/p2-holdout-v3-dataset.md`、`docs/evaluation/p2-hard-evidence-classification-v0_1.md`、`docs/superpowers/plans/2026-11-15-h2-v3-authoring-plan.md`、`2026-11-14-h2-v3-design-spec.md`（分层/判据/机制描述）；
  - `docs/reports/OBS-EVAL/P2/T207-SAFETY-TRIAGE-20261114/`（上一轮同轴 triage 的方法与结论，仅作交叉参考）。
- 语料只读用于构造**同构合成数据**（`fixtures/acceptance-h2v3` 的 12 个源、字段形状与"物品位置表/合作店家信息"角色），不复制题面/答案，不改语料。

## 2. 探针脚本（本包自写，离线）

| 文件 | 作用 | 改前/改后 |
|---|---|---|
| `probe_security_refusal.py` | 合成“物品记录 + 店家联系人/电话/地址”请求，打印产品 kind / 模型调用数 / 证据实体 | `probe-security-before.json`（改前、任何代码改动之前跑）→ `probe-security-after.json`（最终代码） |
| `probe_other_entity.py` | 合成多轮（单实体→电话/同店另一物品/换门店/多目标→指代…），打印每轮证据实体 | `probe-other-entity-before.json` → `probe-other-entity-after.json` |
| `probe_forbidden_source.py` | 只读调用冻结 `p2_hard_evidence._ref_matches_unit`，对比“旧版禁源 ref / 当前正确行 / 版本感知复核” | 仅一份（判据只读，与产品改前改后无关） |
| `regression_probe_A_multi_target.py` | 复用 fix-1 独立验收探针（原样复制、未改），跑 13 例 A 正/反例 | `A-planner-multi-target.json` |
| `reconstruct_pre_round.py` | 反向删除本包新增块，重建 `rag/query.py`、`conversations/service.py` 的“改前”字节并比对 fix-1r1 收尾 SHA | `reconstructed-pre-round.json` |
| `build_fix_diff.py` | 生成 `fix.diff` 与 `fix-sha.json` | — |
| `preservation_snapshot.py` | 只哈希保全对象，与 fix-1r1 收尾快照对照 | `preservation-after.json`、`preservation-compare.json` |

- 探针均为临时 SQLite + offline provider + `EvidenceEchoGateway` 替身模型；不建产品库、不读 `.env`、不调用真实模型/embedding/rerank/OCR/检索服务。
- 合成数据：`物品位置表`（门店/物品/别名/标识/位置）与 `合作店家信息`（标识/店家/联系人/电话/地址/合作状态），行值全部为本包自拟（示例路/010-0000xxxx/模拟联系人），不来自 H2 语料。

## 3. 零调用守卫来源

- `netguard_plugin.py`：**原样复制**自 `docs/reports/OBS-EVAL/P2/H2V3/fix-1r1/evidence/netguard_plugin.py`（未改）。
- `netguard/`：**原样复制**自 `docs/reports/OBS-EVAL/P2/H2V3/fix-1/independent/netguard/`（`netguard_independent.py`、`sitecustomize.py`、`positive_control.py`；未改）。
- 复制是为了本轮可独立复跑同一口径的守卫与正对照；两份源文件在前几轮已由独立验收使用。
- `netguard-positive-control-run.json` 是守卫进程退出时写的计数（NETGUARD_OUT），`netguard/netguard-positive-control.json` 是正对照脚本写的逐项结果；两者互补。

## 4. 复现步骤（离线；backend/ 下）

```powershell
$ev = (Resolve-Path "../docs/reports/OBS-EVAL/P2/H2V3/safety-fix/evidence").Path
../.venv/Scripts/python.exe "$ev\probe_security_refusal.py"     "$ev\probe-security-after.json"
../.venv/Scripts/python.exe "$ev\probe_other_entity.py"        "$ev\probe-other-entity-after.json"
../.venv/Scripts/python.exe "$ev\probe_forbidden_source.py"    "$ev\probe-forbidden-source.json"
../.venv/Scripts/python.exe "$ev\regression_probe_A_multi_target.py"
../.venv/Scripts/python.exe "$ev\reconstruct_pre_round.py"
../.venv/Scripts/python.exe "$ev\build_fix_diff.py"
../.venv/Scripts/python.exe "$ev\preservation_snapshot.py"

# netguard（正对照 4/4 + 定向测试）
$env:PYTHONPATH="$ev"; $env:NETGUARD_OUT="$ev\netguard-targeted-run.json"
../.venv/Scripts/python.exe -m pytest -q -p netguard_plugin `
  tests/unit/test_v3_safety_fix_policy.py tests/integration/test_v3_safety_fix_e2e.py `
  tests/rag/test_v3_fix1_multi_target.py tests/rag/test_v3_fix1_business_date_filter.py `
  tests/rag/test_v3_fix1r1_anaphora_multi_target.py tests/unit/test_v3_fix1_wiring.py `
  tests/observability/test_paths_e2e.py
```

## 5. 未做的事（如实声明）
- 未跑真实 H2（零调用轮），因此“修复后在真实 30 题上是否消失”未验证；本包只证明合成复现消失与回归不退化。
- 未改冻结评测模块（含 `_ref_matches_unit`），未改阈值/评分/题集/语料/密文/账本/GO/预算。
- 未 stage/commit/push，未新建 worktree、未切分支。
- `A-planner-multi-target.json` 为探针输出（含 13 例逐项结果）；`netguard-targeted-run.json` 含回环计数（本机 anyio/pytest socketpair，不是业务出站）。

## 6. 清单

- `MANIFEST.json`：本目录逐件字节数 + SHA-256（生成时排除 `__pycache__` 与 `MANIFEST.json` 自身）；`file_count` 为生成时文件数。
- 生成顺序：先跑完全部探针/测试/日志，再 `build_manifest.py`，最后 `preservation_snapshot.py`，三者互不覆盖对方的产物哈希。

