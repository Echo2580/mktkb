# P2 发布决定记录（D-014 行使）

2026-11-21（Asia/Shanghai）

## 决定

- **决定人**：主人
- **决定**：**发布 P2（现候选）**
- **原话/选项**：「发布 P2（现候选）」
- **适用范围**：仅限 `candidate-freeze.json`（schema `p2-candidate-freeze/v0.2`）所指候选。

## 绑定身份

| 项 | 值 |
| --- | --- |
| 分支 / HEAD | `codex/p2-e2e` / `97b0066726e5b8d6f94cbc0b63a890084550c106` |
| 冻结件 | `candidate-freeze.json` / `candidate-freeze.md` |
| 正式门禁 JSON | `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/gate-result.real-ncu.json` |
| 门禁 JSON SHA-256 | `d4c98f92c0873addbda01b28394b292b3fcd4bdec2aa39a25af6b8384ba66461`（53,053 B，47 行） |
| 批准配置 | `docs/evaluation/gate_v0_3_approved.json` `b1094cc7…`（canonical `7fa6f47a…`） |
| 正式 B0 基线 | `7981d4afc2d1` / run `p2-t209-b0-20261120-02` |
| 技术门判定 | `technical_gate = pass`、`decision = pass`、`reason_codes = []` |
| 独立总判定 | T900 `review.md`：**有保留通过**（20 PASS / 0 FAIL / 0 BLOCKED / 1 NOT-RUN） |

## 与冻结门禁 JSON 的关系（重要）

冻结的正式门禁 JSON 保留 `release_allowed=false`、`release_authority=owner`、`owner_release_decision=not_decided`，那是**决定前的快照**，作为 T900 验收输入。本记录是主人行使发布权的独立凭据，**不改写**该 JSON——因此门禁 JSON 的 SHA 不因发布而变，冻结候选保持可复现。

## 随发布生效的限定语（必须随结论出现）

1. D-011 受控口径：U 八项硬门禁实际只在 1 条 run 级样本（U01）上评估，其余 9 条为本地控制。
2. U `trace_integrity` 的 suite 行 N/A，原始 fail 与 D-005 修正 pass 只在 `binding.p2-t207-r2…` 行分列。
3. H2 卡本体受 D-001 限制，29/30 逐题与 C25 历史值仅 `NOT-VERIFIED（受限）`。
4. 供应商实账不可得，全部资金结论为账本保守口径。
5. T900 真实抽验 `NOT-RUN`（P-002：经理判定不必要，未获新授权）。

## 约束

- 发布后若候选发生影响判定的变更，须重新冻结、定向复验并重新取得主人发布决定。
- 本次发布不包含任何新增真实请求或费用；本轮新增真实请求 / 费用为 **0**。

## 关联记录

- 总报告：[p2-report.md](p2-report.md)
- 决定链：[manager-decisions.md](manager-decisions.md)（D-013 / D-014 / D-015）
- 经理核收台账：[manager-acceptance.md](manager-acceptance.md)

## 交付提交

| 项 | 值 |
| --- | --- |
| 提交 | 一条本地收尾提交，SHA 见 `git log -1 --format=%H`（该提交同时包含本记录） |
| 父提交 | `97b0066726e5b8d6f94cbc0b63a890084550c106` |
| 范围 | 387 个文件（`backend/` 194、`OBS-EVAL/P2/` 144、`docs/evaluation/` 23、`fixtures/` 14、`plans/` 8、`tools/` 4） |
| 推送/合并 | **未执行**（D-015） |
| 一致性 | `git show HEAD:<path>` 复算，47 项冻结工件 **47/47** 与冻结清单一致 |
