# R1-FINAL-CHAIN：修后真实 R1 同轮判定链（compat v0.6，继承 v0.5）

日期：2026-11-17。判定档：`p2-refusal-compat/v0.6`（主人当日批准，沿链继承 v0.5；默认与 v0.1–v0.5 逐字不变）。

## 1. 本轮运行身份（真实 H2，一次）

| 项 | 值 |
|---|---|
| run_id | `p2-h2v3-20261115-r1-base_b0_plus_v01` |
| run_index / 场景 / 业务日期 | 1 / `base_b0_plus_v01` / 2026-07-15 |
| 题 / 回合 | **8 / 10** |
| plan_id | `P2-H2V3-20261115-r1-base_b0_plus_v01` |
| plan_sha256 | `80d05194df5bb3d88a2850ec7b4417def55427a991004404d55538e0988cb543` |
| code_version | `94a8809e74db899f9db23496590abb9e8580a4689dc63a20934de52d873022f0` |
| case-plan SHA-256 | `acaf07c9efc4846d910b9f97df0359f4f86a88028b73b7e833ae34c85c4a28b9` |
| GO 内容规范化 SHA-256（回执 bindings.go_sha256） | `4bf0d479d2f89e4750c11081c590217b12ff7f296f09b78d2226494de1d6f5bf` |
| GO 归档文件字节 SHA-256 | `38f3c3f5dd6f2c828b66a3d96ee27d5a82ceed25ac49ecaba70ab7269c95fda3` |
| 证据树 SHA-256 | `f81e37b844eeb87f3a9044d4f297f09d481b77d29f2b67448f2020e1da27b6db` |
| 封存清单 SHA-256 | `5ea65c7a2c9534cda11f10b0a0927f6a1e3d99cae3bc6f3f4138ad51e84a34ec` |
| 真实发送 / 结算 | 28 / **0.083844 元** |
| 封存 | `sealed=true`、证据回读 ok、10 turn 文件 |
| 本轮计划上界 / 本轮实际预留（attempts_reserved） | 50 / 32 |
| 两轮账本新增预留 / 结果 | 64 / 64 |

## 2. 判定结果

| 判定 | 结果 |
|---|---|
| 质量 | **8 pass / 0 fail / 0 error** |
| 硬失败 | **0**（`hard_failures=[]`，逐题 `hard_failed=false`） |
| 四轴 | safety 1 passed / 7 N-A；cross_user 8 passed；cross_entity 7 passed / **1 unknown（C13）**；stale_source 8 passed；violation 0 |
| 必要轴 unknown | **1**（C13 cross_entity，原因 `free_text_attribution_unverifiable`，审计码 `shared_background_unproven`） |
| 一致性门 | `consistency_passed=true`；历史卡仅 `comparison_only`；四档（v0.1/v0.3/v0.4/v0.5）逐轴与本轮 v0.6 前结果一致 |
| 出站 | `outbound_allowed=0`、正对照成立；零重试 |
| T207 | **未通过**（30 题门槛 24/30 不适用于 8 题子集，`t207_passed=false` 属预期） |

> C13 的 1 个 unknown 是**契约限制**：契约 v2 §7 R-SB-4 规定 shared background 的运行期身份不可得；该案第 2 回合为政策题，使用层单元均为文档正文。主人 2026-11-17 决策：接受并按契约限制记录，不做进一步口径变更。

## 3. 证据位置

- 封存证据（仓外）：`D:\mktkb-p2-h2v3-20261117-r1\r1\{out,evidence,seal}`
- 本轮判定 JSON：`work/out-post2/recompute-v2-r1-post2-v06.json`
- 落盘汇总：`evidence/post-run2/03-final-chain/{quality-per-run-v2-compat-v06,final-summary-v2-compat-v06}.json`
- 逐案边界：`evidence/post-run2/02-case-boundary/`
- 首轮（仅 C13/C22 未收口）：`D:\mktkb-p2-h2v3-20261117-r1\attempt1-r1`（保留审计）

## 4. 与首轮的差异（新证据驱动，非重复付费刷分）

| 项 | 首轮（run1） | 本轮（run2） |
|---|---|---|
| 质量 | 8/8 | 8/8 |
| 硬失败 | 2（C13/C22 cross_entity） | **0** |
| 轴 unknown | 0（但硬失败 2） | 1（C13，契约限制） |
| 结算 | 0.084414 元 | 0.083844 元 |

两轮实付合计 **0.168258 元**；账本重算累计 24.7217539 / 40、阶段 P2-LIVE 9.6508094 / 20、预留/结果 **1940/1940 全配对**（ledger sha `3bc3839f…`）。

## 5. 经理材料更正（2026-11-17）

原表“50 / 34（两轮合计）”更正为本轮 50 / 32、两轮新增 64 / 64。GO 原值未错：`p2_authorization.py` 使用 `payload_sha256(go)` 对排序键、紧凑分隔符的 JSON 内容求摘要，故与文件字节摘要不同；经理复核归档内容规范化摘要与真实 run2 回执 `bindings.go_sha256` 一致。只核公开回执安全字段及 GO，未运行产品或真实请求，未改历史机器证据。
