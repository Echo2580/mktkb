# P2 发布决定记录（重新资格化候选 · v0.3 冻结）

2026-11-21（Asia/Shanghai）

## 决定

- **决定人**：主人
- **决定**：**发布 P2（重新资格化候选）**
- **原话/选项**：先「解决所有阻断，P2交付」，再「授权」（回应"把这次提交推上去或宣布发布"）
- **适用范围**：仅限 [`candidate-freeze.v0_3.json`](candidate-freeze.v0_3.json)（schema `p2-candidate-freeze/v0.3`，
  `payload_sha256=13e9d0996c329f9da6c86a72b8759b1e357f8f379fcf8028847bd273359456af`）所指候选。

## 绑定身份

| 项 | 值 |
| --- | --- |
| 分支 / 提交 | `codex/p2-e2e` / `7556efd`（父提交 = 候选基线 `93486b6590c6542f34dd70d20a19b792c659f416`） |
| 冻结件 | `docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification/candidate-freeze.v0_3.json`（21,862 B） |
| 冻结件 payload 摘要 | `13e9d0996c329f9da6c86a72b8759b1e357f8f379fcf8028847bd273359456af` |
| 候选流水线 | `pipeline_source_sha256 = 13a962ed103e18ec775de9f0f2764af2a2de325392df1194b09c76932814f4e4`；`pipeline_version = d3ca88d2c515+13a962ed…` |
| 正式门禁 JSON | `docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification/gate/gate-result.json` |
| 门禁 JSON SHA-256 | `8cd28d36c0b04a0ce3049586674b335412659c3f070af5ec4abc56a9761c584d`（51,380 B，49 行） |
| 批准配置 | `docs/evaluation/gate_v0_3_approved.json` `b1094cc7…`（canonical `7fa6f47a…`）——**未改** |
| 正式 B0 基线 | `2b40ee9b4740` / run `p2-t209-b0-20261121-01`（`evidence_sha256=f94bbb5b…`） |
| B0 结果 | 执行 **40/40**、正确 **38/40**、精确 **24/24**、OCR 执行 **8/8**（通过 7）、硬失败 **0**、必要未知 **0**、真实调用 **112** |
| 技术门判定 | `technical_gate = pass`、`decision = pass`、`counts = 39 pass / 0 blocked / 0 pending / 10 observed`、`reason_codes = []` |
| 费用 | 保守计入 **5.719853 元**（上界 7.464016）；预留 112 / 结算 112 / 悬账 0；供应商实账未出 |
| 独立性 | 开发自测 + 独立子代理 FU-2 端到端 + 干净检出复跑（42 passed）均记录在报告；T900 独立总验收不替代 |

## 与冻结门禁 JSON 的关系（重要）

冻结的正式门禁 JSON 保留 `release_allowed=false`、`release_authority=owner`、
`owner_release_decision=not_decided`，那是**决定前的快照**。本记录是主人行使发布权的独立凭据，
**不改动**该 JSON——因此门禁 JSON 的 SHA 不因发布而变，冻结候选保持可复现。这与 D-014 对 v0.2 候选的
处理一致（见 [`release-decision.md`](../release-decision.md)）。

## 随发布生效的限定语（必须随结论出现）

1. 沿用 D-011 受控口径：U 八项硬门禁实际只在 1 条 run 级样本（U01）上评估，其余 9 条为本地控制。
2. 沿用 D-005/D-001：U 的 `trace_integrity` 原 `fail` 与 H2 卡本体受限的披露**逐字保留**，未改写为 pass。
3. N/C/U 六条原机械失败（N01/C01/C02/C05/C06/U01）与 D-011 披露行保留原样。
4. **FU-2 端到端派生为合成证据**：4/4 卡经官方校验器通过且确定性成立，但证据包
   `completeness=incomplete` → 四轴 `unknown`、卡 `verified=false`；**不得**据此声称 FU-2 质量已达标。
5. **浏览器复验为隔离实例 + 受控替身网关（Mock 标注）**，不是真实模型生成；真实问答/来源详情/OCR 亲验
   （`S2-OWNER-ACCEPTANCE` 余 96 次 / 9.99 元）未执行。
6. 真实受限批次与四份真 binding 的 `derive-cards` CLI 组合、H2 30 题重跑、746 件历史泄露逐件复核、
   三张卡真实分享副本再扫描：均 `NOT-RUN`。
7. 供应商实账不可得，全部资金结论为账本保守口径。

## 约束

- 本候选若发生影响判定的变更（含产品/评测/门禁登记/阈值/语料），须**重新冻结、定向复验并重新取得主人发布决定**。
- 本次发布不含任何新增真实请求或费用；本轮真实费用已在 §绑定身份 中单列并已结算。
- 部署（deploy）不在本决定范围内；推送与合并各自单独授权。

## 关联记录

- 收尾报告：[`report.md`](report.md)（§1 结论、§3 检查清单、§6 门禁与重新冻结、§8 NOT-RUN、§11 提交建议）
- 新冻结件：[`candidate-freeze.v0_3.json`](candidate-freeze.v0_3.json)
- B0 请批单与回执：[`b0-preflight-request.md`](b0-preflight-request.md)、[`evidence/b0-acceptance-receipt.json`](evidence/b0-acceptance-receipt.json)
- 旧候选发布决定（v0.2）：[`release-decision.md`](../release-decision.md)（D-014）
- 决定链与经理核收：[`manager-decisions.md`](../manager-decisions.md)、[`manager-acceptance.md`](../manager-acceptance.md)

## 交付提交

| 项 | 值 |
| --- | --- |
| 提交 | 一条本地收尾提交，SHA 见 `git log -1 --format=%H`（该提交同时包含本记录） |
| 父提交 | `7556efd`（候选提交，父为 `93486b6`） |
| 推送 / 合并 / 部署 | 推送按主人「授权」执行；合并与部署**未执行** |
