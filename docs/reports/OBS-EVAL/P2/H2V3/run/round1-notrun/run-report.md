# H2 v3 真实基线执行报告（v3 真实基线执行者）

- 结论：**`NOT-RUN`**（r0 入口门在 `code_version` 复核处拒绝，**零请求、零金额**；按串行纪律停止，未装槽 r1..r3）
- 工作区：`D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存 0 项
- 计划/GO：`rollback-40` 版（`D:\mktkb-p2-h2v3-20261115\rollback-40\`），`max_requests=1137`，项目总上限 40 元
- 运行期显式环境：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=40`
- 全程未 stage/commit/push，未新建 worktree/切分支，未改 GO/预算/账本/计划/评测模块

---

## 1. 停止点与失败码

| 项 | 值 |
|---|---|
| 停止 run | `r0`（`p2-h2v3-20261115-r0-base_b0`） |
| 失败码 | **`code_changed_since_plan`**（入口固定码，exit 2） |
| 尝试次数 | 1（未重试） |
| 已花请求 | **0** |
| 已花金额 | **0 元** |
| 网络观察 | `network.external=[]`、`network.local=[]`（拒绝发生在读 `.env`、开真实门之前） |
| 后续 run | r1/r2/r3 未装槽、未执行 |

原始拒绝输出（逐字，`r0/attempt.json`）：

```json
{"command":"run","detail":"","error_code":"code_changed_since_plan","network":{"external":[],"local":[]},"ok":false}
```

---

## 2. 四 run 门检查（零发送，4/4 拒绝）

`check-only` 证据：`preflight/check-r0.json` .. `check-r3.json`（工具直出，零发送；r0 为全契约重载，r1..r3 为 `--plan-only`）。

| run | scenario | business_date | `ok` | `reasons` | `code_version` | `authorization.production_ready` | 请求已用/剩余 | 外部尝试 | 账本未写 |
|---:|---|---|---|---|---|---|---:|---:|---|
| 0 | `base_b0` | 2026-10-15 | false | `["code_version"]` | **false** | true | 952 / 185 | 0 | true |
| 1 | `base_b0_plus_v01` | 2026-07-15 | false | `["code_version"]` | **false** | true | 952 / 185 | 0 | true |
| 2 | `pre_v05_without_v07` | 2026-11-20 | false | `["code_version"]` | **false** | true | 952 / 185 | 0 | true |
| 3 | `post_v05_without_v01` | 2026-12-15 | false | `["code_version"]` | **false** | true | 952 / 185 | 0 | true |

> 资金/GO/账本侧是**通过**的（`production_ready=true`、`go_binding.ok=true`、`plan_recompute.ok=true`）；唯一失败项是代码身份与 binding 不一致。四份 binding 均绑定 `code_version=efe1c66e…`。

---

## 3. 四 run 结果表（题/回合/pass/fail/error/硬失败/四轴/请求/金额）

| run | scenario | 题 / 回合（计划） | 状态 | pass | fail | error | 硬失败 | 四轴计数 | 请求 | 金额（元） |
|---:|---|---:|---|---:|---:|---:|---:|---|---:|---:|
| 0 | `base_b0` | 12 / 14 | **NOT_RUN** | — | — | — | — | 未出数 | 0 / 64 | 0 / 0.63552 |
| 1 | `base_b0_plus_v01` | 8 / 10 | **NOT_RUN** | — | — | — | — | 未出数 | 0 / 49 | 0 / 0.460672 |
| 2 | `pre_v05_without_v07` | 5 / 6 | **NOT_RUN** | — | — | — | — | 未出数 | 0 / 35 | 0 / 0.287872 |
| 3 | `post_v05_without_v01` | 5 / 6 | **NOT_RUN** | — | — | — | — | 未出数 | 0 / 37 | 0 / 0.291968 |
| Σ | 4 | **30 / 36** | 0 执行 | — | — | — | — | — | **0 / 185** | **0 / 1.676032**（最坏情形） |

- 四轴（`safety` / `cross_user` / `cross_entity` / `stale_source`）：**未执行，无计数**；不填 0 冒充出数。
- `card.json` / `case-plan.json` / `run_manifest.json`：**未产出**。入口在写任何产物前拒绝，故不伪造空卡。逐 run 事实见 `r0..r3/status.json`。

---

## 4. 根因（已复算归因，不是猜测）

计划/binding 生成于 **2026-11-15 06:30:39**，绑定 `code_version=efe1c66e…`；此后 `fix-1r1` 于 **06:55:45** 修改了 `backend/src/mktkb/rag/query.py`（fix-1/A → R1，SHA `f73fc735…` → `82776def…`），当前代码摘要变为 `1e5930…`。

归因复算（`run/code-identity.json`）：把 `fix-1r1/independent/_pre_r1_query.py` 的字节代入 `query.py` 路径后，代码摘要**逐字节等于** `binding.code_version=efe1c66e…`；其他在范围源文件 mtime 均早于 06:30:39。

| 量 | 值 |
|---|---|
| binding 期望 | `efe1c66ef290b612650bbf9417dd9cf659b1f77b35cbf37c70b0bbd15d659a1c` |
| 当前树 | `1e5930664cb0fdd62ee5a4d9d7166b27688e9dbd3e70e1fa29c16145dc473002` |
| 代入 pre-R1 `query.py` | `efe1c66ef290b612650bbf9417dd9cf659b1f77b35cbf37c70b0bbd15d659a1c`（= binding） |
| 当前 `query.py` | `82776def986afa6defd37d75f6596a51dc1402fcdbe4725c7aa7d7d1ecc27fef` |
| pre-R1 `query.py` | `f73fc7353501e09e65a474fc2599fa4235e1db5d72fc4ea802e0e881f680c372` |

含义：`rollback-40` 计划集生成于 R1 之前；入口的代码冻结门按设计拒绝了“用旧计划跑新代码”。这不是工具故障，也不是资金/GO 问题。

---

## 5. 账本与预算（前后一致）

| 项 | 执行前 | 尝试后 |
|---|---|---|
| `live-ledger.jsonl` 文件 SHA-256 | `ca9dceb9019790eb6ba4e25cfaf88232915b607d756d0eae21ad7cdf10c6fec9` | 相同 |
| 行数 | 1905 | 1905 |
| reservation / result | 952 / 952 | 952 / 952 |
| 账本内链哈希（GO 绑定） | `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014` | 相同 |
| 累计已记账（总） | 22.2033828 元 | 相同 |
| P2-LIVE 阶段已记账 | 7.1324383 / 20 元 | 相同 |
| 请求余量（GO 1137） | 185 | 185 |
| GO 固定槽 | r0（40 元版）`dbc198c8…`，1183 B | 未换槽 |

---

## 6. 消耗 vs 硬顶

| 限额 | 本包 | 已用 | 状态 |
|---|---:|---:|---|
| 本包四 run 请求 | 185 | **0** | 未消耗 |
| 累计请求（GO `max_requests=1137`） | 1137 | **952** | 未增长 |
| 项目总额（40 元） | 40.00 | **0.00** | 未增长 |
| 单请求上限 | 0.50 | — | 未发生 |
| GO 阶段（P2-LIVE 20 元） | 20.00 | 0.00 | 未增长 |

---

## 7. 纪律合规

- 串行：仅 r0 一次尝试；失败后**立即停止**，未装 r1..r3 的 GO，未重试。
- 未改：GO/预算/账本/四份计划/30 题/标签/阈值/四状态/评分标准/评测模块/C 冻结 12/v2·v3 语料与密文。
- 未 stage/commit/push；未新建 worktree/切分支；暂存 0 项。
- 未把任何题面/答案写入公开产物；仓内新增仅安全聚合（路径、计数、哈希、固定码）。

---

## 8. 需要经理决策的选项（本执行者未擅自选择）

| 选项 | 内容 | 代价/风险 |
|---|---|---|
| A（推荐，已离线验证） | 以当前 R1 代码刷新四份 **binding**，计划与 GO 不动，再按现有 GO 串行跑四 run | 需经理授权“刷新 binding”；已验证四份 plan 逐字节不变、`plan_sha256` 不变（见 §8.1） |
| B | 将 `query.py` 临时还原到 pre-R1 `f73fc735…` 再跑 | 会重新引入 fix-1r1 刚关掉的 N2“纯指代假放行”，基线测的不是评审通过的代码；**不建议** |
| C | 以 R1 代码重新冻结计划+新 GO（新 nonce）再跑 | 最干净但改动最大，需新 GO/预算件 |

### 8.1 选项 A 的离线验证（shadow，未安装、未发请求）

在 `D:\mktkb-p2-h2v3-20261115\plans-shadow-r1` 用当前代码重生成了一套 shadow 计划/binding（`plan-private`，零发送；证据 `option-a-shadow-check.json`）：

| run | plan 文件 SHA-256 | 与 rollback-40 逐字节相同 | `plan_sha256` 与 GO 一致 |
|---:|---|---|---|
| 0 | `3f1c0014…` | true | true |
| 1 | `b1ba1ffc…` | true | true |
| 2 | `59ae317b…` | true | true |
| 3 | `989cdc94…` | true | true |

- 四份 **plan 文件逐字节不变**（`plan` 内不含 `code_version`），因此现有 GO 的 `plan_sha256` 绑定仍然成立。
- binding 的差异只有：`code_version`、`config.code_version`、`runs[0].evidence_bindings.code_version`、`…config_sha256`（因含 code_version）、`plan_file` 绝对路径、`binding_sha256` 自哈希；`config` 其余逐值相同。
- **shadow 计划集未安装、未替换 rollback-40、未换 GO 槽、未发任何请求**；是否采用由经理决定。

---

## 9. 残余

- 本包未产生任何真实请求/金额；四轴、pass/fail/error、硬失败均无真实数据，**不得**据此宣称任何质量结论。
- `r1..r3` 的 preflight 为 `--plan-only`（不加载私有数据集）；`code_version` 失败与 r0 全契约重载同码同因。
- 固定 GO 槽仍是 r0（40 元版）；r1..r3 的 pending GO 未动。
- shadow 计划集只存在于仓外 `D:\mktkb-p2-h2v3-20261115\plans-shadow-r1`，**未安装**；仓内仅记录其哈希与比对结论。
