模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T900：P1 独立总验收（review）

> 分支 `p1/fix-retrieval`；HEAD `05e67cd`（其后 PM 簿记只改 `.claude/handoffs/**`）；
> 开工/收尾 `git status --short` 仅有人主侧未跟踪 `docs/面试/` 与 PM 并发草稿
> `.claude/handoffs/T900-p1-closeout/pr-body.md`，无 tracked 改动。零 live 重跑；
> 未读 `.env`；未读 Holdout 逐题；未改代码/测试/配置/fixtures/`docs/evidence/**`/`var/**`。

## 1. 总判定

**有保留 PASS**。七条中 6 条 PASS、第 4 条为“b0 PASS + badcase/regression/holdout live
NOT-RUN（主人方案 A）”；第 1 条附“RG005/RG007 仍 fail（#46 意图词表，已披露）”的保留。
关键数字：全量 **1933 passed / 0 failed / 0 error（498.11s，只跑 1 次）**；定向 407 passed；
账本 **505/1000**、P1-RETRIEVAL **0.0143149/3.0 元**、总 accounted **15.0709445/20**、
`provider_billed_cny=null`。

## 2. P1 设计 §9 七条

| # | 判定 | 依据（命令 / `文件:行`） |
| --- | --- | --- |
| 1 | **PASS（有保留）** | T101–T106 七个缺陷均有 regression 种子与前后对比（`fixtures/evaluation/regression.jsonl` 7 行，`source_err_id` 齐全）；local regression **5 pass/2 fail**（RG005/RG007），RG006 fail→pass；b0/badcase 对 P0 签名 **0/40、0/13**、gate hard `[]`。保留：按“7 条全部 RED→PASS”字面未满足，RG005/RG007 属 `_index` #46，T104/T106 handoff 明示不修。 |
| 2 | **PASS** | local 三套对 P0：b0/badcase 逐例签名 0 diff；regression 仅 RG006 变化、RG005/RG007 不变。`AskResult` 12 字段、`MessageView` 12 字段（`backend/src/mktkb/conversations/schemas.py:96,118`）；`schemas.py` 零 diff；T104 七类码/T106 文案清单在包证据中。 |
| 3 | **PASS** | 导出 `holdout-questions.jsonl` sha `a8c8aa7f…6738`、30 行、13 键、`label_version=holdout-2026-11-04`、分层 10/5/5/5/5；labels sha `8f713a2a…c1bf` 且不在 git；T108-R2 证据 30/30、error=0、分母 30；T900 独立 local 聚合复跑同值（`backend/.pytest-tmp/t900-holdout-20261109225600`，仅 manifest+summary）；CI details/`--from-run` 均 exit 3、不建 out。 |
| 4 | **PASS（b0）/ NOT-RUN（其余）** | T111 pilot 10/10、chat 0、请求 17/10、+0.0026345 元（验收方 ≤10 复跑另 +0.0026345 → 0.005269/435）；T112 b0 40 题（32 计分/8 OCR）、70 请求（39/31）、chat 0、零重试、+0.0090459 元（→0.0143149/505）；账本与 run summary 一致。**badcase/regression/holdout live = NOT-RUN（主人方案 A），未写成通过**；未重跑任何 live。 |
| 5 | **PASS** | `gate_v0_2.json status=approved`：`min_sample=8`、R/MRR/nDCG `0.855`、hard_filter `0.02`、empty_recall `0.145`、`max_regression_pp=2.0`，answer/refusal/runtime 仍 null；approved 配置对 T112 run `exit 0/quality pass`，R0 逐字节 unapproved `exit 3/unknown`；`bc6f6f906db1` 六要素=manifest、approval=主人/exit 0/quality pass、`baseline list approved=yes`、P0 baseline 未创建；跨版本代码固定 `release_allowed=False`（`report.py:492-493`）。 |
| 6 | **PASS** | T900 自写探针 **39/39**：4 端点 × 匿名 401/employee 403/admin 200；无原文/`*_json`/路径；span 仅键名+计数；trace 关闭 200+`trace_disabled`；holdout 有 cases 时 `details_withheld=true` 且不返回；OpenAPI 4 paths 仅 GET、401/403、无分页。OpenAPI 快照 sha `51f7ed…db5979`。已知 LOW：无 `securitySchemes`（文档已声明）。 |
| 7 | **PASS** | 全量 `backend/tests` **1933 passed/0 failed/0 error**（498.11s，跑前空闲 5310MB，无 flake）；前端 `npm run typecheck` exit 0、`vite build` exit 0；21 个 dev commit 全在允许路径；`pyproject.toml`/`uv.lock`/`requirements*.lock`/`package.json` 零 diff；业务 API schema 零 diff。e2e NOT-RUN（未装配浏览器）。 |
| 8 | **PASS** | `review.md`/`p1-report.md` 的数字统一取本次实测/账本/run summary；未覆盖与 NOT-RUN 明列；证据 4 份。 |

## 3. 逐包抽查（T100–T114）

> 共同动作：各包本包测试均包含在 **407 passed** 定向套件（文件清单见
> `evidence/T900/02-tests.md` §B）；下表只列额外动作与差异。“无差异”=仍同意包 review 结论。

| 包 | 结论 | 我的额外复核 | 与包 review 差异 |
| --- | --- | --- | --- |
| T100 | PASS | `test_s4_stage_limit.py` 随 407 通过；配置/账本只读核对 | 无 |
| T101 | PASS | 3 个 T101 测试文件随 407 通过；b0/badcase 签名 0 diff | 无 |
| T102 | PASS | 2 个 T102 测试文件随 407 通过；b0/badcase 签名 0 diff | 无 |
| T103 | PASS | 2 个 T103 测试文件随 407 通过；b0/badcase 签名 0 diff | 无 |
| T104 | PASS | 3 个 T104 测试文件随 407 通过；`AskResult` 12 字段 | 无；#46 RG005 残余仍在 |
| T105 | PASS | T105-R3 独立探针 **131/133**；两失败为 T106 后旧文案“未记录”断言，非回归；#51 的 576 字/8 markers 复现 | 包 review 未跑 T106 后探针；结论不变 |
| T106 | PASS | `test_p1_t106_copy.py` 随 407；前端 typecheck/build 0；`format.ts:165` not_found 徽标仍在、`INVALID_QUERY` e2e 仍 NOT-RUN | 无（#52 仍存在） |
| T107 | PASS | `test_regression_suite.py` 随 407；local regression 7 题 5 pass/2 fail | 确认 RG005/RG007 fail；T107 只要求初始 RED |
| T108 | PASS | `test_holdout_suite.py` 随 407；独立 holdout 聚合 30/30、error 0、分母 30 | 无 |
| T109 | PASS | `test_multiturn_runner.py` 随 407 | 无 |
| T110 | PASS | 自写 macro 复算 b0/badcase 的 Recall/MRR/nDCG 与 summary 逐位一致 | 无；#55 保守下界仍在 |
| T111 | PASS | 只读核对 pilot run manifest/summary/请求/账本；未重跑 | 无 |
| T112 | PASS | approved/unapproved gate 0/3、canonical gate digest、baseline identity/approval/list | 无功能差异；handoff 的 0.0142293 与账本 0.0143149 不符，采用账本 |
| T113 | PASS | 独立探针 4 端点/OpenAPI；`test_routes.py` 随 407 | 无；#57 仍在 |
| T114 | PASS | 独立探针 39/39；`test_routes_security.py` 随 407 | #58 第三项“trace_unavailable/partial_data 无专项测试”不成立（`test_routes.py:558,807-818` 已有且通过）；LOW-1 仍复现 |

## 4. 全量 / 本地 / 前端（实测）

```text
pytest backend/tests -q --basetemp backend\.pytest-tmp\t900-full  -> 1933 passed, 1 warning, 498.11s
pytest <15 包定向文件> --basetemp backend\.pytest-tmp\t900-targeted -> 407 passed, 137.36s
local b0/badcase/regression -> 29/3/8、9/4、5/2；P0 签名 0/40、0/13
gate_v0_1 on local -> 三套 exit 3 / hard [] / quality unknown(unapproved)
frontend: npm run typecheck -> 0；vite build -> 0（40 modules，261ms）
```

## 5. 越界审计

- `git rev-list --count main..HEAD` = **84**（21 个非 chore dev + 63 个 PM 簿记）；
  `git show --name-status` 全部落在允许路径；无 `var/**`、`docs/evidence/**`、`.env`、
  签名 `budget.json`/`S2-LIVE-GO.json`/账本改动；无新生产依赖；无业务 API schema 改动。
- `docs/接口与数据契约.md` 仅追加 §8（观测只读接口），既有章节未改。
- 工作树外部文件：主人侧 `docs/面试/…`（未读改）、PM 草稿 `T900-p1-closeout/pr-body.md`
  （并发写入，未读改）。T900 临时物只在 `.claude/handoffs/_scratch/T900/` 与
  `backend/.pytest-tmp/t900-*`。

## 6. 未覆盖 / NOT-RUN

- **badcase/regression/holdout 的 live**：NOT-RUN（主人方案 A 请求上限；未扩套件/未重跑）。
- **真实模型/embedding/rerank/OCR**：未重跑（零真实调用）；T111/T112 只读 run+账本。
- **P0 跨版本 baseline 比较**：NOT-RUN（P0 baseline 不存在，未创建）；代码路径只分析。
- **Holdout 逐题**：未读；只用聚合与导出 sha。**T108 真实 holdout**：未重跑，读 T108-R2 聚合证据。
- **前端 e2e**：NOT-RUN（未装配浏览器/服务）；typecheck/build 已过。
- **T113/T114 的 500/异常信封**：未专项注入（不是 P1 验收项）；`trace_unavailable`/`partial_data` 已有测试。
- **P1 baseline 可移植性**：`bc6f6f906db1` 与 run 产物在 gitignored `var/eval/**`，不随 PR；
  fresh clone 需重建/归档后才可用 `baseline list`。

## 7. 残余 #51–#59 逐条判断（证据 04 §C）

| # | 仍存在？ | 依据 |
| --- | --- | --- |
| 51 | **是** | T105 探针 H-standard-spec/price-standard/submit-qty 均 576 字/8 markers 倾倒 |
| 52 | **部分是** | `format.ts:165` not_found 徽标仍“无匹配资料”；`INVALID_QUERY` e2e 仍 NOT-RUN |
| 53 | **是** | T108 report 167 行；holdout 23 fail/7 pass（含 3 拒答题） |
| 54 | **是** | T109 report 140 行；fail-closed 行保留 1 条诊断 trace |
| 55 | **是** | `scorers.py:914-916` nDCG ideal 每 unit 占一 chunk（保守下界）；empty_recall 语义未变 |
| 56 | **是** | GO 计划 7/4 vs 实际 T111 17/10、T112 39/31；pilot 指标平凡 |
| 57 | **是** | OpenAPI 无 `securitySchemes`；T113 report/证据 01 父提交笔误 `fcc3434`（实际 `10bb42b`） |
| 58 | **部分是** | LOW-1 复现（manifest false + summary details_written true + 无 cases -> `details_withheld=false`，无泄露）；LOW-2 同 #57；**“trace_unavailable/partial_data 无专项测试”不成立**（`test_routes.py:558,807-818` 已有且通过） |
| 59 | **是** | R1 重写 run `gate.json`（exit 3→0，已披露）；审批后 config_hash 变化；R0 §5 跨版本理由过时；diff 放行不重核当前 gate 配置哈希（`report.py:492-508`） |

## 8. 给主人摘要（≤10 行）

1. 总判定：**有保留 PASS**；七条 6 PASS，第 4 条 b0 PASS、badcase/regression/holdout live NOT-RUN（方案 A）。
2. 全量 **1933 passed / 0 failed / 0 error（498.11s，只跑 1 次）**；定向 407 passed；前端 typecheck/build 0。
3. 第 1 条保留：regression 5/7 pass，RG005/RG007 仍 fail（#46 意图词表，已披露）；无 hard failure。
4. 第 3 条独立复核：holdout 30/30、error=0、分母 30；导出 sha/13 键/分层与冻结值一致。
5. 第 4 条：T111 10/10、T112 b0 40 题 70 请求/chat 0/零重试；账本 505/1000、0.0143149 元、15.0709445/20。
6. 第 5 条：gate_v0_2 approved 阈值逐项=批准值；approved exit 0、unapproved exit 3；baseline `bc6f6f906db1` approval 齐全。
7. 第 6 条：T900 独立探针 39/39（401/403/200、不泄露、OpenAPI 4 GET）；无 `securitySchemes` 为已知 LOW。
8. 越界：84 commits（21 dev/63 簿记）无 var/docs.evidence/依赖/API schema 改动；仅外部 `docs/面试/` 与 PM 草稿。
9. 未覆盖：badcase/regression/holdout live、真实调用、P0 跨版本、Holdout 逐题、前端 e2e。
10. 产物：`docs/reports/OBS-EVAL/P1/{review.md,p1-report.md}` + `evidence/T900/`（4 份）。
