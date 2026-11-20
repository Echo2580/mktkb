# p2-report.md 独立结论区块（T900 提供，2026-11-21）

> 直接摘录用。结论：**有保留通过**（T900 独立窗口；非开发方）。

## 独立结论

| 项 | 独立结论 | 依据 |
| --- | --- | --- |
| 冻结候选 | **PASS** | v0.2：47 项技术工件 drift 0；2 项台账前缀 violations 0；missing 0；正式门禁 JSON/批准配置匹配 |
| 正式跨场景门禁 | **PASS** | `wire_real_ncu.py` 独立 exit 0；产物 `d4c98f92…`/53,053 B 与冻结 JSON 逐字节相同；47 行 38 pass/0 blocked/0 pending/9 observed；`reason_codes=[]` |
| B0 | **PASS** | 40/40 执行、38 通过、精确 24/24、OCR 8/8 执行（7 通过）；`p2-admit` `2226fa20…`；Q25/Q33 仍失败（如实保留） |
| 精确 24/24 | **PASS** | B0 `b0.exact` 行 |
| OCR 8/8 执行 | **PASS** | `b0.ocr` 行（7/8 通过） |
| N / C / U | **PASS** | N 8/8、C 6/6、U 10/10（1 真实 + 9 本地）；无条件 7/2/9，正式 8/6/10；U01 原始 citation/trace FAIL 保留，D-004/D-005 修正视图分列；U 的 `trace_integrity` suite 行为 N/A，原始 fail/修正 pass 只在 binding 行 |
| H2 同批 | **PASS（受限）** | 30/36、五层 10/5/5/5/5、29/30、硬失败 0、必需未知 0；C25 历史 unknown 1 / 派生 N/A 0；卡本体按 D-001 记 `NOT-VERIFIED（受限）` |
| 八项硬门禁 | **PASS** | 汇总 `hard_gates=pass`；唯一 disclosed unknown 为 `min_sample_not_met`；`not_applicable` 为 cross_entity/pagination/stale_bypass，不称“已通过” |
| 最小样本 | **PASS（D-011）** | b0 32/40、badcase 8/8、boundary 6/6、update_delete 10/1（run 级 1，披露行在 47 行内）、regression 7、holdout 30 |
| 必需 / 非必需未知 | **PASS** | H2 必需未知 0；C25 非必需历史 1（派生 0）单列；U 仅 min_sample 披露 unknown |
| 真实请求 / 费用（本轮新增） | **0 / 0** | 账本 `088dec5f…` 前后一致，最后一行 11:31:46Z，之后 0 行 |
| 历史资金 | **账本口径** | 项目 40 / 占用 37.1647137 / 余 2.8352863；P2 24 / 22.0937692 / 余 1.9062308；2679/2679/0；供应商实账不可得（P-004） |
| 请求上限 | **PASS（D-006）** | 主人裁定 B0 GO `unlimited` 为准，2,679 不构成违规；硬常量 1600 被哨兵跳过，属实现事实 |
| B0 档案恢复 | **PASS** | verify/restore/list/diff 全 exit 0；7 份运行工件逐字节一致；仅 `baseline.json` 的 `run_dir` 重写 |
| T208 | **PASS（受限）** | 24/24、4 scored + 1 refusal unknown、硬失败 retained、0.0383 元、0 重试；完整 Ragas 套件未在 T900 重跑 |
| 浏览器 | **PASS** | T08 10/10（exit 0）；acceptance-05 2/2（exit 0，`external=[]`）；5 张截图 |
| T900 真实抽验 | **NOT-RUN** | P-002 经理判定不必要；本轮零真实请求、零新增费用；如主人另要求须新 GO |

## 结论

**有保留通过。** 技术门与全部正式证据通过；保留项为 D-011 受控口径（U 硬门仅 1 条 run 级样本）、U 的 `trace_integrity` suite 行 N/A（原始 fail/修正 pass 只在 binding 行）、H2 卡本体受限、供应商实账不可得、P-002 真实抽验未执行、NCU 校验器内容级覆盖不足、`gate.py` 中间态不可重建、T208 完整 Ragas 套件未重跑、B0 旧状态需分列、历史包摘要漂移、H2 报告路径字符串。以上均为已披露限制，不构成任务书规定的阻断条件；发布由主人决定（`release_allowed=false`、`owner_release_decision=not_decided`）。

## 证据

- `docs/reports/OBS-EVAL/P2/T900-ACCEPTANCE/report.md`
- `docs/reports/OBS-EVAL/P2/review.md`
- `docs/reports/OBS-EVAL/P2/evidence/T900/probes/out/*.json`
- `docs/reports/OBS-EVAL/P2/evidence/T900/phase2/gate-result.rerun.json`
