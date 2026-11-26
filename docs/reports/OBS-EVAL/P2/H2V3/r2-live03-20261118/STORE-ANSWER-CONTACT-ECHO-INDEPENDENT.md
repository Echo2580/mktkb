# 店家记录回答正文回显独立验收

主人，**独立验收通过，范围为离线合成资料中只问店家合作状态的新回答及其重放、历史读取。** 51 项核心定向用例全部通过。独立 HTTP 探针用另一组店家行实测，两个模型输出变体的正文均命中 0/3 个合成联系值。仅在探针进程回退渲染过滤条件后，同一条资料和问题的正文命中 3/3 个。真实 R2 仍停在既有 attempt4 的 4/5，attempt5 保持暂停。

## 验收范围

- 分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，验收对象为该 HEAD 上带未提交改动的当前工作树。产品只审查 `_CONTACT_ECHO_ROLES` 及 `_record_answer_text` 的本包增量。工作树已有改动及既有断言保留。
- 受查文件 SHA-256 与开发交付一致。`service.py` 为 `07C7885127781AF9CEB9859CE69370FB284A096B1BF19C238E1400EE2F8EC592`，`test_r2_206b_contact_gate_increment.py` 为 `3DA1E170782E9371F9F0948F8FD3DFC64F1736AADECA3514A381764D1EFDEE0D`。
- 验收依据为任务书、开发报告及 C-1 独立复验报告 §7.2。新增 E 段、相关既有回归和独立合成探针由独立验收员重新运行。临时探针与 SQLite 数据位于隔离目录。

## 实测结果

| 场景 | 证据与判定 |
| --- | --- |
| 只问状态 | 新增 E 段的标准表头用例通过。独立探针使用带干扰店家行的合成 XLSX，先上传、解析并发布，再由员工会话走问答 HTTP 入口。模型只输出状态与模型多输出 3 个联系值分别实测，均返回正确店家和状态，正文命中 0/3。唯一引用命中目标文件、`独立验收台账` 第 5 行、活动版本 1。 |
| 联系字段别名 | E 段的「负责人 / 联系方式 / 门店地址」通过。独立探针改用「负责人 / 联系电话 / 详细地址」，两种模型输出下正文均命中 0/3。 |
| 重放和历史 | 两种模型输出各执行首答、同 `client_request_id` 重放及 GET 历史。每组首答与重放的消息 ID 相同，重放无新增模型调用，三处正文和引用完全相同，正文与摘要合成值均零命中，摘要无 `locator.cells`。 |
| 显式允许、受限组合、凭据 | E 段的联系人、电话、地址三个显式允许变体均通过。206b 的受限混合组合维持既有拒答或剥离策略。独立凭据请求返回 `not_found`、零引用、零新增模型调用，正文无状态或任一联系值。 |
| 明问电话的兼容范围 | 现有 `test_g09_phone_update_and_same_entity_conflict` 与 `test_g04_record_accepts_role_bound_alias_and_echo` 均通过。独立探针模型仅给出电话，HTTP 正文同时显示同一行的联系人和地址。任务书中的「跳过附带输出」在本次实现中仅对没有任何已校验联系字段的回答启用。明问电话时的同行披露是已有兼容范围，本轮通过判定限于未询问联系字段的目标场景。 |
| C29 与 C-1 | C29 既有独立同形文件 9 项通过。另以独立合成两份 XLSX 重做跨店取值，得到两个正确值、两条引用，各指向正确资料的活动版本 1、`独立验收台账` 第 4 / 5 行，两个摘要均无 `locator.cells`，两个对照值及三项联系哨兵均未出现在正文。206b 的 C-1 摘要用例通过，来源访问 3 项通过。 |
| 改前因果对照 | 在同一探针进程内复制当前渲染函数，临时移除附带回显过滤式的唯一条件，走同样的 HTTP 入口，模型仅给出状态，正文即命中 3/3。引用坐标正确且摘要仍无 `locator.cells`。随后恢复函数，工作树产品源码和既有测试断言未修改。 |

源码与观察一致。匹配问句的已校验事实形成 `validated`，模型额外带出的同行联系字段不会成为请求事实。渲染器从 `validated` 确定是否已有联系字段。只问状态时，附带字段循环按 `resolve_requested_role` 识别并跳过 `contact`、`phone`、`address`，正常保留状态和公开店家字段。来源定位沿用既有引用生成及 `SourceSummary` 摘要投影。

## 执行及退出码

从项目根执行，`$auditRoot` 为
`C:\Users\dell1712\.codex\visualizations\2026\11\18\01a1edc0-41f5-7d23-a727-f88ab41ec7bf`。
下列通过记录均来自本轮执行。

```powershell
.\.venv\Scripts\python.exe -B -m pytest `
  backend/tests/integration/test_r2_206b_contact_gate_increment.py `
  backend/tests/integration/test_c29_reverify_20261118_independent.py `
  backend/tests/integration/test_conversation_recovery.py `
  backend/tests/integration/test_source_access.py `
  backend/tests/integration/test_t09_d6_r1_record_phrasing.py `
  -q --tb=short -p no:cacheprovider --basetemp (Join-Path $auditRoot 'store-echo-ia-core-run-b-7ec3')

.\.venv\Scripts\python.exe -B (Join-Path $auditRoot 'store_echo_ia_probe_7ec3.py')

.\.venv\Scripts\python.exe -B (Join-Path $auditRoot 'store_echo_ia_pytest_7ec3.py') `
  backend/tests/integration/test_chat.py::test_g09_phone_update_and_same_entity_conflict `
  backend/tests/integration/test_chat.py::test_g04_record_accepts_role_bound_alias_and_echo `
  backend/tests/integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call `
  -q --tb=short -p no:cacheprovider --basetemp (Join-Path $auditRoot 'store-echo-ia-chat-7ec3')

.\.venv\Scripts\python.exe -B (Join-Path $auditRoot 'store_echo_ia_pytest_7ec3.py') `
  backend/tests/integration/test_conversation_recovery.py `
  backend/tests/integration/test_source_access.py `
  backend/tests/integration/test_t09_d6_r1_record_phrasing.py `
  -q --tb=short -p no:cacheprovider --basetemp (Join-Path $auditRoot 'store-echo-ia-other-7ec3')
```

| 执行 | 结果 | 退出码 |
| --- | --- | --- |
| 206b（含 E 段 8 项）、C29、会话恢复、来源访问、记录措辞 | 51 passed，47.54 s | 0 |
| 独立合成 HTTP 探针 | 状态/重放/历史、改前对照、凭据、明问电话兼容范围、C29、模型输入观察均通过，`NETWORK external=0` | 0 |
| 两条电话兼容契约和一条 0.2 秒预算用例 | 3 passed，3.71 s，`NETWORK external=0` | 0 |
| 会话恢复、来源访问、记录措辞，附加零外发守卫复跑 | 14 passed，19.42 s，测试主进程 `NETWORK external=0`。会话恢复按既有用例启动本机 Python 子进程并使用内置阻塞模型替身，其网络调用未纳入主进程守卫计数。 | 0 |

206b 与 C29 使用其声明的仓库 `t09_network_guard`，206b 另启用现有零子进程守卫。独立探针及额外两组复跑以相同的仓库守卫包住当前进程，正常用例通过离线模型替身或 ASGI TestClient 完成。运行范围为本机，未使用真实资料、真实题面、配置密钥、真实供应商、GO 或预算账本。

首轮沙箱默认临时目录无法创建 pytest 子目录（1 passed / 50 setup errors，退出码 1）。换为明确可写的目录后，沙箱进程仍无用例输出，已中止（退出码 1）。仅对上述本机用例使用需提权执行后取得通过记录。独立探针第一次运行的功能断言均通过，退出阶段因 Windows 仍占用 RAG SQLite 文件而返回 1。补上探针的 QA 资源关闭后完整复跑，最终退出码为 0。各通过批次均见 Starlette TestClient 的 `httpx` 弃用告警。

开发报告记录的 `test_g08_short_budget_cancels_inflight_model_call` 组合负载时序失败，本轮在三项定向组合中未复现。本轮未重复开发方的全合并负载，未据此判定该波动已消失。

## 遗留与未覆盖

- **模型输入。** 独立探针从两次本地模型替身入参观测到，证据 `fields` 和 `text` 均保留整行三项联系值，命中 3/3。`_model_input` 的整行事实传入仍有待独立评估，真实供应商没有接收本次探针请求。
- **已持久化的旧正文。** 探针用临时改前渲染器在隔离数据库生成旧消息，恢复修复后同键重放及历史读取仍原样命中 3/3。本包只覆盖新生成的回答及这些新回答的读取。
- **联系字段之间的同行披露。** 明问电话时已实测仍显示联系人和地址。更严格的披露规则未纳入本次判定。
- 本轮未覆盖真实模型或付费服务、浏览器显示、生产旧数据、全量回归及并发版本替换。真实 R2 attempt5 保持暂停。

