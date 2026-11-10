# P1FIX-C 证据：文档/法规答案的来源链路与 not_found 徽标一致性

> 起点：T105-R3 证据 §A/C（`docs/reports/OBS-EVAL/P1/evidence/verify/T105-R3/03-probe-results.md`）
> 记载“C3/C4/C5/C6 文档/法规答案 `sources=[]`，但内核有 citations”；#52 记载
> `not_found` 徽标仍写“无匹配资料”。本文件核实并修复。

## 1. 链路核实（内部引用 → 产品提交 → API → 前端）

代码事实（修复前）：

1. 内核答案 `RagAnswer.citations` 有文档来源；`rag.answer._citation()` 提供 `Citation`，
   但该类型**没有**产品来源单元 ID（只有 chunk/source 标识）。
2. 产品转换 `conversations/service.py::_rag_turn_result`：`kind in {answer, conflict}` 时
   **只从 `answer.facts` 取 `source_unit_id`**；文档/法规抽取答案 `facts=[]`，于是
   `source_ids=()`。
3. 提交事务 `_commit_result_impl` 只按 `reference_ids` 建 `MessageSource` 行并回填
   `AskResult.sources`；`sources=[]` 的答案在 API/前端就没有来源区，前端还显示
   “本次回答未返回可核对来源，请勿直接引用”。
4. `_document_fallback` 的 `citations` 是真实引用（只取包含答案句的证据）；问题在**转换丢失**，
   不是内核没有引用，也不是测试夹具独有现象。

## 2. 修改

| 文件 | 修改 |
| --- | --- |
| `backend/src/mktkb/rag/types.py` | `Citation` 新增 `unit_ids: tuple[str, ...] = ()`（本 chunk 背书的产品来源单元 ID；默认空，兼容既有构造）。 |
| `backend/src/mktkb/rag/answer.py` / `retrieval.py` | `_citation()` 与 `_to_evidence()` 填充 `unit_ids=chunk.unit_ids`。 |
| `backend/src/mktkb/conversations/service.py` | `_rag_turn_result`：结构化答案仍只用 facts 来源（行为不变）；文档答案（无 facts）用 citations 的 `unit_ids` 映射为产品来源，交给既有 `_commit_result_impl` 统一复核可见性/有效版本后落 `MessageSource`。 |
| `backend/src/mktkb/conversations/service.py` | `FIELD_NOT_RECORDED` 拒答时带出缺失字段名到 `missing_fields`（值变化，API 字段结构不变），供前端徽标区分。 |
| `frontend/src/utils/format.ts` / `MessageCard.tsx` | `resultBadgeLabel(..., missingFieldCount)`：`not_found` 且有缺失字段 → 徽标“字段未记录”，与正文“记录存在，但缺少该字段”一致；无缺失字段仍“无匹配资料”（既有 e2e 断言不变）。 |

**没有伪造来源**：来源只来自内核真实 citations 的单元；**没有删除答案**；API 字段结构未变
（`AskResult` 12 字段、`MessageView` 12 字段、`SourceSummary` 6 字段、`SourceView` 10 字段）。

## 3. 修复后验证

### 3.1 同一 T105-R3 独立探针：文档/法规答案 sources 从 0 → 非 0

| 场景 | 修复前 sources | 修复后 sources |
| --- | --- | --- |
| C3 那个海报的档期物料要提前多少天提报需求？ | 0 | **6** |
| C4 那个海报的《明码标价…规定》自何时起施行？ | 0 | **4** |
| C5 那个海报的价格欺诈规定是什么？ | 0 | **6** |
| C6 那个海报的审批流程是什么？ | 0 | **5** |
| H 系列 审批要求/审批权限/盘点规定 | 0 | **5 / 5 / 5** |
| C7（缺字段拒答）/ B2 新内容拒答 | 0 | 0（拒答不暴露来源，符合预期） |

### 3.2 来源归属 / 版本 / 访问权限（真实 HTTP，`backend/tests/integration/test_p1_source_bridge.py`）

上传台账 + 法规原文并发布后，多轮问“那个海报的价格欺诈规定是什么？”：

- `sources` 每条含 `source_id / document_name / version_number / status=active / locator`，
  且包含法规资料名；
- `GET /api/v1/messages/{message_id}/sources/{source_id}` → 200，返回同一资料名/版本/`active`
  与真实片段文本（用户可访问的来源详情）；
- 另一员工访问同一来源详情 → 403/404（先鉴权消息归属）；
- `GET /conversations/{id}/messages` 的历史消息 `sources` 与实时响应一致（来源已持久化，
  刷新后仍可见）；
- 记录型答案（数量）来源保持可访问；越界拒答 `sources=[]`。
- 结果：该文件 3 passed（含上述全部断言）。

### 3.3 not_found 徽标一致性

- 内核/产品：`missing_fields` 现在对“记录存在但缺字段”返回如 `["日期"]`；
  前端 `format.ts` 依此显示“字段未记录”；正文为“资料中未记录日期（记录存在，但缺少该字段）”。
- 未知门店/资料未收录等无缺失字段的 `not_found` 仍显示“无匹配资料”，既有 e2e 断言（
  `frontend/e2e/02-chat.spec.ts`、`acceptance-02-kinds.spec.ts` 等）不需要改写；
  无涉及 `not_found` 徽标文案的 e2e 变更。
- 前端 `npm run typecheck` exit 0、`vite build` exit 0（本次改动仅 utils/MessageCard）。

## 4. 单元/回归

- `backend/tests/unit/test_p1_source_bridge_mapping.py`（4 用例）：文档答案 citations→source_ids；
  结构化答案仍 facts-only；FIELD_NOT_RECORDED→missing_fields；拒答不暴露 citations。
- 既有 `source_access`/`test_chat`/`test_t105`/前端 e2e 断言未改；typecheck/build 通过。

## 5. 剩余问题（如实）

- 文档答案来源数量可能多于“答案句”本身（同一证据 chunk 聚合多个相邻 unit），属既有
  证据面粒度，不是伪造；本次未改分页/来源数上限。
- 前端 e2e 未在本次环境运行（未装配浏览器/服务）；已用 typecheck/build + 后端真实 HTTP 覆盖
  数据链路，e2e 记为 **NOT-RUN**（需要主人既有 e2e 环境），不作为本次通过依据。
