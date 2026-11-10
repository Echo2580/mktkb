wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T102 独立验收 review（组 A 状态继承 ERR-01/ERR-02/D5）

- 验收对象：`p1/fix-retrieval` @ `85d9ffc`（单 commit）；基线 `9fa8101`。本人未改交付物、未 commit/push/切分支；`git status` clean。
- 方法：只把 `report.md` 当线索；所有 PASS 均来自本人复跑/自建探针（证据 `docs/reports/OBS-EVAL/P1/evidence/verify/T102/01..04`）。零真实模型/embedding/rerank/OCR。

## 1. 必须复跑（全部本人执行，cwd=仓库根，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）

| # | 范围 | 结果 | 判定 |
| --- | --- | --- | --- |
| 1 | 本包 2 文件 | **20 passed**（2.13s） | PASS |
| 2 | `backend/tests/rag` | **326 passed**（21.88s） | PASS |
| 3 | `backend/tests/integration` | **350 passed + 1 failed**；`test_g08_short_budget_cancels_inflight_model_call` 隔离复跑 **1 passed**（既有 0.2s 预算 flake） | PASS（§11A） |
| 4 | `backend/tests/observability` | **255 passed**（17.71s） | PASS |
| 5 | 全量 `backend/tests` | **1634 passed / 0 failed / 0 error**（394.71s，跑前空闲内存 2.7GB） | PASS |

命令均含 `-B -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`；无 skip/xfail/删断言（`git show --name-status 85d9ffc` 仅新增 2 个测试文件）。

## 2. b0/badcase local run + gate（独立复现）

```text
b0      pass29/fail3/skipped8（Q25,Q26,Q31；Q33–Q40 skipped）；gate exit3 hard=[]
badcase pass9/fail4（N05,N06,N09,N11）；gate exit3 hard=[]
```

- 与 P0 `var/eval/runs/p0-b0|p0-badcase` 逐例投影 `(status,outcome.kind,outcome.reason,failed checks,path)`：`case_diffs=0`；trace 表全字段（剔除 id/time/latency）`diffs=0`，span 367/129 多重集相同。
- 与开发证据 01/02 的前后对照一致。**PASS**。

## 3. regression local run + gate

- `run_id=regression-local-20261105T174337218586Z-fdff5e1b`；`pass3/fail4`；gate exit1，`hard_failures=['security_leak']`（无新名称；`pagination_contract` 消失属允许收敛）。
- **RG001 PASS**：`answer`，3 值齐备（L02 paragraph:39）。
- **RG002 PASS**：`clarification`「资料中没有收录“城西区”这个门店/区域…」；不含 `城东店`/`B区1号货架`/`滨江店`/`店内外侧`；无来源。
- **RG003 PASS**：`answer`「根据资料，档期物料须提前 21 天提报。」；不含 `卓刀河店`/`马克杯`；来源 W02。
- **RG004–RG007** 失败 check 与 T101 收口记录逐条相同（`kind_correct+refusal_unexpected` / `kind_correct+refusal_expected` / `value_forbidden+kind_correct` / `kind_correct+refusal_expected`），未被改弱或顺手修好。**PASS**。

## 4. 两条多轮独立复现（自建 HTTP 产品路径 + parse 对照）

- 探针：真上传→worker→发布→多轮；资料 D01+E11+W02；模型为离线回显替身；`%TEMP%\t102_probe_http.py`。
- ① 城东店海报→「城西区」：base 答 `城东店/B区1号货架第二层`；当前 `clarification`，不含城东店/B区。**PASS**
- ② 滨江店海报→「城西区」（真实语料 RG002 同型）：base 答 `滨江店/店内外侧`；当前 `clarification`，不含两者。**PASS**
- ③ 卓刀河店马克杯 QF21→「档期物料…给出所有内容」：base 枚举回显「卓刀河店马克杯」；当前 `answer` 含 `21 天`、不含 `卓刀河店`/`马克杯`。**PASS**
- ④ 澄清后补「城西店」：第三轮正确答 `C区2号货架第一层`，state 未被「城西区」污染。**PASS**

## 5. 过度收紧/误伤（同一探针 base vs 当前逐字对比）

| 探针 | 结果 | 判定 |
| --- | --- | --- |
| 合法门店「城西店」「滨江店」 | 均正常命中（C区2号货架第一层 / 店内外侧），与 base 相同 | PASS |
| 裸门店 follow-up「城西店」 | 继承物品，答 C区2号货架第一层；与 base 相同 | PASS |
| 「那家店呢」 | not_found；base 亦 not_found（既有产品层行为，非 T102 回归） | PASS（不变） |
| 「换成滨江店」 | 切换生效、无城东店；与 base 相同 | PASS |
| 政策题紧跟实体题 | 答 21 天；与 base 相同 | PASS |
| 真正缺字段（采购价格，带/不带实体） | `not_found 资料中未记录：采购价格。`；与 base 相同 | PASS |
| T101 法规题 | RG001 PASS；155 题单轮 parse sweep `changed=0`；b0/badcase 逐例 0 差异 | PASS |
| 全语料 155 题 sweep | prev=None 变化 0；prev=滨江店+海报 62 题仅清旧实体，新澄清 0、reason 变化 0 | PASS |

**残余风险（非验收失败项，证据 03 §C）**：
- R1 区域词启发式会把「物料区/陈列区/收银区/展示区」等 2 字店内位置误判为未知区域（澄清）；155 题语料与 b0/badcase/regression 均未出现该措辞。
- R2 无字段词 follow-up（那款呢/这款呢/保质期是多少/还有呢）由 base 继承改为 reset；字段词表内追问、指代、分页、裸补槽、切换词仍继承。
- R3 词表外 `*店` 在 parse/RAG 直答层仍继承上一轮门店（base 相同）；产品 HTTP 层为 `not_found`，未复现用户可见串店。开发证据 04 的“P0 live 测试锁定”理由未在只读核对中复现到关联。

## 6. 最小改动与范围合规

- `query.py` +190/−1，唯一改动源码；`answer.py`、`conversations/`、`qa/`、`types.py` 零改动（`git diff --name-only` 为空）。
- 未发现死代码/重复函数；`is_policy_question` 复用 `is_regulation_question`；`_RAG_OWNED_CLARIFICATION_FILTER` 仅在 `query.py:207,1204`，`answer.py:85-99` 澄清分支先于检索返回，未检索/未持久化（第三轮补门店已验证）。
- `regression.jsonl` 仅 RG002/RG003 两行变化；RG001/RG004–RG007 未动；禁止项（budget/GO/账本/b0/badcase/gate/.env/Holdout）未触碰。**PASS**。

## 7. 证据与报告格式

- 证据 4 份（≤4）`verify/T102/01..04`；report 首行模型行、五段、47 行（≤80）。**PASS**。

## 8. 判定

- **通过（PASS）**：T102 验收 §6.1–§6.7 全部满足；ERR-01/ERR-02 在独立产品路径复现为修复态，b0/badcase/回归无 case 级回退，T101 未被改坏。
- FAIL：无。BLOCKED：无。
- NOT-RUN（按约束）：T109 多轮 runner（依赖 T109，不属本包）；真实模型/embedding/rerank/OCR（禁止）；Holdout（禁止）。R1–R3 为已记录残余风险，是否另立任务由 PM 裁量。
