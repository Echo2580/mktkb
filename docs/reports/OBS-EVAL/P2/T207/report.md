# P2-T207 准备交付（report）

- 角色：T207 准备助手（全新上下文）。真实调用 **0**；未读 `.env`/H1/H2；未联网；未写真实 budget/GO/账本；
  未改代码/测试/冻结夹具；未 commit/push。分支 `codex/p2-e2e`，HEAD `9a740ce`（未变）。
- 现场（只读复核一致）：账本 `6b053520…`（1,050,298 B / 1095 行 / 547 reserved / 547 result），预算 `79b21700…`（limit 40 / P2-LIVE 20），
  历史前缀 `f4710b18…`；P2 阶段已占 `0.5713583`（ocr 0.5 + answer_retrieval 0.0713583），**余 19.4286417 元 / 453 请求**。

## 1 结论（一句话）

计划、导入配方、成本核算与候选 GO 的算术**全部可离线复算**（254 请求 / worst-case 8.127376 元 / 12 页 OCR 5.65），
但**整套矩阵今天还不能跑**：3 处必须由经理决定的前置（请求硬顶、GO 重签、用例与 H2 计划生成器），
外加 6 处**矩阵可执行性缺口**（F1/F2/F4/F5/F6/F7 中的 4 条 BLOCKER）。这不是额度问题，是接线与治理问题。

## 2 交付物

| 文件 | 说明 |
|---|---|
| `PM/T207-plan-v0_1.json` | 公开矩阵 `P2RunPlan`：233 项 / 55 个真实回合（`plan.turn_count=60` 还含 INGEST 与 4 个 OCR 文档码的 turn=1 伪回合）/ 12 页 OCR / **254 请求** / `max_requests=1000`；`plan_sha256=d788a83b3b27ff4e4aa43cb89b2230012d4f89eeecd232e2ac489e398cb3a947` |
| `PM/T207-plan-h2-v0_1.template.json` | H2 **模板**（不是 P2RunPlan）：36 回合 ×4 项 + 1 个 ingest 项；case_id 只能由封存进程生成 |
| `PM/T207-GO.CANDIDATE-DRAFT.json` | 公开矩阵候选 GO（DRAFT，`production_ready=false`）：绑 plan sha、账本前缀、13 天、中心 8.5/6.5/3/2、`max_requests=1000`、`max_request_cny=0.5` |
| `PM/T207-GO-h2.CANDIDATE-DRAFT.json` | H2 候选 GO（DRAFT；`plan_sha256` 为全零占位 ⇒ 授权链必然失败，只作形状/上限预审） |
| `PM/T207-import-recipe.md` + `.json` | 42 步导入配方（V03→D01→V04 同槽三版：历史/当前/未生效）、逐 step 状态断言、失败判定、chunk/批 清单、与 corpus V01–V08 的关系 |
| `PM/T207-cost-and-quota.md` | 逐 operation/中心/案例/页/批的请求与 worst-case；R1/R2/R3 拆分；中心重排证明；H2 可行域；拟提 `HARD_MAX_REQUESTS=1600` 的实算 |
| `PM/T207-fix-scope.md` | 供 T207-FIX 的最小修复清单（A–G 七组，逐项含现象/复现/根因行号/允许改文件/禁止项/验证/回归风险） |
| `PM/T207-runbook.md` | 执行手册：只读检查、签发、三次运行命令（与 `cli.py` 参数逐字对齐）、停止规则、产物核对、归因表、H2 注入与审计、部分重跑、回滚 |
| `evidence/` | `estimate.py`（chunk/批 + OCR 三档 + corpus 包络）、`build-plan.py`（确定性造计划/GO）、`validate-plan.py`（预检/授权/负例）、三份输出 JSON/TXT |

## 3 计划与成本要点

- 55 回合 = B0 40 + N8 + C6 + U01（任务书要求的「计划绑定的有限真实更新 smoke」）；每回合 4 次底层请求（query_embedding/rerank/query_expansion/answer）。
- 灌库 22 批 = 11（fixtures 非 OCR，实测）+ 11（12 页 OCR，按每页 ≤2,700 字上限：7+2+1+1）。
- 拆三次运行（同一计划、同一 GO）：R1 230 请求 / 7.994704 元；R2 19 / 0.545024；R3 6 / 0.04832 → 累计 **255 / 8.588048**。
- 中心必须重排：ocr 已占 0.5 + 本次 5.65 = **6.15 > 原 6.0** → `8.5/6.5/3/2 = 20`（`budget.json` **不用改**）。
- 余量对照：255 ≤ 453 ✓、8.588 ≤ 19.4286 ✓；但 R2/R3 的再次授权在 1000 硬顶下不可行（`plan.total_requests ≤ max_requests − 已用`）。

## 4 缺口（BLOCKER 单列）

| # | 缺口 | 级别 | 最小方案 |
|---|---|---|---|
| F1 | H2 逐 case 计划项 vs 隐藏 case_id（`p2_runner.py:1073-1083`、`p2_live.py:241-245`） | **BLOCKER** | 封存进程内生成计划（只落 `plan_sha256` 进仓库），新增 ~100 行生成器 |
| F2 | H2 语料包未声明（全仓只有任务书一句） | **BLOCKER（数据保管面）** | 保管方给 `corpus code 列表 + 是否含 OCR 页 + 导入顺序`（repo-safe） |
| F4 | U 行的 L/R 与 `execution_mode_mixed`（`p2_scoring.py:1178-1182`）；U07–U09 无 question、U10 需重复 id | **BLOCKER（口径）** | 逐题 `evidence_basis` + `allow_mixed_basis`（suite 内一致），U verdict 取既有 `test_t09_mutation.py` |
| F5 | run 产物 → 评分/门禁的驱动不存在（src 里只有定义、无调用者） | **BLOCKER** | 新增 `p2_score_run.py` + CLI `p2-score` |
| F3 | N8/C6 只有 `questions.json`，不是 CaseSpec | 高 | 只读转换器 → `CaseSpec`；C05/C06 用独立 run 的 ingest 计划表达 |
| F6 | gate 链**不能**产出 `release_ready` | 设计如此 | `gate_v0_3` unapproved → `gate_config_unapproved`（unknown）；放行权在 T209 |
| F7 | 多 run 共用一扇门：`gate_reserved` 累计 vs 本 run 期望 → `attempt_accounting_mismatch` | 高 | 每次 run 新开门 + 计划 `max_requests` 留重授权余量 |

## 5 请求硬顶（拟提）

`547(已用) + 255(公开) + 144(H2 回合) + ≤68(H2 灌库) + 160(T208 judge≈3 元) + 107(T900 independent≈2 元) = 1,281`，
+20% 余量 → **建议 1,600**（主人预授权 ≤2000 内）。配套：公开计划提顶后重发 `max_requests=1200`、H2 1100、judge 1200、independent 1400；
同步改 `live_authorization.py:94`（`test_p2_authorization.py:481` 的不变式）与契约 §1.3/§3 文本。**到值即停**。

## 6 风险 / 未做

1. **R1 今天只能授权一次**（计划 `max_requests=1000`）；R2/R3/H2 需提顶后重发计划+重签 GO（sha 会变）。
2. 固定路径 `P2-LIVE-GO.json` 仍在（绑 T206 pilot 计划 `02725aa7…`）：直接换计划会 `go_plan_sha256_mismatch` 拒；必须重签。
3. OCR 文本长度是**假设**（每页 ≤2,700 字；转录锚定只要 4 批）：超限在发送前 `attempt_quota_exhausted` 停（fail-closed，不超支），但会烧掉已付的 OCR 页费。
4. H2 若含 12 页 OCR：阶段会到 21.18 > 20 → 必须排除 OCR 页或提阶段额（需预算修订）。
5. 未做：真实调用/OCR/H2/Ragas/全仓测试；未跑 `p2-run`（含 dry-run）；未改任何产品代码；未评估质量。
6. `output_valid` 疑点：`build_chat_evidence` 未传该字段（默认 False，`settlement_policy.py:479/713`）→ 可能让 live chat 结算退回保守留账；
   已列入 fix-scope §C，需 T207-FIX 用离线用例确证。

## 7 复跑入口（零真实调用）

```powershell
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\estimate.py --corpus
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\build-plan.py
.venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207\evidence\validate-plan.py
```

预期：`preflight_real_snapshot.ok=true`（`requests_remaining=453`）、`authorize_candidate.production_ready=false`、
10 条负例全部按稳定码拒绝、`read_only_proof.unchanged=true`、`go_path_exists_after=true`（未创建/未修改）。
