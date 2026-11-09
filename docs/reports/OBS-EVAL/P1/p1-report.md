模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# P1 收口报告（OBS-EVAL / P1）

> 分支 `p1/fix-retrieval`（基线 `main@083eaef`），HEAD `05e67cd`；独立总验收见
> `docs/reports/OBS-EVAL/P1/review.md` 与 `evidence/T900/`。零 live 重跑；未读 `.env`；
> 未读 Holdout 逐题；本报告不含答案原文/凭据/逐题明细。

## 1. 范围

P1 目标：修 7 项已知缺陷 → Holdout 30 防污染 → 真实 embedding/rerank 的
`live + retrieval_only` 检索评测 → gate v0.2 校准/审批与 P1 release baseline →
只读监控 API → 回归与边界。非目标（P2）：live 端到端答案质量、Ragas、看板/告警、
容量/供应商 429/5xx、真实 OCR 质量、供应商实账、新生产依赖。

## 2. 逐包交付与 commit

| 包 | 内容 | dev commit |
| --- | --- | --- |
| T100 | 基线测试与已签 P1 配置解耦 | `b35ae72` |
| T107 | regression suite 与数据集契约 | `36fe095` |
| T101 | ERR-03 词表语境/法规优先 | `a7282b3` |
| T102 | ERR-01/02 + D5 状态继承 | `85d9ffc` |
| T103 | D4 记录路回落（ERR-04） | `43b7976` |
| T104 | D1 异常原因透传（ERR-07 产品侧） | `e7ee804` |
| T105 | D6 指代/字段错配（ERR-06） | `2306aaa` + `fc60c57` + `b37ad21` |
| T106 | D3 文案统一（ERR-05，前后端） | `a42ee48` + `972f508` |
| T108 | Holdout 支持与防污染 | `af08848` + `d3b5745` |
| T109 | 多轮 turns runner | `703b7e0` + `1ffd57a` |
| T110 | 检索金标与同 chunk 指标 | `6c82a8f` |
| T111 | live 检索运行器 + 真实索引（pilot 10 停） | `735bb93` |
| T112 | gate v0.2 校准 + b0 全量 live baseline + 审批 | `7f46121`（R0）+ `4c2b7ba`（R1） |
| T113 | 监控 API（只读聚合） | `9edc003` |
| T114 | 监控 API 权限/负例/文档 | `2a0c192` |

分支共 84 commit（21 dev + 63 PM 簿记），均未 push/未 amend；全部 dev 路径在允许范围。

## 3. 七条结果（详见 review §2）

1. **7 项修复转正：PASS（有保留）**。7 个缺陷均有 regression 种子与前后对比；b0/badcase
   对 P0 签名 0 diff、无 hard failure。保留：regression 5/7 pass，RG005/RG007 仍 fail
   （`_index` #46 意图词表，T104/T106 handoff 明示不修；“7 条全部 RED→PASS”字面不成立）。
2. **行为变化受控：PASS**。local 三套对 P0：b0/badcase 0 diff；regression 仅 RG006 变化；
   `AskResult` 12 字段 / `MessageView` 12 字段未变；业务 API schema 零 diff；T104/T106
   错误码/文案清单在包证据中。
3. **Holdout 30 冻结可用：PASS**。导出 sha `a8c8aa7f…6738`、30 行、13 键、
   `label_version=holdout-2026-11-04`、分层 10/5/5/5/5；labels sha `8f713a2a…c1bf`
   未入库；T900 独立 local 聚合 30/30、error=0、分母 30；CI details/`--from-run` 均拒绝。
4. **真实检索评测：PASS（b0）/ NOT-RUN（其余）**。T111 pilot 10/10；T112 b0 40 题
   （32 计分/8 OCR）、70 请求、chat 0、零重试；指标 all=0.96875 / exact=1.0 /
   text=0.875（R/MRR/nDCG 同值）。badcase/regression/holdout live 为
   **NOT-RUN（主人方案 A）**，未写成通过，未补跑。
5. **门禁与 baseline：PASS**。`gate_v0_2 approved` 阈值逐项=主人批准值；approved 配置
   exit 0/quality pass，R0 unapproved 配置 exit 3/unknown；`bc6f6f906db1` approval 齐全、
   六要素=manifest、`baseline list approved=yes`；P0 baseline 未创建；跨版本只分析。
6. **监控 API 只读可用：PASS**。4 端点 admin 200/employee 403/匿名 401；无原文/逐题；
   trace 关闭降级；OpenAPI 4 paths 仅 GET；T900 独立探针 39/39。已知 LOW：无
   `securitySchemes`（文档已声明 cookie-session）。
7. **回归与边界：PASS**。全量 **1933 passed / 0 failed / 0 error（498.11s，只跑 1 次）**；
   定向 407 passed；前端 typecheck/build 0；无新生产依赖、无业务库/索引库 schema 改动、
   无业务 API 字段结构改动。e2e NOT-RUN（未装配浏览器）。

## 4. 真实调用与成本（保守口径）

| 项 | T111 pilot | T112 b0 全量 |
| --- | --- | --- |
| 题数 / 计分 | 10 / 10 | 40 / 32（8 OCR 跳过） |
| 请求 | 27 = embedding 17 + rerank 10 | 70 = embedding 39 + rerank 31 |
| chat | 0 | 0 |
| 重试 | 0 | 0 |
| 账本增量 | +0.0026345 元 | +0.0090459 元 |
| 阶段累计 | 0.005269 元 / 435 请求 | **0.0143149 元 / 505 请求** |
| 总 accounted | 15.0592641 / 20 | **15.0709445 / 20** |

- `P1-RETRIEVAL` 额度 3.0 元，阶段剩余 2.9856851；总上限 20 元，剩余 4.9290555；
  请求硬顶 1000，已用 505（S2-DEV 381 + P1-RETRIEVAL 124）。口径：T111 pilot 后
  0.0026345/408；T111 验收方 ≤10 复跑另 +0.0026345/+27 -> 0.005269/435；T112
  +0.0090459/+70 -> **0.0143149/505**。
- `provider_billed_cny=null`；以上是账本 conservative 记录 + 官方标价估算，**不是供应商账单**。
- T112 预检上限 0.771174 元（71 请求）；实际 70 请求/0.0090459 元；单笔最大预留
  0.04096 ≤ 0.05。rerank 比 query 少 1 次：1 个 query 无候选，未伪造请求。
- handoff §5.4 的 `0.0142293` 与账本/run summary `0.0143149` 差 0.0000857；
  本报告采用账本事实值。

## 5. 残余 / NOT-RUN（不阻断）

- **#46**：`营收/报销标准` 等意图词表未短路，RG005/RG007 仍 fail；P1 不收口，留 P2/另派。
- **#51**：T105 政策词+台账字段词仍 576 字 8×8 倾倒（等于基线）。
- **#52**：T106 `not_found` 徽标仍“无匹配资料”；`INVALID_QUERY` 徽标分支无 e2e 注入入口。
- **#53**：T108 report 167 行；holdout 23 fail/7 pass（含 3 个拒答题）。
- **#54**：T109 report 140 行；fail-closed 行保留 1 条诊断 trace。
- **#55**：T110 nDCG 单 chunk/单 gain 保守下界；empty_recall 沿用 P0 语义。
- **#56**：T111 GO 计划计数 7/4 与实际 17/10（T112 39/31）有口径差；pilot 指标平凡。
- **#57**：OpenAPI 无 `securitySchemes`；T113 report/证据父提交笔误 `fcc3434`（实际 `10bb42b`）。
- **#58**：T114 holdout 标志 LOW-1 仍可复现（无泄露）；OpenAPI LOW-2 同 #57；
  “`trace_unavailable`/`partial_data` 无专项测试”**不成立**（`test_routes.py:558,807-818` 已有）。
- **#59**：T112 R1 重写 run `gate.json`（exit 3→0，已披露）；审批后 config_hash 变化；
  R0 §5 跨版本理由过时；diff 放行路径不重核当前 gate 配置哈希。
- **NOT-RUN**：badcase/regression/holdout live；真实模型/embedding/rerank/OCR 重跑；
  P0 跨版本 baseline 比较（P0 baseline 不存在）；Holdout 逐题；前端 e2e。
- **可移植性提示**：P1 baseline `bc6f6f906db1` 与 T111/T112 run 产物位于 gitignored
  `var/eval/**`，不会随 PR 进入 main；新环境/CI 需重新生成或另行归档，不能假定
  `baseline list` 在 fresh clone 可见。
- 另有形式偏差：T112 report 105 行、T105/T106 report 99/113 行 > 80 行预算（已记录）。

## 6. 发布建议（主人决策）

- 技术验收层面：**有保留 PASS**，可开 1 个 PR 交主人；**不建议在主人决策前合并**。
- 合并前请主人确认：① 方案 A 导致 badcase/regression/holdout live 缺口；② RG005/RG007
  意图词表残余（#46）；③ #51–#59 的 P2 清单；④ Holdout 质量（7/30 pass）不作为 P1 门禁，
  但不应被读作“质量通过”。
- 不建议直接进入 P2：先由主人决定是否接受上述保留，并决定是否补 live 三套/意图词表专项。
