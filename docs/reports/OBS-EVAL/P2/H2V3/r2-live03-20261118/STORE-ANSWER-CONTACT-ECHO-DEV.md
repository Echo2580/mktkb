# 店家记录正文回显修复开发自测报告

主人，结果：**已修复并通过开发自测；本次不是独立验收。** 只问店家合作状态时，正文不再附带同一行未请求的联系人、电话、地址；显式请求且既有策略允许的联系字段仍正常作答。改前在仓外临时副本上复现了 4 条失败、4 条通过；改后核心定向套件 51 项全过，`test_chat.py` 52 项全过，C-1 独立摘要探针 83/83。

真实 R2 未执行，attempt5 继续暂停。本次仅合成数据、本机 TestClient、离线模型替身和零外发检查。

## 0. 结论先行

- **主例已转绿**：`松涛店的合作状态：合作中；店家：松涛店。` 三个合成联系值均未进入正文。
- **改前已复现**：`松涛店的合作状态：合作中；店家：松涛店；联系人：合成负责人·丙；电话：020-00000011；地址：示范巷27号。`
- **最小修复**：在 `_record_answer_text` 的附带回显分支，用现有 `resolve_requested_role` 识别 `contact/phone/address`；当本次问题**没有涉及任何联系字段**时跳过这些附带值。显式请求的字段仍由 `validated` 生成。
- **没有改检索、安全策略、事实校验、模型网关、数据库结构或历史数据。**
- **测试**：新增 8 条定向用例；`206b + C29 + 会话恢复 + 来源访问 + 记录措辞` 合并 51 通过；`test_chat.py` 52 通过。
- **未做**：独立验收、真实模型、全量回归、旧已持久化消息改写、模型输入侧数据最小化。

## 1. 范围与工作树身份

| 项 | 值 |
| --- | --- |
| 仓库 | `D:\GPT项目\市场部AI知识库` |
| HEAD | `97b0066726e5b8d6f94cbc0b63a890084550c106` |
| Python | 仓库 `.venv\Scripts\python.exe`，Python 3.12.7 |
| 产品改动 | 仅 `backend/src/mktkb/conversations/service.py` 的 `_record_answer_text` 及其常量；该文件内其他差异为此前交付，未回滚 |
| 测试改动 | 仅向 `backend/tests/integration/test_r2_206b_contact_gate_increment.py` **追加** E 段；既有断言未改 |
| 临时目录 | 仓外 `%TEMP%\store-echo-*`；改前副本 `%TEMP%\store-echo-prefix` |
| 受查文件 SHA-256 | `service.py` `07C7885127781AF9CEB9859CE69370FB284A096B1BF19C238E1400EE2F8EC592`；`test_r2_206b...` `3DA1E170782E9371F9F0948F8FD3DFC64F1736AADECA3514A381764D1EFDEE0D` |

边界：

- 自建合成店家行，全部为虚构值；未读取私有材料、冻结题面、真实 case_id、期望值或评分/预算/账本。
- 未发起真实外发，未生成/使用 GO，未启动 attempt5。
- 改前复现只在仓外副本删除本次修复，工作树产品代码未被回退。
- 既有 `t09_network_guard`/`no_subprocess` 由 206b 文件级 `pytestmark` 继承；自建探针另加 socket 守卫。

## 2. 改前复现与联系值首次出现层

### 2.1 合成店家行

| 列 | 值 |
| --- | --- |
| 标识 | `SX-01` |
| 店家 | `青槐店` |
| 联系人 | `虚构联系人·甲` |
| 电话 | `000-0000-1001` |
| 地址 | `虚构大道101号` |
| 合作状态 | `合作中` |

资料经真实 HTTP 上传 → worker 解析 → 发布；问句 `青槐店的合作状态是什么？` 走 `POST /api/v1/conversations/{id}/messages`，模型替身输出只包含状态：

```text
根据资料：合作状态：合作中。
```

### 2.2 改前用户正文

```text
青槐店的合作状态：合作中；店家：青槐店；联系人：虚构联系人·甲；电话：000-0000-1001；地址：虚构大道101号。
```

三个未请求值均出现在正文。改后同主例：

```text
青槐店的合作状态：合作中；店家：青槐店。
```

### 2.3 首次出现层

按链路逐层核对：

1. **模型输入证据层**：`_model_input` 将记录行的完整 `text`/`fields` 交给模型；这里已经包含联系人、电话、地址。该层是 provider 输入面，不是用户正文。
2. **模型输出层**：受控替身只输出状态；`_record_facts` 只把状态纳入 `validated`。因此用户正文中的联系值不是模型输出直接透传。
3. **用户正文层**：`_record_answer_text` 旧的 `echo_fields` 循环遍历同一行的 `unit.fields`，把未在 `asked_roles` 内的字段追加到正文；联系人、电话、地址首次**用户可见**地出现在这里。

这与任务书线索一致：修复点应在 `_record_answer_text` 的附带回显分支，而不是模型输出或引用摘要。

### 2.4 改前测试证据

在仓外副本 `%TEMP%\store-echo-prefix` 中仅删除本次修复，再跑新增 E 段：

```powershell
cd %TEMP%\store-echo-prefix
D:\GPT项目\市场部AI知识库\.venv\Scripts\python.exe -m pytest `
  tests/integration/test_r2_206b_contact_gate_increment.py -q -k "test_e_"
```

结果：**4 failed / 4 passed，退出码 1**。失败项：

- `test_e_store_status_does_not_echo_unrequested_contact_fields`
- `test_e_status_model_echo_is_not_promoted_to_user_text`
- `test_e_status_filter_uses_existing_header_aliases`
- `test_e_new_answer_replay_and_history_are_echo_clean`

失败正文与 §2.2 同形，包含 `020-00000011`、`示范巷27号`、`合成负责人·丙`（E 段沿用 206b 既有合成行：松涛店，与 §2.1 的青槐店探针同形不同值）。另外 4 条（显式联系字段 3 参数 + 凭据拒答）改前也通过，说明它们是非回归对照，不是本次红转绿项。

## 3. 最小修复

产品代码只增加一个联系字段集合和一次上下文判断：

```python
#: 联系字段：本次问题未涉及联系字段时，不随行回显到正文；显式请求的字段仍由 validated 作答。
_CONTACT_ECHO_ROLES = frozenset({"contact", "phone", "address"})
```

`_record_answer_text` 内：

```python
asked_roles = {resolve_requested_role(label) for label, _value, _row_id in validated}
asked_contact = bool(asked_roles & _CONTACT_ECHO_ROLES)
...
if (
    role in asked_roles
    or (role in _CONTACT_ECHO_ROLES and not asked_contact)
    or role in (_RECORD_IDENTIFIER_ROLE, None)
    or not value
):
    continue
```

行为：

- 只问状态/位置等非联系字段：`asked_contact=False`，附带回显跳过 `contact/phone/address`。
- 显式问联系人/电话/地址：字段本身由 `validated` 进入正文；同行其它联系字段按既有“联系信息上下文”回显。
- 公开字段（如“店家”“合作状态”）和合法缺字段说明保持原样。
- 引用行、版本、来源定位、C-1 摘要均未改。

### 3.1 与任务书字面的一个有意收窄

任务书建议“识别 `contact`、`phone`、`address` 并跳过附带输出”。最初按字面无条件跳过，导致既有 `test_chat.py` 两条契约测试失败：

- `test_g09_phone_update_and_same_entity_conflict` 要求电话更新回答仍带同行联系人，证明“电话更新不串改联系人”；
- `test_g04_record_accepts_role_bound_alias_and_echo` 要求电话题保留同行联系人回显。

因此最终收窄为：**只有本次问题没有涉及任何联系字段时才跳过联系字段回显**。这样既修复“只问状态却附带联系值”，又不破坏既有电话/联系人回答契约。若经理希望进一步禁止联系字段之间的相互回显，需要另行裁决并同步改既有测试；本轮未擅自改。

## 4. 测试命令与结果

均使用仓库 `.venv\Scripts\python.exe`，仓库根执行，`-q --tb=short`。

| # | 范围 | 结果 | 退出码 |
| --- | --- | --- | --- |
| 1 | 新增 E 段（8 条） | **8 passed** | 0 |
| 2 | `test_r2_206b_contact_gate_increment.py`（20+8） | **28 passed** | 0 |
| 3 | `test_c29_reverify_20261118_independent.py` | **9 passed** | 0 |
| 4 | `test_conversation_recovery.py` | **2 passed** | 0 |
| 5 | `test_source_access.py` | **3 passed** | 0 |
| 6 | `test_t09_d6_r1_record_phrasing.py` | **9 passed** | 0 |
| 7 | `test_chat.py` | **52 passed** | 0 |
| 8 | 2+3+4+5+6 合并 | **51 passed** | 0 |
| 9 | C-1 独立摘要探针（复用 2026-11-18 验收脚本） | **83/83 checks** | 0 |
| 10 | 1+3+4+5+6+7 全合并 | **102 passed / 1 failed**（见 §4.1） | 1 |
| 11 | 改前副本 E 段 | **4 failed / 4 passed** | 1 |

关键命令示例：

```powershell
cd D:\GPT项目\市场部AI知识库
.\.venv\Scripts\python.exe -m pytest `
  backend/tests/integration/test_r2_206b_contact_gate_increment.py `
  backend/tests/integration/test_c29_reverify_20261118_independent.py `
  backend/tests/integration/test_conversation_recovery.py `
  backend/tests/integration/test_source_access.py `
  backend/tests/integration/test_t09_d6_r1_record_phrasing.py -q --tb=short

.\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_chat.py -q --tb=short
```

### 4.1 组合负载下的一条时序敏感失败

全合并运行 `102 passed / 1 failed`，失败为：

```text
test_g08_short_budget_cancels_inflight_model_call
assert len(facts["calls"]) == 1
实际 0
```

该测试把总预算压到 0.2s，并断言模型调用已进入一次；在组合负载下 `_ask` 尚未走到模型调用预算就到期，得到 0 次。单独复跑该用例 **1 passed**，`test_chat.py` 全量 **52 passed**。该文件不在本次产品改动内，失败点也不经过 `_record_answer_text`；本轮判断为组合负载下的既有时序敏感测试，不计入本修复回归，但已保留为复跑观察项。

### 4.2 验收矩阵对照

| 场景 | 证据 | 结果 |
| --- | --- | --- |
| 只问店家合作状态 | E1/E3/E6；正文 `松涛店的合作状态：合作中；店家：松涛店。`；来源 row 4/version 1 | PASS |
| 字段别名 | E2：行头 `负责人/联系方式/门店地址`；只问状态，三个值均不出现 | PASS |
| 新答复重放及历史 | E3：同一 `client_request_id` 同 `message_id`、同正文；历史 assistant 同正文；零命中 | PASS |
| 显式允许字段 | E4：联系人/电话/地址分别显式询问，均正确作答；既有电话→联系人回显契约保留 | PASS |
| 既有受限/凭据 | E5 店家级凭据题 `not_found`；既有 b1/b3/b4 全过 | PASS |
| C29 两值两引用 | C29 套件 9 通过；本次重跑 | PASS |
| C-1 摘要 | C-1 探针 83/83；206b C-1 两条定向用例 | PASS |

零外发/零子进程：206b 文件级 `pytestmark` 的 `t09_network_guard`/`no_subprocess` 对所有 E 用例生效；本次复用的 C-1 独立探针自带 socket 守卫，非本地地址 0 次。自建 store-echo 探针只使用本机 `TestClient` 与离线替身，未单独配置 socket 守卫；其行为证据不作为零外发主证据。

## 5. 覆盖入口

实际 HTTP 覆盖：

- `POST /api/v1/conversations/{id}/messages`：首次状态问答、显式联系人/电话/地址、凭据拒答。
- 同 `client_request_id` 重放。
- `GET /api/v1/conversations/{id}/messages`：历史 assistant 正文与来源。
- 来源摘要：C-1 探针与 206b C-1 用例；`locator.cells` 缺席、行/版本/工作表可核对。
- 引用/版本：E1 校验来源 row 4、version 1、active；E2/E4 校验 row 4；C-1 用例校验摘要无 `cells`。

仅源码/数据库核对：

- `_model_input` 仍把整行 `fields` 交给模型（provider 输入面）；本次未改，见 §6。
- `_record_facts` 对模型回显的其它字段只做“不据此放行事实”的处理，最终正文由 `validated` 重建。
- 旧已持久化消息的正文不改写；本次只影响新生成回答及其重放/历史读取。

## 6. 未覆盖与遗留项

- **未做独立验收**：本次是开发自测；经理需另行安排独立验收。
- **真实模型/供应商未跑**：只使用 `EvidenceEchoGateway`；真实模型是否会在正文外自行输出联系值、以及真实 provider 的输入数据最小化，未验证。
- **模型输入仍含整行字段**：`_model_input` 的证据 `text/fields` 包含联系人、电话、地址。它不进入本次用户正文，但 provider 侧数据暴露面仍在；若在范围内，应另立“模型输入最小化”任务。
- **联系字段之间的回显仍保留**：显式问电话/联系人/地址时，同行其它联系字段仍按既有契约回显（`test_chat.py` 两条用例要求）。本轮只修“问题未涉及联系字段”的场景；更严格的相互隔离需经理裁决。
- **旧消息**：已持久化的历史消息正文不重写；本次只保证新回答、重放和历史读取的新结果。
- **格式**：合成数据为 xlsx + docx；PDF/OCR/图片/合并单元格未逐格式覆盖。
- **前端**：只验证 HTTP JSON，未验证 Web 展示。
- **全量**：未跑全量；`test_chat.py` 全量通过，但组合负载下有 1 条时序敏感失败（§4.1）。
- **并发**：未构造并发同请求、并发版本替换。

## 7. 交付物

- 产品修复：[service.py:1195-1196](backend/src/mktkb/conversations/service.py#L1195-L1196)、[service.py:1691-1711](backend/src/mktkb/conversations/service.py#L1691-L1711)
- 新增用例：[test_r2_206b_contact_gate_increment.py:736](backend/tests/integration/test_r2_206b_contact_gate_increment.py#L736) 起 E 段
- 本报告：[STORE-ANSWER-CONTACT-ECHO-DEV.md](docs/reports/OBS-EVAL/P2/H2V3/r2-live03-20261118/STORE-ANSWER-CONTACT-ECHO-DEV.md)
- 仓外改前副本：`%TEMP%\store-echo-prefix`
- 自建探针输出：`%TEMP%\store_echo_probe_out.json`、`%TEMP%\store_echo_matrix_out.json`、`%TEMP%\store_echo_prefix_clean2.txt`

停手点：产品修复、测试和开发报告已交付；等待经理接收并安排独立验收。真实 R2 attempt5 仍暂停。
