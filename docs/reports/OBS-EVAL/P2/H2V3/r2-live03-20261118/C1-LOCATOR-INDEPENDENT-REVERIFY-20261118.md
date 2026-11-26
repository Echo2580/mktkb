# C-1 引用摘要脱敏独立复验报告

主人，验收结论：**C-1 通过（仅限本轮离线合成数据与 `sources[].locator.cells` 引用摘要面）。**

本轮未发现 C-1 阻塞项或回归。本轮 C-1 实际修改只有 `SourceSummary.locator` 的一个输出层校验器；首次问答、同请求重放、历史消息、冲突消息（含 legacy 回退）均不再返回 `locator.cells`，资料名、版本、工作表、行号/段落仍可用。四个指定测试文件独立复跑 **34 passed / 0 failed**；自建合成 HTTP 探针 **83/83** 通过；改前临时副本上两条 C-1 用例 **2 failed**，独立复现了电话、地址、联系人随整行快照泄漏。

一处**范围外**观察：店家级单字段问题（如“白榆店的合作状态是什么？”）的 **正文** 仍会带出该行联系人、电话、地址；这不属于本轮 `sources[].locator.cells` 验收面，也不是本次改动引入，故不改变 C-1 判定，但建议另立任务处理。详见 §7。

真实 R2 未执行，仍为 attempt4 的 **4/5**；attempt5 保持暂停。

## 1. 验收边界与身份

| 项 | 值 |
| --- | --- |
| 仓库 | `D:\GPT项目\市场部AI知识库` |
| HEAD | `97b0066726e5b8d6f94cbc0b63a890084550c106` |
| Python | 仓库 `.venv\Scripts\python.exe`，Python 3.12.7 |
| 受查产品文件 | [schemas.py](backend/src/mktkb/conversations/schemas.py)，SHA-256 `412DEF4E3270E954FD26EB63FD4B3B60BBE65AA6FAC04CD999149A772B9DCE24` |
| 工作树 | 保留现有改动，未提交、未回滚、未清理；本轮只读取产品代码与运行测试，未改产品代码、冻结题目、评分口径或预算 |
| 临时目录 | 仓外 `%TEMP%\c1-acceptance-*`、`%TEMP%\c1-prefix`；未向仓库写入临时探针 |

边界：

- 自建探针全部使用自建合成虚构值，未读取 fixtures、冻结题面、真实 case_id、期望值或私有材料；复跑既有测试时，fixture 由测试自身读取，本轮未人工查看或复制私有材料。
- 只使用本机 `TestClient` 与离线模型替身；未调用真实 DeepSeek、OCR 或外部服务。
- 未发起真实外发，未启动 attempt5，未生成/使用新 GO，未写账本或预算。
- 未跑全量；仅跑指定四个测试文件、两条定向 C-1 用例和自建 HTTP 探针。

零外发检查：自建探针在进程内拦截 `socket.connect` / `connect_ex` / `getaddrinfo`，只允许本机地址。运行期间只观察到 `127.0.0.1` 本地回环（TestClient/anyio 的本地装配），**非本地地址 0 次**；两个离线模型替身调用次数均为 **0**。

## 2. 实际修改范围核对

`git diff --numstat` 对该文件为 `6 0`，即只新增 6 行、无删除；diff 只有一个 hunk：

```diff
@@ -66,6 +66,12 @@ class SourceSummary(BaseModel):
     locator: dict
     published_at: datetime | None = None
 
+    @field_validator("locator")
+    @classmethod
+    def _omit_cell_snapshots(cls, locator: dict) -> dict:
+        # A citation pointer needs the row coordinates, not the values of the whole row.
+        return {key: value for key, value in locator.items() if key != "cells"}
+
```

见 [schemas.py:69-73](backend/src/mktkb/conversations/schemas.py#L69-L73)。该实现有两个关键性质：

1. **发生在引用摘要输出层**：`SourceSummary` 是问答响应 `AskResult.sources`、历史消息 `MessageView.sources`、冲突消息 sources 共用的模型；变更只影响该模型实例化后的 `locator`，不改检索、解析、入库或 `SourceUnit` 原始记录。
2. **不写回原始来源记录**：校验器返回新 dict，不原地 `pop`/修改传入的 `unit.locator`。自建探针在问答前后按 `SourceUnit.id` 对比原始 `locator`，原有 `cells` 与单元格行值保持不变；数据库中持久化的 `ConversationRequest.result_json.sources` 则是脱敏后的响应载荷（这是响应结果记录，不是原始来源记录）。

构造/使用点核对：

| 入口 | 代码位置 | 是否经 `SourceSummary` |
| --- | --- | --- |
| 首次问答响应 | [service.py:2076](backend/src/mktkb/conversations/service.py#L2076) | 是 |
| 同请求重放 | [service.py:644](backend/src/mktkb/conversations/service.py#L644) 重新走 `_message_sources_for` | 是 |
| 历史消息 | [sources/service.py:118](backend/src/mktkb/sources/service.py#L118)、[sources/service.py:128](backend/src/mktkb/sources/service.py#L128) | 是 |
| 冲突消息回退 | [service.py:211](backend/src/mktkb/conversations/service.py#L211) → `summary_for` | 是 |
| 来源详情 | [sources/service.py:156](backend/src/mktkb/sources/service.py#L156) 使用独立的 `SourceView` | 否，按既有契约保留完整 `locator` |
| 原件下载 | [sources/service.py:170](backend/src/mktkb/sources/service.py#L170) | 不涉及摘要模型 |

源码核对结论：

- 产品代码中 `cells` 的摘要输出面只有 `SourceSummary` 裁剪处；`SourceView` 的详情/解析层按契约保留完整定位，未发现第二个把 `locator.cells` 塞回摘要的序列化器。
- 未发现 `SourceSummary.model_construct` 绕过校验；`SourceSummary` 的直接构造和 `model_validate` 都会触发该 validator。
- `SourceView` 详情保留 `cells` 是既有“授权后看原件”契约，不是 C-1 摘要泄漏；其归属鉴权与版本有效性见 §5。

## 3. 指定测试复跑

命令均在仓库根执行，Python 为 `.venv\Scripts\python.exe`。逐文件结果：

| # | 测试文件 | 结果 | 退出码 | 用时 |
| --- | --- | --- | --- | --- |
| 1 | `backend/tests/integration/test_r2_206b_contact_gate_increment.py` | **20 passed** | 0 | 13.30 s |
| 2 | `backend/tests/integration/test_c29_reverify_20261118_independent.py` | **9 passed** | 0 | 6.11 s |
| 3 | `backend/tests/integration/test_source_access.py` | **3 passed** | 0 | 3.49 s |
| 4 | `backend/tests/integration/test_conversation_recovery.py` | **2 passed** | 0 | 7.04 s |

复跑命令示例：

```powershell
cd D:\GPT项目\市场部AI知识库
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_r2_206b_contact_gate_increment.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_c29_reverify_20261118_independent.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_source_access.py -q
.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_conversation_recovery.py -q
```

四文件合并复跑：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  backend/tests/integration/test_r2_206b_contact_gate_increment.py `
  backend/tests/integration/test_c29_reverify_20261118_independent.py `
  backend/tests/integration/test_source_access.py `
  backend/tests/integration/test_conversation_recovery.py -q
```

结果：**34 passed, 1 warning in 29.06 s，退出码 0**。`1 warning` 是 FastAPI/Starlette 的 `StarletteDeprecationWarning`（httpx 兼容提示），不是产品或断言失败。

两条定向 C-1 用例：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  "backend/tests/integration/test_r2_206b_contact_gate_increment.py::test_c_locator_cells_must_not_expose_restricted_values" -q
```

结果：**2 passed，退出码 0，1.92 s**（参数 `a1_mixed3`、`a2_mixed4`）。

### 3.1 改前独立复现（临时副本，不修改工作树）

为核对开发报告“改前两条 C-1 用例均能复现”的说法，把 `backend` 复制到仓外 `%TEMP%\c1-prefix`，**只在副本**删除 `_omit_cell_snapshots` validator，复制 `migrations`/`alembic.ini` 后运行同一组定向用例：

```powershell
cd %TEMP%\c1-prefix
D:\GPT项目\市场部AI知识库\.venv\Scripts\python.exe -m pytest `
  "tests/integration/test_r2_206b_contact_gate_increment.py::test_c_locator_cells_must_not_expose_restricted_values" -q
```

结果：**2 failed，退出码 1，1.95 s**。两条失败均在 `sources[].locator.cells[*].display` 检出合成受限值：

```text
a1_mixed3 / a2_mixed4: ['020-00000011', '示范巷27号', '合成负责人·丙']
```

失败断言原文指向 `sources[].locator` 的用户可读 JSON，包含店家行整行 `cells`。这独立证明：修改前缺陷真实存在，修改后定向用例转绿；不是测试口径放宽。

## 4. 自建合成 HTTP 验收

### 4.1 合成资料与问题

全部为虚构值，和开发方/既有探针的实体、值、文档名不重叠：

| 资料 | 工作表 | 行 | 内容 |
| --- | --- | --- | --- |
| `合成验收物品台账-甲.xlsx` | `台账` | 4 | 青槐店 / 铜制标牌 / ZX-01 / 子区9号架 / 7 |
| 同上 | `台账` | 5 | 白榆店 / 铜制标牌 / ZX-02 / 丑区8号架 / 4 |
| `合成验收店家名册-甲.xlsx` | `台账` | 4 | 青槐店 / 虚构联系人·甲 / 000-0000-1001 / 虚构大道101号 / 合作中 |
| 同上 | `台账` | 5 | 白榆店 / 虚构联系人·乙 / 000-0000-1002 / 虚构大道102号 / 暂停合作 |
| `合成验收冲突名册-甲.xlsx` | `台账` | 4 | 青槐店 / 虚构联系人·甲 / 000-0000-1001 / 虚构大道101号 / 合作中 |
| `合成验收冲突通知-乙.docx` | — | 段落 1 | “青槐店的合作状态为暂停合作。” |

问句：

- C29/首次问答/重放/历史：`青槐店的铜制标牌放在哪个位置？白榆店的合作状态如何？`
- 冲突：`青槐店的合作状态是什么？`

表头行均为第 3 行，数据从第 4 行开始；文档版本均为 1，均经真实上传 → worker 解析 → 发布。

### 4.2 实际覆盖的入口

| 入口 | 实际请求 | 本轮结果 |
| --- | --- | --- |
| 首次问答 | `POST /api/v1/conversations/{id}/messages` | 200，`kind=answer`；2 条来源，无 `cells`，无受限值 |
| 同请求重放 | 同一 `client_request_id` 再 POST | 200，同一 `message_id`，响应 JSON 与首次逐字段相等 |
| 历史消息 | `GET /api/v1/conversations/{id}/messages` | 200，assistant 来源 2 条，无 `cells` |
| 冲突首次问答 | `POST .../messages`，两个有效值 | 200，`kind=conflict`；值恰为 `{合作中, 暂停合作}`；2 条来源，无 `cells` |
| 冲突重放 | 同一 `client_request_id` | 200，同一 `message_id`，响应 JSON 与首次相等 |
| 冲突历史 | `GET .../messages` | 200，来源 2 条，无 `cells` |
| legacy 冲突回退 | 删除该冲突消息的 `MessageSource` 行后再取历史 | 200，仍从 `result_json.conflicts` 解析 2 条来源，无 `cells` |
| 来源详情 | `GET /api/v1/messages/{message_id}/sources/{source_id}` | 200，授权本人；`SourceView` 保留完整 `locator.cells`（既有契约） |
| 原件下载 | `GET .../sources/{source_id}/file` | 200；字节与上传文件一致；`no-store`、`nosniff`、RFC5987 文件名 |
| 持久化响应 | 读 `ConversationRequest.result_json` | `sources` 无 `cells` |
| 原始来源记录 | 读 `SourceUnit.locator` | 原有 `cells` 与行值完整保留 |

仅靠源码核对的入口/事实：

- 没有第二个摘要序列化器输出 `locator.cells`（源码检索 + diff 核对）。
- `SourceView` 详情/原件路径保留完整 `locator`，按既有契约属于授权后查看，不是本轮摘要面。
- `ConversationRequest.result_json` 的写入点确实使用 `ask_result.model_dump()`，因此持久化的是脱敏后的响应载荷；未发现任何消费者依赖该 JSON 的 `sources[].locator.cells`。
- legacy 冲突来源详情回退（`_legacy_conflict_reference`）未单独构造 HTTP 用例；其摘要回退已由“删除 MessageSource 后取历史”覆盖。

### 4.3 关键结果

**首次问答**：

```json
{
  "kind": "answer",
  "sources": [
    {
      "document_name": "合成验收物品台账-甲.xlsx",
      "version_number": 1,
      "status": "active",
      "locator": {"sheet": "台账", "row": 4, "header_row": 3, "cell_types": {"门店": "s", "物品": "s", "标识": "s", "位置": "s", "数量": "s"}}
    },
    {
      "document_name": "合成验收店家名册-甲.xlsx",
      "version_number": 1,
      "status": "active",
      "locator": {"sheet": "台账", "row": 5, "header_row": 3, "cell_types": {"标识": "s", "店家": "s", "联系人": "s", "电话": "s", "地址": "s", "合作状态": "s"}}
    }
  ]
}
```

- 两条来源的 `locator` 均无 `cells`；`sheet=台账`、`row=4/5` 与资料名、版本 1、状态 active 一致。
- 序列化整个 `sources` 后，六个虚构受限值（两店电话、地址、联系人）均未出现。
- 正文只含 `子区9号架` 与 `暂停合作`，不含 `丑区8号架` / `合作中`，未串店。
- 离线模型替身调用 0 次。

**重放与历史**：重放响应与首次逐字段相等；历史 assistant 消息同样 2 条来源、无 `cells`、无受限值。

**冲突**：`conflicts[0].entries` 恰为 `{合作中, 暂停合作}`，两个 `source_id` 都出现在 `sources`；xlsx 行 4 与 docx 段落 1 的摘要均无 `cells`，受限值未出现。删除 `MessageSource` 行后，legacy 历史仍解析出同样 2 条来源，仍无 `cells`。

**原始记录未被写回**：按 `SourceUnit.id` 比较问答前后的 `locator`，原有 `cells`、`display`、`header`、`cell_types` 完全一致；新增版本只新增单元，不改变旧单元。`result_json.sources` 则无 `cells`。

## 5. C29 同形与来源详情

### 5.1 两个值、两条引用、各自门店

C29 同形问句实测：

| 检查 | 实际 |
| --- | --- |
| 值归属 | 正文含 `子区9号架` + `暂停合作`；不含 `丑区8号架` / `合作中` |
| 引用数量 | 2 条，分别为物品台账与店家名册 |
| 行号 | 物品台账 `row=4`；店家名册 `row=5` |
| 版本 | 两条均 `version_number=1`、`status=active`；`Document.active_version_id` 与各自引用 `version_id` 一致，`version.state=published`，`document.deleted=false` |
| 物品引用单元文本 | `门店: 青槐店 | 物品: 铜制标牌 | 标识: ZX-01 | 位置: 子区9号架 | 数量: 7` |
| 店家引用单元文本 | `标识: SX-02 | 店家: 白榆店 | 联系人: 虚构联系人·乙 | 电话: 000-0000-1002 | 地址: 虚构大道102号 | 合作状态: 暂停合作` |

即：两个正确值分别绑定青槐店物品行与白榆店店家行；两条引用分别指向各自门店的当前有效记录，没有互相顶替，也没有拿另一店补值。

### 5.2 显式来源详情与原件访问

| 路径 | 预期 | 实际 |
| --- | --- | --- |
| 本人打开 active 来源详情 | 200，`SourceView` 返回完整定位/字段 | 200；`status=active`、`version_number=1`；`locator.cells` 存在（详情契约，非摘要） |
| 他人打开同一详情 | 403 | 403 |
| 他人下载同一原件 | 403 | 403 |
| 伪造 source UUID | 404 | 404 |
| 发布新版本后旧来源详情 | 410，`SOURCE_UNAVAILABLE`，`details.status=superseded` | 410；`code=SOURCE_UNAVAILABLE`、`status=superseded`、`version_number=1` |
| 发布新版本后旧来源原件 | 410 | 410 |
| 本人下载 active 原件 | 200，字节一致，`no-store`/`nosniff`/RFC5987 | 200；字节一致；头符合 |
| 历史摘要随版本变化 | 旧来源 `superseded`，另一来源 `active` | 与预期一致；摘要仍无 `cells` |

删除资料后的 `deleted`/410 路径未在自建合成中用 HTTP 重造，但指定套件 `test_source_access.py` 的 3 项已全部通过，覆盖了删除、替换、同字节重导入不恢复旧链接等既有契约；本轮不对该路径单独宣称独立 HTTP 覆盖。

## 6. 未覆盖项

- **未跑全量**：按要求只跑四个指定文件、两条定向 C-1 用例和自建探针；未重跑 unit/evaluation/rag 全量。
- **真实 R2 未执行**：无新 GO/保管人/受控窗口/外发授权；attempt5 未启动。真实状态仍为 attempt4 的 4/5。
- **无真实模型/供应商**：仅离线模型替身；未验证真实 DeepSeek 的引用摘要序列化（模型输出不直接构造 `SourceSummary`，但真实链路未跑）。
- **格式覆盖有限**：自建数据为 xlsx + docx；未覆盖 PDF、OCR、图片、表格合并单元格等格式。C-1 是模型层脱敏，格式无关，但未逐格式实测。
- **未覆盖前端渲染**：只验证 HTTP JSON；未验证 Web 前端如何展示 `locator`/详情。
- **未覆盖文档预览面**：资料版本的 `PreviewResponse`/`SourceUnitPublic` 仍按原样返回 `locator`（含 `cells`）；这是资料预览/原件面，不是会话引用摘要，本轮未按 C-1 验收。
- **未覆盖历史真实脏数据**：legacy 冲突回退是用合成数据删除 `MessageSource` 行模拟，不是实际旧库样本。
- **`cell_types` 仍保留**：摘要 `locator` 仍带 `cell_types`（表头 → 类型），不含行值；本轮未构造“表头本身含敏感字符串”的样例。若未来允许敏感表头，需另评估。
- **单店正文观察**：见 §7；不属于本轮 C-1 摘要面，未纳入通过/失败判定。
- **并发/竞态**：只验证顺序重放与历史读取；未构造并发同请求、并发版本替换。

## 7. 发现的问题与范围外观察

### 7.1 C-1 阻塞项/回归

**未发现。** 未发现 `locator.cells` 在问答、重放、历史、冲突摘要中复现；未发现原始 `SourceUnit.locator` 被改写；未发现 C29 两条引用串店或指向过期版本。

### 7.2 范围外观察：店家级单字段正文仍带出整行联系值

这不改变 C-1 判定，因为 C-1 的验收面是 `sources[].locator.cells`，不是正文；该路径也不经过本次修改的 `SourceSummary.locator` 校验器。

- **触发条件**：对包含联系人/电话/地址的店家行，只问一个非联系字段，例如“白榆店的合作状态是什么？”。
- **预期（按最小披露）**：正文只回答合作状态，或按联系信息闸门拒答/收敛。
- **实际**：`kind=answer`，正文包含 `联系人：虚构联系人·乙；电话：000-0000-1002；地址：虚构大道102号`；同时 `sources[].locator` 已无 `cells`，摘要面是干净的。
- **性质**：既有正文渲染面，不是本次 `SourceSummary` 改动引入；本轮未修，建议另立任务评估是否属于 C-1 之外的独立泄漏面。

### 7.3 残余说明：`cell_types`

摘要仍保留 `cell_types`（表头到类型的映射），不含单元格行值。本轮的虚构电话/地址/联系人都在行值中，因此未进入摘要；若业务允许表头本身承载敏感字符串，`cell_types` 会保留表头文本，建议后续按数据字典约束或在摘要层进一步收敛。

## 8. 判定与状态

- **C-1：通过（离线合成数据范围）。** 脱敏发生在引用摘要输出层；首次问答、同请求重放、历史消息、冲突消息（含 legacy 回退）均无 `locator.cells`，虚构受限值未进入摘要；资料名、版本、工作表和行号/段落仍可核对；原始 `SourceUnit` 未被写回。
- **C29 同形：通过本轮独立核对。** 两个正确值、两条引用各自绑定各自门店的当前有效记录；详情归属鉴权与版本有效性符合既有契约。
- **范围外**：§7.2 的正文联系值观察不改变 C-1 结论，建议单独立项。
- **真实 R2：未执行。** 仍为 attempt4 的 **4/5**；attempt5 保持暂停。

## 9. 证据路径

- 本报告：[C1-LOCATOR-INDEPENDENT-REVERIFY-20261118.md](docs/reports/OBS-EVAL/P2/H2V3/r2-live03-20261118/C1-LOCATOR-INDEPENDENT-REVERIFY-20261118.md)
- 开发报告：[C1-LOCATOR-REDACTION-20261118.md](docs/reports/OBS-EVAL/P2/H2V3/r2-live03-20261118/C1-LOCATOR-REDACTION-20261118.md)
- 产品修改：[schemas.py:69-73](backend/src/mktkb/conversations/schemas.py#L69-L73)
- 指定测试：
  - [test_r2_206b_contact_gate_increment.py](backend/tests/integration/test_r2_206b_contact_gate_increment.py)
  - [test_c29_reverify_20261118_independent.py](backend/tests/integration/test_c29_reverify_20261118_independent.py)
  - [test_source_access.py](backend/tests/integration/test_source_access.py)
  - [test_conversation_recovery.py](backend/tests/integration/test_conversation_recovery.py)
- 仓外自建探针原始 JSON：`%TEMP%\c1_independent_acceptance.json`（83 项检查，0 失败）；改前副本：`%TEMP%\c1-prefix`（仅副本删除 validator，工作树未动）。
