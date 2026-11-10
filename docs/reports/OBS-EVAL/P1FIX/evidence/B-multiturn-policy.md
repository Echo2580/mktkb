# P1FIX-B 证据：多轮追问不再倾倒整批记录（字段角色 / 政策意图 / 上下文继承）

> 复现依据：`docs/reports/OBS-EVAL/P1/evidence/verify/T105-R3/`（#51 残余）与
> `docs/reports/OBS-EVAL/P1/evidence/T900/04-observability-and-residuals.md` §B。
> 本文件所有数字均为零真实调用的本地/HTTP 自测；未读 Holdout 逐题/答案。

## 1. 原失败（T105-R3 独立证据，修复前）

上文「城西店的宣传海报在哪里？」后追问（产品 HTTP 路径，EchoGateway）：

| 追问 | 修复前 kind | 修复前长度 | 记录标记 | 判定 |
| --- | --- | --- | --- | --- |
| 那个海报的标准规格是什么？ | answer | **576** | 8 | 8×8 整条倾倒（R1 曾 29 字，回退到基线） |
| 那个海报的价格标准是什么？ | answer | **576** | 8 | 同上（R1 曾 23 字） |
| 那个海报的提交数量呢 | answer | **576** | 8 | 同上（R1 曾 20 字） |
| 那个海报的报销规则是什么？ | not_found | 22 | 0 | 真正政策问法被当台账备注字段吞掉 |
| 那个海报的陈列规则呢 | not_found | 22 | 0 | 正确（台账 note 字段缺省） |
| 那个海报的审批要求是什么？ | answer | 37 | 0 | 正确（政策正文） |

根因（三处冲突叠加）：
1. `rag/query.py` 的指代分支要求 `not policy_followup` 才走“单字段作答”；
   `标准/提交` 属于 `POLICY_WORDS`，于是 `标准规格/价格标准/提交数量` 被跳过单字段分支；
2. `报销` 不在任何政策/法规词表里（`规则` 又被 `is_policy_followup` 排除），制度话题被当成台账
   备注字段；
3. 上述计划落回产品 legacy 路径，把 8 条记录证据交给模型措辞面，产生整批字段回显。

## 2. 修改

| 文件 | 修改 |
| --- | --- |
| `backend/src/mktkb/rag/query.py` | 新增强制度/流程话题词表 `_STRONG_POLICY_TOPIC_WORDS`（报销/核销/审批/申请/提报/流程/制度/规定/办法/政策/法规/权限/时限）与 `strong_policy_topics()`。① 单字段分支改为 `not (policy_followup and strong_policy_topic)`：`标准/提交` 这类泛化词不再阻止单字段作答；② 强话题词与字段词同形冲突（如“报销规则”）新增 `POLICY_TOPIC_FOLLOWUP`：清继承字段、交正文检索，且保留“全部/列出/第 N 页”的枚举/分页优先级。 |
| `backend/src/mktkb/rag/answer.py` | `POLICY_TOPIC_FOLLOWUP` 换正文计划；正文证据里必须确有该强话题词，否则如实拒答（不拿同形字段的无关正文冒充）。 |
| `backend/src/mktkb/copy.py` | 新增 `POLICY_TOPIC_NOT_FOUND` 诚实文案（“找到的资料中没有可支撑{话题}相关制度/流程的内容…”）。 |

## 3. 修复后验证（同一 T105-R3 独立探针 = 最严格对照）

命令：

```powershell
$env:T105R3_OUT="backend\.pytest-tmp\p1fix\T105-R3-probe.json"
.\.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T105-R3\02-probe.py
```

结果：**131/133 checks passed**，仅 2 条失败为 T105-R3 脚本写死的 T106 前旧文案断言
（要求文案含“未记录”，“B2-material/B2-display”；T106 统一文案后已改为“不属于台账字段的新内容”，
T900 证据同口径），**不是产品回归**。

修复前后同场景对照（同一探针、同一夹具）：

| 场景 | 修复前 | 修复后 | 判定 |
| --- | --- | --- | --- |
| 那个海报的标准规格是什么？ | answer 576 / 8 markers | **answer 29 / 0 markers**（仅 A2 铜版纸 157g） | 修复 |
| 那个海报的价格标准是什么？ | answer 576 / 8 | **answer 23 / 0**（仅 2.6 元） | 修复 |
| 那个海报的提交数量呢 | answer 576 / 8 | **answer 20 / 0**（仅 20 张） | 修复 |
| 那个海报的报销规则是什么？ | not_found 22（记录式） | **not_found 67**（“找到的资料中没有可支撑…制度/流程…”） | 修复 |
| 那个海报的陈列规则呢 | not_found 22 | not_found 49（T106 文案；仍如实缺字段） | 保持 |
| 那个海报的扣分规则是什么？ | not_found 22 | not_found 49 | 保持 |
| 那个海报的审批要求是什么？ | answer 37 | answer 37（政策正文） | 保持 |
| 那个海报的审批权限是什么？ | answer 37 | answer 37 | 保持 |
| 那个海报的盘点规定是什么？ | answer 34 | answer 34 | 保持 |
| B1 枚举→第2页 / 裸“第2页” / 下一页 | pass | pass（page=2,total=12,returned=2） | 保持 |
| 显式“把那个海报的位置列出来”/“全部信息” | pass | pass | 保持 |
| 无上文“那个海报呢”/“那个呢” | clarification | clarification（0 值 0 sources） | 保持 |
| C3 档期物料/ C4 法规施行 / C5 价格欺诈规定 / C6 审批流程 | answer 20/136/58/37 | answer 20/136/58/37（0 继承字段） | 保持 |
| 控制组：单独 D4（21 天）/ T101（2022-07-01） | answer 518/861 | answer 518/861 | 保持 |

原始结果：`backend/.pytest-tmp/p1fix/T105-R3-probe.json`（本地临时；摘录见本目录 data/）。

## 4. 新增回归测试（产品 + 内核两层）

- `backend/tests/rag/test_p1_t105_anaphora_field.py`：新增
  `标准规格/价格标准/提交数量` 参数化单字段用例、`报销规则` 诚实拒答、`陈列规则/扣分规则`
  仍为台账 note 字段（不被强话题词劫持）。
- `backend/tests/integration/test_p1_t105_anaphora_field.py`：新增上述 HTTP 产品用例 +
  B7 覆盖：位置/数量/规格/价格字段追问、政策追问（审批要求）、话题切换不继承门店、
  未知门店不倾倒、无上文指代澄清、缺字段如实说明并带 `missing_fields`、
  显式“全部/第2页”枚举分页保持。
- 结果：rag 包 + 产品集成两层均全绿（见 `08-tests-and-evals.md`）。

## 5. 剩余问题（如实）

- **单轮无上文**「宣传海报的打印材质是什么？」在产品 legacy 路径仍可能把 8 条证据交给模型
  措辞面（T105-R3 探针 D1：answer 576/8，与基线相同）。这不是本次报告的“多轮追问倾倒”；
  真实模型下措辞由模型产生，离线探针的 EchoGateway 会回显证据。按 T105 口径记为**范围外
  既有项**，未在本次扩大改动（避免改 legacy 模型措辞面引入更大回归）。
- 强话题词表是“制度/流程话题”的有限词表；同类新词（如“报备规则”）需按语料再补，属词表
  治理后续项；本次已覆盖点名项“报销规则”并保留台账字段问法（扣分/陈列规则）不被误改判。
