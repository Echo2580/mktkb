wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T103 独立验收 review（D4 记录路回落语义检索，ERR-04）

- 验收对象：`p1/fix-retrieval` @ `43b7976`（HEAD `dcb7054` 仅为 PM 裁定记录）；基线 `43b7976^`=`cbc40f8`。本人未改交付物、未 commit/push/切分支；`git status --short` 为空。
- 方法：`report.md` 只当线索；所有 PASS 均来自本人复跑/自建探针（证据 `docs/reports/OBS-EVAL/P1/evidence/verify/T103/01..04`）。零真实模型/embedding/rerank/OCR。

## 1. 必须复跑（cwd=仓库根，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）

| # | 范围 | 结果 | 判定 |
| --- | --- | --- | --- |
| 1 | 本包 2 文件 | **6 passed**（1.70s） | PASS |
| 2 | `backend/tests/unit` | **306 passed**（6.92s） | PASS |
| 3 | `backend/tests/integration` | 首次 **352 passed + 1 failed**（280.44s）；`test_g08_short_budget_cancels_inflight_model_call` 隔离复跑 **1 passed**（1.47s，既有 flake） | PASS |
| 4 | `backend/tests/observability` | **255 passed**（17.50s） | PASS |
| 5 | 全量 `backend/tests` | **1640 passed / 0 failed / 0 error**（425.35s，跑前空闲内存 2.68GB） | PASS |
| 6 | `frontend` | `npm run typecheck` exit 0；`npm run build` exit 0（vite 255ms） | PASS |

命令均含 `-B -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`；无 skip/xfail/删断言（commit 仅新增 2 个测试文件）。

## 2. 重点证伪（PM §9 条件逐条）

**① 本地文本诚实 — PASS**
- RG004 local：`path=rag`、`kind=no_answer`、`reason=DOCUMENT_NOT_FOUND`、文本「资料“物料领用通知”未收录，未使用其它资料替代。」（`cases.jsonl` / trace `646bf907…`）；无「该历史消息未保存候选明细」「符合条件的记录过多」。
- 我按 49 份本地装配语料复核：`物料领用通知`/`登记表`/`领取`/`先填写` 均 0 命中；C01–C08 扫描件因 `subset_group:scan` 全 skipped；`填写` 仅 2 条无关正文。本地离线可达范围内不存在可回答内容，`no_answer` 诚实。
- 前端：`MessageCard.tsx:135-141` 仅对 `live` 零候选显示「本次回答没有返回可选项…」；历史加载分支（`:141-144`）保留原文案；`ChatPage.tsx:183,193,343` 以 `message_id` 绑定 live，分叉可达。typecheck/build 通过。

**② 强制 truncated 的 document/record 两分支 — PASS**
- document（探针 C）：真实上传 filler+target；包装 `_retrieve` 使 broad 多词（limit=20/100）**排除 target** 且 `truncated=True`，单检索词走真实检索 → `kind=answer`，文本含「领取活动物料前，请填写领用登记表」，来源含 `target.docx`；broad 已排除 target，故目标只可能由逐词回落带回。
- record（探针 C，未 monkeypatch）：真实 120 个物品组 → `kind=clarification`「匹配到 120 条候选记录…已列出前 8 条候选…缩小范围」，`candidates=8`。
- trace：两分支均出现 `filter_decisions_json.record_overshoot_*`（document `term_union/total=11`；record `record_candidates/total=120`），`validate_required_spans==[]`；产品八题也逐个出现 marker（证据 02 §D）。
- 开发集成用例的假 `_retrieve` 每次都返回同一 target，只证明分支进入；target 被首 100 挤出的真实场景由探针 B/C 补齐（证据 02 §E）。

**③ RG001–RG003 / RG005–RG007 — PASS**
- RG001–003 仍 PASS；RG005/RG006/RG007 仍 RED，失败 check 集合分别为 `kind_correct+refusal_expected` / `value_forbidden+kind_correct` / `kind_correct+refusal_expected`，与 T102 收口逐条相同。

**④ gate 无新 hard failure — PASS**
- b0 `hard=[]`（exit 3）、badcase `hard=[]`（exit 3）、regression `hard=['security_leak']`（exit 1，与 T102 相同）；三套 `trace_integrity=pass`。

**⑤ RG004 非“口径伪装” — PASS**
- `regression.jsonl` 逐 case 对比父提交：仅 RG004 一行变化（`expected_kind no_answer`、`should_refuse=true`、补 `refusal_reason`、`notes`），`forbidden_values` 原样保留；其余 6 行字节级不变。
- 本地不存在可回答正文（见①），因此不是“本应 answer 被收口为 refuse”；`should_refuse=true` 与 local `no_answer/refused=true` 一致。

**⑥ 回落是真的，不是换皮 — PASS**
- Q34：limit=100 `total=281`、首 100 文档 {D04,D09,E02,E03,法规}、`target_in_first100=[]`；逐词「扫描」total=7(D07)、「活动」17、「申请」11；并集 118；既有 `_rank_document_units` top8 = **D07×8**。真实证据被挤出→回落带回→既有排序取到。

**⑦ 八题端到端 — PASS**
- `var/mktkb.sqlite3` 只读副本 + 回显替身（`rag_qa_enabled=False`）：父提交八题全部 `clarification/0 候选/0 来源` + 「符合条件的记录过多…」；当前八题全部 `answer/8 来源`，关键来源含 D03/D05/D07/D08/D09；无禁用文本。
- 零真实 provider：`non_loopback_network_attempts=[]`；`qa=None`、`ocr=None`、`model=EchoGateway`；evaluation local 强制 `provider_mode=offline`（`runner.py:314-318`）。

**⑧ 不误伤 — PASS**
- b0/badcase 对 P0 基线逐例 `(status,kind,reason,failed,path)` **case_diffs=0**；b0/badcase 文本无禁用短语。
- base vs current 独立探针：4 个普通题（海报位置/法规日期/海报数量/废止规定）`kind/text/sources` 逐字相同；仅 overshoot 题变为 answer。
- `filter_decisions_json` 未破坏 trace：gate `trace_integrity=pass`、observability 255 passed、探针必需 span 完整；API schema/响应字段无 diff。

## 3. 范围 / 格式 / 证据

- `git show --stat 43b7976`：10 files，+633/−6；`service.py +87/−5`、`MessageCard.tsx +5`、`regression.jsonl +1/−1`、2 个新测试文件、4 份证据、report 41 行；全部在允许路径。未触碰 b0/badcase/gate/budget/GO/账本/`.env`/Holdout。
- 证据 4 份（≤4）：`verify/T103/01-pytest.md`、`02-fallback-probes.md`、`03-eval-runs.md`、`04-scope-and-format.md`；report 五段 41 行（≤80）、首行模型行、commit 1 个。

## 4. 残余风险 / 未跑项 / 判定

- **FAIL：无。BLOCKED：无。**
- 风险（非验收失败）：R1 document 回落把澄清变为 answer，回显探针显示 8 条证据可带入 E01 等泛化正文，真实模型可能偏泛化；R2 逐词并集仍按 100 截断（Q34“日期”264），换语料不保证命中；R3 record overshoot 在生产 `rag_qa_enabled=True` 时受 rag 候选约束，可达性未证明（合成 `rag_qa_enabled=False` 覆盖分支）；R4 RG004 `forbidden_values` 未含旧错文「符合条件的记录过多」，靠 `expected_kind` 兜底，dataset 层禁止值偏弱；R5 开发集成假 `_retrieve` 每次返回 target，只证明分支进入，由本人探针补齐。
- NOT-RUN（按约束）：真实模型/embedding/rerank/OCR；Holdout；真实 OCR 解析链路（b0 Q34/Q35/Q37/Q38 仍 `skipped_requires_ocr`）；T109 多轮 runner（不属本包）。
- **判定：通过（PASS）**——PM §9 ①–⑤ 全部满足；回落为真实检索行为，八题不再是无解澄清，b0/badcase/regression 无 case 级回退或新增 hard failure。
