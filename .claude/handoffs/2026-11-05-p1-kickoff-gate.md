# P1 开工门清单与 P0 遗留复核（PM，2026-11-05）

> 本文件是 PM 交接材料（不是交付物）。滚动更新到 2026-11-05 21:45：**PR #1 已合并 `083eaef`**、**P1-PRE-2 已签并验签通过（GO 有效期至 2026-11-30）**、PRE-3/PRE-4 完成、`_scratch` 已清理、**T100 已获批准**。剩余：**主人发令"开工"**。
> 边界：只读核对 + 获授权的 PR 合并 + 获授权的两个文件写入（含旧 GO 备份）+ `_scratch` 清理 + 只读验签 + 2 个定向测试文件；未派包、未建 P1 分支/目录/提示词、未跑全量 pytest（空闲内存 1.01GB，按 §11D 暂缓）、未调用真实模型、未 commit。

## 0. 需要主人做的事（对应第 8 节问题）

| # | 事项 | 门 | 状态（2026-11-05 21:4x 更新） |
|---|---|---|---|
| 1 | 定 P1 分支基线（PR #1 未合并） | G0 | ✅ 已完成：主人授权 PM 合并，2026-11-05 21:38 用 **Create a merge commit** 合并（`083eaef`，父 `8e44158`+`35815c3`）；P0 38 个交付 commit sha 原样保留；`main` 已同步；P1 自 `main` 建分支 |
| 2 | 签 `budget.json` + `S2-LIVE-GO.json`（清单见 §2） | P1-PRE-2 | ✅ **已签并验签通过**（2026-11-05 21:5x，主人授权 PM 写入；旧 GO 已备份 `S2-LIVE-GO-20261104.json`；详见 §10） |
| 3 | 确认 PRE-2 关键参数（§2.4 五项） | P1-PRE-2 | ✅ 全部按建议（stage=P1-RETRIEVAL、services=[rag]、max_requests=1000、max_request_cny=0.05、expires=2026-11-30） |
| 4 | D-3 兼容授权书面确认（§3） | P1-PRE-4 | ✅ **已确认**（2026-11-05：允许错误码/文案取值变化、字段结构不变） |
| 5 | §7.2 locator 口径怎么处理（§4.4） | P0 可选项 | ✅ 决策：**不回写 P0 设计文档**；T110 handoff 引用 `_index` #30/#35 追认口径 |

> 当前剩余动作：**仅剩主人发令"开工"**（T100 已批准，§11）；发令后 PM 自 `main@083eaef` 建 `p1/fix-retrieval`、派 T100 → T107 → …
> 节奏决定（主人）：**T111 pilot（10 题）跑完停一次**再放全量；**不提前开零 live 包**；**PRE-2 落盘后先等主人发令开工**。

## 1. 现场核对（2026-11-05 21:0x 实测，只读）

| 项 | 实测值 |
|---|---|
| 分支 / HEAD | 本地在 `p0/obs-eval` @ `35815c3`；`main` 已更新为 **`083eaef`**（P0 已并入） |
| PR #1 | **MERGED**（2026-11-05 21:38，merge commit `083eaef`，父 `8e44158`+`35815c3`）：https://github.com/Echo2580/mktkb/pull/1 |
| 远端 | `origin` 有 `main`/`p0/obs-eval`；**无** `p1/*` 分支；tag `v0.1-local-20261104` |
| 共享账本（BudgetLedger.summary 只读实测） | 累计占用 **15.0566296 / 20**；剩余 **4.9433704**；S2-DEV 已占 **15.0266296 / 18.4**；381 预留 / 381 结果 |
| 账本 sha | 整本 `ca48b09a…7deb1`；`historical_import` 前缀 `f4710b18…a014`（= 现 GO 绑定值，实测一致） |
| Holdout（PRE-1） | `questions.jsonl` sha `a8c8aa7f…6738`（30 行）、`labels.jsonl` sha `8f713a2a…c1bf`（30 行），与索引记录一致；未入库（`.gitignore` 覆盖 `docs/evidence/`） |
| P0 三项可选项 | 均未执行：`gate_v0_1.json status=unapproved`、无真实 baseline、P0 设计 §7.2 未回写 |
| P1 脚手架 | 均不存在：`fixtures/evaluation/{regression,holdout}.jsonl`、`docs/evaluation/gate_v0_2.json`、`observability/routes.py`、`docs/reports/OBS-EVAL/P1/` |

## 2. P1-PRE-2：预算划转 + GO 改版（清单；主人已授权 PM 代为写入，2026-11-05 21:5x 已执行）

### 2.1 算术（主人已定口径，实测可行）

```
当前：S1-DEV 0 + S1-IA 0 + S2-DEV 18.4 + later_shared_reserve 1.57 = 19.97；+历史 0.03 = 20.00
改后：S1-DEV 0 + S1-IA 0 + S2-DEV 15.4 + P1-RETRIEVAL 3.0 + later_shared_reserve 1.57 = 19.97；+0.03 = 20.00
实测佐证：S2-DEV 已占 15.0266296 ≤ 15.4（划转后仍剩 0.3733704，成立）；总上限不追加。
```

### 2.2 `docs/evidence/LOCAL-R1-20261101/budget/budget.json` 修订清单

只改两处，其余字段（`limit_cny` 20.0、`historical_conservative_accounted_cny` 0.03、`ledger`、`historical_sources` 等）原样保留：

1. `stages` →
   `{"S1-DEV": 0.0, "S1-IA": 0.0, "S2-DEV": 15.4, "P1-RETRIEVAL": 3.0, "later_shared_reserve": 1.57}`
2. `stage_revision` →
   - `revision`: 7 → **8**
   - `revised_at` / `revised_by`: 签发时刻 / 主人（或按实际签发记录）
   - `previous_stages`: `{"S1-DEV": 0.0, "S1-IA": 0.0, "S2-DEV": 18.4, "later_shared_reserve": 1.57}`
   - `change`: 新增 `P1-RETRIEVAL` 3.0：自 `S2-DEV` 18.4→15.4 划转，总分配仍 19.97（+历史 0.03=20），总上限不动。
   - `arithmetic`: `0 + 0 + 15.4 + 3.0 + 1.57 = 19.97；19.97 + 0.03(历史) = 20.00`
   - `retained`: 历史 0.03 与全部已发生占用（实测 15.0266296）保留，未清账、未重置。

### 2.3 `docs/evidence/LOCAL-R1-20261101/PM/S2-LIVE-GO.json` 修订清单

代码硬绑定该路径与 `document="S2-LIVE-GO"`（`live_authorization.py:40-42`），**只能覆盖同一文件**。

| 字段 | 现值 | 建议值 | 依据（代码实测） |
|---|---|---|---|
| `stage` | `"S2-DEV"` | **`"P1-RETRIEVAL"`** | 代码强制 `payload.stage == 请求 stage`（`:502`）；一个 GO 文件只能承载一个 stage |
| `authorization` | S2-DEV 文案 | 改为 P1 文案：仅 `mode=live + scope=retrieval_only`，服务仅 rag（embedding+rerank），不调 chat；零重试、串行、首个失败即停；超限拒绝 | 设计 §5/§8 |
| `issued_by` | 项目经理 lead 代表主人签发 | 主人（或按实际签发方式，见问题 2） | 字段仅要求非空 ≤200 字（`:506-508`） |
| `nonce` | `7add501b…` | **新生成 32 位十六进制** | 要求 ≥16 字符（`:509-511`） |
| `issued_utc` | 2026-11-04T11:30:10+08:00 | 签发时刻（ISO8601 +08:00） | — |
| `expires_utc` | 2026-11-05T23:59:59+08:00（**今晚到期**） | 建议 `2026-11-30T23:59:59+08:00`（或主人指定） | 必须晚于生效（`:514`） |
| `budget_ledger_sha256` | `f4710b18…a014` | **保持 `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014`** | 见 §2.4 坑 b |
| `scope.services` | `["rag","chat"]` | **`["rag"]`** | 设计 §8；chat 不再授权（P1 不生成答案） |
| `scope.stage_limits_cny` | `{"S2-DEV": 18.4}` | **`{"P1-RETRIEVAL": 3.0}`** | `:539-543` 必须含请求 stage |
| `scope.max_requests` | `600` | **`1000`**（代码上限，`MAX_GO_REQUESTS=1000`） | 见 §2.4 坑 c |
| `scope.max_request_cny` | `2.103552` | **`0.05`** | 设计 §8；T111 按此裁剪单请求批次 |
| `scope.bindings.rag` | 32 字段 | **整块原样保留**（provider/model/host/region/dimensions 等，逐字段不变） | T111 用 `assert_provider_binding` 核对 |
| `scope.bindings.chat` | 22 字段 | 可删（`services` 已不含 chat；保留也不报错） | `_parse_scope_bindings` 只校验服务名在允许清单 |

### 2.4 三个必须避开的坑（不照抄设计稿字面）

- **坑 a｜GO 是单阶段文档**：设计稿写"`stage_limits_cny` 增加 P1-RETRIEVAL"，但代码要求顶层 `stage` 与请求 stage 一致，`stage_limits_cny` 只读取该 stage。→ 必须把顶层 `stage` 改为 `P1-RETRIEVAL`。**代价：签署后 S2-DEV 产品 live（chat/rag 产品路径）不再被授权**；P1 期间无此需求（P1 只跑检索评测），同意即可。
- **坑 b｜账本绑定必须保持历史前缀哈希**：`refresh_request_limits` 在**每笔请求前**重验 `budget_ledger_sha256`（`:692-698`），有效方式是"整本精确哈希"或"`historical_import` 前缀哈希"（`:386-432`）。只有前缀哈希 `f4710b18…` 在账本继续增长后仍有效；若误写成当前整本 sha `ca48b09a…`，**第一笔 P1 事件写入后就会全面拒绝**。→ 保持 `f4710b18…` 不动（实测与当前前缀一致）。
- **坑 c｜请求上限 600 不够**：`max_requests` 是**全账本累计**口径（`:431` `reservation_count`，现 381）。设计稿按"83/600"估算已过期；P1 预计再需约 320–420 次（索引 embedding + 113 题 ×（1 embed + 1 rerank） + pilot/复跑余量），381+420≈801 > 600。→ 建议 **1000**（代码上限；仍不足时需再签 GO）。

### 2.5 环境与执行纪律

- 真实运行需 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`（否则默认 10 → 与 `budget.json.limit_cny` 不等，全部拒绝）。
- 旧 GO 覆盖前建议主人留档（如 `PM/S2-LIVE-GO-20261104.json`）；固定路径只认 `S2-LIVE-GO.json`。**PM 不碰原件、不 commit 账本/GO。**
- 签署后 PM 跑一次**只读**校验（预计零 HTTP、零账本写入）：JSON 可解析 → `load_live_authorization(stage="P1-RETRIEVAL", service="rag")` → `resolve_live_gate(...)` 收敛额度/请求上限 → 记录输出。校验通过才派单。

## 3. P1-PRE-4：D-3 兼容授权（待主人书面确认）

设计稿 §11 已记录 2026-11-04 口头授权，拆解稿 PRE-4 要求书面确认。请主人回一句等价确认（示例）：

> 确认 P1-D3：允许 P1 期间错误码与文案**取值**变化（T104/T106 需要），业务 API 请求参数与响应 Body 的**字段结构不变**；不因此视为行为回退。

T104/T106 开工前必须有这句；未确认前这两包不派（其余包不受影响，但按 §6 串行顺序 T104 在 T103 之后，实际不阻塞前面的 T107–T103）。

**主人书面确认（2026-11-05 21:1x）：已确认授权**（允许错误码/文案取值变化、字段结构不变；T104/T106 可开工）。

## 4. P1-PRE-3：P0 遗留项复核（PM 已完成）

复核方法：逐条对照 `_index.md` 遗留 #1–#38 + 只读核对代码/文档/证据/账本（未跑 pytest）。结论：**无阻塞 P1 开工的遗留项**；30 项可关闭/接受，8 项作为 P1 handoff 注意事项带上，1 个事项需主人决定（§7.2，与 #30-MEDIUM-1、#35 同一事项）。

| # | 结论 | 说明 / 承接 |
|---|---|---|
| 1 | 关闭 | 报告数字勘误已在 `review.md` §6 更正，历史文档瑕疵 |
| 2 | 接受 | amend 前证据快照，report 已披露 |
| 3 | 关闭 | `trace_schema_v0_1.md` L147 明示 `legacy_with_rag_candidates` 共用 legacy 规则；L182–186 reason-aware 表 |
| 4 | 接受 | 等价论证口径随 §11A 沿用（不重跑旧基线全量） |
| 5 | 带入 T111/T112 | `pipeline_version` 首次延迟 import 有秒级开销（P1 仍 run 级调用，T111 计时留意） |
| 6 | 带入 T111/T112 | `config_hash` 白名单需随真实 embedding 配置扩展；`token` 命名规则限制 `max_output_tokens` 类字段 |
| 7 | 带入 T111 | 内核 `_coerce_mode` 仍接受 `live`；T111 必须**显式校验 scope=retrieval_only**，不依赖内核拒绝 |
| 8 | 已知约束 | trace 当不可信输入（`annotate` 可覆盖启动字段），门禁沿用 |
| 9 | 关闭 | T006a 已加 `*_json` JSON 合法性校验 |
| 10 | 关闭 | `replayed`/status 优先级口径已定并实现 |
| 11 | 接受 | amend 前 stat 已由验收方补采 |
| 12 | 已知 | 测试写 `docs/evidence/` 属既有行为，不入 commit |
| 13 | 带入 T101–T106 | 改埋点后必须用 `set_path/set_outcome` 覆盖中间件默认值；中间件边界断言按 T003b 授权"最小修改、只增强" |
| 14 | 关闭 | T006a 按 outcome/error 过滤失败请求，不计产品成功样本 |
| 15 | 带入 P1 全量 | 既有 flake `test_g08_short_budget_cancels_inflight_model_call`（`test_chat.py:1012`）：遇 flake 定向复跑 1 次并记录，不重跑整套 |
| 16 | 关闭 | T003c/T003d 已按授权更新断言并留 diff 证据 |
| 17 | 关闭 | T003d reason-aware 契约修订 + T006a 按新表实现 |
| 18 | 关闭 | T003d 补 rerank 失败断言、注释更正 |
| 19 | 关闭 | T003d §5.11 落地（schema L182–186） |
| 20 | 关闭 | 执行异常由接续者收尾，单 commit |
| 21 | 关闭 | subagent 模式延续至 P1（一包一开发 + 一包一验收） |
| 22 | 关闭 | 旧指令（停止自动推进/不独立验收）已被当前 P1 指令覆盖 |
| 23 | 关闭 | 验收证据已入库（实测 150 个 tracked 文件） |
| 24 | 接受 | T003d `01-tdd-red.txt` 仍为 UTF-16（实测首字节 `FF FE`）；历史证据，不修 |
| 25 | 关闭 | 提速策略 A/C/D 已写入 project-manager §11，P1 默认全开 |
| 26 | 关闭 | T003d R1 定向复验 PASS |
| 27 | 部分带入 | `replayed` 跳过完整性已实现（`gate.py` L80）；commit 阶段异常注入仍未覆盖（T103/T104 若改 commit 路径需补） |
| 28 | 接受 | P0 暂停交接为历史记录 |
| 29 | 关闭 | 簿记入库 commit `9d52b7c` |
| 30 | 1 项待主人 | MEDIUM-1 `locator` 范围型口径未回写设计 §7.2（PM 追认在 `_index` #30/#35）；MEDIUM-2 已由 T005 fail closed（`runner.py:1028`）；MEDIUM-3 已在 T009 披露；LOW 接受 |
| 31 | 关闭 | 4 MEDIUM/5 LOW 均按 PM 裁决落地（软指标、拒答排除 error/service_error、unit_ids 真实归属、record_code fail closed、CaseResult 版本字段、分页与同 chunk nDCG 口径） |
| 32 | 关闭 | `hard_gate_min_sample` b0=32/badcase=13 已配置；`record_code`+空 `locator` → unknown/exit3；指标实测值已记录 |
| 33 | 带入 T112 | `GateConfig.to_dict` 仍输出旧 `min_sample` 键（LOW，T112 改 gate 配置时可顺手；不阻塞） |
| 34 | 关闭 | T006b 中断后由接续者完成 |
| 35 | 2 项带入 T112 + 1 项待主人 | `refusal_recall` 零样本 `status=pass` 展示误导 → T112；`calibrate_gate` per-stratum 需人工按最小非零 stratum 取值 → T112；§7.2 回写 → 主人；NOT-RUN 清单中 retrieval_only 由 P1 覆盖，其余留 P2 |
| 36 | 关闭 | PR #1 状态核对（OPEN、未合并，主人门） |
| 37 | 关闭 | 主人 G5 决策通过；P0 G6 收口 |
| 38 | 完成 | 本次开工门处理（本文件 §2–§5） |

### 4.1 写入后续 P1 handoff 的注意事项（8 项）

- T111：内核接受 `live` → 必须显式 `scope=retrieval_only`；`pipeline_version` 延迟 import 计时；`config_hash` 白名单随真实 embedding 配置扩展；GO 单阶段 + 账本前缀哈希 + 请求上限口径。
- T101–T106：埋点默认值必须覆盖；中间件断言只做"最小修改、只增强"；commit 阶段异常注入（T103/T104）。
- 全量：既有 flake 处理口径（§11A）。
- T112：`GateConfig.to_dict` 旧键、`refusal_recall` 零样本展示、per-stratum 校准。

### 4.2 需主人决定的事项

- **§7.2 `locator` 口径**：P0 设计 §7.2 仍写"解析到 0 个或**多个** unit → `GoldUnresolved`"，与 PM 2026-11-05 追认（`unit_key` 身份型严格唯一；`locator` 范围型返回 unit 集合）不一致。P1 T110 直接改 `gold.py`，验收会对照设计 §7.2 → 需先定口径（问题 5）。

## 5. G0 阻塞：P1 分支基线（PR #1 未合并）

- 设计稿 §1/前置门写"P0 合入 `main` 后 P1 才开工"；实际 PR #1 OPEN、未合并，主人指示不擅自合并。
- P1 代码依赖 P0 产物（`evaluation/`、`observability/` 等只存在于 `p0/obs-eval`；`main` 无）。分支基线必须先定，否则无法按"每包 1 commit、最后 1 个 PR"执行。
- 三个选项（详见问题 1）：A 先合并 PR #1 再从 main 建分支（推荐，最干净）；B 从 `p0/obs-eval` @`35815c3` 建 P1 分支 + P1 PR 以 `p0/obs-eval` 为 base（stacked，#1 合并后改 base）；C 从 `p0/obs-eval` 建分支 + P1 PR 直接以 main 为 base（会包含 P0 全部提交）。
- **主人决策（2026-11-05 21:1x）：选 A** ——先合并 PR #1，再从 `main` 建 `p1/fix-retrieval`。
- **已执行（2026-11-05 21:38，主人授权 PM）**：`gh pr merge 1 --merge` → PR #1 状态 MERGED，merge commit **`083eaef`**（父 `8e44158` + `35815c3`）；本地 `main` 已同步到 `083eaef`；P0 交付 commit sha 全部保留（未用 rebase/squash）。P1 分支基线 = `main@083eaef`。

## 6. 签完后 PM 的执行计划（草案，按主人指令执行）

1. 建 `p1/fix-retrieval`（基线按问题 1 决策）→ 建 `docs/reports/OBS-EVAL/P1/` 与 `.claude/handoffs/T1xx-*/`。
2. 串行：T107 → T101 → T102 → T103 → T104 → T105 → T106 → T108 → T109 → T110 → T111 → T112 → T113 → T114 → T900。
3. 每包：1 个开发 subagent（全新上下文）+ 1 个验收 subagent（全新上下文、证伪导向）；每包 **1 commit**；开发证据 `docs/reports/OBS-EVAL/P1/evidence/T<NNN>/`，验收复跑证据 `docs/reports/OBS-EVAL/P1/evidence/verify/T<NNN>/`；PM 只写 `.claude/handoffs/**`。
4. 除 T111（`live + retrieval_only`，且需 PRE-2 已签）外**零真实调用**；T111 零 chat 调用、零重试、账本/GO 硬绑定。
5. 全部完成后开 **1 个 PR** 交主人；PR #1 是否合并仍由主人决定；P0 三项可选项（阈值/baseline/§7.2）未得指令不执行。

## 7. G6 残余 housekeeping（低优先，待主人一句话）

- `.claude/handoffs/_scratch/` 仍在（T001–T007 子目录 + `p1-holdout-validate.py`；均被 `.gitignore` 覆盖、**未入库**）。按 PM 技能 G6 应删除；因删除不可逆，等主人确认后由 PM 清理（不影响 git 与证据链）。

## 8. 本次边界声明（滚动更新）

- 已做：只读核对（git/gh/文件哈希/账本只读汇总/代码审阅）；**获主人授权合并 PR #1**（merge commit）；生成 PRE-2 成品草稿（`p1-gate-drafts/`，未覆盖原件）；PM 材料未 commit。
- 未做：未派任何开发/验收包；未建 P1 分支、任务目录、P1 handoff/提示词；未跑 pytest；未调用真实模型/embedding/rerank/OCR；**未改 `budget.json`/GO/账本**；未改业务代码/fixtures；未读 `.env`。

## 9. 主人决策记录（2026-11-05，滚动更新）

| 事项 | 决策 |
|---|---|
| P1 分支基线（问题 1） | **A**：先合并 PR #1，再从 `main` 建 `p1/fix-retrieval` |
| PR #1 合并执行 | **主人 2026-11-05 授权 PM 执行**：已用「Create a merge commit」合并 → `083eaef`（父 `8e44158` + `35815c3`）；`main` 已同步；P0 38 个交付 commit sha 保留 |
| PRE-2 写入人（问题 2） | **A（授权 PM 写入）→ 已执行**：旧 GO 备份 + 两份成品写入原件 + 只读验签通过（§10）；`_scratch` 按主人授权已清理 |
| PRE-2 参数（问题 3） | **全部按建议**：GO `stage=P1-RETRIEVAL`、`services=["rag"]`、`max_requests=1000`、`max_request_cny=0.05`、`expires_utc=2026-11-30T23:59:59+08:00`、`budget_ledger_sha256` 保持 `f4710b18…a014`；budget `S2-DEV 15.4` + `P1-RETRIEVAL 3.0`（总 20 不变） |
| PRE-4 D-3（问题 4） | **已书面确认授权** |
| §7.2 locator 口径（问题 5） | **不回写设计文档**；T110 handoff 引用 `_index` #30/#35 追认口径 |
| T111 放行节奏 | **pilot（10 题）跑完停一次**给主人过目，再放全量（主人 2026-11-05） |
| 零 live 包提前开 | **不提前开**（主人 2026-11-05） |
| 开工时点 | **先等主人发令**（主人 2026-11-05）：落盘 + 验签完成后 PM 待命，不动分支不派包 |
| P0 可选项 / `_scratch` | ✅ 三项继续冻结 + `_scratch` 已清理（主人 2026-11-05） |
| T100（新增前置小包） | ✅ **已批准**（2026-11-05；§11；待主人发令开工后派单） |
| 子智能体模型 | **B（主人 2026-11-05）**：开发/验收均 `wb / cn:deepseek-v4.1-flash`，**推理档统一 `max`**（主人 2026-11-05 追加）；详见 §12 |

> 下一步顺序（PM）：① 主人批准 T100 → ② 主人发令"开工" → ③ PM 自 `main@083eaef` 建 `p1/fix-retrieval` 与 P1 目录 → ④ 派 T100（修基线上耦合测试）→ ⑤ 派 T107（一包一开发 + 一包一验收 subagent）。

## 10. PRE-2 签署记录与验签结果（2026-11-05 21:5x）

**授权**：主人选择「A 授权 PM 写入」（2026-11-05）。PM 未改动原件之外的任何文件；**未 commit**（`.claude/handoffs/**` 与 `docs/evidence/**` 均未入库；后者被 `.gitignore` 覆盖）。

**落地动作（全部为本地文件，不入 git）**：

| 动作 | 结果 |
|---|---|
| 旧 GO 备份 | `docs/evidence/LOCAL-R1-20261101/PM/S2-LIVE-GO-20261104.json`，sha256 `63d60b0a…1c0a`（= 原 S2-DEV GO 原样） |
| `budget.json` 写入 | sha256 `084ba9ac…cc58`（= 草稿，与 `p1-gate-drafts/budget.json.proposed` 一致） |
| `S2-LIVE-GO.json` 写入 | sha256 `39070de5…1df4`（= 草稿，与 `p1-gate-drafts/S2-LIVE-GO.json.proposed` 一致）；nonce 32 hex、`expires_utc=2026-11-30T23:59:59+08:00` |
| `_scratch` 清理 | 按主人授权删除 `.claude/handoffs/_scratch/`（45 个 gitignored 未入库文件）；工作树仍只有 PM 材料 |

**只读验签（零 HTTP、零账本写入；原始输出 `p1-gate-drafts/gate-validation-20261105.txt`）**：

- `load_live_authorization(stage="P1-RETRIEVAL", service="rag")`：通过。stage=`P1-RETRIEVAL`、limit=3.0、max_requests=1000、max_request_cny=0.05、expires=2026-11-30、账本绑定 `f4710b18…a014`、bindings.rag 32 字段齐全。
- `resolve_live_gate(...)`：通过。收敛后 stage_limit=3.0、max_requests=1000、total_limit=20.0。
- 账本只读汇总：accounted 15.0566296 / 20，剩余 4.9433704；**P1-RETRIEVAL 已用 0 / 额度 3.0**；381 次预留。
- 负例：`service="chat"` 被拒（GO 未授权 chat）；`stage="S2-DEV"` 被拒（单阶段 GO 已换为 P1-RETRIEVAL）。→ 符合设计：P1 不许 chat、S2-DEV 产品 live 随旧 GO 退役。
- 账本 sha 验签前后一致（`ca48b09a…7deb1`），确认零写入。
- `budget.json`：stages = `{S1-DEV 0, S1-IA 0, S2-DEV 15.4, P1-RETRIEVAL 3.0, later_shared_reserve 1.57}`；合计 + 历史 0.03 = 20.00。

**后续运行注意**：T111 真实运行必须显式 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`（否则默认 10 与 budget 不符，全部拒绝）——写入 T111 handoff。

## 11. 新增 G0 项：基线测试耦合旧真实配置（待主人批准 T100）

**现象（已实测）**：签名后定向运行 `backend/tests/rag/test_s4_stage_limit.py` → **1 failed**：

- `test_current_go_and_budget_are_consistent_and_above_three_yuan`：`KeyError: 'S2-DEV'`（该测试直接读**真实** `S2-LIVE-GO.json`/`budget.json`，把"当前真实配置"硬编码为 `S2-DEV=18.4`）。
- 证据：`p1-gate-drafts/baseline-impact-20261105.txt`；同跑 `backend/tests/unit/test_s2h_r3_official_profile.py` 通过（两文件合计 21 passed / 1 failed）。
- 这是**签名导致预期变化**打破旧断言，不是代码缺陷；但 P1 每包"全量 pytest 无新增失败"门禁会从第 1 包起带 1 failed，必须先修。

**建议（推荐 A；主人 2026-11-05 已批准 A）**：

- **A. 新增前置小包 T100**（只改 `backend/tests/rag/test_s4_stage_limit.py` 1 个测试，1 commit，约 5–10 分钟）：断言改为"当前真实 GO 与 budget 互相一致（GO 里的 stage 额度 == budget 同 stage 分配）+ P1-RETRIEVAL=3.0 + S2-DEV 分配 15.4 仍 ≥ 已占 15.0266296 + 总额 19.97+0.03=20"，保留测试意图、不削弱覆盖；完成后 T107 起跑。
- B. 并入 T107（放宽 T107 允许文件到该测试）——不新增包，但 T107 边界变宽，不推荐。
- C. 跳过该测试——违反"不放宽断言"纪律，不推荐。

**未做**：全量 pytest 未跑（空闲内存 1.01 GB < 2 GB，按技能 §11D 暂缓）；定向运行已足以定位。开工前建议主人释放内存，P1 首个全量前 PM 再确认。

## 12. P1 子智能体模型策略（主人 2026-11-05 定）

| 角色 | provider | model | reasoning_effort |
|---|---|---|---|
| 每包开发 subagent | `wb` | `cn:deepseek-v4.1-flash` | **`max`** |
| 每包验收 subagent（全新上下文） | `wb` | `cn:deepseek-v4.1-flash` | **`max`** |
| **T111 开发 subagent**（live + retrieval_only，最高风险包） | `wb` | `cn:deepseek-v4.1-flash` | **`max`** |

- 主人 2026-11-05 指令：**推理档一律用 `max`**（原建议的"开发默认档/验收 high"作废）。
- 实现方式：`subagent(provider="wb", model="cn:deepseek-v4.1-flash", reasoning_effort="max", ...)`；T900 总验收同样 `max`。
- `subagent_fork` / `spawn_teammate` 不支持指定模型（P1 按计划用 `subagent`，不受影响）。
- **与项目预算无关**：子智能体推理走 harness 侧，不写 20 元项目账本、不触发 GO 闸门。
- 可追溯性：每包 `handoff.md`/`report.md`/`review.md` 记录实际使用的 provider/model/effort，验收方核对与本节一致。
