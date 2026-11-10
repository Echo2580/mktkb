# T105 R3 独立探针结果（verify/T105-R3/03）

环境：Windows；cwd=`D:\GPT项目\市场部AI知识库`；`.venv\Scripts\python.exe` 3.12.7；每个进程 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；零真实模型/embedding/rerank/OCR，未读 `.env`/Holdout。脚本：`02-probe.py`（验收方自写，不 import 开发测试）。夹具：12 行台账（城西店/QF02/位置/数量/2.6/规格）+ 海报制度 docx（材质/陈列/盘点/审批）+ `corpus/…/W02` + `W10` + `明码标价…规定`；`EchoGateway` 只回显证据，不作业务回答。

命令：`.\.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T105-R3\02-probe.py` → **133/133 checks passed；0 failed**（当前 `b37ad21`）。原始 JSON：`backend\.pytest-tmp\T105-R3\probe-results.json`（临时产物，不入库）。

## A. R2 判据（同一 conversation；上文 `城西店的宣传海报在哪里？`；C5d 上文问规格）

| # | 追问 | kind | 长度 | sources | 结论 |
| --- | --- | --- | --- | --- | --- |
| C5 | 那个海报的价格欺诈规定是什么？ | answer | 58 | 0 | 第二十一条条文；0 位置/规格/记录标记；<576 |
| C5b | 那个海报的相关规定是什么？ | answer | 140 | 0 | 法规条文；同上 |
| C5c | 那个海报适用的价格欺诈规定是什么？ | answer | 156 | 0 | 第二条（适用范围/定义）；同上 |
| C5d | 上文问规格 → C5 | answer | 58 | 0 | 条文；0 规格（修前 R1 为 29 字规格） |
| C5e | 该海报的价格欺诈规定是什么？ | answer | 58 | 0 | 同 C5（"该"指代也成立） |
| C5f | 上文先问打印材质 not_found → C5 | answer | 58 | 0 | 同 C5（not_found 后不丢政策路径） |
| C3 | 那个海报的档期物料要提前多少天提报需求？ | answer | 20 | 0 | 「档期物料须提前 21 天提报。」 |
| C4 | 那个海报的《明码标价和禁止价格欺诈规定》自何时起施行？ | answer | 136 | 0 | 2022年7月1日 + 两项废止规定 |
| C6 | 那个海报的审批流程是什么？ | answer | 37 | 0 | 「市场部通路行销组发起，门店店长确认。」 |
| C7 | 那个海报的盘点时间是什么？ | not_found | 22 | 0 | 「资料中未记录日期（记录存在，但缺少该字段）。」无「没有匹配记录/未找到记录」 |

C5 系列与 C3/C4/C6 均无 `标识：` 记录块、无分页、无继承的位置/规格值。附注：C5 系列/文档答案 `sources=[]`（产品只暴露 `facts` 来源，文档答案仅有内核 citations）——报告 §7 已披露，本包口径无硬性要求（见 §D）。

## B. 必须保持（回归）

| 项 | 实测 | 结论 |
| --- | --- | --- |
| B1 枚举→`那个海报的第2页` | answer，`{page:2,total:12,returned:2,has_more:false}`，272 字（夹具文件名比 R2 探针长 6 字符；页/条数一致） | PASS |
| 单独 `第2页` / `那个海报的下一页` | 均 page=2 | PASS |
| 显式 `把那个海报的位置列出来` / `全部信息` | total=1 枚举 / 枚举或「共」文本 | PASS |
| 无上文 `那个海报呢` / `那个呢` | clarification 31 / 20 字，0 值 0 sources | PASS |
| B2 `规格型号呢` | answer 29 字，仅 `A2 铜版纸 157g` | PASS |
| B2 `打印材质呢` / `陈列要求呢` | not_found 35 字，0 记录字段/0 未问值/`sources=[]` | PASS |
| B2 `位置/数量/参考供价` | 27 / 20 / 23 字，仅该字段 | PASS |
| not_found 后 `那个海报呢` | 27 字仅位置 | PASS |
| 控制组 单独 D4 | answer 518 字含 21 天 | PASS |
| 控制组 单独 T101 法规 | answer 861 字含 2022-07-01 + 废止规定 | PASS |
| 控制组 `那个流程要提前几天提报` | answer 139 字 | PASS |
| D1 单独 `宣传海报的打印材质是什么？` | answer 576 字、8 个 `标识：`（legacy 记录倾倒；P2 既有） | 记录 |

## C. 新启发式 `is_policy_followup` 证伪（词面/字段同形）

谓词（全部符合预期）：`陈列要求`=False、`打印材质要求`=False、`扣分规则`=False、`陈列规则`=False、`盘点时间`=False、`报销规则`=False；`审批要求`=True、`价格欺诈规定`=True、`档期物料…提报`=True、`审批流程`=True。`is_policy_question("…陈列要求呢")=True`（故需 R2 的新 helper 排除「要求/规则」）。

HTTP（上文问位置）：

| 追问 | kind | 长度 | 判定 |
| --- | --- | --- | --- |
| 那个海报的陈列要求呢（点名 B2） | not_found | 35 | 未被改判政策正文；0 泄露 PASS |
| 那个海报的陈列规则呢 | not_found | 22 | 记录存在/缺字段文案；未被改判政策 PASS |
| 那个海报的扣分规则是什么？ | not_found | 22 | 同上（`规则` 是台账 note 字段） PASS |
| 那个海报的审批要求是什么？ | answer | 37 | 政策/流程词命中，正文作答（合理） |
| 那个海报的审批权限是什么？ | answer | 37 | 同上 |
| 那个海报的盘点规定是什么？ | answer | 34 | 「规定」→法规/制度路径，答出盘点时间（合理） |
| 那个海报的报销规则是什么？ | not_found | 22 | 仅「规则」→按记录字段处理；真正的政策问法被保守吞掉（P2 词面限制） |
| **那个海报的标准规格是什么？** | **answer** | **576** | **8×8 记录倾倒；R1 为 29 字单字段；基线 17c0e63 同为 576** |
| **那个海报的价格标准是什么？** | **answer** | **576** | **同上（R1 23 字价格）** |
| **那个海报的提交数量呢** | **answer** | **576** | **同上（R1 20 字数量）** |
| `它适用的价格欺诈规定是什么？`（无显式实体） | answer | 881 | 法规正文多条（无记录标记）；非点名项，记录 |

## D. 三树对照（同一探针；`T105R3_ROOT`）

| 场景 | R1 `fc60c57` | 基线 `17c0e63` | 当前 `b37ad21` |
| --- | --- | --- | --- |
| C5/C5b/C5c | 27 字继承位置 | 576 8×8 | 58/140/156 条文 |
| C5d | 29 字继承规格 | 576 | 58 条文 |
| C3 | not_found 35 | 576 | answer 20 含 21 |
| C4 | not_found 42（不实「没有匹配记录」） | 576 | answer 136 含日期 |
| C6 | not_found 35 | 576 | answer 37 |
| C7 | not_found 42（不实） | 576 | not_found 22（文案准确） |
| B2 规格/打印材质 | 29 / not_found 35 | 576 / 576 | 29 / 35 |
| `标准规格` | **29** | 576 | **576（相对 R1 回退，等于基线）** |

探针在该两树分别 23/111、60/111 checks 失败（该两树运行早于 `02-probe.py` 的 C5e/C5f/谓词增补，故为 111 checks；R1 树无 `is_policy_followup`，谓词段自动跳过）。

## E. 残余

1. **P2（新发现，建议下一包）**：`标准规格/价格标准/提交数量` 这类「政策词 + 台账字段词」组合被 R2 三处守卫（`query.py:1355-1390`）跳过单字段分支（`field_roles` 非空使 `ANAPHORA_NEW_CONTENT`/`POLICY_FOLLOWUP` 均不成立，`elif` 又被 `not policy_followup` 挡住），落回 legacy 576 字 8×8；相对基线不变差，但相对 R1 单字段是回退。最小建议：`elif` 守卫改为 `(not policy_followup or bool(field_roles))`，或让 `POLICY_FOLLOWUP` 在 `field_roles` 非空时也清字段/走正文。
2. **P2**：`报销规则` 仅含被排除词「规则」→ 22 字记录式 not_found（真正政策问法被保守吞掉）；词面启发式限制，报告 §7 已作一般性披露。
3. **P2**：文档/法规答案 `sources=[]`（C3/C4/C5/C6/C7）；`B2/spec` 等记录答案有 sources。handoff §6 无 sources 硬性条款，按 PM 裁定记非阻塞。
4. 未跑：真实模型/live、embedding/rerank/OCR、`.env`、Holdout、T109 多轮 runner（边界/未纳入）。
