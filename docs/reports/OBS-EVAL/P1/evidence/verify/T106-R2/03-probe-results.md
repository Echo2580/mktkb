# T106 R2 探针结果（03）

环境：Windows，仓库根 `D:\GPT项目\市场部AI知识库`，`.venv\Scripts\python.exe` 3.12.7；只读源码 + git 对象，不建库、不启服务、不调模型。

## A. 本轮自写探针（`02-probe.py`）

命令：

```powershell
.\.venv\Scripts\python.exe -B "docs\reports\OBS-EVAL\P1\evidence\verify\T106-R2\02-probe.py"
```

结果：**FAILS: 0**（A–H 全 ok）。关键输出：

```text
B1: 本次未按标识检索（当前检索不支持按标识筛选，系统未执行标识查询），不能据此判断该记录不存在，也不能确认该记录未找到；这不是资料中没有答案；请去掉标识，改用门店、物品名称等条件后重新查询，或联系管理员补充。
plan: intent=None identifier='QF21' unknown=None clarification=None fields=('位置',)
service 分支顺序：IDENTIFIER(2078) 先于 NO_INTENT(2094)
parse→IDENTIFIER 分支之间无检索调用（calls=['_Result','annotate','bool','len','parse_question','text']）
B2: 没有识别出这个问题的查询意图，本次未作答；这不是资料中没有答案；请补充门店、物品或要查询的字段等更具体的问法后重试。
intent=None 计划: [(412, {'unknown_identifier'}), (428, {'clarification'}), (438, {'clarification'}), (546, {'clarification'}), (519, {'clarification'}), (512, {'identifier'})]
B3: 这次追问带入了不属于台账字段的新内容，本次未作答；这不是资料中没有答案；请指定要查询的字段（例如位置、数量、规格、价格）后重新提问。
```

### A.1 B1 文案判定（全部 ok）

- `material_related=False`；含 `未按标识检索`、`不能据此判断该记录不存在`、`不是资料中没有答案`、`未执行标识查询`、门店/物品/重新查询/管理员自救。
- 不含 `资料中未找到`、`资料中未记录`、`未找到标识`；剥离 `不是资料中没有答案` 后不含 `资料中没有`。
- 可达性：标识-only 查询 `intent=None + identifier=QF21 + 无 unknown_identifier + 无 clarification`；`service.py:2071`（identifier）先于 `:2091`（intent is None）；`:2050` parse 与 `:2071` 之间无检索类调用。

### A.2 B2 / B3（全部 ok）

- B2：`material_related=False`；说明“未识别查询意图、本次未作答、不是资料中没有答案、补充门店/物品/字段后重试”；不含 `资料中未找到`。
- 不可达守卫：`intent.py` 6 处 `IntentPlan(intent=None)` 全部带非空阻断字段；动态抽样 8 条问题无“无阻断 intent=None”。
- B3：`material_related=False`；不含 `资料中未记录`；含 `不属于台账字段`、`不是资料中没有答案`、指定字段后重试；`answer.py:262-270` 直接渲染 copy。
- 机械规则：全部 COPY 中 `material_related=False` 无资料侧结论（剥离允许否定句后）；`material_related=True` 无服务失败结论；三条目均含否定句与自救指引。
- 测试覆盖：`test_p1_t106_copy.py:212-218`（False 规则）、`:221-227`（True 规则）、`:230-241`（B1）、`:244-269`（B1 可达）、`:272-279`（B2）、`:282-289`（B3）、`:292-324`（AST 守卫）；测试遍历 `COPY.values()`，不是只断言三条目。

### A.3 T104 / 结构不变（全部 ok）

- 从 `9933a7b:backend/src/mktkb/conversations/service.py` 的 `_MODEL_ERROR_REASONS` 逐字重建 8 个码（七类 + `MODEL_POST_SEND_AUTH_DENIED`），与当前 `copy.service_error_text` **8/8 相同**。
- 加载 `a42ee48` 的 `copy.py` 与当前比较：仅 `IDENTIFIER_NOT_RETRIEVABLE`、`NO_INTENT`、`ANAPHORA_NEW_CONTENT` 三条模板变化；元数据仅 B2/B3 的 `material_related` 由 True→False（B1 保持 False）。
- `schemas.py` 在 `a42ee48..972f508` 与 `cb602b2..972f508` 均无 diff；`AskResult` 12 字段、`MessageView` 12 字段、`ResultKind` 集合（`answer/clarification/not_found/conflict/service_error/knowledge_changed`）均不变。
- 前端：`INVALID_QUERY → 查询条件问题`；`resultBadgeLabel(kind, candidates.length, errorCode)` 传入 errorCode；`INVALID_QUERY` 历史提示与正文一致；`该历史消息未保存候选明细` 不再出现；`需补充条件`/`需要确认` 仍在。

## B. 复用上轮验收方探针（独立复核）

命令：

```powershell
.\.venv\Scripts\python.exe -B "docs\reports\OBS-EVAL\P1\evidence\verify\T106\02-probe.py"
```

结果：**FAILS: 0**（A–H 全 ok）。覆盖：33 reason 登记/别名/模板唯一、源码 reason 字面量全登记且无 `UNCLASSIFIED`、T104 8/8、服务码集合、前端非重试集合、G 段三条目诚实性、H 段标识-only 可达。G 段 R1 前为 3 FAIL，本轮 0 FAIL。

## C. 结论

R1 三条目（B1/B2/B3）文案已改为“系统未检索/未识别 + 不能据此判断资料有无 + 自救指引”，`material_related` 与文案一致；机械规则与可达性/不可达守卫均有可执行证据。无新增的自相矛盾短语组合。
