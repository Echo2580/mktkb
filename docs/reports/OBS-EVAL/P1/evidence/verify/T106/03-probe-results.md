# T106 独立验收 03：探针结果

探针：`02-probe.py`（本目录；自写，不依赖开发测试）。命令（仓库根）：

```powershell
.\.venv\Scripts\python.exe docs\reports\OBS-EVAL\P1\evidence\verify\T106\02-probe.py
```

环境：Python 3.12.7；只 import `mktkb.copy` 并用 `git show` 读父提交；不启动服务、不调模型、不建库。

## A–F（机械项）全部 ok

- **A 映射清单**：`REQUIRED_REASONS=33`；33 个 required reason 全部登记；别名目标都在 `COPY`；无别名链；`COPY` 53 条模板全局唯一；33 个 reason 均可渲染且非空，按 copy key 去重后模板无重复（别名共享属显式登记）；所有模板占位符都是已登记字段（`copy.py:544-581/584-609`）。
- **B 源码覆盖**：AST 扫描 `service.py`/`answer.py`/`query.py` 的 `reason=`、`_no_answer(..., "REASON")`、`plan_reason`、`plan.reason == "..."` 字面量，共 28 个 reason；全部在 `REASON_COPY_KEY`，无一落 `UNCLASSIFIED`。另 `CHAT_UNAVAILABLE`/`CHAT_ERROR`/`RAG_ERROR` 等动态码由 `REASON_ALIASES`/`COPY` 覆盖。
- **C T104 逐字对照**：从 `git show 9933a7b:.../service.py` 解析父提交 `_MODEL_ERROR_REASONS` 8 个码，按父模板拼接后与 `copy.service_error_text(code)` 比较，**8/8 逐字相同**（含 `MODEL_POST_SEND_AUTH_DENIED`）；7 类 + 网关码的“这是服务调用失败，不是资料中没有答案”“服务端不会因重试而重复保存同一条回答”完整保留。
- **D 三要素/重试**：所有 `service_error=True` 条目含统一模板两句；`retryable=True` 条目均含重试/改问提示；`retryable=False` 条目不含“可稍后重新提问”；未登记码按 `retryable` 选提示（T104 复核残余 5 已修）。T104 矩阵 `retryable` 8/8 与父提交一致。
- **E 服务码**：`service.py` 实际 `_service_error` 码（`INDEX_NOT_READY`/`INVALID_QUERY`/`MODEL_NOT_CONFIGURED`）及动态 `_classify_model_error` 可达码均在 `SERVICE_ERROR_CODES`/`COPY`。
- **F 前后端集合**：`NON_RETRYABLE_SERVICE_ERROR_CODES={MODEL_NOT_CONFIGURED, MODEL_BUDGET_REFUSED, QA_INTERNAL_ERROR, INVALID_QUERY}`；后端 `retryable=False` 服务码全部在内，可重试码无误标。

## G 文案诚实性：3 条 FAIL

探针按 handoff §1/§5/§6-1 固化了“系统侧失败不得伪装成资料缺失”的检查，全部命中：

1. **`IDENTIFIER_NOT_RETRIEVABLE`（阻塞）** `copy.py:192-200`，调用点 `conversations/service.py:2071-2082`。实际文案：

   > 资料中未找到标识“{identifier}”对应的记录，但这不是资料中没有答案；本次未按标识检索，不能据此判断该记录不存在；请改用门店、物品名称等条件后重新查询。

   `service.py:2072-2074` 注释与分支明确：产品检索层没有标识筛选键，内核未接手时**失败关闭、不检索**。因此“资料中未找到……记录”是无检索依据的资料侧断言，与“本次未按标识检索”直接矛盾；`CopyEntry.material_related=False` 也与首句自相矛盾。探针 H 段用 `parse_question("QF21 放在哪里？", lexicon with QF21)` 实测得到 `intent=None, identifier="QF21", clarification=None, fields=("位置",)`，确认会走到 `service.py:2071` 分支。开发证据 `01-copy-mapping.md:73` 明示“保留……以满足验收可接受的缺失措辞”，但 handoff 没有这种豁免。

2. **`ANAPHORA_NEW_CONTENT`（同类）** `copy.py:338-345`，调用点 `rag/answer.py:262-270`：

   > 资料中未记录这项信息；这次追问带入了新内容，不是资料中没有答案；请指定要查询的字段……

   同一句“资料中未记录这项信息”与“不是资料中没有答案”互斥；该 reason 的实际情形是新内容未进入记录检索（`query.py:1350-1371`），不能据此断言资料未记录。

3. **`NO_INTENT`（同类；当前可能不可达）** `copy.py:201-208`，调用点 `service.py:2091-2097`：

   > 资料中未找到与这个问题相符的内容；如果确认资料中存在，请改用门店、物品或字段等更具体的问法后重试。

   `plan.intent is None` 时尚未检索；文案把系统未识别意图表述为资料中没有内容，且没有“不是资料中没有答案”。当前 `intent.py` 的 `intent=None` 返回均带澄清/标识/未知标识，该服务分支可能已不可达，但仍是交接单要求覆盖的 reason。

探针退出码 1，`FAILS: 3`（其余为 ok）。H 段额外确认标识-only 路径可达：`ok 标识-only 查询产生 intent=None + identifier=QF21 + 无澄清`。详见 `02-probe.py` G/H 段与 `01-verdict.md`。
