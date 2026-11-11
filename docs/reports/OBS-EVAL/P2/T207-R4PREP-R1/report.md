# P2-T207-R4PREP-R1 文档收口报告（零真实调用）

- 角色：R4 准备文档收口助手（全新上下文）。**零真实调用**（未起服务、未跑 python 探针、未跑 p2-run/p2-score）、零网络、**零 commit**；
  未读 `.env`/H1/H2；只写 T207 文档与本目录。分支 `codex/p2-e2e`，基线 HEAD **`1dca413`**
  （= LIVECAP 提交；R4PREP 交付时为 `489aadd`，其后 `24f9cde`(R2) / `1dca413`(LIVECAP) 已提交）。

## 1 改动清单（全部为文档；行号为改后行号）

| 文件 | 位置 | 改动 |
|---|---|---|
| `PM/T207-runbook.md` | §1 L10–L17 | 项编号 1,2,4,3 → 1,2,3,4（验收 LIVECAP「瑕疵 B」）；R4 项由“前置未闭环”改为“备件齐全、前置已闭环” |
| 同 | §3.2 L125–L138 | 前置 1 改为已闭环（R2 文案）+ 不改计划/不重签；前置 2 补「`page_count=0` ⇒ effective=0.04096，**GO `max_request_cny` 必须 ≥0.04096**（候选 0.5 满足），不足装配期 fail-closed」，并把“降级”措辞更正为 live 实参下 `aborted(product_service_error)`（验收 LIVECAP「瑕疵 A」） |
| 同 | §4 L150 | 停止规则补稳定码 `live_request_ceiling_insufficient` |
| 同 | §9 L356 | 给“改了 pipeline/计划/GO → 新版本”加**文案-only 例外**（原 :355 冲突面） |
| 同 | §9 L359–L377 | R4 前置段改写为历史读数 + 已闭环；新增 **F-3 重签口径**（文案-only ⇒ `plan_sha` 不变 ⇒ 不重签计划，GO 仍按流程签发）；接线面补 GO ≥0.04096（含 H2） |
| `report.md` §9 | L89–L91 | **F-4**：HEAD `0260b7b` → 交付时 `489aadd` / 当前基线 `1dca413`，并注明 R2、LIVECAP 已提交 |
| 同 | L126–L132 | **F-6**：B_r4=6（实测）vs 上界 9 的取舍（多 1 POST 即发送前 `attempt_quota_exhausted`） |
| 同 | L141–L149 | **F-6**：12 负例=11 码（`go_max_requests_below_plan` 两次）；case 名≠稳定码（`requests_over_remaining`→`request_budget_insufficient`；`center_below_plan_need` 在计划构造期即 `center_budget_exceeded`，preflight 中心窗口码由验收补测）；V03/V06 的 `forbidden_sources` 因映射表只按产品文档名而**不可命中** |
| 同 | L152–L156 | **F-5**：删「挡住 R4 的不是接线」，改为“当时确有 F-1 接线阻断，已由 LIVECAP 修掉” |
| 同 | L158–L183 | **F-2**：§9.3 改写为「历史读数（`489aadd`，C05/C06 `value_hit fail`）+ FIX-CONFLICT-R2 后三例 pass、计划/case/GO 不变无需改动」+ 残留限制（live 从未观测到 conflict） |
| 同 | L208–L226 | 新增 §9.5：F-1..F-6 闭环表 + F-3 裁定全文 + 0.04096 前置 |
| `PM/T207-cost-and-quota.md` §8 | L227–L235 | 负例清单改名（`requests_over_remaining` → `request_budget_insufficient`）、补 12/11 码说明、补「R4PREP-R1 逐值复核」（18 / 760 / 0.144960 / 709 ≤ 1600 / 6.6859204 / 21.7568649） |
| 同 | L237–L249 | §8.4 标注为**历史读数**（修复前），并写明 R2 落地后三例 pass、金额与请求形状逐值不变 ⇒ §8.1–8.3 继续有效 |

## 2 依据
- `T207-R4PREP/review.md` §3（F-2/F-3/F-4/F-6）与 §1 判据 6/7；
- `T207-FIX-CONFLICT-R2/report.md` §4 + `review.md` §0/§2.3（C05/C06 fail→pass、54 例差分 {C05,C06}）；
- `T207-FIX-LIVECAP/report.md` §3 + `review.md` §2/§4/§6（effective=0.04096、fail-closed、瑕疵 A/B）；
- 既有 sha 只读引用：`plan_sha256=00b9fdef…`、`cases/R4.jsonl=c04b67c6…`、候选 GO `max_request_cny=0.5`；
- 经理裁定（F-3）：只改产品输出文本、不改计划内容 ⇒ `plan_sha` 不变、R4 不重签计划；GO 仍按流程签发。

## 3 未改动 / 未做
- 未改计划/case/ingest/GO JSON（内容与 sha 未变）、未改源码/测试/fixtures/账本/预算/固定路径 GO、未新增 skip、未 commit；
  **未重跑计划校验**（`P2RunPlan` 未变；本包不动 `build-r4.py` / `validate-r4.py`，只引用其既有输出）。
- `PM/T207-PM-decisions-01.md` 不在本包允许改动面（**未改**）：F-3 裁定正文落在 runbook §9 与 `report.md` §9.5，经理可另行补记入决定文件。
- 限制（如实）：(a) 修复后可达性的证据仍只有 Mock，live 上尚未观测到 `conflict`，首验即 R4，存在仍回 `answer` 的可能；
  (b) V03/V06 的 `source_forbidden` 属“不可命中”，其 pass 不构成检查有效性的证据；(c) `index_embedding=6` 是实测值、无安全余量。
