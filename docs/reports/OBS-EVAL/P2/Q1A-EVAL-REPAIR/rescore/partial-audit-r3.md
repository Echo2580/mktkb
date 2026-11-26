# Q1A 部分判据审计 R3：24 个 `stale_source=passed` 的 R-J-3 污染核查

主人，本报告是**保管执行**（新上下文，非开发、非验收、非经理）：只核对 R3 已发布的 `stale_source=passed` 是否被 R-J-3 缺陷污染，并给出严格读法下的修正计数。公开侧**只给计数**；题号、题面、答案、目标值一律不出现在本文件。

- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0 项，0 commit。
- 审计对象：R3 聚合 `acb5922d…`（41549 B）与私有明细 `89739f6d…`（151308 B）中 `stale_source=passed` 的 **24** 题。
- 判据 / 分类器：`p2-stale-source-criterion/v1` `c34d08af…` / `p2_stale_version_state.py` `fed19144…`（只读）。
- 零真实调用；未改 R1/R2/R3/NOT-RUN 任何产物。

## 0. 结论

> **确认假通过 0 / 可疑（缺信息）0 / 确认干净 24。**
>
> **严格读法（`partial` 一律 `unknown`）下：`stale_source` 仍为 pass 24 / unknown 6 / violations 0；题级仍为 pass 11 / hard 0 / unknown 19；仍 < 24/30。**
>
> R-J-3 的“非空 units + `turn_status=partial` 可 passed”通道**真实存在**（反事实 24/24 仍 pass），但**本批 24 个 pass 的 36 个回合全部是 `complete`**，所以该通道在本批**未被触发**，24 个 pass 没有被 R-J-3 污染。

## 1. 方法与可复现路径

1. 重放 R3 的同一投影：`evidence-r3/02-rescore-r3.py` 的 `load_public_inputs` / `load_contract_v1` / `load_contract_v2_inputs` / `plan_and_evidence` / `C.project_turn_v2` / `compute_stale`。旧 evidence 只在进程内解密，不打印/落盘文本。
2. 对每一题逐回合读取：`completeness.status` → `turn_status`（`complete` 当且仅当 status 为 `complete`；否则 `partial`）、`_stale_usage` 的 `units` 数、`determine_stale_case` 的逐回合 state/reason。
3. 与 R3 私有明细逐题比对：**30/30 题的 state/reason/`per_turn` 全部一致**；24/24 个 stale pass 就是 R3 的 24 个 pass，不是重算偏差。
4. 三分类规则：
   - **确认假通过**：某通过回合 `units` 非空且 `turn_status != complete`；
   - **可疑（缺信息）**：某通过回合的 `turn_status` 缺失/不在枚举内，或 `observed != true`；
   - **确认干净**：所有通过回合 `complete`，或空集通过回合本身已经读了 `turn_status`（空集分支 `p2_stale_version_state.py:841` 要求 `complete`）。
5. 反事实（只在内存、不改文件、不改真实输入）：把 24 题每个 executed 回合的 `turn_status` 改为 `partial`，重新调用 `determine_stale_case`，观察分类器是否仍判 pass。

## 2. 逐回合事实（只给计数）

| 项 | 值 |
|---|---:|
| 审计总题数 / 总回合数 | 30 / 36 |
| 回合执行状态 | `executed` 36 |
| 回合 `completeness.status` | `complete` 36 |
| 回合 `turn_status` | `complete` 36；`partial` **0** |
| 24 个 stale pass 的回合数 | 29（24 题） |
| 24 个 stale pass 的通过回合 | 29 |
| 其中非空 `units` 的通过回合 | **29** |
| 其中空集通过回合 | **0** |
| 其中 `turn_status != complete` 的通过回合 | **0** |
| 其中非空 `units` 且 `partial` 的通过回合 | **0** |
| 24 题中“含 partial 回合”的题 | **0** |
| 24 题中“含非空 units + partial 通过回合”的题 | **0** |

24 个 stale pass 的 reason 全部为 `stale_active_version_used`（29 个逐回合通过码同）；`empty_set_not_proven` 只出现在 6 个 unknown 题上，不在 24 个 pass 内。

## 3. R-J-3 命中模式

- 判据 `p2-stale-source-criterion-v1.md:253`（R-J-3）：使用层零观测（无 `units` / 未观测 / 回合未完成 / 回合 `partial`）→ `unknown stale_usage_set_missing`。
- 分类器实现：`_determine_turn` 只在**空集**分支读 `turn_status`（`p2_stale_version_state.py:841`，经 `_empty_use_proven`）；**非空**分支只读 `usage.observed` 与 `units`（`:996-1003`），随后逐 unit 解析（`:1038-1076`），**从不读 `turn_status`**。
- 因此命中形状是：`units 非空` + `turn_status=partial` + 其余 unit 全部合规 → `passed/stale_active_version_used`。本批 24 个 pass 中该形状出现 **0** 次。
- 反事实：把 24 题的 29 个通过回合全部标为 `partial` 后，分类器仍 **24/24 pass、0 unknown**。这证明缺陷通道是活的（严格读法下这些题应为 unknown），但**不是**本批的真实读数；真实输入没有任何 partial 回合。

## 4. 严格读法下的修正数字

严格读法 = “任何 `turn_status != complete` 的回合，其使用集证据不完整 → `unknown stale_usage_set_missing`；题级按 `violation > unknown > not_applicable > passed` 折叠”。其余三轴沿用 R3。

| 项 | R3 主读数 | 本审计严格读法修正 |
|---|---:|---:|
| `stale_source` pass | 24 | **24** |
| `stale_source` unknown | 6 | **6** |
| `stale_source` violations | 0 | **0** |
| `stale_source` not_applicable | 0 | **0** |
| 题级 pass | 11 | **11** |
| 题级 hard failure | 0 | **0** |
| 题级 unknown | 19 | **19** |
| 是否 ≥ 24/30 | 否 | **否** |

- 修正量为 0，原因是 24 个 pass 的通过回合全部 `complete`；没有一题因 partial 改判。
- 若把 0 个可疑也并入 unknown（敏感性上界），题级仍 11 / 0 / 19；区间宽度为 0。
- 24 个 stale pass 中有 **11** 个是题级 pass；其余 13 个题级为 unknown 是其他轴的 unknown 所致，与本轴读数无关。
- **不要把本读数与 R3 的 record 身份严格读数混在一起**：后者（省略 `record_code`、不承认 runtime `unit_key` 作为 record 身份）是 `0 pass / 30 unknown`，属于 R-Q1A3R3-02；本审计的主读数是 R3 的 `unit_key` 桥，只叠加“partial 一律 unknown”这一条。

## 5. 零调用与保全

| 项 | 结果 |
|---|---|
| 零真实调用 | `zero_network_attempts`：`socket.socket.connect/connect_ex`、`create_connection`、`getaddrinfo`、`gethostbyname` 全替换并记账；正对照 `blocked=true`；正对照前事件 **0** |
| HEAD / 分支 / commits | `97b0066…` / `codex/p2-e2e` / 172，前后不变 |
| 暂存区 | 前后均 0 |
| 96 个保护项（判据、分类器、适配器、C 冻结、合同 v1/v2、R1/R2/R3 聚合/报告/私有明细、旧卡/旧 evidence 树、C1-1 审查） | **0 changed / 0 missing** |
| 旧 run 身份 | `package_binding_sha256 = 0ea9d21d…`，`MATCH`；旧 evidence 树 `16420e90…`、旧卡 `53e4a82b…` 前后一致 |
| R3 私有明细 | `89739f6d…` / 151308 B 未变（逐字节在保护项内） |
| 公开侧隐私 | 公开 JSON 的题号命中 **0**；禁止键扫描 `forbidden_public_keys = []`；公开报告只含计数 |

## 6. 限制与不可比

- `turn_status` 是旧 evidence 的 `completeness.status` **声明字段**；本审计没有从 capture 事件独立重算“采集完整性”。就“R3 当时喂给分类器的 `turn_status` 是否含 partial”而言，读数完整；就“旧证据采集器是否可能把不完整回合写成 complete”而言，本审计不能证明。
- record 身份仍是 runtime `unit_key` 桥（R-Q1A3R3-02 未关闭）；citation 层未重跑（R-Q1A3R3-04）；其余三轴直接沿用 R3 私有明细，不重算。
- 反事实注入是**机制检查**，不是“本批存在 partial”的主张；不得把它写成 24 个假通过。
- 本报告只陈述计数与是否达到 24/30；不构成 T207 通过、P2 完成、质量放行、阈值或发布依据。与旧 `19/30`、Q1a-3 R2 的 `1/30`、C1-1 的 stale `0/30` 均不可比。

## 7. 产物

| 类型 | 路径 | SHA256 / 字节 |
|---|---|---|
| 公开报告 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/partial-audit-r3.md` | 本文件 |
| 公开计数值 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/partial-audit-r3.json` | `1bf9f1e8ed5e1c808c7a45d71b2223ef295a980e9ea83f9545bc4282b13a1c0d` / 8168 B |
| 审计脚本 | `docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-partial-audit-r3/02-partial-audit-r3.py` | 只读重放 + 反事实 + 零调用/保全 |
| 私有逐题明细 | `D:\mktkb-q1a3-rescore\partial-audit-r3.fernet` | `41a0c0d79da65c862072d8f2a867f9bff3bcb16a54f631b0c045362b53c606b8` / 27212 B（独占创建，同一 key 容器；明文 20342 B，无文本） |

## 8. 最终结论

**24 个 `stale_source=passed` 未被 R-J-3 污染**：确认假通过 0、可疑 0、干净 24。严格读法下 `stale_source` 仍 24 pass / 6 unknown，题级仍 11 pass / 0 hard / 19 unknown，仍 **< 24/30**。R-J-3 的“非空 units + partial → passed”仍是**未关闭的潜在假通过通道**（反事实 24/24 仍 pass），但本批证据没有 partial 回合，不能把它记成 24 个假通过。
