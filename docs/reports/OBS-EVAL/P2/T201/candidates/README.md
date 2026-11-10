# P2 预算 / GO / 计划 —— 候选（DRAFT，无可用授权）

**这些文件不是授权。** 它们由 T201 开发助手按任务书 §4 的规划值生成，只用于离线预检与
Mock 推演；没有主人批准、没有经理签发、没有写入原 `budget.json` / `S2-LIVE-GO.json` / 账本。
真实调用前必须由 T206 按当时账户与官方价格重算、由经理在限额内落盘正式 GO。

| 文件 | 内容 | 状态 |
|---|---|---|
| `p2-run-plan-v0_1.CANDIDATE-DRAFT.json` | 候选请求计划（6 case / 30 次底层调用） | DRAFT |
| `p2-live-go.CANDIDATE-DRAFT.json` | 候选 GO（`document=P2-LIVE-GO`，含 DRAFT 字样） | DRAFT，不可用 |
| `budget.CANDIDATE-DRAFT.json` | 候选预算（总额 20→40、净新增 `P2-LIVE=20`） | DRAFT，未落盘 |
| `p2-ledger-snapshot.CANDIDATE-DRAFT.json` | 真实账本事实 + 候选预算分配的推演快照（`source=in-memory`） | DRAFT |

## 资金算术（候选）

    limit_cny                       20.00 -> 40.00（候修订）
    历史保守占用                    15.0709445（原样保留，不挪用旧余额）
    原阶段：S1-DEV 0 + S1-IA 0 + S2-DEV 15.4 + P1-RETRIEVAL 3.0 + later_shared_reserve 1.57
    新增阶段：P2-LIVE 20.0
    校验：0 + 0 + 15.4 + 3.0 + 1.57 + 20.0 = 39.97；39.97 + 0.03(历史) = 40.00

累计请求：已用 505（reservation/result 各 505），硬顶 1000 → 余 495；本候选计划要 30 次，
不重置、不提高硬顶。

## 成本中心（候选）与逐项上界

| 中心 | 额度 | 候选计划需要（最坏上界） | 成功估价 |
|---|---|---|---|
| answer_retrieval | 12.00 | 0.181440 | 0.036900 |
| ocr | 3.00 | 0.650000 | 0.650000 |
| judge | 3.00 | 0.037376 | 0.008000 |
| independent | 2.00 | 0.018688 | 0.004000 |
| 合计 | 20.00 | 0.887504 | 0.698900 |

单次上界来自冻结 caps/费率：chat 0.018688（6144×2 + 800×8）/1e6；embedding 0.002048；
rerank 0.0048；OCR text 0.5 / table 0.15。串行单次峰值预留 = 0.5（OCR 页），不是 0.018688。

## 有证据的中心调整建议（不在 T201 应用）

- 任务书 §4.1 给的 `ocr=3` 只够 **6 个 text 页**（6×0.5=3.0）。T204 的 B0 D07–D10 计划是
  **12 页/图调用**：若全部按精准文字识别计价 = 12×0.5 = **6.00 元**，超出 ocr 中心 3 元。
- 若含表格模板（0.15/页），例如 10 页 text + 2 页 table = 5.30 元，仍超 3 元。
- 候选建议（**需经理决定并写进正式 GO**，本包不应用）：
  `answer_retrieval 9 / ocr 6 / judge 3 / independent 2 = 20`（总额仍 20 元，不挪用历史余额），
  或维持 12/3/3/2 但把 OCR 页数压到 ≤6 页并显式说明覆盖收缩。
- 依据：OCR 单价为 Tencent 后付费最高档固定价（J2 已核来源），页数由 T204 的真实页计划决定；
  T201 不能用「猜低单页价」或「少算页」来凑额度。

## 候选 GO 的绑定

- `plan_sha256` 绑定候选计划的 `plan_sha256`（改计划即失效）；
- `budget_ledger_path` + `budget_ledger_sha256` 绑定仓库**真实**共享账本的不可变历史前缀
  （本机前缀 SHA-256 见下），因此候选 GO 与候选计划一起可过预检/授权，但
  `production_ready=False`（快照是推演）。
- 有效期候选 2026-11-10 → 2026-11-24（14 天，符合主人 §12 的「单次有效期 ≤14 天」）。

真实账本事实（生成候选时只读核对）：full SHA-256
`1f46d1b9e846528d5a1635db5175a997eab9da075d61a90a8cbf803f3fde7390`；历史前缀
`f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014`；预算文件 SHA-256
`084ba9acb4ee90379fd51fab8878f6dd4bab1bd481bff2a14c83057ffbc1cc58`。

## 如何使用

    # 只读预检（不预留、不发请求）
    pytest backend/tests/evaluation/test_p2_authorization.py -q

`test_candidate_artifacts_are_coherent_and_not_an_authorization` 会加载这四个文件，断言它们
能一起过预检/授权、且 `production_ready=False`；`test_candidate_budget_keeps_owner_arithmetic`
断言 20→40 的算术与历史保留。任何一项被改动都会让这两个用例失败。
