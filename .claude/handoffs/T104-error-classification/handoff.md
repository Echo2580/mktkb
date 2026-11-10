# T104 交接单：D1 异常原因透传（ERR-07 产品侧，P1 第 6 包 · 需 D-3 授权）

> 基线：分支 `p1/fix-retrieval`（自 `main@083eaef`；T100/T107/T101/T102/T103 已收口）。D-3 兼容授权已获主人书面确认（允许错误码/文案**取值**变化，字段结构不变）。
> 执行者：开发 subagent（`wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`）。PM 不写代码。

## 1. 目标（一句话）
把"预发送/调用期异常一律包装成 `MODEL_UNAVAILABLE`"改为**按真实原因分类透传**（provider / 配置 / 预算 / 超时 / 内部），可重试性说明准确，文案套用 ERR-07 的正面模板（说清"不是资料中没有答案"、可否重试、不会重复落库）；响应**字段结构不变**。

## 2. 背景（ERR-07，依据 `错误记录-20261104.md` §ERR-20261104-07）
- 现象：问「公司今年营收是多少」→「模型服务暂不可用，本次回答未完成，请稍后重试。」错误码 `MODEL_UNAVAILABLE`。
- 已排除配置缺失（.env 三项已设）；12:11 尚可用、12:13 失败 → 临时上游故障可能性大，但**产品侧把各种原因都包装成同一错误码**，用户无法自救。
- 正面样本（作为整改模板，逐字）：
  > 这是服务调用失败，不是资料中没有答案。错误码：MODEL_UNAVAILABLE。可稍后重新提问；服务端不会因重试而重复保存同一条回答。
- 现状代码（T101/T102/T103 后行号自查）：`service.py` `_call_model`（约 `:1416-1441`）对 `ModelError` 透传、`TimeoutError`→`ModelTimeout`、**其余任意异常一律 `ModelUnavailable`**；`_model_error_text`（约 `:1714-1730`）已有 `MODEL_NOT_CONFIGURED / MODEL_TIMEOUT / MODEL_UNAVAILABLE / MODEL_BUDGET_REFUSED / MODEL_OUTPUT_INVALID` 文案；`_answer` 的 `except ModelError` 直接透传 `exc.code/exc.retryable`。
- 需覆盖的真实原因分类（不限于）：**配置**（model 未注入/构造失败）、**预算/授权**（预算拒绝）、**provider**（网络/5xx/上游不可用）、**超时**、**输出校验**（既有 MODEL_OUTPUT_INVALID）、**内部**（我们自己的非预期异常，不应冒充 provider）。

## 3. 输入（先读这些）
1. `.claude\handoffs\2026-11-04-p1-design.md` §3（T104 行）、§9 决策 D-3、任务拆解 T104 段。
2. `错误记录-20261104.md` §ERR-20261104-07（:305-334）。
3. `backend/src/mktkb/conversations/service.py`：`_call_model`、`_model_error_text`、`_service_error`、`_answer` 的异常捕获、`_Result`（error_code/retryable）、`_model_input`。
4. 模型网关异常类定义（grep `class ModelError`/`ModelNotConfigured`/`ModelTimeout`/`ModelUnavailable` 所在模块；**只读**，本包不改网关模块）。
5. 既有测试（不得削弱）：`backend/tests/acceptance/test_t09_security.py:440-465`（错误码矩阵）、`backend/tests/integration/test_chat.py:260-280`、`:515-540`、`backend/tests/observability/test_paths_e2e.py:370-385`（trace reason/error_code）、`backend/tests/unit/test_conversations.py:175-205`、`test_s2b_live_gate.py:465-560`、`test_s2c_paygate_http.py:290-300`、`test_s2d_post_guard_http.py:320-340`。
6. D-3 授权：只允许错误码/文案**取值**变化，`AskResult`/响应 JSON **字段结构**不变（不得新增字段）。

## 4. 交付物（只准写这些路径）
1. `backend/src/mktkb/conversations/service.py`（主改：异常→(error_code, retryable, text) 分类映射；内部异常单独归类，不冒充 provider）。
2. `backend/tests/` 本包测试：**monkeypatch 覆盖各异常类型**（配置/预算/provider/超时/输出校验/内部/未知），断言 `error_code + retryable + 文案模板要素`；同步最小更新被"取值变化"影响到的既有断言（不得削弱结构/行为断言）。
3. `fixtures/evaluation/regression.jsonl`：可追加 T104 种子（`source_err_id=ERR-20261104-07`，`suite=regression`；dataset 层只能表达 kind/notes，须在 report 说明；不得动 RG001–RG004/RG005–RG007 现有状态）。
4. `docs/reports/OBS-EVAL/P1/evidence/T104/`（≤4 份证据）
5. `.claude/handoffs/T104-error-classification/report.md`（五段，≤80 行）
6. 1 个 commit（见 §7）
**不要写**：模型网关模块、API schema/响应字段结构、前端、b0/badcase、gate 配置、其他包文件。

## 5. 允许 / 禁止
- 允许：service.py 异常分类 + 文案映射（取值变化，D-3 已授权）；新增内部错误码取值；本包测试；regression 追加；只读读网关/测试。
- 禁止：新增/删除响应字段、改 API 字段结构、改网关/其他模块、改 b0/badcase、放宽/删除既有断言（只允许因取值变化同步更新"期望字符串/期望错误码"这类取值断言，且必须在 report 列清单）、`skip`/`xfail`、真实模型调用、读 `.env`/Holdout、切分支/push、新增生产依赖。

## 6. 验收标准（逐条可判定）
1. **分类矩阵完整**：每个原因类别（配置/预算/provider/超时/输出校验/内部/未知）都能通过 monkeypatch 触发，得到**可区分**的 `error_code` 与正确 `retryable`（配置/预算：重试无用→False；provider/超时：可重试→True；内部：按实际口径明确并写明理由）。矩阵表进 report。
2. **不再一律 MODEL_UNAVAILABLE**：非 provider 原因不得报 `MODEL_UNAVAILABLE`（有测试逐类证明）。
3. **文案模板一致**：每类文案都说明"是服务调用失败、不是资料中没有答案"或等价语义 + 可否重试 + 不会重复落库（按错误码给出统一模板，D-3 允许取值变化）；provider 类保留 ERR-07 正面模板语义。
4. **响应结构不变**：`AskResult`/响应 JSON 字段集合与改动前一致（有测试或 diff 证明）；`retryable`/`error_code` 语义不变。trace 的 reason/error_code 与响应一致（observability 测试全绿或最小同步，不得削弱）。
5. **不误伤**：b0/badcase local run 与修复前对照 `hard_failures` 无新增、case 级 0 变化；既有错误码相关测试仅在"取值变化"处最小同步并在 report 列清单；全量 `backend/tests` 0 failed/0 error。
6. 证据 ≤4 份、report 五段、1 commit、只改允许文件、无 skip/xfail/删断言。

## 7. 提交要求
- 分支 `p1/fix-retrieval`；**1 个 commit**，消息：`p1/T104 model error cause classification`；不 push/不 amend 历史。
- 提交前 `git status --short` 只含允许路径；report 记录 commit 信息与"既有断言取值同步清单"。

## 8. 报告格式（五段，≤80 行）
1) 完成内容；2) 验收标准自证（每条 ≤2 行，带命令/`文件:行`）；3) 实际运行结果（本包/受影响目录/全量 + b0/badcase 前后对照 + commit sha + stat + 异常分类矩阵）；4) 偏离或未做（含既有断言取值同步清单、ERR-07 的"营收未短路"词表残余声明）；5) 风险（一句话）。
