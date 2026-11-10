# P1FIX-A 证据：越界财务指标拒答（RG005/RG007）与正向控制

> 分支 `p1/fix-retrieval`，起始 HEAD `3eec866`（本次改动未提交，均为工作区改动）。
> 零真实 provider/网络；数据仅用公开语料 `corpus/enterprise-20261101` 与公开 fixtures。
> 未读 Holdout 逐题/答案；本文件不含任何 Holdout 内容。

## 1. 原失败（可复现）

命令（修复前，工作区 HEAD 代码）：

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite regression --mode local `
  --out .claude\handoffs\_scratch\p1fix\before-regression
```

结果：`status_counts={'fail': 2, 'pass': 5}`；RG005/RG007 两条冻结用例
`kind_correct`、`refusal_expected` 均 fail：

| case | 修复前 kind | 修复前实际回答（摘录） | 引用 |
| --- | --- | --- | --- |
| RG005 公司今年营收是多少 | `answer` | 「根据资料，启沣饮品（苏城）有限公司 市场部｜启市字〔2026〕41号」 | X01（无关资料） |
| RG007 公司今年的利润率是多少 | `answer` | 「根据资料，第一条 新品指公司首次进入流通的单品…」 | W09（无关资料） |

原始产物：`.claude/handoffs/_scratch/p1fix/before-regression/`（`summary.json`、`cases.jsonl`、`dump.txt`）。

## 2. 根因（意图识别 / 资料支持判定 / 路由 / 回答阶段）

1. **意图识别**：`conversations/intent.py` 与 `rag/query.py` 都没有“公司级经营/财务指标”这一类
   语料不覆盖的语义；`营收/利润率` 既不进记录字段也不进缺失字段，问题被当作普通正文题。
2. **资料支持判定**：`rag/answer.py::_document_fallback` 只要有任意证据且 `_best_sentence` 命中
   任一问题词（如“公司”）就输出「根据资料，…」，没有“证据是否真的支持所问指标”的判定。
3. **路由**：产品路径 `conversations/service.py::_answer` 在文档题命中证据后会进入模型措辞/答案
   阶段；本地离线 eval 直接 `index.ask`，两条路径都没有“提前判无依据”的分支。
4. **回答阶段**：无证据支持时不拒答，用弱相关段落拼答案（甚至引用无关资料），违反“无依据应拒答”。

## 3. 修改（最小、可解释）

| 文件 | 修改 |
| --- | --- |
| `backend/src/mktkb/rag/query.py` | 新增 `FINANCIAL_METRIC_TERMS`（营收/营业收入/营业额/利润/净利润/利润率/毛利率/净利率/市值/资产负债/现金流 等同义词组）与 `financial_metric_question()`；法规/制度题（`is_regulation_question`）不判越界；新增 `texts_support_financial_metric()`：指标词必须与数值/百分比同窗出现才算“资料有支持”。 |
| `backend/src/mktkb/rag/answer.py` | 检索后、答案生成（含 live chat）前做支持判定：无支持 → `kind=no_answer`、`reason=UNSUPPORTED_FINANCIAL_METRIC`、无 citations；有支持 → 保持原路径。 |
| `backend/src/mktkb/conversations/intent.py` | `IntentPlan.out_of_scope` + 早期标记（走正文检索以做支持判定，不直接按题干拒答）。 |
| `backend/src/mktkb/conversations/service.py` | 产品路径在检索后、`query_expansion`/模型调用前做同一支持判定；无支持返回 `not_found`，不进入 chat 生成。 |
| `backend/src/mktkb/copy.py` | 新增 `UNSUPPORTED_FINANCIAL_METRIC` 诚实文案（说明“找到的资料没有可支撑数据”，不冒充服务故障、不编造）。 |
| `backend/src/mktkb/qa/service.py` | `QA_ENGINE_VERSION` `s2-a-1`→`s2-a-2`（行为语义变化，新 run pipeline_version 与旧 baseline 区分；见 E5/D）。 |

## 4. 修复后验证

### 4.1 冻结 regression（原检查转绿，期望值/标签/评分规则未改）

命令同 §1（输出到 `_scratch/p1fix/final-regression`）：

```text
status_counts={'pass': 7}  error_count=0
RG005 | status=pass | kind=no_answer
RG007 | status=pass | kind=no_answer
RG005 文案：找到的资料中没有可支撑“营收”的经营财务数据，不能据此推算或编造；
          这不是服务故障，请改问制度、价目表、台账等资料已覆盖的内容后重新查询。
RG007 文案：找到的资料中没有可支撑“利润率”的经营财务数据，不能据此推算或编造；…
citations=[]（两条均无来源）
```

### 4.2 同义改写/不同句式（公开独立数据，非改冻结用例）

新增 `fixtures/evaluation/refusal-controls-2026-11-10.jsonl`（独立文件、`label_version=p1fix-refusal-controls-2026-11-10`；
20+ 用例：12 条越界财务问法 + 10 条正向控制），由
`backend/tests/evaluation/test_p1_refusal_controls.py` 在 offline 全量语料索引上执行：

- 拒答变体全部 `kind=no_answer / reason=UNSUPPORTED_FINANCIAL_METRIC / citations=[]`：
  营业收入、营业额、净利润、毛利率、净利率+利润率、市值、经营现金流、亏损、资产负债率、
  祈使句“帮我查一下…”等；
- 正向控制保持可答：台账位置/数量/规格、标识定位、法规施行日期、制度时限、价目表组合价、
  黄金陈列位高度、Q3 销量（“销量”不是越界财务指标）、未知区域澄清、预算/审批题；
- 采购价格题（`滨江店的宣传海报的采购价格是多少？`）按既有“冲突值”口径作答，**未被**越界规则拒答。

命令与结果：`pytest backend\tests\evaluation\test_p1_refusal_controls.py -q` → **23 passed**
（含单元分类/支持判定、数据契约、语料级拒答与正向控制、冻结 RG005/RG007 复核）。

### 4.3 spy 证明“明确越界拒答路径没有 chat 调用”

`backend/tests/integration/test_p1_refusal_scope_http.py`（真实 HTTP + `EvidenceEchoGateway` 调用 spy，
零真实调用）：对 6 条越界问法逐条断言 `kind=not_found`、`sources=[]`、文案诚实，且
`len(model.calls)` 在拒答前后**不增加**；同时正向控制“城东店的宣传海报在哪里？”仍 `kind=answer`
且模型被调用（证明没有把整条链路关掉）。结果 **3 passed**。

## 5. 剩余问题（如实）

- 指标词表是“类”级语义（公司级经营/财务结果指标），不是语料支持与否的全集判定；若未来语料
  收录同类指标，`texts_support_financial_metric` 会在有“指标词+数值”证据时正常作答（本次用
  合成文本单测锁定该行为），但**未**用真实支持语料端到端验证（当前公开语料不含此类数据）。
- 标价/法规/制度题不在此规则内（`is_regulation_question` 直接跳过）；跨行业术语（如“GMV/ARR”）
  未纳入词表，属后续语料扩展项，不在本次范围。
