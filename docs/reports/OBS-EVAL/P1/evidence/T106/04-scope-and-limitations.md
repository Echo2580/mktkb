# T106 证据 04：改动范围、边界与残余

## A. 改动文件（只含允许路径）

| 文件 | 改动 |
| --- | --- |
| `backend/src/mktkb/copy.py`（新增） | reason→文案唯一映射、别名白名单、T104 服务错误模板、动态构造器 |
| `backend/src/mktkb/conversations/service.py` | 文案来源改为 `copy`；`_model_error_text(code, retryable)`；legacy 5 reason/overshoot/澄清追问/知识版本/索引错误 |
| `backend/src/mktkb/rag/answer.py` | `_no_answer` 各 reason、冲突/多实体/枚举/有效期/模型错误/事实拒绝文案 |
| `backend/src/mktkb/rag/query.py` | 澄清、未知区域、指代、缺槽、空查询文案 |
| `frontend/src/features/chat/MessageCard.tsx` | 徽标、无候选澄清、历史服务错误可重试性/提示 |
| `frontend/src/utils/format.ts` | `resultBadgeLabel`、clarification 中性标签、service_error 标签取值 |
| `backend/tests/unit/test_p1_t106_copy.py`（新增） | 映射唯一性/三要素/覆盖/T104 矩阵/文案不变量 |
| `frontend/e2e/02-chat.spec.ts`、`acceptance-02-kinds.spec.ts` | 徽标取值同步 + 新增 C02 无候选澄清用例 |

未改：`AskResult` 12 字段、`MessageView` 字段集、`ResultKind` 集合/顺序、
`error_code` 语义、`intent.py`/意图词表、b0/badcase 数据、gate 配置、`var/`、
账本/GO；未 push/amend 历史；未读 `.env`/Holdout。

## B. 行为不变自证

- 响应字段：既有 T104 HTTP 测试逐字断言 12 字段，全部通过（`backend/tests/integration/test_p1_t104_error_classification_http.py`）。
- kind/error_code：b0/badcase 逐例 0 差异；regression 仅 RG006（T105 既有收口）；
  b0/badcase/regression gate `hard_failures=[]`（regression 基线为 `['security_leak']`，只收缩不新增）。
- 检索路径/状态机：只替换文案表达式；`answer.py` 的冲突文本保留 FactValidator
  可验证句式（曾因追加说明句被事实闸门拒绝，已回退为 `CONFLICTING_VALUES_RECORD` 原句式）。
- T104 七类 + `MODEL_POST_SEND_AUTH_DENIED` 文案逐字保留（证据 01 §B）。

## C. 偏离 / 未做

- **未改 `not_found` 徽标“无匹配资料”**：`NO_INTENT` 等系统侧解析失败仍与资料侧
  共用同一 kind，`MessageView` 无 reason，前端无法可靠区分；本包只在正文明确
  “如果确认资料中存在，请改用更具体问法”，不臆造更细徽标。
- **`POLICY_FOLLOWUP` 别名到 `NO_EVIDENCE`**：该 plan reason 不是独立用户结局，
  保持内部 reason 不变，文案复用检索未命中说明；避免改 Trace reason 语义。
- **历史冲突/来源明细文案未动**：本包验收只要求 clarification；这两处仍保留
  “未保存…明细”表述（kind=conflict 本身已说明存在冲突，风险较低）。
- `MODEL_OUTPUT_INVALID` 在实时响应 `retryable=true`（T104 既有语义），前端仍按
  “重新提问不会改变结果”处理（既有产品口径，本包未改）。
- 前端未新增组件测试框架；新增行为由 Playwright C02 覆盖（live + reload）。

## D. 残余风险（P2，不阻塞）

- 前端对历史服务错误只能按稳定码集合推导可重试性；未来新增非重试码若未同步
  `NON_RETRYABLE_SERVICE_ERROR_CODES`，会短暂显示“重新提问”。集合与后端
  `copy.SERVICE_ERROR_CODES` 的 retryable 需同步维护。
- `NO_INTENT` 仍无法在徽标层区分系统解析失败与资料缺失（见 §C）；彻底解决需
  新增 reason 字段，受 D-3 字段结构约束，本包不做。
- 文案为中文单语；未引入 i18n。

## E. R1 返工（2026-11-08）

### E.1 改动文件

| 文件 | 改动 |
| --- | --- |
| `backend/src/mktkb/copy.py` | 三条目文案 + `material_related`（IDENTIFIER/NO_INTENT/ANAPHORA） |
| `backend/tests/unit/test_p1_t106_copy.py` | +7 条诚实性/可达性测试（8→15） |
| `backend/tests/{integration,rag}/test_p1_t105_anaphora_field.py` | 旧文案“未记录”断言按取值最小同步为“不属于台账字段”（各 1 行，语义不变） |
| `frontend/src/utils/format.ts`、`MessageCard.tsx` | P2：INVALID_QUERY 徽标/历史提示按 `error_code` 对齐正文 |
| `report.md`、本证据 03/04 | R1 段与 P3 更正 |

未改：API 字段结构、`ResultKind`/`error_code` 语义、`intent.py`/词表、
`fixtures/**`、gate 配置、`var/**`、账本/GO；无 skip/xfail/删断言/新依赖/真实调用。

### E.2 诚实性口径

- 本包 01 证据 §A 的三条目 `material_related` 与 §C 的旧文案描述为 R1 前状态，
  已被本节与 report §6 取代（按返工单只追加 03/04，不重写 01）。
- `material_related=False` 的文案不得含资料侧结论；唯一的否定形态
  “不是资料中没有答案”在机械测试中先剥离再断言。三条目最终文案见 report §6.1。
- `IDENTIFIER_NOT_RETRIEVABLE` 保留“未按标识检索…不能据此判断该记录不存在…也不能确认
  该记录未找到”，明确系统未执行检索；该“未找到”仅出现在否定句内，且满足 T09 U04
  冻结题集的可接受缺失措辞（U04 随全量通过）。
- `NO_INTENT` 当前不可达：AST 枚举 `intent.py` 全部 `IntentPlan(intent=None)`，
  均带 `unknown_identifier`/`identifier`/`clarification`（非空）。文案仍按系统侧
  失败保持诚实；未来若出现裸 `intent=None`，
  `test_no_intent_branch_is_guarded_by_current_intent_plans` 会失败。
- `ANAPHORA_NEW_CONTENT` 仍由 `rag/answer.py:262-270` 直接使用 copy 文本；无接线改动。

### E.3 P2 / P3 / 残余

- P2：`SERVICE_ERROR_BADGE_LABELS={INVALID_QUERY:"查询条件问题"}`；历史提示
  “这是查询条件问题，不是服务故障；请换个说法后重新提问。”，与正文一致。
  其他服务码徽标不变。
- P3：report §2-6 的 RG006 表述已更正（RG001–RG005 不变、RG006 fail→pass）。
- 残余：`INVALID_QUERY` 徽标分支无既有 e2e 注入入口（acceptance 只注入模型错误），
  本 R1 记为 NOT-RUN（不新增 mock e2e），由 typecheck/build + 纯函数映射覆盖。
- 残余：历史 clarification 有候选但未持久化时仍只能显示“需补充条件”
  （前端无 reason 字段，保持 T106 原判断）。
