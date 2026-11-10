# T105 R3 独立复跑：测试 / 评测 / 合规（verify/T105-R3/04）

环境：Windows；cwd=`D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；每条 pytest 前 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`；统一 `-B -m pytest <路径> -q -p no:cacheprovider --basetemp backend\.pytest-tmp\T105-R3\<label>`；同一时间只跑一套 pytest。零真实模型/embedding/rerank/OCR；未读 `.env`/Holdout。

## A. 测试（当前 `b37ad21`；§11A 各 1 次）

| # | 范围 | label | 结果 |
| --- | --- | --- | --- |
| 1 | 本包 2 文件 | `pkg` | **40 passed**，15.87s |
| 2 | `backend/tests/rag` | `rag` | **347 passed**，20.70s |
| 3 | `backend/tests/observability` | `observability` | **255 passed**，14.88s |
| 4 | `backend/tests/integration` | `integration` | **381 passed**，277.16s（无 flake，未触发隔离复跑） |
| 5 | 全量 `backend/tests` | `full` | **1718 passed / 0 failed / 0 error**，385.57s；跑前 `FreePhysicalMemory=4.1GB` |
| 6 | T101/T102 窄集 | `t101-t102` | **37 passed**，12.36s |
| 7 | T101/T102 全集（含 unit `test_p1_t101_*`） | `t101-t102-all` | **44 passed**，14.84s |

与 report §7：40/347/381/255/1718、37/44 全部一致；时间差异属正常波动。上一轮 `test_g08_short_budget_cancels_inflight_model_call` flake 未出现，无隔离复跑。

## B. b0 / badcase（local run + gate，当前树）

命令：`.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite <b0|badcase> --mode local --out backend\.pytest-tmp\T105-R3\eval\<suite>`，随后 `gate --run <同上>`；未写 `var/eval/runs/p0-*`。

| suite | run_id | 状态 | gate | 与 `var/eval/runs/p0-*` 逐例 |
| --- | --- | --- | --- | --- |
| b0 | `b0-local-20261106T182633804408Z-5d994af5` | pass 29 / fail 3 / skipped_requires_ocr 8 | exit 3，hard `[]` | **`case_diffs=0`（40/40）** |
| badcase | `badcase-local-20261106T182645606516Z-363c0a7d` | pass 9 / fail 4 | exit 3，hard `[]` | **`case_diffs=0`（13/13）** |

比较口径 `(case_id,status,outcome.kind,failed check ids)`；失败集仍为 b0 Q25/Q26/Q31、badcase N05/N06/N09/N11。

## C. regression（当前 vs `17c0e63` 基线）

- 当前：`regression-local-20261106T182718496600Z-646012b8`，pass 5 / fail 2（RG005/RG007），gate exit 3，hard `[]`。
- 基线：`17c0e63` 提取到 `backend\.pytest-tmp\T105-R3\trees\base`；`PYTHONPATH=…\backend\src`、cwd=基线树；`mktkb.__file__` 已确认指向基线副本。`regression-local-20261106T182849164146Z-27b0e384`，pass 4 / fail 3（RG005/RG006/RG007），gate exit 1，hard `['security_leak']`。
- 逐例：**仅 RG006** `fail/answer/(kind_correct,value_forbidden)` → `pass/clarification/()`；RG001–RG004 pass 不变；RG005/RG007 失败 checks 仍为 `kind_correct,refusal_expected`；gate hard 由 `['security_leak']` 收缩为 `[]`，无新增 hard 名。

## D. 范围/合规（起始工作树 clean）

| 检查 | 结果 |
| --- | --- |
| 起始状态 | `git status --short` 空；分支 `p1/fix-retrieval`；HEAD `ca88c9a`；R2 `b37ad21` 父 `cbbb241` |
| R2 commit | 仅 `b37ad21` 1 个 dev commit；7 文件：query.py、answer.py、2 测试、report、证据 03/04；均在允许路径 |
| PM commit | `ca88c9a` 仅 `.claude/handoffs/**`（3 文件）；无 backend/fixtures |
| `git diff 2306aaa..b37ad21 -- fixtures` | 空 |
| 禁止路径（`conversations/`、`intent.py`、b0/badcase/gate、fixtures、`var/eval`） | `git diff … --stat --` 全部为空；无第二 dev commit |
| 测试改动 | 仅两个 T105 测试文件追加；`git diff cbbb241..b37ad21 -- backend/tests` 删除行仅 2 个文件头；无 skip/xfail/mark |
| 证据 | `docs/…/evidence/T105/` 仍 4 份；03 §E、04 §F 含 R2 段 |
| report | 99 行、首行模型标注 `wb / cn:deepseek-v4.1-flash / reasoning_effort=max`；**99 > 80 行预算，记非阻塞观察** |
| 未读/未调用 | 未读 `.env`/Holdout；零真实模型/embedding/rerank/OCR；未 push/amend/切分支/提交 |

## E. report/证据 与复跑的差异

- 数字：40/347/255/381/1718、37/44、b0 pass29/fail3/skipped8、badcase pass9/fail4、`case_diffs=0`、gate hard `[]`、regression 仅 RG006——全部与 report §7 一致。
- 场景：C3 20 字、C4 136、C5 58/140/156/58、C6 37、C7 22、B2 29/35/27/20/23、D4 518、T101 861、C8 139——逐项复现一致。
- B1：report 266 字；本人探针 272 字，差 6 字符来自夹具文件名 `t105-r3-ledger.xlsx` 比 R2 探针 `t105-ledger.xlsx` 长 3（页 2 两条各带来源名）；`page=2/total=12/returned=2/has_more=false` 完全一致，非行为差异。
- report §7 的「独立探针 62/62」是开发方复跑上一轮验收脚本；本轮验收方新写探针 **133/133**，另覆盖「该海报」、not_found 后政策追问、字段同形组合，结论不变。
- report §7 已披露 C7 文案、`sources=[]`、`is_policy_followup` 词面限制；**未披露**「政策词+台账字段词」组合（`标准规格`/`价格标准`/`提交数量`）从 R1 单字段退回 legacy 576 字 8×8 的新副作用——记 P2 残余（不阻断，等于基线 `17c0e63`）。
- 残余：C4/C7 文案已修；`sources` 空为口径限制；未跑真实模型/live、Holdout、T109 多轮 runner（边界禁用/未纳入）。
