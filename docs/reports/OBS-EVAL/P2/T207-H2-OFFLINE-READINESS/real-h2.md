# T207 真实 H2 四状态运行记录（2026-11-14，主人实时授权）

- 授权：主人 2026-11-14 指令“检查是否能跑 H2 测试，如果能就跑；所有决策你来安排，预算管够”。
  本次为该指令下的真实执行记录；不改变此前 T207 离线结论，也不等于 P2 质量通过。
- 结果：**四状态 run0–r3 全部 succeeded；30/30 题、36/36 回合 complete；**
  但 **`verified=false`、`threshold_met=false`、`release_ready=false`**，2 个 safety 硬失败、
  27 题缺证据、11 题质量 fail，cross_entity 仍有 27 unknown。真实质量仍待后续返工/复跑。
- 费用：账本结算合计 **0.2182299 元**（预算上限 40/阶段 20，未超）；累计请求余量充足；零重试。

## 1. 运行对象与身份

| 项 | 值 |
|---|---|
| 新私有计划 | `D:\mktkb-p2-t207-h2-20261114\plans2\run-binding.json`（4 run） |
| plan prefix / run prefix | `P2-T207-H2-20261114-r1` / `p2-h2-20261114-r1` |
| code_version | `f6c118432a73aa2541c78b9b33c08314bee462b1e1aa70c4391933625b2892ea` |
| config_sha256 | `9cb322863939522d5defb948b8739dd9385a3bf219c7291c5d1e916de3efbd65` |
| binding_sha256 | `291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4` |
| business_date | 2026-10-28（冻结 manifest） |
| 代码范围 | 当前工作树（含 T207 A/B/C 与 R11 修复）；未提交、未改产品业务代码 |

四个 run 的 plan/GO（GO 文件 SHA256；每 run 单独签发并绑定该 run 计划）：

| run | scenario | plan_sha256 | GO file sha256 |
|---|---|---|---|
| r0 | base_b0 | `932927a46dddf312c072269a8e82f4bad83c400741f0bcc6e8578ee2ea637755` | `946c428f3d4ca18e9231f63a7f2e454e983e2102d91fbe69b128ef657d663f7f` |
| r1 | base_b0_plus_v01 | `473d60ee631c407388cd13421c4c9fbd28c969ff3e6ae6808862dd934e45914c` | `312113123bf355ffbc2ce3ad68e132b30a6ca05cad89c7aaedd7756671b1932c` |
| r2 | pre_v05_without_v07 | `18e4335d84afa8d084e8f536c48f776e8d89bec7ad7ae6a434e380caa428d0e2` | `5749f2186d0c506cf77e231e068af62549660c10bff518ec06379500fb6e07df` |
| r3 | post_v05_without_v01 | `110c425384a31b8bbb33bea8b66efda81add7fe571f5f50bd006fcb8371c6f4a` | `c72dc7abf6ba135fb6c53f77c35b40dda34e97cf535d3be212467c6734b27324` |

- 旧 GO（`f688ec7e…`，任务书保护对象）已原样归档：
  `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.t207-h2-run-20261114.pre.archived.json`
  （SHA256 仍为 `f688ec7efb7e8ddc145ae9fd593a482a85a6e4a764a9d49a09eab4f3fc26ea98`）。
- 当前固定 GO = r3 GO（`c72dc7ab…`），绑定 r3 计划；r0/r1/r2 GO 分别归档为
  `P2-LIVE-GO.t207-h2-20261114-r0/r1/r2.done.archived.json`。
- `budget.json` 未改（`79b21700…`）；共享账本因真实花费已增长：
  `4d80d776…` → `ca9dceb9019790eb6ba4e25cfaf88232915b607d756d0eae21ad7cdf10c6fec9`。
  这是真实 H2 的合法副作用；旧 hash 已不适用于本 run，不能回写或掩盖。

## 2. 四状态结果（真实卡，`runs/rN/card.json`）

| run | 题/回合 | passed | failed | errors | safety 硬失败 | 缺证据题 | verified | threshold_met |
|---|---|---|---|---|---|---|---|---|
| r0 base_b0 | 26 / 32 | 18 | 8 | 0 | 1 | 24 | false | false |
| r1 base_b0_plus_v01 | 1 / 1 | 1 | 0 | 0 | 0 | 1 | false | false |
| r2 pre_v05_without_v07 | 2 / 2 | 0 | 2 | 0 | 1 | 2 | false | false |
| r3 post_v05_without_v01 | 1 / 1 | 0 | 1 | 0 | 0 | 0 | **true** | false |
| **合计** | **30 / 36** | **19** | **11** | **0** | **2** | **27** | **false** | **false** |

四轴合计（30 题 × 4 轴 = 120）：

| 轴 | planned | checked | passed | not_applicable | unknown | violations |
|---|---|---|---|---|---|---|
| safety | 30 | 27 | 1 | 24 | 3 | **2** |
| cross_user | 30 | 27 | 27 | 0 | 3 | 0 |
| cross_entity | 30 | 3 | 3 | 0 | **27** | 0 |
| stale_source | 30 | 25 | 25 | 0 | 5 | 0 |

关键解读：

- **四状态 run 能真实跑通**：32/32、1/1、2/2、1/1 回合全 `complete`，无超时/中止，无重试；
  写盘证据分别 32/2/3/2 份，seal/明文清理全通过。此前旧 run 的 `product_service_error` 未再出现。
- **质量未通过**：整体 `verified=false`、`threshold_met=false`、`release_ready=false`；
  2 个 safety 硬失败（r0、r2 各一）必须优先返工；11 题质量 fail。
- **cross_entity 仍大面积 unknown（27/30）**：真实私有 scope/targets 映射尚未生成；
  这是 B 包定义的“未来可信输入”缺口，不能用合成通过宣称旧 14 题已可判。
- r3 的 `verified=true` 仅限其 1 题场景，不能外推整体。
- `missing_evidence_cases=27` 与 cross_entity 的 27 unknown 基本同源（真实 scope 合同缺失），
  不是采集失败；采集/封存/重算链本身 36/36 complete。

## 3. 资金与调用

| run | attempts | success | failed | reserved CNY | settled CNY |
|---|---|---|---|---|---|
| r0 | 73 | 67 | 6 | 0.726016 | 0.1565696 |
| r1 | 12 | 11 | 1 | 0.043968 | 0.0197853 |
| r2 | 17 | 16 | 1 | 0.073600 | 0.0217320 |
| r3 | 15 | 14 | 1 | 0.047360 | 0.0201430 |
| 合计 | 117 | 108 | 9 | 0.890944 | **0.2182299** |

- 账本最终：`accounted_cny=22.203382799999936`，`p2_stage_accounted_cny=7.132438300000006`，
  `reservation_count=result_count=952`；四 run 均 `paired_one_to_one=true`、`duplicate_* =0`、
  `orphan_results=[]`、`prefix_binding_ok=true`。
- 阶段余额约 **12.8676 元**，累计请求已用 952/1100（余 148）；预算未触碰 40 元上限。
- 所有真实请求均为计划内 operations（answer/index_embedding/query_embedding/query_expansion/rerank），
  无 OCR 新增（OCR 历史占用 6.15 未再增长）。

## 4. 证据与安全

- 每 run：`runs/rN/out/controlled/case-plan.json`、`runs/rN/evidence/<run_id>/*.fernet`、
  `runs/rN/seal/<run_id>/seal-manifest.json`、`runs/rN/card.json`、`runs/rN/runN.stdout.log`
  （公开回执，不含题面/答案）。
- 四个 run 的 cleanup 回执均 `plaintext_clean=true`、`final_plaintext_scan.clean=true`、
  `needles=66`、`hit_count=0`；业务库/原件/索引在 close 后删除，仅保留密文与安全聚合。
- 真实私有材料只在本进程内解密使用；公开报告不列题面/答案/逐题 ID。
- 本轮**不再有** `release_ready=true`/`production_ready`/`REAL_READY` 声明。

## 5. 结论与下一步（不宣称通过）

1. **H2 能跑且已跑**：四状态矩阵真实完成，链路、封存、重算与资金配对均正常。
2. **质量未达标**：2 safety 硬失败 + 11 质量 fail + 27 缺证据；先做 safety 违规定位与返工，
   再生成真实 scope/targets 合同（B 包未来输入），然后才谈复跑。
3. 旧 4 fail/14 unknown 的历史结论**未被本轮清零或改写**；本轮是新计划/新 GO 的新鲜结果，
   不得与旧分数拼接。
4. 本轮 GO/账本已按真实花费变更；旧 GO 已归档、旧 hash 不回写。后续复跑需新计划/新 GO。
5. 本次不进入 T208/T209/T900；等待主人对 safety 返工、真实 scope 映射和是否继续复跑的裁决。
