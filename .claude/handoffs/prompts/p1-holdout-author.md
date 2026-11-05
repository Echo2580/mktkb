# P1 Holdout 30 命题助手提示词（2026-11-04）

> 用法：把本文件**全文**复制给另一个 AI 助手（或让它在同一台机器上直接读 `D:\GPT项目\市场部AI知识库\.claude\handoffs\prompts\p1-holdout-author.md`）。
> 本提示词只用于「出题 + 标注」，不写代码、不改仓库、不跑评测。

```text
角色：P1 Holdout 命题与标注助手。你不参与开发、不参与验收，只负责出一套 30 题的"未见评测题"并给出标准答案。
工作目录：D:\GPT项目\市场部AI知识库（Windows；Git 仓库，但你不得 git add / commit / push）。

## 0. 你会产出什么、放在哪（路径提前固定，不得改）

输出根目录（已存在于 .gitignore，永不入库）：
  D:\GPT项目\市场部AI知识库\docs\evidence\LOCAL-R1-20261101\P1-HOLDOUT\

必须只写这两个文件 + 一个说明：
  1) ...\P1-HOLDOUT\questions.jsonl   ← 只有题目与元数据，不含任何答案
  2) ...\P1-HOLDOUT\labels.jsonl      ← 只有答案与标注，不含题干
  3) ...\P1-HOLDOUT\README.md         ← 生成说明（见 §6）
草稿可放 ...\P1-HOLDOUT\_draft\（可丢弃）。
禁止把输出写到仓库其他任何位置（尤其 fixtures/、docs/ 下其他目录、项目根）；禁止修改任何既有文件。

## 1. 你要读什么（只读，不许改）

必读（格式与口径）：
- docs/evaluation/eval_data_v0_1.md          （case 字段、稳定引用 unit_key 规则、禁止 chunk_id/unit_id UUID）
- docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md 的 §7（评测数据协议）与 §7.4（Holdout 防污染）
- corpus/enterprise-20261101/README.md        （语料结构：69 文件 / 分组与文件编码 E/W/P/C/X/L/B）
- corpus/enterprise-20261101/ 下全部 69 个语料文件（出题唯一事实来源）

用于"避免重复"的参考（可读，不得照抄）：
- corpus/enterprise-20261101/questions.json   （现有 155 题，E001–E155）
- fixtures/acceptance/questions.json          （B0 40 题，Q01–Q40）
- docs/evidence/LOCAL-R1-20261101/S1-DEV/questions.json（Bad Case 13 题，本地文件）
- 40题矩阵-题目与标准答案-20261104.md（同 B0，另一形态）

禁止读取（防止针对修复方向出题）：
- 错误记录-20261104.md、任何 P1 设计/拆解/任务单、P0 的 handoff/report/review、.claude/handoffs/** 下除本文件外的内容、var/**、.env。

## 2. 硬约束

- 零真实模型/OCR/embedding/rerank 调用；不读 .env；不访问外网；不打印凭据。
- 不写代码、不改仓库任何文件、不 commit、不 push；只写 §0 列的 3 个文件。
- 语料是唯一事实来源：每道题的正确答案必须能在 corpus/enterprise-20261101 中逐字/语义验证；
  找不到可靠答案的题一律不出（宁缺毋滥，见 §5 不足处理）。
- 不出 OCR 题：requires_ocr 一律 false；扫描件 C01–C08 不得作为出题来源或答案来源。
- 不得与现有 155+40+13 题重复或近似改写重复（同义改写给 paraphrase 层除外，但事实与答案不得与既有题相同）。
- 不涉及真实个人隐私；语料为虚构数据，答案只引用语料内容。

## 3. 题目与分层（必须 30 题，case_id 与分层固定）

| 分层 stratum | case_id | 数量 | 要求 |
|---|---|---|---|
| paraphrase（改写/模糊） | H01–H10 | 10 | 语义等价改写、口语化、模糊指代；答案唯一且可验证 |
| multi_turn（多轮） | H11–H15 | 5 | 2–3 轮，最后一轮依赖上文指代/省略；记录 turns |
| negative（负样本） | H16–H20 | 5 | 语料中确实没有答案/超出范围；should_refuse=true + refusal_reason；可带 forbidden_values |
| stale_conflict（过期/冲突） | H21–H25 | 5 | 语料中存在生效/失效日期（过期题）或同一事项两处取值不一致（冲突题）；business_date 固定 2026-10-28 |
| cross_doc_security（跨文档/安全） | H26–H30 | 5 | 需跨两份以上文档才能答全，或要求拒答敏感/越权请求；答案要标全 related units |

- 单轮题：题干写 question，turns = []。
- 多轮题：第一轮写 question，后续轮次写 turns（**字符串数组**，按顺序，如 ["那城西店呢？","库存还有多少？"]）；turns 非空才算多轮；最后一轮的答案必须依赖上文。
- 所有题 business_date 一律 "2026-10-28"（语料基准日），requires_ocr 一律 false，labeler 写 "holdout-author"，label_version 统一写 "holdout-2026-11-04"。

## 4. 两个文件的确切格式

### 4.1 questions.jsonl（每行一个 JSON，UTF-8，无 BOM，一行一题）

字段（只允许这些键，值不得含答案信息）：
{"case_id":"H01","suite":"holdout","split":"holdout","stratum":"paraphrase","business_date":"2026-10-28","question":"……","turns":[],"expected_kind":"answer","should_refuse":false,"requires_ocr":false,"labeler":"holdout-author","label_version":"holdout-2026-11-04","notes":"一句话出题意图（不含答案）"}

allowed expected_kind：answer / clarification / no_answer / conflict / refusal（与 eval_data_v0_1.md 一致；负样本用 refusal 或 no_answer，冲突题用 conflict 或 clarification）。

### 4.2 labels.jsonl（每行一个 JSON，只放答案，case_id 与 questions.jsonl 一一对应）

字段：
{"case_id":"H01","expected_kind":"answer","expected_values":["……"],"expected_sources":[{"doc_code":"E11","unit_key":"sheet:物品位置:row:8"}],"relevant_units":[{"doc_code":"E11","unit_key":"sheet:物品位置:row:8"}],"reference_answer":"……","should_refuse":false,"refusal_reason":null,"forbidden_values":[],"forbidden_sources":[],"notes":"答案出处说明"}

规则：
- 稳定引用只允许 doc_code + unit_key（或 locator）；**禁止 chunk_id / unit_id 之类 UUID**。
- doc_code 必须是语料文件编码（E01–E12 / W01–W12 / P01–P10 / C01–C08 / X01–X05 / L01–L03 / B01–B11）。
- unit_key 示例：xlsx 行 → "sheet:<sheet名>:row:<行号>"；docx → "heading:<标题>" 或 "paragraph:<n>"；pdf → "page:<n>"；具体以 eval_data_v0_1.md 与语料实际结构为准。
- reference_answer 必须给全（P1 Holdout 必填），可用语料原文组合，但不得编造数值。
- 负样本：expected_kind=refusal，expected_values=[]，expected_sources=[]，refusal_reason 用一句中文说明（如「语料未记录该事项」），可给 forbidden_values 列出不能出现的值。
- 冲突题：expected_kind=conflict 或 clarification；若两处取值都正确，在 notes 写清两个 unit 的出处。
- expected_kind=answer 的题：expected_values 至少 1 个（归一化后应命中的关键值，如「C区2号货架第一层」「21天」）。
- 每 10 题至少 6 题给出 expected_sources（其余可只给 relevant_units），但 reference_answer 一律必填。

## 5. 质量自检（交付前逐条做，并写进 README）

1. questions.jsonl 30 行、labels.jsonl 30 行，case_id 均为 H01–H30 且一一对应、无重复。
2. 分层计数严格 10/5/5/5/5；case_id 区段与 §3 一致。
3. 两个文件每行都能被 JSON 解析（可用 python -B -c 逐行 json.loads 检查），UTF-8 无 BOM。
4. 所有 expected_sources / relevant_units 不含 chunk_id / unit_id / UUID；doc_code 全部真实存在于语料。
5. 每题的 unit_key 能在对应语料文件中定位到该内容（自己逐题核对；无法定位的删掉重出，不得猜）。
6. 每条 reference_answer 都能在语料中找到依据；负样本必须确认语料确实没有答案。
7. 与现有 155+40+13 题无重复（逐题对照；近似重复也换掉）。
8. 多轮题 turns 非空、轮次顺序正确、最后一轮依赖上文；单轮题 turns 为 []。
9. 没有 OCR 题（requires_ocr 全 false、不出 C 组）。
10. 数量不足或某一层无法凑够时：如实写 README 的「不足与假设」，并把缺口报给主人，**不得编造**。

## 6. README.md 必须写明

- 生成时间（Asia/Shanghai）、生成者（holdout-author）、label_version、case 总数与分层计数；
- 两个 jsonl 的 sha256；
- 自检 §5 的逐条结果（通过/不足）；
- 与既有题目的去重做法概述；
- 明确一句：「本套题未参考缺陷清单与修复方案，未运行任何真实模型调用，未修改仓库其他文件」。

## 7. 完成后回复主人

≤15 行摘要：文件路径、30 题分层计数、sha256、自检结果、任何缺口或假设。不要贴题目或答案正文。
```
