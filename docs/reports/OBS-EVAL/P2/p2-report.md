# P2 收尾总报告

2026-11-21（Asia/Shanghai）· 经理核收 · 项目根 `D:/GPT项目/市场部AI知识库`

**结论：有保留通过（主人 D-013 采纳），并已按主人 D-014 发布现候选。** 技术门 `pass`、`release_allowed` 在冻结门禁 JSON 中保留为 `false`（决定前快照），发布由主人以独立发布记录行使（D-014）。

---

## 1. 送审候选（已锁定）

| 项 | 值 |
| --- | --- |
| 分支 / HEAD | `codex/p2-e2e` / `97b0066726e5b8d6f94cbc0b63a890084550c106` |
| 冻结件 | [`candidate-freeze.json`](candidate-freeze.json) / [`candidate-freeze.md`](candidate-freeze.md)（schema `p2-candidate-freeze/v0.2`） |
| 冻结范围 | **47 项 `frozen_artifacts`**（代码/配置/门禁 JSON/各包报告与复核）逐字节 + **2 项 `records_append_only`**（台账，前缀不变） |
| 独立核验 | T900 回读：47 项 `drift 0`、2 项 `prefix violations 0`、`missing 0` |
| 正式门禁 JSON | `CROSS-SCENARIO-GATE/gate-result.real-ncu.json`，`d4c98f92c0873addbda01b28394b292b3fcd4bdec2aa39a25af6b8384ba66461`（53,053 B，**47 行**，行 id 摘要 `985d0556…`） |
| 批准配置 | `docs/evaluation/gate_v0_3_approved.json`，`b1094cc7…`（5,785 B）；canonical `7fa6f47a…`。**未跟踪，归档须显式取件** |
| 正式 B0 基线 | `7981d4afc2d1` / run `p2-t209-b0-20261120-02`；准入证据 `2226fa208aec7db84ab69e5f7a068e94322414d38b90c14399979b96fcea8b5d` |
| `gate.py` 身份链 | HEAD `7e54fbf6…` → D-004 前工作树 `10235099…`（**git 不可重建**）→ 当前 `e04990db…` |

**T900 独立复跑**：`wire_real_ncu.py` → exit 0，产物与冻结 JSON **逐字节相同**（[gate-result.rerun.json](evidence/T900/phase2/gate-result.rerun.json)）。

---

## 2. 正式质量门

| 项 | 结果 | 验证边界 |
| --- | --- | --- |
| B0 执行 | **40/40** | 真实运行 + 独立复算 |
| B0 正确 | **38/40**（阈值 ≥36） | 真实运行 |
| 精确 | **24/24** | 真实运行 |
| OCR | **8/8 执行、7/8 通过** | 真实运行 |
| N | **8/8**（无条件可采 7/8） | 独立离线复算 |
| C | **6/6**（无条件可采 2/6） | 独立离线复算 |
| U | **10/10**（无条件可采 9/10；1 真实 smoke + 9 本地控制） | 独立离线 + 已有真实 smoke |
| H2 同批 | **30 题 36 回合、五层 10/5/5/5/5、质量 29/30、硬失败 0、必需未知 0** | 保管方认证 + 独立聚合核验 |
| `hard_gates` 汇总 | **pass** | 独立复跑 |
| `reason_codes` | `[]`；38 pass / 0 blocked / 0 pending / 9 observed | 独立复跑 |

N/C/U 的 `ADOPTED_WITH_BINDING_PROOF` 六条（N01、C01、C02、U01、C05、C06）**机械 `trace_integrity` FAIL 留痕**，按主人 D-005 以可复算的历史绑定适用性证明采信；不得在任何汇总中写成 pass。

---

## 3. 八项硬门禁

按批准配置逐项适用性成立。其中 `cross_entity`、`stale_bypass`、`exact_value_contract`、`pagination_contract` 对 N/C/U 为 `not_applicable`（数据集无对应字段/分层），**不得反读为已通过**；`security_leak`、`conflict_not_rejected` 在 C05/C06 上适用并通过；`citation_required` 在 U01 上按主人 D-004 由 fail 转 pass；`trace_integrity` 见上条。

最小样本按主人 **D-011** 采用 suite 计划题数口径：B0 40≥32、N 8≥8、C 6≥6、U 10≥10、H2 30≥30。**披露行 `hard_gate_min_sample.run_level_subset` 是要求的输出行**，消费方不得删除；单读 `technical_gate=pass` 而不读该行会误读为「10 条 run 级证据都过了门」。

---

## 4. 未知项

| 口径 | 值 |
| --- | --- |
| 必需未知 | **0** |
| 非必需未知 | **0** |
| C25 | 历史 live `unknown` = 1 / 本派生 `not_applicable` = 0（**双列，不合并**） |

C25 的闭合由授权身份输入驱动（2×2 消融 + 360/360 单元身份双射实证），不是判据放宽。

---

## 5. Ragas（辅助诊断）

作为 T208 辅助诊断沿用已批准标准；本轮只复跑 `test_p2_judge_budget.py`（27 passed）并核真实回执，**完整套件未重跑**（保留项 8）。

---

## 6. 资金与真实请求

| 项 | 值 |
| --- | --- |
| 项目上限 / 占用 / 余额 | 40 / 37.1647137 / **2.8352863** 元 |
| P2-LIVE 阶段 / 占用 / 余额 | 24 / 22.0937692 / **1.9062308** 元 |
| 四中心余额 | answer 1.7632188 / ocr 0.05 / judge 0.043012 / independent 0.05 |
| 账本 | 2,679 预留 / 2,679 结算 / 待结算 0 / 孤儿 0 / 重复 `reservation_id` 0 |
| B0 两次真实运行 | 合计 **11.4397992** 元（attempt2 因 `trace_integrity` 阻断仍结算 5.7197526） |
| **本轮新增** | **0**：账本 `088dec5f…`、预算 `8f1b061b…`、GO `43e0f622…` 前后一致；账本最后一行 `2026-11-20T11:31:46.309888Z` 之后 0 行 |

- 请求上限口径按主人 **D-006**：以 B0 GO 的 `unlimited` 为准，2,679 笔不构成违规。代码硬常量 `HARD_MAX_REQUESTS=1600` 被 `unlimited` 哨兵跳过，属实现事实。
- 供应商实账**不可得**（`provider_billed_cny` 非空 0 条），全部资金结论为账本保守口径（**P-004 限制**）。

---

## 7. 档案恢复

`7981d4afc2d1` 归档 `baseline verify` 通过；隔离目录 `restore` → `list` → `p2-diff` 全通过；恢复后 7 份运行工件与源/归档逐字节一致（仅 `baseline.json` 的 `run_dir` 重写）。B0 归档内 `p2_release_status` 仍写 `blocked_pending_n_c_u_h2_evidence`，为**历史快照**，不得当作当前总门阻断（保留项 9）。

---

## 8. 浏览器与接口

| 用例 | 结果 |
| --- | --- |
| T08 离线（`02-chat` 7 + `04-kinds-and-isolation` 3） | **10 passed / 0 failed**，exit 0 |
| `acceptance-05-sources` | **2 expected / 0 unexpected**，exit 0，`external=[]`、`local_count=131` |

断言对应实际接口响应：a14 原件 200 + `nosniff`；a19 删除后原件 410、旧来源失效、新问答未引用 D03。5 张脱敏截图入册（[screenshots](evidence/T900/browser/d3p2/screenshots/t900-phase2/05-sources/)）。

---

## 9. 未运行项

| 项 | 状态 | 原因 |
| --- | --- | --- |
| T900 真实抽验（原口径 ≤5 题 / 独立成本中心 2 元） | `NOT-RUN` | 经理判定不必要（P-002）：阶段余额 1.9062308 元、independent 中心 0.05 元；结构性问题无法靠单题重跑改变。主人未另批。 |
| T208 完整 Ragas 套件 | `NOT-RUN` | 沿用既有 19 项证据，仅复跑预算测试 |

---

## 10. 保留项（12 条，真实限制，不构成阻断）

1. **D-011 受控口径**：U 八项硬门禁实际只在 **1 条 run 级样本（U01）** 上评估，其余 9 条为本地控制；披露行必须保留在 47 行中。
2. **U `trace_integrity` suite 行 N/A**：原始 U01 fail 与 D-005 修正 pass 只在 `binding.p2-t207-r2…` 行分列；不得反读为「U trace 已通过」。
3. **H2 卡本体受限**（D-001）：29/30 逐题与 C25 历史值只能 `NOT-VERIFIED（受限）`，只做聚合外层核验。
4. **供应商实账不可得**：只能账本保守口径（P-004）。
5. **T900 真实抽验 `NOT-RUN`**（P-002）。
6. **N/C/U 校验器内容级覆盖不足**：任务 3 送检器挡不住合法 hex 题干哈希篡改、幽灵证据路径、`trace_id` 互换；正式门禁从原始 run 重算且冻结门复跑字节一致，限制保留。
7. **`gate.py` 中间态不可重建**：D-004 前工作树值无 git 基线。
8. **T208 完整 Ragas 套件未重跑**。
9. **B0 归档内旧状态**须与当前门禁 JSON 分列，不得混读。
10. **T201–T209 早期报告源码摘要与当前树不同**，属历史演进，T900 不重跑旧包。
11. **H2 报告 guard 负例含 holdout 路径字符串 1 处**（非题干/答案/密钥/源单元标识），建议后续脱敏。
12. **发布权属主人**：冻结门禁 JSON 保留 `release_allowed=false`、`owner_release_decision=not_decided` 作为决定前快照。

---

## 11. 主人决定

| 编号 | 日期 | 原话/选项 | 所指候选与约束 |
| --- | --- | --- | --- |
| D-013 | 2026-11-21 | 「接受「有保留通过」（推荐）」 | 指向本报告 §1 冻结候选；12 条保留项须随结论出现 |
| D-014 | 2026-11-21 | 「发布 P2（现候选）」 | 仅限 D-013 候选；以独立发布记录行使，不改写冻结门禁 JSON |
| D-015 | 2026-11-21 | 「只提交 P2 交付范围（推荐）」 | 本地一条提交；不推不合并；排除 5,257 个历史脚手架未跟踪文件 |

完整决定链见 [manager-decisions.md](manager-decisions.md)（D-001 ~ D-015）。

---

## 12. 实际办理结果

- 发布：见 [release-decision.md](release-decision.md)（D-014 行使记录，绑定门禁 JSON `d4c98f92…`）。
- 提交：一条**本地收尾提交**（其 SHA 见 `git log -1 --format=%H`；该提交同时包含本报告），父提交 `97b0066726e5b8d6f94cbc0b63a890084550c106`，共 **387 个文件**：`backend/` 194、`docs/reports/OBS-EVAL/P2/` 144、`docs/evaluation/` 23、`fixtures/` 14、`docs/superpowers/plans/` 8、`tools/` 4。**未推送、未合并**（D-015）。
- **提交树一致性核验**：以 `git show HEAD:<path>` 逐项复算，**47 项冻结工件全部与冻结清单 SHA/字节一致**（`47/47`，`mismatches=[]`）。
- 已被排除的未跟踪脚手架：`.claude/handoffs/_scratch`、`.tmp-*`、`%SystemDrive%/`、`tmp_*`、`var/`、`__pycache__` 等（约 5,000+ 文件）；这些不属 P2 交付范围。
- 台账：[manager-acceptance.md](manager-acceptance.md) 记录每包的开发自测 / 独立复核 / 经理核收三层状态。

> 说明：`candidate-freeze.json` 记录的是**冻结时刻**的 HEAD `97b0066…`；提交后 HEAD 变为收尾提交，但**文件字节未变**（已用上述 `git show` 核验）。冻结以字节为准，提交不改内容。
>
> **提交范围限制**：本轮提交只含本轮 P2 交付与它们依赖的源码/测试/夹具。**更早期的 P2 证据目录**（`T207-*`、`H2V3/`、`Q1A-EVAL-REPAIR/` 等，约 230 个未跟踪条目）自本轮接手前即为未跟踪状态，本轮**未纳入**提交，仍留在工作树。因此若在干净检出上复核，冻结工件里的 `evidence_paths` 指向的部分历史证据需从工作树而非提交中取得。

---

## 13. 证据索引

| 包 | 开发 | 独立复核 | 经理核收 |
| --- | --- | --- | --- |
| 任务 1 H2 文档级禁源 | [report](H2-DOC-REBUILD/report.md) | [review](H2-DOC-REBUILD/review.md) | manager-acceptance §任务 1 |
| 任务 2 四场景派生卡 | [report](H2-REBUILT-CARDS/report.md) | [review](H2-REBUILT-CARDS/review.md) | manager-acceptance §任务 2 |
| 任务 3 N/C/U 证据 | [report](NCU-RELEASE-EVIDENCE/report.md) + [manifest](NCU-RELEASE-EVIDENCE/manifest.json) | [review](NCU-RELEASE-EVIDENCE/review.md) | manager-acceptance §任务 3 |
| 任务 4 跨场景门禁 | [report](CROSS-SCENARIO-GATE/report.md) | [review](CROSS-SCENARIO-GATE/review.md) | manager-acceptance §任务 4 |
| 任务 5 T900 总验收 | — | [review.md](review.md) + [报告](T900-ACCEPTANCE/report.md) | 本报告 |
| 任务 6 收尾 | 本报告 | [p2-report-block.md](T900-ACCEPTANCE/p2-report-block.md) | 本报告 |

T900 最终证据索引：[evidence/T900/index.md](evidence/T900/index.md)。

---

## 14. 后续工程债

| 编号 | 项 | 说明 |
| --- | --- | --- |
| P2-FU-1 | 通用 P2 运行路径 `binding_components()` 仍绑产品计数（仅 B0 已修） | 未来新 run 会复现 `trace_integrity` 同名异义计数器问题 |
| P2-FU-2 | 派生入口 v3 单 run 绑定未进正式工具 | 本批依赖 D-010 有条件接受的包装器 |
| P2-FU-3 | N/C/U 送检器内容级覆盖不足 | 建议补回源校验为默认 |
| P2-FU-4 | H2 报告 guard 负例含 holdout 路径 | 建议统一脱敏 |
