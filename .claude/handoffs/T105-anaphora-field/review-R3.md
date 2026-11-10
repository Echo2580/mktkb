wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T105 独立验收 review-R3（R2 返工复验，ERR-06）

**结论：PASS（无阻断；P2 残余 3 项）。** R2 判据 C3/C4/C5 系列/C6 全部按修复目标作答，C7 文案已准确；B1/B2 与控制组逐项保持；测试/评测数字全部复现。新发现「政策词+台账字段词」组合仍会 576 字 8×8 倾倒（相对基线不变差、相对 R1 是回退），不命中本轮命名判据，记 P2。证据：`verify/T105-R3/`（01-verdict、02-probe.py、03-probe-results、04-test-eval-runs）。

## 1. 范围/合规：PASS

- 起始 `git status --short` 空；分支 `p1/fix-retrieval`；HEAD `ca88c9a`；R2 `b37ad21` 父 `cbbb241`。
- `git show --stat b37ad21`：**7 文件**（`query.py`、`answer.py`、2 测试、`report.md`、证据 03/04），全部在允许路径；无第二 dev commit。
- `git diff 2306aaa..b37ad21 -- fixtures` 空；`-- backend/src/mktkb/conversations backend/src/mktkb/rag/intent.py fixtures var/eval docs/evaluation` 空；`ca88c9a` 只动 `.claude/handoffs/**`（3 文件）。
- 两测试文件无 `skip/xfail/mark`；`git diff cbbb241..b37ad21 -- backend/tests` 删除行仅 2 个文件头，无删断言。
- **非阻塞观察**：`report.md` **99 行 > 80 行预算**（handoff §8）。

## 2. C5 系列（上轮 FAIL）：PASS

命令：`.\.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T105-R3\02-probe.py`（验收方自写，未 import 开发测试）→ **133/133 checks**。

同一 conversation，上文 `城西店的宣传海报在哪里？`：

| 追问 | R2 前 `fc60c57` | 当前 `b37ad21` |
| --- | --- | --- |
| `那个海报的价格欺诈规定是什么？` | 27 字继承位置 | **`answer` 58 字**第二十一条条文 |
| `那个海报的相关规定是什么？` | 27 字位置 | **`answer` 140 字**条文 |
| `那个海报适用的价格欺诈规定是什么？` | 27 字位置 | **`answer` 156 字**第二条 |
| 上文问规格 → 同 C5 | 29 字继承规格 | **`answer` 58 字**，0 规格 |

- 四例均 0 `标识：`、0 位置/规格值、无分页、<576；基线 `17c0e63` 为 576 字 8×8。附加：`该海报…` 与「not_found 后追问」同口径 58 字。
- 代码：`query.py:1386-1390`（清继承 `field_role`、`POLICY_FOLLOWUP`）+ `answer.py:33-57`（换 document 计划）+ `answer.py:679-690`（标题/半句过滤）。

## 3. C3/C6（上轮 FAIL）：PASS

- C3 `那个海报的档期物料要提前多少天提报需求？` → `answer` **20 字**「档期物料须提前 21 天提报。」（R1 35 字 `not_found`；单独 D4 仍 518 字含 21）。
- C6 `那个海报的审批流程是什么？` → `answer` **37 字**「市场部通路行销组发起，门店店长确认。」（R1 35 字 `not_found`）。
- 代码：`query.py:1355-1365`（`not is_policy_followup` 守住「新内容→未记录」）；C3/C6 `sources=[]` 见 §9。

## 4. C4/C7（上轮 FAIL）：PASS

- C4 `那个海报的《明码标价和禁止价格欺诈规定》自何时起施行？` → `answer` **136 字**，含 `2022年7月1日` + 两项废止规定（R1 42 字不实「没有匹配记录」）。`answer.py:793-807` 过滤标题/截断半句。
- C7 `那个海报的盘点时间是什么？` → `not_found` **22 字**「资料中未记录日期（记录存在，但缺少该字段）。」；不含「没有匹配记录/未找到记录/未在资料中找到」。`answer.py:387-397`。

## 5. 新启发式证伪：PASS（带 P2）

谓词 10 例全对：`陈列要求/打印材质要求/扣分规则/陈列规则/盘点时间/报销规则`=False；`审批要求/价格欺诈规定/档期物料提报/审批流程`=True；`is_policy_question("…陈列要求呢")=True`（说明 R2 helper 必要）。

HTTP（上文问位置）：`陈列要求` 仍 `not_found` 35 字 0 泄露（未被改判政策正文）；`陈列规则/扣分规则` 22 字记录式（`规则`=note 字段）；`审批要求/审批权限` 37 字正文；`盘点规定` 34 字正文。

**P2（新发现）**：`那个海报的标准规格是什么？`/`价格标准是什么？`/`提交数量呢` → **576 字 8×8 倾倒**（R1 分别 29/23/20 字单字段；基线 576）。根因：`query.py:1355-1390` 中 `field_roles` 非空使 `ANAPHORA_NEW_CONTENT`/`POLICY_FOLLOWUP` 均不成立，`elif` 又被 `not policy_followup` 挡住 → legacy 整条渲染。等于基线、非比基线更差；建议 `elif` 守卫改为 `(not policy_followup or bool(field_roles))`。**若 PM 以「任何指代追问不得 576 倾倒」为硬标准，可将此项升级为阻断并派第 3 轮返工；按本轮 rework-R2 命名判据与「不得比基线更差」口径判 PASS。**

## 6. 必须保持（B1/B2/控制组）：PASS

- B1：枚举 → `那个海报的第2页` `answer` `{page:2,total:12,returned:2,has_more:false}`、272 字（R2 探针 266，差 6 为夹具文件名）；单独 `第2页`/`下一页` 均 page=2；`把那个海报的位置列出来`/`全部信息` 保持枚举；无上文 `那个海报呢` 31 字澄清、`那个呢` 20 字澄清，0 值 0 sources。
- B2：`规格型号呢` 29 字仅规格；`打印材质/陈列要求` `not_found` 35 字、0 字段/0 值/`sources=[]`；位置/数量/价格 27/20/23 字；not_found 后纯指代 27 字仅位置。
- 控制组：单独 D4 **518** 字含 21；单独 T101 **861** 字含 2022-07-01；`那个流程要提前几天提报` **139** 字；T101/T102 定向 **37/44 passed**。
- 三树对照（同一探针）：R1 树 C5 27/29、C3/C6 not_found 35、C4/C7 not_found 42；基线树全部 576；当前全部修复（`03-probe-results.md` §D）。

## 7. 测试/评测：PASS

- 本包 **40 passed**（15.87s）；rag **347**（20.70s）；observability **255**（14.88s）；integration **381**（277.16s，无 flake）；全量 **1718 passed / 0 failed / 0 error**（385.57s，跑前 4.1GB）。
- b0 `b0-local-20261106T182633804408Z-5d994af5` pass29/fail3/skipped8，gate exit 3 hard `[]`，`case_diffs=0`（40/40）；badcase `badcase-local-20261106T182645606516Z-363c0a7d` pass9/fail4，hard `[]`，`case_diffs=0`（13/13）。
- regression 当前 `regression-local-20261106T182718496600Z-646012b8` pass5/fail2 hard `[]`；基线 `17c0e63` `regression-local-20261106T182849164146Z-27b0e384` pass4/fail3 hard `['security_leak']`；逐例**仅 RG006 fail→pass**，RG005/RG007 失败 checks 不变，无新 hard 名。
- 数字与 report §7 全部一致；无 flake，未触发隔离复跑。

## 8. report/证据：PASS（带观察）

- §7 如实记录修复前后（C5 58/140/156/58、C3 20、C4 136、C6 37、C7 22）、根因、最小改动；`report.md:72-99`。证据仍 4 份，`03-test-runs.md:56` §E、`04-scope-and-limitations.md:40` §F 含 R2 段。
- `report.md:66` 已更正上轮「观察（不阻塞）」的错误判断。
- **观察**：§7 的 `is_policy_followup` 词面限制仅一般性披露，未写明「政策词+字段词」组合会退回 576 倾倒（§5/P2）；report 70→99 行超预算。

## 9. 残余 / NOT-RUN

- **P2-1**（新）：`标准规格/价格标准/提交数量` 576 字 8×8（相对 R1 回退、等于基线）；建议下一包收口。
- **P2-2**：`报销规则`（仅含被排除词「规则」）→ 22 字记录式 not_found，真正政策问法被保守吞掉；词面启发式限制。
- **P2-3**：文档/法规答案 `sources=[]`（C3/C4/C5/C6/C7；记录答案有 sources）。handoff §6 无 sources 硬性条款，按 PM 裁定记非阻塞。
- **NOT-RUN**：真实模型/live、embedding/rerank/OCR、`.env`、Holdout、T109 多轮 runner（按边界/未纳入）。
- 未改任何交付物；未 commit/push/切分支/stash/reset；探针与临时产物只在 `backend\.pytest-tmp\T105-R3\` 与 `$env:TEMP`。

证据：`docs/reports/OBS-EVAL/P1/evidence/verify/T105-R3/`（01-verdict、02-probe.py、03-probe-results、04-test-eval-runs，共 4 份）。
