# P2 · T900 独立总验收结论

2026-11-21（Asia/Shanghai）。独立验收窗口 `t900-acceptance`（非开发方；同一窗口完成阶段一 `PREP-PARTIAL` 与阶段二）。依据 [T900 任务书](../../superpowers/plans/2026-11-20-p2-closeout-5-t900-acceptance.md)、[v0.2 冻结清单](candidate-freeze.md)、[正式验收报告](T900-ACCEPTANCE/report.md)。

## 结论

# 有保留通过

**一句话理由**：冻结候选 47 项技术工件字节一致、2 项台账前缀完整；独立复跑正式门禁 `wire_real_ncu.py` 退出 0 且与冻结 JSON 逐字节相同（47 行 38 pass/0 blocked/0 pending/9 observed）；B0 40/40、精确 24/24、OCR 8/8 执行，N/C/U 8/8、6/6、10/10，H2 30/36、五层 10/5/5/5/5、29/30、硬失败 0、必需未知 0；八项硬门禁与最小样本、D-011、两组自写负例、浏览器均通过，本轮新增真实请求/费用为 0。保留项为 D-011 受控口径（U 硬门只 1 条 run 级样本）、H2 卡本体受限、供应商实账不可得、T900 真实抽验经 P-002 不执行、NCU 校验器内容级覆盖不足、`gate.py` 中间态不可重建、T208 完整 Ragas 套件未重跑等已披露限制，均不构成任务书规定的阻断条件。

## 状态统计（21 项）

| PASS | FAIL | BLOCKED | NOT-RUN |
| ---: | ---: | ---: | ---: |
| 20 | 0 | 0 | 1 |

`NOT-RUN` = T900 真实抽验（P-002；本轮零真实请求、零新增费用）。

## 关键实测

| 项 | 结果 |
| --- | --- |
| 冻结门 | 47 `frozen_artifacts` drift 0；2 `records_append_only` prefix violations 0；missing 0；exit 0 |
| 正式门禁复跑 | exit 0；`d4c98f92…` / 53,053 B；与冻结 JSON **逐字节相同** |
| 47 行 | 38 pass / 0 blocked / 0 pending / 9 observed；`reason_codes=[]`；行 id 集合摘要 `985d0556…` 一致 |
| B0 | `p2-admit` exit 0，`evidence_sha256=2226fa20…`，proof 与存档相等；40/40、38 通过、24/24、OCR 8/8（7 通过） |
| N/C/U | N 8/8、C 6/6、U 10/10；无条件 7/2/9，正式 8/6/10；6 条证明档原始机械 FAIL 保留 |
| H2 | 30/36；五层 10/5/5/5/5；29/30；硬失败 0；必需未知 0；四卡文件/聚合哈希分列且 4/4 不等；C25 历史 1 / 派生 0 |
| 八硬门 + 最小样本 | 汇总 pass；唯一 disclosed unknown 为 `min_sample_not_met`；b0 32/40、badcase 8/8、boundary 6/6、update_delete 10/1（D-011 披露） |
| D-011 | 披露行 10/10/1 如实；伪造计划数被拒；自造 U01 run 级引用失败 → `u.hard_gates` 与 `hard_gates` **双 blocked**（`release_hard_failure`），对照 pass |
| 自写负例 | 卡文件哈希=聚合哈希 → `h2.cards_index` blocked（`release_identity_mismatch`）；伪造 attested 99/actual 12 → binding blocked（`release_binding_attestation_invalid`） |
| B0 归档 | verify/restore/list/diff 全 exit 0；7 份运行工件逐字节一致；Q25/Q33 仍失败 |
| T208 | 24/24 调用、4 scored + 1 refusal unknown、硬失败 retained、0.0383 元、0 重试；GO/plan 匹配 |
| 资金 | 40 / 37.1647137 / 余 2.8352863；P2 24 / 22.0937692 / 余 1.9062308；2679/2679/0；D-006 裁定不违规 |
| 本轮新增 | 账本 `088dec5f…`、预算 `8f1b061b…`、GO `43e0f622…` 前后一致；最后一行 `2026-11-20T11:31:46Z`，之后 0 行 |
| 浏览器 | T08 **10/10 passed**（38.9s，exit 0）；acceptance-05 **2 expected / 0 unexpected**（exit 0，`external=[]`），5 张截图 |

## 主要证据

- [正式验收报告](T900-ACCEPTANCE/report.md)
- [冻结门探针](../evidence/T900/probes/freeze_v2.py) → `probes/out/freeze_v2_final.json`
- [正式门复跑产物](../evidence/T900/phase2/gate-result.rerun.json)、[字节比对](../evidence/T900/phase2/gate-rerun-compare.json)
- [47 行审计](../evidence/T900/probes/out/gate_audit.json)（50 项断言 0 失败）
- [D-011 专项](../evidence/T900/probes/out/d011_probe.json)、[两组负例](../evidence/T900/probes/out/negatives_probe.json)
- [B0 diff](../evidence/T900/phase2/b0-diff.json)、[B0 admit](../evidence/T900/phase2/b0-admit.json)
- [T208 审计](../evidence/T900/probes/out/t208_audit.json)、[资金重算](../evidence/T900/probes/out/funds_audit_phase2.json)
- [浏览器阶段二截图](../evidence/T900/browser/d3p2/screenshots/t900-phase2/05-sources/02-a14-source-drawer.png)

## 保留项

1. **D-011 受控口径**：U 八项硬门禁实际只在 1 条 run 级样本（U01）上评估，9 条为本地控制；披露行必须在 47 行中保留。
2. **H2 卡本体受限**：D-001 边界，29/30 逐题与 C25 历史值只能作 `NOT-VERIFIED（受限）`，T900 只核聚合外层。
3. **供应商实账不可得**：`provider_billed_cny` 全 null，只能账本保守口径（P-004）。
4. **T900 真实抽验 NOT-RUN**：P-002 判定不必要；本轮零真实请求、零新增费用。
5. **NCU 校验器内容级覆盖不足**：任务 3 独立复核 R2 的 3 个内容级篡改未被其单验器拒绝；正式门禁从原始 run 重算且冻结门复跑字节一致，但该证据完整性限制保留。
6. **`gate.py` 中间态不可重建**：HEAD `7e54fbf6…` → D-004 前工作树 `10235099…`（git 不可重建）→ 当前 `e04990db…`。
7. **T208 完整 Ragas 套件未重跑**：只复跑 `test_p2_judge_budget.py`（27 passed）并核真实回执；完整错误边界沿用 T208 IA R02 的 19 项。
8. **B0 旧状态分列**：B0 归档仍写 `blocked_pending_n_c_u_h2_evidence`，未被改写；当前技术输入以跨场景门禁 JSON 为准。
9. **历史包摘要漂移**：T201–T209 早期报告源码摘要与当前树不同，属历史演进；T900 不重跑旧包，冻结候选以 47 项为准。
10. **H2 报告路径字符串**：guard 负例含 holdout 根路径 1 处（非题干/答案/密钥/源单元标识），建议后续脱敏。
11. **U 的 `trace_integrity` suite 行为 N/A**：U01 原始 trace fail 与 D-005 修正 pass 只在 `binding.p2-t207-r2` 行分列；八门汇总未把 U trace 计为 pass，属适用性/呈现限制，不得反读为“U trace 已通过”。
12. **发布权**：`release_allowed=false`、`owner_release_decision=not_decided`；发布由主人决定，T900 不代主人发布。

## 纪律

零真实请求、零出站、零新增费用；未修改 `backend/**`、冻结清单内文件或开发方交付物；未 commit/push/merge。
