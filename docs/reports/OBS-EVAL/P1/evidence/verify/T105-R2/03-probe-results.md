# T105 R2 独立 HTTP 探针结果（verify/T105-R2/03）

- 脚本：`02-probe.py`（验收方独立编写；未 import 开发方 `test_p1_t105_*`，只复用 `backend/tests/conftest.py` 的登录/上传工具与 `EchoGateway` 思路）。
- 路径：`create_app` + `TestClient` 真实 HTTP（上传→worker→发布→`POST /conversations/{id}/messages`），隔离临时 SQLite/数据目录；零真实模型/embedding/rerank/OCR，未读 `.env`/Holdout。
- 夹具：12 行 × 8 列 xlsx（12 家门店的“宣传海报”，标识/门店/物品/别名/位置/数量/参考供价/规格型号）；另发布 `W02_广宣物料与道具管理办法.docx`、`W10_品牌视觉与物料印制规范.docx`、`corpus/enterprise-20261101/legal/明码标价和禁止价格欺诈规定（国家市场监督管理总局令第56号）.docx`，以及自建 `poster-production-spec.docx`（打印材质/陈列要求/盘点时间/审批流程）。
- 三棵树同一脚本、同一夹具：当前 `fc60c57`（58/62 checks）；基线 `17c0e63`（32/62）；R1 父 `2306aaa`（32/62）。基线/父树用 `git archive 17c0e63|2306aaa` 解压到 `%TEMP%\t105-r2-*`，运行时 `T105_ROOT=<树根>`、`T105_OUT=<json>`；`mktkb.__file__` 分别指向 `%TEMP%\t105-r2-baseline\backend\src\mktkb\__init__.py`、`%TEMP%\t105-r2-parent-2306aaa\backend\src\mktkb\__init__.py`（已打印，见日志）。
- 当前运行：`$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T105-R2\02-probe.py`（默认写 `backend\.pytest-tmp\T105-R2\probe-results.json`）。
- 原始 JSON（临时，不入库）：`backend\.pytest-tmp\T105-R2\probe-results.json`、`%TEMP%\t105-r2-{baseline,parent}-probe-final.json`。

## 1. B1 分页/枚举（当前 8/8 PASS）

| 场景 | 当前 `fc60c57` | 父 `2306aaa` | 基线 `17c0e63` |
| --- | --- | --- | --- |
| 枚举 `把宣传海报都列出来` | answer，`{page:1,total:12,returned:10,has_more:true}` | 同 | 同 |
| 枚举→`那个海报的第2页` | **answer，`{page:2,total:12,returned:2,has_more:false}`，266 字** | **clarification 31 字，pagination=null** | answer，page2，266 字 |
| 枚举→`第2页`（无指代） | answer page2，266 字 | 同 | 同 |
| 枚举→`那个海报的下一页` | answer page2，266 字 | 同 | 同 |
| 显式 `把那个海报的位置列出来`/`全部信息` | 分页 total=1；`全部` 非澄清 | 同 | 同 |
| 无上文 `那个海报呢`/`那个呢` | clarification 31/20 字，0 字段值，sources=[] | 同 | `那个海报呢` 576 字 8×8 倾倒 |

## 2. B2 点名项（当前 PASS）

| 场景（上文均为 `城西店的宣传海报在哪里？`） | 当前 | 父/基线 |
| --- | --- | --- |
| `那个海报的规格型号呢` | answer 29 字，仅 `A2 铜版纸 157g`，0 标识/分页 | answer 576 字，8 条×8 字段 |
| `那个海报的打印材质呢` | not_found 35 字，0 记录字段/0 未问值，sources=[] | answer 576 字，8×8 |
| `那个海报的陈列要求呢` | not_found 35 字，同上 | answer 576 字，8×8 |
| `那个海报的位置呢`/`数量呢`/`参考供价是多少` | answer 27/20/23 字，仅该字段 | 位置 43 字（含门店/物品/别名）；数量/价格 576 字 |
| not_found 后再 `那个海报呢` | answer 27 字，仅位置 | answer 27 字，仅位置 |

## 3. §5-2/§5-3：政策/法规/正文追问（触发 B2 FAIL）

| 场景（上文均为 `城西店的宣传海报在哪里？`，另注明者除外） | 当前 | 父 `2306aaa`/基线 `17c0e63` | 判定 |
| --- | --- | --- | --- |
| C3 `那个海报的档期物料要提前多少天提报需求？` | **not_found 35 字**（0 泄露） | answer 576 字，8×8 倾倒 | §5-3 字面为保守化；但单独 D4 可答 21 天 → §5-2 过度拦截 |
| C4 `那个海报的《明码标价和禁止价格欺诈规定》自何时起施行？` | **not_found 42 字**“未在资料中找到城西店的宣传海报记录…” | answer 576 字，8×8 | 记录存在，文案不实；未答法规 |
| C5 `那个海报的价格欺诈规定是什么？` | **answer 27 字：位置 C区2号货架第一层** | answer 576 字，8×8 | **错误字段答案（阻断）** |
| C5b `那个海报的相关规定是什么？` | **answer 27 字：位置** | answer 576 字，8×8 | 同上 |
| C5c `那个海报适用的价格欺诈规定是什么？` | **answer 27 字：位置** | answer 576 字，8×8 | 同上 |
| C5d 上文问规格→`那个海报的价格欺诈规定是什么？` | **answer 29 字：规格** | answer 576 字，8×8 | 同上（继承字段随上文变化） |
| C6 `那个海报的审批流程是什么？` | not_found 35 字 | answer 576 字，8×8 | 政策/流程被压成未记录 |
| C7 `那个海报的盘点时间是什么？` | not_found 42 字（记录存在但无日期字段） | answer 576 字，8×8 | P2 文案/字段残余 |
| C1 `档期物料要提前多少天提报需求？`（无指代） | answer 518 字，含 21 天，无城西店 | 同 | PASS（T102 行为不变） |
| C2 单独 T101 法规题 | answer 861 字，含 2022年7月1日 + 两项废止规定 | 同 | PASS（T101 行为不变） |
| C8 `那个流程要提前几天提报`（无记录实体） | answer 139 字，含 21 天/审批流程 | 同 | PASS（不进入新分支） |
| D1/D2/D3 单独 `宣传海报的打印材质/陈列要求/审批流程` | answer 576 字，8×8（未取正文） | 同 | 说明打印材质/陈列要求不是 §5-3 基线可答问题 |
| D4 单独 `档期物料要提前多少天提报需求？` | answer 518 字，含 21 天 | 同 | 证明 C3 本可从正文答 |

## 4. 根因（代码级）

`backend/src/mktkb/rag/query.py:1336-1352`：

- `anaphora_new_content` 条件含 `and not is_regulation_question(question)`，但**不排除 `is_policy_question`**；C3/C6 因此进入 `ANAPHORA_NEW_CONTENT` → `answer.py:230-238` 直接 `_no_answer`。
- `elif explicit_record_entity and is_anaphora_field_followup(question, state.field_role)` **没有政策/法规守卫**；C5/C5b/C5c/C5d 的 `is_regulation_question=True`、`field_roles=()`，但继承的 `state.field_role=location/spec` 使 `is_anaphora_field_followup(..., 'location')=True`，置 `enumerate=True` → `_rag_owns_turn` 走 RAG → `_answer_record` 单字段渲染继承字段。
- 谓词实测（当前树）：

| 问题 | `is_regulation_question` | `is_policy_question` | `field_roles_for_question` | `is_anaphora_field_followup(...,'location')` |
| --- | --- | --- | --- | --- |
| C5/C5b/C5c/C5d | True | True | `()` | True |
| C3 | False | True | `()` | True |
| C6 | False | True | `()` | True |
| C7 `盘点时间` | False | False | `('date',)` | True |
| `那个海报的规格型号呢` | False | False | `('spec',)` | True |

## 5. 结论

- B1 已修复；B2 的点名三问（规格/打印材质/陈列要求）已收窄。当前 58/62 checks，4 个失败全为 C5 系列“法规追问 → 继承字段答案”。
- 这不是 §5-3 的 `not_found` 保守化，而是 §5-2 的“扩大拦截 + 错误字段答案”；父/基线均为 576 字倾倒，R1 的 `elif` 新引入了 27/29 字的错误答案。建议最小修复：`anaphora_new_content` 与 `elif` 均加 `not is_policy_question(question)`（必要时对政策/法规题重置继承 `field_role`/走 document），并补 T101/T102 组合用例。
