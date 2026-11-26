# R0-3C / v0.5 空用集增补报告（投影 units 逐值镜像检索层）

日期：2026-11-16（Asia/Shanghai）。执行者：外部 AI 修复助手（v05）。
授权：主人已**明确批准**本增补（`C16-EMPTY-SCOPE-PROPOSAL.md` §5 与本次对 v0.5 的批准）。
契约：`docs/evaluation/p2-refusal-compat-v0_5.md`。

## 1. 结论

- **v0.4 结构上不可达已确证**：生产不变式 `db_projection.units = _event_unit_ids(events)`
  （`p2_evidence_capture.py`）⇒ 检索层非空时投影 `units` 必非空 ⇒ v0.4 放行检索层后仍在
  E 段"投影 `units` 必须显式为空"被拒，返回与 v0.3 完全相同的 `(False,'empty_set_not_proven')`。
- **新增 v0.5**：只多放行一种情况——投影 `units` 的 unit_id 集合**逐值等于**检索层
  `retrieval_observed[*].unit_ids` 并集（且 v0.4 放行条件已成立）。仅显式 `compat=v0.5` 生效；
  默认仍 `v0.1`；v0.1/v0.3/v0.4 逐值不变。
- 测试：新增 36 passed；四套合并 215 passed（62 + 29 + 88 + 36），定向子集 77 passed。
  同一**可达** C16 形状：v0.1/v0.3/v0.4 → `empty_set_not_proven`，v0.5 → `empty_use_scope_ok`。

## 2. 改动清单与净增行数

| 文件 | 性质 | 行数（前 → 后）= 净增 |
|---|---|---|
| `backend/src/mktkb/evaluation/p2_hard_evidence.py` | v0.5 常量/链式继承/镜像判据/E 段一处/审计一处 | 3989 → 4105 = **+116** |
| `backend/tests/evaluation/test_r0_repair_v05_projection_mirror.py` | 新增测试 | 0 → 637 = **+637** |
| `backend/tests/evaluation/test_r0_repair_c16_empty_scope.py` | 夹具修正 + 版本参数 | 518 → 563 = **+45** |
| `backend/tests/evaluation/test_p2_hard_evidence.py` | 投影 units 夹具镜像 + 4 条测试 | 4242 → 4328 = **+86** |
| `backend/tests/evaluation/test_p2_empty_scope_proof.py` | FROZEN_SHA 授权注释 + 新值 | 1379 → 1388 = **+9** |
| `docs/evaluation/p2-refusal-compat-v0_5.md` | 新增契约 | 0 → 131 = **+131** |

合计净增 **+1024** 行。未改产品代码、账本、预算、旧证据、case-plan；未安装依赖；未执行
`git add/commit/stash/reset/checkout/clean`。

## 3. `p2_hard_evidence.py` 前后哈希

- 改前：`8f206ee9f016b9fbf5d9d0c0568117f05692849c540fe232c3ec50b5c42c5bec`（= v0.4 批准 pin 字节，
  本会话开工时实测一致）。
- 改后：`7956b2b7159d6bc740a7ecff156605c85ad75c00ef57c45f99f282f19e14ba19`（= 新 `FROZEN_SHA` pin）。
- 改动面：1 个版本常量、1 条继承表项、`_compat_lineage`/`_relax_retrieval_enabled` 两个解析辅助、
  `_retrieval_unit_id_union`/`_projection_units_mirror_retrieval`/`_projection_mirror_relaxable`
  三个判据、E 段"units 为空"一处、`_ref_empty_use_scope` 一处。未改阈值、词表、匹配器、产品文案；
  未引入线程不安全全局状态（审计码走既有 `_AxisAccumulator.ref` 出口）。

## 4. 红 → 绿证据

**红**（把模块退化到 v0.4 代码路径：删 `REFUSAL_COMPAT_V0_5`、继承表单步、镜像判据恒 False）：
- `hasattr(REFUSAL_COMPAT_V0_5) = False`；
- 同一可达 C16 形状 + 字面量 `"p2-refusal-compat/v0.5"` → `(False,'empty_set_not_proven')`；
- 新测试文件：**9 failed / 27 passed**（`test_v0_5_constant_and_inheritance_chain`、核心翻转
  `[v0_5]`、axes、两处 audit、两处旧版不变等）。
**绿**（当前实现）：新测试 **36 passed**；放行样本 proof = `(True,'empty_use_scope_ok')`，
两轴 audit = `empty_use_scope` + `retrieval_observed_unused` + `projection_mirrors_retrieval`；
被拒样本不出现镜像码。

## 5. 旧版不变自证

- 68 个既有样本（C16 battery 10 + C16 反例 16 + 拒答 battery + 拒答容器变异）：
  - `default == v0.1`：68/68 逐值相同；
  - 63 个 `relax_v04=False` 样本：`v0.3 == v0.4 == v0.5`（同一代码路径）；
  - v0.3→v0.4 翻转集 = **[]**（可达样本上 v0.4 不翻转任何形状）；
  - v0.4→v0.5 翻转集 = **["c16_battery/c16_shape"]**（唯一新增放行）。
- 套件：`test_r0_repair_refusal_compat.py` **62 passed**；`test_r0_repair_c16_empty_scope.py`
  **29 passed**（原 28 + 1 个新增版本参数）；`test_p2_empty_scope_proof.py` **88 passed**；
  `test_p2_hard_evidence.py` 定向子集（r4/empty_scope/c16/strict_empty/no_fact）**77 passed**。

## 6. 夹具修正说明

- 原 C16 夹具 = `units=[]` + 检索非空 → **生产不可达**（v0.4 因此不可能生效）。
- `test_r0_repair_c16_empty_scope.py`：`c16_envelope` / `model_pair_envelope` 改为投影镜像检索；
  新增反例 `projection_unit_not_in_retrieval`（投影多出不在检索并集里的 unit → 仍
  `empty_set_not_proven`）；v0.4 窄放行判据仍逐条 pin（v0.5 下同样启用）。
- `test_p2_hard_evidence.py`：`build_evidence` 在 `retrieval_candidates` 非空时按生产口径
  （`strip` / 去空 / 去重）把候选写成投影 `units`（复制生产不变式）；`retrieval_scope` 可覆盖
  （默认值不变）；新增 4 条 C16 夹具/镜像反例测试。
- 因夹具改为可达形状而**被迫修正**的断言：C16 核心翻转改判 v0.5（v0.4 由"放行"变"拒绝"，
  这正是 v0.5 的动机）；反例的轴级断言改为"两轴不得**同时** passed"（`model_evidence_non_empty`
  在可达形状下 `stale_source` 走真实使用层路径，与 v0.3 逐值相同）。未放宽其它断言。

## 7. 未验证项

- 未在真实 H2/C16 envelope 上跑 v0.5（禁读私有材料，本轮只用合成件）；"C16 两轴升 passed"
  需在真实 envelope 上用 v0.5 重跑后确认。
- 未改/未重算任何旧证据与旧分；未验证 v0.5 对 11 题全集的逐题 0 差异（需真实件，本轮不做）。
- `test_p2_hard_evidence.py` 全量在任务指定 `--basetemp`（仓内）下 2 failed + 27 errors，均为
  `evidence_root_inside_forbidden` / `scenario_private_path_inside_workspace` 环境门（与改动无关）；
  改在仓外 basetemp 运行：**316 passed**。
