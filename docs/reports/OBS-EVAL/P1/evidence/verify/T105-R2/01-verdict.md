wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T105 R2 独立验收结论（verify/T105-R2/01）

- 验收对象：`p1/fix-retrieval` @ `fc60c57`（R1 交付，父 `f1b96e2`，其上仅 PM 簿记 commit；HEAD `fecdfcc`，工作树起始 clean）。
- **结论：FAIL（B2 未收口；B1 已修复）**。B1 分页回退已按基线 `17c0e63` 修好；B2 三个点名追问已不再整条倾倒。但 R1 新增的 `elif`/`ANAPHORA_NEW_CONTENT` 对政策/法规追问的排除不完整（`elif` 政策/法规均未排，`ANAPHORA_NEW_CONTENT` 漏排政策）：独立 HTTP 探针复现“那个海报的（适用/相关）价格欺诈规定是什么”在上一轮问位置/规格后返回继承的 **位置/规格**（27/29 字），而不是法规正文；同前缀的“档期物料/审批流程”则被压成 `not_found`，而去掉指代后同一内容问题可从 W02 正文答出 21 天。违反 `rework-R1.md` §5-2“不得扩大拦截”。
- B1：同一 conversation `把宣传海报都列出来`→`那个海报的第2页` 返回 `answer` + `{page:2,total:12,returned:2,has_more:false}`、266 字；单独 `第2页`、`下一页`、`全部` 均保持分页/枚举；基线 `17c0e63` 同 266 字。PASS。
- B2 点名项：`规格型号`→29 字仅规格；`打印材质/陈列要求`→`not_found` 35 字、0 记录字段、0 未问值、`sources=[]`；纯指代/数量/价格/位置仍只答继承字段。PASS。
- B2 §5-2 证伪（阻断）：`那个海报的价格欺诈规定是什么？`/`那个海报的相关规定是什么？`/`那个海报适用的价格欺诈规定是什么？`（上文问位置）→ `answer`“城西店的宣传海报的位置：C区2号货架第一层。”（27 字）；上文问规格后同问 → 规格 29 字。`backend/src/mktkb/rag/query.py:1336-1352`：`anaphora_new_content` 只排除 `is_regulation_question`，`elif` 无政策/法规守卫；`is_regulation_question=True`、`field_roles=()`、`is_anaphora_field_followup(...,'location')=True`，于是继承的 field_role 进入 RAG 单字段渲染。基线/父 `2306aaa` 同一问题为 576 字 8×8 倾倒，**不是**本文期望的“保守化”，而是 R1 新增的错误字段答案。
- B2 §5-3：`那个海报的打印材质呢`/`陈列要求` 在基线/父树也是 576 字倾倒，当前 `not_found` 属保守收窄（P2 残余，非 §5-3 行为回退）；但 `那个海报的档期物料要提前多少天提报需求` 单独问可答 21 天（D4 控制 518 字），带指代后被压成 35 字 `not_found`（C3），属 §5-2 过度拦截（非 §5-3 字面回退）；`那个海报的《明码标价…规定》…`（C4）/`审批流程`（C6）/`盘点时间`（C7）同为 35/42 字 `not_found`，其中 C4/C7 的“未找到记录”文案不实（记录存在）。
- 测试/评测：本包 **23 passed**；rag **339**；observability **255**；integration **372**；全量 **1701 passed / 0 failed / 0 error**；T101/T102 窄集 37、全集 44 passed。b0 pass29/fail3/skipped8、badcase pass9/fail4，逐例 `case_diffs=0`，gate hard `[]`；regression 仅 RG006 fail→pass，RG005/RG007 失败集不变，gate `['security_leak']`→`[]`。全部与 report §6 数字一致（无 flake）。
- 范围/合规：R1 仅 `fc60c57` 1 个 dev commit，7 文件（query/answer/2 测试/report/证据 03/04），均在允许路径；PM 6 个 commit 仅 `.claude/handoffs/**`+`verify/T105/**`；fixtures/conversations/intent 未动；无 skip/xfail/删断言；证据 T105 仍 4 份，03 §D/04 §E 含 R1 段。
- report/证据：§6 已如实披露 B2 收窄与 P2 残余，并修正 §5“不会再整条倾倒”；数字与复跑一致。但 report:66 / 证据 04:37 把“政策题+实体+字段词+指代”组合记为“观察（不阻塞）/未见回退”，本轮探针证伪；report:68 的 70/70 是上一轮验收方脚本（未覆盖该组合），不能作为 §5-2 全覆盖证据。
- 残余/NOT-RUN：真实模型/embedding/rerank/OCR、`.env`、Holdout、T109 多轮 runner 按边界未跑；C4/C7 文案不实为 P2；`那个海报的规格型号呢` 等单字段 PASS 不受影响。
