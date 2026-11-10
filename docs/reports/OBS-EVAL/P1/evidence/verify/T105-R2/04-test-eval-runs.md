# T105 R2 独立复跑：测试 / 评测 / 合规（verify/T105-R2/04）

环境：Windows；cwd=`D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；每条 pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；命令统一 `… -B -m pytest <路径> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T105-R2\<label>`；全量/集成前检查 `FreePhysicalMemory`，无并发 pytest。零真实模型/embedding/rerank/OCR，未读 `.env`/Holdout。

## A. 测试复跑（当前 `fc60c57`）

| # | 范围 | label | 结果 |
| --- | --- | --- | --- |
| 1 | 本包 2 文件（13 单测 + 10 HTTP） | `pkg` | **23 passed**，6.88s |
| 2 | `backend/tests/rag` | `rag` | **339 passed**，20.77s |
| 3 | `backend/tests/observability` | `observability` | **255 passed**，16.35s |
| 4 | `backend/tests/integration` | `integration` | **372 passed**，240.18s（无 flake，未触发隔离复跑） |
| 5 | 全量 `backend/tests` | `full` | **1701 passed，0 failed，0 error**，399.65s；跑前 `FreePhysicalMemory=3.59GB` |
| 6 | T101/T102 窄集（T101 集成 + T102 rag/integration + `test_query_state` + `test_s2b_intent_semantics`） | `t101-t102` | **37 passed**，20.47s |
| 7 | T101/T102 全集（含 unit `test_p1_t101_*`） | `t101-t102-all` | **44 passed**，12.73s |

- report §6 的 23 / 339 / 255 / 372 / 1701 / 44 全部复现一致；时间差异属正常波动。
- 上一轮 `test_g08_short_budget_cancels_inflight_model_call` flake 本轮 integration/全量均未出现。

## B. b0 / badcase（local run + gate，当前树）

命令：`python -B -m mktkb.evaluation.cli run --suite <b0|badcase> --mode local --out backend\.pytest-tmp\T105-R2\eval\<suite>`，随后 `gate --run <同上>`。未写 `var/eval/runs/p0-*`。

| suite | run_id | 状态 | gate | 与 `var/eval/runs/p0-*` 逐例 |
| --- | --- | --- | --- | --- |
| b0 | `b0-local-20261106T172003747773Z-7193bbc2` | pass 29 / fail 3 / skipped_requires_ocr 8 | exit 3，hard `[]` | **`case_diffs=0`（40/40）** |
| badcase | `badcase-local-20261106T172014584247Z-31b30089` | pass 9 / fail 4 | exit 3，hard `[]` | **`case_diffs=0`（13/13）** |

比较口径 `(case_id,status,outcome.kind,failed check ids)`；失败集仍为 b0 Q25/Q26/Q31、badcase N05/N06/N09/N11。

## C. regression（当前 vs `17c0e63`）

- 当前：`regression-local-20261106T172058239096Z-47cd7950`，pass 5 / fail 2（RG005/RG007），gate exit 3，hard `[]`。
- 基线：`17c0e63` 提取到 `%TEMP%\t105-r2-baseline`，`PYTHONPATH=…\backend\src`、cwd=基线树；`mktkb.__file__` 已确认指向基线副本。`regression-local-20261106T172239206383Z-5c26d774`，pass 4 / fail 3（RG005/RG006/RG007），gate exit 1，hard `['security_leak']`。
- 逐例：**仅 RG006** `fail/answer/(kind_correct,value_forbidden)` → `pass/clarification/()`；RG001–RG004 pass 不变；RG005/RG007 失败 checks 仍为 `kind_correct,refusal_expected`；gate hard 由 `['security_leak']` 收缩为 `[]`，无新增 hard 名。
- RG006 基线文本 `根据资料，滨江店的宣传海报（标识：QF01）位于店内外侧，数量 40 张。`（4 个未问值）；当前 `请问要查询宣传海报的哪项信息？…`（0 泄露）。

## D. 范围/合规（起始工作树 clean）

| 检查 | 结果 |
| --- | --- |
| 起始状态 | `git status --short` 空；分支 `p1/fix-retrieval`；HEAD `fecdfcc`；R1 `fc60c57` 父 `f1b96e2` |
| R1 commit | 仅 `fc60c57` 1 个 dev commit；7 文件：query.py、answer.py、2 测试、report、证据 03/04；均在允许路径 |
| `git diff 2306aaa..fc60c57 -- backend fixtures` | 仅 query/answer/2 测试（4 文件），fixtures 空 |
| PM commits（`2306aaa..fc60c57` 的 6 个） | 仅 `.claude/handoffs/**` + `docs/…/verify/T105/**`；无 backend/fixtures |
| 禁止路径 | 未改 `backend/src/mktkb/conversations/`、`intent.py`、fixtures/b0/badcase/gate；无第二 dev commit |
| 测试改动 | 仅新增/调整夹具签名；`git diff … backend/tests` 无删除断言；无 skip/xfail/mark |
| 证据 | `docs/…/evidence/T105/` 仍 4 份；03 §D、04 §E 含 R1 段 |
| report | 70 行、首行模型标注；§5 已修正“不会再整条倾倒”；§6 披露 B2 收窄/P2/观察项 |
| 未读/未调用 | 未读 `.env`/Holdout；零真实模型/embedding/rerank/OCR；未 push/amend/切分支/提交 |

## E. 报告/证据与复跑的差异

- 数字：23/339/255/372/1701/44、b0/badcase `case_diffs=0`+hard `[]`、regression 仅 RG006、gate 无新 hard——全部与 report §6 一致。
- report:68 的“`verify/T105/02-probe.py` 70/70 checks”是上一轮验收方脚本，其场景未覆盖“实体+指代+政策/法规”；本轮独立探针 58/62（4 个 C5 系列失败），故 70/70 不能作为 §5-2 全覆盖证据。
- report:66 / 证据 04:37 将“政策题+实体+字段词+指代”记为“观察（不阻塞）/未见回退”；本轮实测该组合返回继承字段答案（C5 系列），该判断不成立。
- 残余：C4/C7 的“未在资料中找到…记录”文案不实（记录存在，仅缺该字段/法规命中），记 P2；未跑真实模型/live、Holdout、T109 多轮 runner（边界禁用/未纳入）。
