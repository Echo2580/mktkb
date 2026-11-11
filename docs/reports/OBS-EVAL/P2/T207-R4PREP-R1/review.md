# P2-T207-R4PREP-R1 独立复验（review）

- 角色：R4PREP-R1 独立复验助手（全新上下文）。**零真实调用**（未起服务、未跑 p2-run/p2-score、未跑产品探针）、
  零网络、零 commit；未读 `.env`/H1/H2；只写本目录（`review.md`、`evidence/verify/`）。
- 现场：分支 `codex/p2-e2e`，HEAD **`1dca413`**（复验前后未变；无新 commit、无 staged 改动）。
- 只读事实（复核前后逐值一致）：账本 `05b54d06…`（1,354,211 B / 1383 行 / **691 reserved / 691 result**）、
  预算 `79b21700…`、固定路径 GO `3ed427f4…`（H2 GO，未被创建/修改）；阶段占用 **6.5409604**、
  中心 `answer_retrieval 0.3909604 / ocr 6.15`、项目总占用 **21.6119049**。

## 0 判定摘要

| # | 检查项 | 判定 | 一句话 |
|---|---|---|---|
| 1 | 范围：只改 T207 文档；plan/case/ingest/GO/源码/测试/夹具/账本/预算/固定 GO 未变；零真实；无 commit | **PASS** | 15 条产物/账本快照与 R4PREP 验收时**逐字节相同**；窗口内只有 3 个文档 + 本包目录被写 |
| 2 | F-1..F-6 闭环表述准确（含 0.04096 前置、fail-closed 码、R2 让 C05/C06 fail→pass、F-3 裁定、HEAD、删除错误表述、F-6 四子项） | **PASS** | 六项逐条与提交/验收/代码/证据对得上，未发现夸大或错引 |
| 3 | 数字一致性（cost §8 六个数、runbook §3.2 的 0.04096 与 GO 下限、§4 稳定码名） | **PASS** | 我用契约模型 + 自写账本解析器复算全部逐值一致；仅"余"列基准混用（F-10） |
| 4 | runbook 可执行性（§1 编号、§3.2 前置、§9 例外、R4/H2 命令） | **PASS** | 检查项全过；但 §1.1 期望账本 SHA 过期会挡住 R4（F-7）、跑后检查项 `index_status.degraded` 不可读（F-8） |
| 5 | 合规与限制（零真实、未读凭据、残留如实、无新增矛盾） | **PASS** | 残留四项原样保留；新发现均为文档小项，无安全/资金面矛盾 |

**总判定：接收（阻断 0）。** 本包只做文档收口，F-1..F-6 的闭环表述与全部数字经独立复算成立；
7 条文档小项（F-7..F-13）不改变"计划/请求形状/操作集合"任何事实，也不放宽任何闸门。
其中 **F-7、F-8 建议在签 R4 GO 之前修掉**（一条会让按本执行的 R4 在 §1.1 停，一条指向不存在的字段），其余可随手改。

## 1 逐条判定

### 1 范围 — PASS

- 本包声明改动面（`T207-R4PREP-R1/report.md` §1）= 4 个文档：`T207/report.md` §9、`PM/T207-runbook.md`、
  `PM/T207-cost-and-quota.md` §8、本包 `report.md`。写入时刻 06:20:25Z / 06:21:08Z / 06:22:13Z / 06:22:18Z，
  与本包 report 的改动清单逐条对得上（行号亦对：`report.md` 89–91 / 126–132 / 141–149 / 152–156 / 158–183 / 208–226、
  `runbook` 125–138 / 150 / 356 / 359–377、`cost` 227–235 / 237–249 全部落在所写行段）。
- **plan/case/ingest/GO 未变**：用 `T207-R4PREP/evidence/verify/package-hashes-after.json` 的 15 条快照逐字节比对当前文件
  ⇒ `changed=[]`（`evidence/verify/verify_r1.out.json` 的 `scope`）。其中：
  plan `d68db207…`、cases `c04b67c6…`、ingest-plan `07c2694b…`、候选 GO `7903dd66…`、`document-codes.json` `3ac6a4eb…`、
  账本 `05b54d06…`、预算 `79b21700…`、固定路径 GO `3ed427f4…` —— 与验收时**完全相同**。
- **计划内容哈希**独立重算：`P2RunPlan.from_dict(plan).plan_sha256 = 00b9fdefd8cc…b5d2b9`（与文档、与 GO 绑定三方一致）；13 项 / 18 请求 /
  `max_requests=760` / worst `0.14496` / `reserve_peak=0.018688` / `page_count=0` / 五操作（无 ocr）。
- **未改源码/测试/夹具**：窗口内 `backend/**`、`fixtures/**` 零写入（LIVECAP 的最后写入 06:00:09Z，早于本包）。
  工作区 tracked 改动只有 5 个文件，其中 3 个属本包、`.claude/handoffs/_index.md` mtime 为 2026-11-10T17:43Z（早于本包）。
- **零真实（可证的那一半）**：任何真实发送都先在共享账本留 reservation ⇒ 账本 sha/字节/行数与验收快照逐字节相同 ⇒ 本包期间**不可能有真实发送**。
  另：`post_counters` 类证据未新增，本包也未跑 `p2-run`。
- **无 commit**：HEAD 仍 `1dca413`，`git diff --cached` 为空。
- **归因备注（F-12）**：`PM/T207-PM-decisions-01.md` 的 mtime 是 06:22:46Z（与本复验任务书 06:22:46.278Z 同刻），内容是经理决定日志
  §11/§12（含 F-3 裁定、R4PREP 验收记录）⇒ 经理侧追加，不是本包交付面。本包 report 写"该文件未改"在"本包没改"这层成立，
  但工作区 git 会把该 tracked 文件显示为已改，建议报告里补一句归因（见 F-12）。

### 2 F 项闭环准确性 — PASS

证据：`T207-FIX-LIVECAP/{report,review}.md`、`T207-FIX-CONFLICT-R2/{report,review}.md`、
`backend/src/mktkb/evaluation/p2_live.py:341-429`、两个提交的 `--name-only`、`evidence/r4-ingest-state.json`、`evidence/validate-r4-out.txt`。

| 项 | 文档写的 | 我核到的 | 判定 |
|---|---|---|---|
| F-1 | LIVECAP（`1dca413`）+ 验收"接收（阻断 0）"；`page_count=0` ⇒ effective **0.04096**；GO 的 `max_request_cny` 必须 ≥ 0.04096；不足则装配期 `live_request_ceiling_insufficient`（零发送/零预留/零降级/无产物） | 提交存在且只碰 `p2_live.py`/`product_adapter.py`/测试/文档；`resolve_request_ceiling` 规则 = `max(计划峰值, 各 provider 单次预留)` 且 ≤ `authorization.max_request_cny`，不足即抛该码；我用真实 `RagConfig` 跑：bounds = embedding **0.04096** / rerank 0.024 / chat 0.018688，GO=0.5 ⇒ effective **0.04096**；GO=0.04096 放行、0.040959 抛 `live_request_ceiling_insufficient` | ✓ |
| F-2 | R2（`24f9cde`）使冻结评分下 C05/C06 fail→pass、N08 不变；**计划/case/GO 不变**；§9.3 改写为"历史读数 + 修复后可达" | R2 提交只碰 `conversations/service.py`、`copy.py`、1 个新测试、其证据与报告（`--name-only` 里无 `/PM/`、无 `/cases/`、无固定 GO）；其 review §0 判 3/4 明写 C05/C06 `value_hit fail→pass`、54 例差分仅 {C05,C06}；§9.3 现有"历史 `489aadd`（两形状都 value_hit fail）+ R2 后三例 pass"两段，并标注 `r4-ingest-state.json` 为修复前读数 | ✓ |
| F-3 | 裁定原文："只改产品输出文本、不改计划内容 ⇒ `plan_sha` 不变 ⇒ 不重签计划，GO 仍按流程签发"，judge 面 = 计划项/请求形状/操作集合/证据链 | runbook §9 L366–370 与 report §9.5 L219–222 两处同文；runbook §9 L371 仍保留"因计划/请求形状变更而重跑 = 新计划 + 新 GO"；L374–376 另说 GO 的 `max_request_cny` 门槛，未把"改 GO"纳入例外 | ✓ |
| F-4 | 交付时 `489aadd`、当前基线 `1dca413`，并注明 `24f9cde`/`1dca413` 已提交 | `git log`：`489aadd` → `24f9cde` → `1dca413`，HEAD=`1dca413`；report L89–91 逐句相符 | ✓（引用小错见 F-11） |
| F-5 | 删掉"挡住 R4 的不是接线"，改写成"当时确有 F-1 接线阻断，已由 LIVECAP 修掉" | report §9.2 L152–156 现文即此意；`§4` 停止规则已补 `live_request_ceiling_insufficient` | ✓ |
| F-6 | ①12 负例=11 码（`go_max_requests_below_plan` 两次：600/10）；②`requests_over_remaining`→`request_budget_insufficient`；`center_below_plan_need` 在**计划构造期**即 `center_budget_exceeded`、未覆盖 preflight 中心窗口码；③`C05.forbidden=[V03]`/`C06.forbidden=[V06]` 不可命中（`document-codes.json` 无 V03/V06）；④`B_r4=6` vs 上界 9 | `validate-r4-out.txt` 的 12 行负例码集合 = 11 个唯一码，两次 below_plan 分别打 600/10；脚本 `validate-r4.py:252-257` 里 `center_below_plan_need` 的 `P2RunPlan.from_dict` 先行抛 `center_budget_exceeded`（construct-time）；`document-codes.json` 12 键中**无** V03/V06（V03 是 D01 槽版本、V06 不在灌库包）；`r4-ingest-state.json`: `batches_B=6`、`batches_B_upper_bound=9`、`crosscheck_r2_r3.matches_live={R2:true,R3:true}`（账本 R2=4/R3=2 我另行复算一致） | ✓ |

### 3 数字独立复算 — PASS

自写解析器（`evidence/verify/verify_r1.py`）不复用开发方结论：

| 项 | 文档值 | 我的复算 | 判定 |
|---|---|---|---|
| 账本/预算/固定 GO sha | `05b54d06…` / `79b21700…` / `3ed427f4…` | 同（1,354,211 B / 1383 行 / 691 reserved / 691 result） | ✓ |
| R1 / R2 / R3 请求 | 129 / 10 / 5（合计 144） | 129 / 10 / 5 | ✓ |
| R1 / R2 / R3 结算（元） | 5.9473320 / 0.0207119 / 0.0015582（合计 5.9696021） | 逐值相同 | ✓ |
| 累计请求 | 547 + 144 = **691**，R4 后 **709 ≤ 1600** | 547 = 505（历史）+42（pilot），691；+18 = 709 | ✓ |
| 阶段占用 | 6.5409604 → **6.6859204 ≤ 20** | 5.9696021+0.5713583 = 6.5409604；+0.14496 = 6.6859204 | ✓ |
| 项目总占用 | 21.6119049 → **21.7568649 ≤ 40** | 15.6423028（=S2 15.0266296+P1 0.0143149+P2 0.5713583+历史 0.03）+5.9696021 = 21.6119049；+0.14496 | ✓ |
| answer_retrieval 中心 | 0.3909604 → 0.5359204 ≤ 8.5 | 0.3909604（P2-LIVE embedding+rerank+chat）+0.14496 | ✓ |
| 计划 worst-case | 0.144960（18 请求） | Decimal 逐项：6×0.002048+3×0.002048+3×0.0048+3×0.018688+3×0.018688 = 0.144960 | ✓ |
| 单次上界公式 | embedding 0.002048 / rerank 0.004800 / chat 0.018688 | 4096×0.5/M、6000×0.8/M、6144×2/M+800×8/M | ✓ |
| R4 生效单请求上限 | effective 0.04096（81920×0.5/M） | 0.04096；GO 边界 0.04096 放行 / 0.040959 拒 | ✓ |
| §4 稳定码名 | `live_request_ceiling_insufficient` | `p2_live.py:419` 源码同名 | ✓ |

- B_r4 的方法学自证也复算过：`r4-ingest-state.json` 每次待嵌入文本 9/1/1/4/1 ⇒ Σceil(/5)=6；R2 计划同法=4、R3=2，
  与账本 `ingest-index-embedding` 预留数（我从账本按 run 数得 4/2）逐值相等。
- 唯一数字问题：cost §8.3「判定」列的**余量基准混用**（F-10）。

### 4 runbook 可执行性 — PASS（附 F-7/F-8）

- §1 编号：1→2→3→4 顺序正确（L7/L8/L10/L13），第 4 项内容与计划事实一致（13 项/18 请求/worst 0.144960/760/无 OCR）。
- §3.2：标题与计划一致；前置 1（R2 文案闭环、不重签）与前置 2（effective 0.04096、GO ≥ 0.04096、fail-closed 码、
  历史后果 `aborted(product_service_error)` + 账本 1 次 chat 预留 `failed/INDEX_NOT_READY`）**逐项与代码/LIVECAP 验收对得上**；
  H2 同形（H2 计划 `page_count=0`、H2 候选 GO `max_request_cny=0.5`，我核对了两份 JSON）。
- §9：文案-only 例外被限定在"只改产品输出文本、不改计划内容（计划项/请求形状/操作集合）"，且 L371 仍要求形状变更走"新计划 + 新 GO"，
  **没有误伤**新计划/新 GO 规则；§10 的"重跑 = 新计划 + 新 GO"也未被放宽。
- R4 命令可执行：`p2-run` 确有 `--plan/--out/--cases/--ingest-plan(--ingest 互斥)/--mode{dry-run,live}/--run-id/--dataset-version/--label-version`；
  包装器 `tools/p2_live_execute.py --env-file … -- p2-run …` 的参数形态与其 `--env-file` 语义一致（拒名 `.env`）。本包改文档未使命令失效。
- **F-7（应修）**：§1.1 期望账本 `6b053520… / 1,050,298 B`（= R1–R3 跑前的 T207 准备态），当前是 `05b54d06… / 1,354,211 B`。
  §1 声明"每次执行、任一不符即停"，§4 规则 1 也据此停 ⇒ 照本执行 R4 会在第一步被自己挡住。建议改成当前基线，
  或标明"§1.1 期望值为 R1–R3 前基线，R4 用 `05b54d06…/1,354,211 B`"。§3.1 表里的 547/553/568 是历史读数，同理。
- **F-8（建议修）**：§3.2 末条"跑后先看 `summary.json` 的 `providers.live.request_ceiling.effective_max_request_cny` = 0.04096 且
  `index_status.degraded` 为空"——前半个字段成立（`p2_live.py:1229` 的 `wiring.as_dict()` 会带 `request_ceiling`），
  但 `index_status`/`degraded` **不在** `summary.json`，也不在 `run_manifest.json`（runner 只把 documents/units/chunks/provider_mode/engine_version
  抄进 `pipeline.index`，见 `p2_runner.py:2190-2297`；R1 真实产物里 grep 无 `index_status`/`degraded`）。建议改为
  "`run_manifest.json` 的 `pipeline.index` 与 `ingest` 回执 + `summary.providers.live.request_ceiling`"。

### 5 合规与限制 — PASS

- 零真实：见 §1（账本逐字节未变是最强证据）；本包也未触碰任何 provider 配置。
- 未读 `.env`/H1/H2：仓库根无 `.env`；本包 report 与证据里无 H2 题面/case_id；`runbook` 的 H2 段未被改。
- 残留如实保留（4 项，逐条核对未删减）：① 修复后可达性只有 Mock 证据、live 从未观测到 `conflict`（R2/R3 的 `actual=answer`）；
  ② `C05.forbidden=[V03]`/`C06.forbidden=[V06]` 不可命中，pass 不证明检查有效；③ `B_r4=6` 无安全余量（多 1 POST 即 `attempt_quota_exhausted`）；
  ④ HEAD/口径类历史标注（`489aadd` 读数不当作现状）。
- 无新增矛盾（除 F-7..F-13 七条文档项）：report §9.3 / §9.5、runbook §3.2 / §9、cost §8.4 三处对"不改计划、不重签 GO、0.04096 前置"的表述一致；
  §9.3 与 cost §8.4 同为"历史 + 现状"两段式，未互相打脸。

## 2 发现（按严重度）

| # | 级别 | 位置 | 问题 | 建议 |
|---|---|---|---|---|
| F-7 | P2（执行阻断，非本包引入） | `runbook` §1.1 L31 | 期望账本 `6b053520…/1,050,298 B` 已过期（现 `05b54d06…/1,354,211 B`）；按 §1/§4 规则 1，R4 会在第一步停 | 改为当前基线（或写明"R1–R3 前基线"），§3.1 的 547/553/568 同步标注为历史 |
| F-8 | P3 | `runbook` §3.2 L137–138 | 让读者去 `summary.json` 找 `index_status.degraded`，该字段不在 `summary.json`/`run_manifest.json` | 改指 `run_manifest.pipeline.index` + `ingest` 回执；`request_ceiling` 那半保留 |
| F-9 | P3 | `runbook` §9 L361、`report` §9.3、`cost` §8.4 | `product_adapter.py:2137` 在 `489aadd` 正确，LIVECAP 之后该语句在 **2156**（+19）；同行段 `1999-2028` 整体漂移 +17~+19（`async def ask_turn` 2003→2020）；`scorers.py:632` 仍正确 | 行号后加"（`489aadd`）"或改为 2156（并把 `1999-2028` 改成对应新行段或标注 `489aadd`） |
| F-10 | P3 | `cost` §8.3 判定列 | 余量基准混用：请求 891 = 1600−709（R4 后），而阶段 13.4590、项目 18.3880 是 **R4 前**余量；R4 后应为 **13.3140796** / **18.2431351** | 统一为 R4 后，或加一列"R4 前余量" |
| F-11 | P3 | `report` §9.5 F-4 行 | 引用"§9.0 更正"，报告无 §9.0 标题（HEAD 更正段在 §9 首部 L89–91） | 改指 §9 首段 |
| F-12 | P3 | `report` §3 末条 | 写"`PM/T207-PM-decisions-01.md` … 未改"，但该 tracked 文件工作区已改（经理 06:22:46Z 追加 §11/§12） | 补一句"该文件的改动属经理侧追加，非本包交付面" |
| F-13 | P3（文案） | `runbook` §3.2 / §9 | §3 下只有"### 3.2"、没有"### 3.1"；§9 L356 的"见下条「重签口径」"实际隔了一条 bullet | 给公开三 run 加 `### 3.1` 标题；"下条"改"§9 下文「重签口径」" |

## 3 复跑（零真实调用；只读）

```powershell
# 我的独立探针（只读：契约模型 + 自写账本解析 + RagConfig 的 ceiling 推导 + 提交面 + 行号漂移）
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207-R4PREP-R1\evidence\verify\verify_r1.py
```

| 证据 | 内容 |
|---|---|
| `evidence/verify/verify_r1.py` | 本次复验全部检查的实现（不 import 开发方探针；只读） |
| `evidence/verify/verify_r1.out.json` | 15 条 sha 比对（`changed=[]`）、计划逐值、GO 绑定、cases/ingest、账本分 run/分中心、§8 算术（含余量基准）、ceiling 边界、行号漂移、提交面、字段存在性 |
| `evidence/verify/workspace-window.json` | 本包写入窗口（4 个文档时刻）、tracked 改动清单、`PM/T207-PM-decisions-01.md` 的归因说明、R4PREP 交付物最后写入时刻 |

## 4 限制

1. 未重跑开发方脚本（`build-r4.py`/`validate-r4.py`/`r4-ingest-probe.py`）与 `p2-run` dry-run：它们会重写同一批文件或写仓库外产物；
   本次以"15 个产物 sha 与验收快照逐字节相同"替代"可复现"这一环，再用自写探针复算数字。
2. "零真实"以"账本逐字节未变"作证（任何真实发送必先留 reservation）；无法从外部证明网络层零出站。
3. 未读 `.env`/H1/H2，故 H2 侧只核了计划模板（`page_count=0`）与 H2 候选 GO（`max_request_cny=0.5`），未核 H2 数据面。
4. 行号漂移（F-9）只对 `product_adapter.py` 做了精确核对（`text=str(payload.get("text"))` 2137→2156；`async def ask_turn` 2003→2020）；其他文件的行号未逐一复查。

## 5 最终建议

**接收（阻断 0）。** 本包的实质目标——把 F-1..F-6 的闭环结论写准、让 R4 计划/金额/窗口可复算、把"不重签计划"口径写死——
**已达成且可独立复现**：15 个 R4 产物逐字节未变、`plan_sha256=00b9fdef…` 与 GO 绑定三方一致、§8 六个数逐值复算成立、
0.04096 与 fail-closed 码与代码同源、F-3 裁定在 runbook 与 report 两处同文且没有放宽"新计划/新 GO"。

- 签 R4 GO 之前**建议先修** F-7（否则按 runbook 执行会在 §1.1 停）与 F-8（跑后检查项指向不存在的字段）。
- F-9/F-10/F-11/F-12/F-13 可随手修；它们不改变任何计划事实，也不影响 GO 绑定的字段。
- 残留限制（Mock-only 可达性、live 未观测 conflict、forbidden 不可命中、B=6 无余量）保持如实披露，不因本次复验而升级为已验证。
