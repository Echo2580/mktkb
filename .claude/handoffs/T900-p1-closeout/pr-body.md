# PR：P1 检索与评测修复 + 真实检索 baseline + 监控 API（待主人审核，不合并）

> 由 PM 按流程创建；**不合并**，等主人 G5 决策（通过 / 有条件通过 / 返工 / 改需求）。
> 分支 `p1/fix-retrieval`（自 `main@083eaef`，P0 已合并）→ base `main`；共 84 commits（21 个 dev + 63 个 PM 簿记）。

## 零、独立总验收结论（T900）

- 总判定：**有保留 PASS**（`docs/reports/OBS-EVAL/P1/review.md`，110 行；`p1-report.md` 112 行；`evidence/T900/` 4 份）。
- 七条：1 PASS（保留：regression 5/7，RG005/RG007 仍 fail，#46 已披露）；2 PASS；3 PASS（Holdout 30/30、error=0、分母 30 独立复跑）；4 PASS（b0）+ NOT-RUN（badcase/regression/holdout live，方案 A）；5 PASS（approved exit 0 / unapproved exit 3）；6 PASS（独立探针 39/39）；7 PASS（e2e NOT-RUN，typecheck/build 0）。
- 全量 `pytest backend/tests` = **1933 passed / 0 failed / 0 error（498.11s，只跑 1 次）**；定向 407 passed。
- 越界审计：84 commits 全部落在允许路径；无 `var/**`、`docs/evidence/**`、账本/GO、依赖清单、业务 API schema 改动。

## 一、这个 PR 做了什么

P1 阶段（自 `main@083eaef`，P0 已合并）完成三类工作：

1. **7 项检索/回答缺陷修复**（按 `错误记录-20261104.md` 的 ERR 编号）：
   - T101 ERR-03 词表语境与法规优先
   - T102 组 A 状态继承（ERR-01/02/D5，多轮槽位继承不再张冠李戴）
   - T103 D4 记录路回落语义检索（ERR-04）
   - T104 D1 异常原因透传（ERR-07 产品侧）
   - T105 D6 指代/字段错配（ERR-06；多轮两轮返工 + 窄口径）
   - T106 D3 文案统一（ERR-05，前后端诚实文案）
2. **评测与门禁升级**：regression suite（7 条修复用例 RED→GREEN）、Holdout 30 与防污染、多轮 turns runner、检索金标与指标（同 chunk 同排名）、**live retrieval_only 运行器**（真实 embedding/rerank、零 chat、零重试、账本/GO 硬绑定）、**gate v0.2 + P1 release baseline**（主人已批准检索层阈值）、监控 API（4 个只读端点 + 权限/负例/文档/OpenAPI）。
3. **基础设施前置**：T100 修基线测试与真实配置耦合；T107 regression 数据集契约。

## 二、逐包交付（P1）

| 包 | 内容 | 交付 commit |
|---|---|---|
| T100 | 基线测试耦合修复 | `b35ae72` |
| T107 | regression suite + 数据集契约 | `36fe095` |
| T101 | ERR-03 词表/法规优先 | `a7282b3` |
| T102 | 组 A 状态继承 | `85d9ffc` |
| T103 | D4 记录路回落 | `43b7976` |
| T104 | D1 异常原因透传 | `e7ee804` |
| T105 | D6 指代/字段错配（R1/R2） | `2306aaa` + `fc60c57` + `b37ad21` |
| T106 | D3 文案统一（R1） | `a42ee48` + `972f508` |
| T108 | Holdout 支持与防污染（R1） | `af08848` + `d3b5745` |
| T109 | 多轮 turns runner（R1） | `703b7e0` + `1ffd57a` |
| T110 | 检索金标与检索指标 | `6c82a8f` |
| T111 | live 检索运行器 + pilot 10 题 | `735bb93` |
| T113 | 监控 API（只读聚合） | `9edc003` |
| T114 | 监控 API 权限/负例/文档 | `2a0c192` |
| T112 | gate v0.2 校准 + P1 b0 live baseline（R0/R1） | `7f46121` + `4c2b7ba` |
| T900 | P1 独立总验收与收口（本 PR 的来源） | 见收口 commit |

> 每包流程：1 个开发 subagent + 1 个全新上下文独立验收 subagent；证据 `docs/reports/OBS-EVAL/P1/evidence/{T<NNN>,verify/T<NNN>}/`；流程材料 `.claude/handoffs/T<NNN>-*/`。

## 三、验证证据

- **T900 总验收**：`docs/reports/OBS-EVAL/P1/review.md`（七条逐条判定 + 逐包抽查 + 越界审计，110 行）、`docs/reports/OBS-EVAL/P1/p1-report.md`（112 行）、`docs/reports/OBS-EVAL/P1/evidence/T900/`（4 份）。
- **全量测试**：`pytest backend/tests` → **1933 passed / 0 failed / 0 error（498.11s，只跑 1 次）**；15 包定向 **407 passed**；前端 `npm run typecheck` 与 `vite build` 均 exit 0。
- **本地评测对照**：b0 40 / badcase 13 / regression 7 对 P0 基线 `case_diffs=0`、`gate hard=[]`。
- **真实检索**：T111 pilot（b0 前 10，零 chat、0.0026 元/27 请求）+ T112 b0 全量 40 题（70 请求、+0.0090459 元、无 retry、`provider_billed_cny=null`）；账本 505/1000、P1-RETRIEVAL 0.0143149/3.0 元。
- **门禁/baseline**：`gate_v0_2.json` approved（仅检索层：min_sample=8、R/M/nDCG≥0.855、hard_filter≤0.02、empty_recall≤0.145、max_regression_pp=2.0）；P1 release baseline `bc6f6f906db1`（b0/live/retrieval_only，approval=主人）。

## 四、真实调用与预算（保守口径）

- 账本 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`：505/1000 请求预留；P1-RETRIEVAL 已计 **0.0143149/3.0 元**；总 accounted **15.0709445/20**；`provider_billed_cny=null`（供应商实账未核对，账本为保守口径，不等于账单）。
- 无 chat 调用；零重试；GO 有效期至 2026-11-30。

## 五、NOT-RUN / 已知残余（不阻塞本 PR，但需主人知悉）

- **P1 §9 第 4 条部分覆盖**：live 只覆盖 b0（主人 2026-11-09 方案 A 请求上限决策）；badcase/regression/holdout live = NOT-RUN。
- **#46（第 1 条保留）**：`营收/报销标准` 等意图词表未短路，regression RG005/RG007 仍 fail；P1 不收口，留 P2/另派。
- `_index` **#51–#59** 逐条记录（T105 P2 词组合倾倒、T106 前端徽标 e2e NOT-RUN、T108 报告超行数/3 拒答题 fail、T110 nDCG 保守下界、T111 GO 计数口径差、T113 OpenAPI 无 securitySchemes、T114 holdout 标志措辞、T112 diff 放行路径不重核 gate 配置哈希等）。T900 复核更正：#58 第三项「trace_unavailable/partial_data 无专项测试」**不成立**（`test_routes.py` 已有并通过）。
- **P1 baseline 可移植性**：`bc6f6f906db1` 与 T111/T112 run 产物在 gitignored `var/eval/**`，不随 PR 进入 main；新环境需重新生成/另行归档。
- P0 三项可选项（阈值审批 / 真实 baseline / 设计 §7.2 回写）仍冻结，未在本 PR 处理。

## 六、兼容性与风险

- **未改**业务 API 请求/响应 Body 字段结构；**未改**业务库/索引库 schema；无新增生产依赖；前端仅文案/徽标相关改动（T106）。
- 已知行为变化：错误码/文案取值变化（D-3 已授权），见各包 review与 `_index`。
- 回滚：本 PR 为独立分支，revert 本 merge 即可；不涉及数据迁移/外部服务。

## 七、审查建议（给主人）

1. 先读 `docs/reports/OBS-EVAL/P1/review.md` 的「有保留 PASS/NOT-RUN」与七条表；
2. 重点看：T111/T112 真实调用与账本、gate v0.2 阈值与 baseline 审批、T900 的 NOT-RUN 清单；
3. 决定：通过 / 有条件通过 / 返工 / 改需求（合并动作由主人执行；本 PR 未合并）。

## 八、测试计划（复跑命令）

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\pr-check
# 本地评测（零真实调用）
.\.venv\Scripts\python.exe -B tools\rag_eval.py run --suite b0 --mode local --out var\eval\runs\pr-b0
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run var\eval\runs\pr-b0 --config docs\evaluation\gate_v0_2.json
```
