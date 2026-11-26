# 记录型回答模型证据最小化独立验收

主人，**通过离线独立验收。** 55 项定向用例全部通过。独立合成 HTTP 探针经真实 DeepSeek 适配器和 `httpx.MockTransport` 捕获 POST 请求体：只问合作状态时未出现三项已登记联系值中的任何一项，显式问联系人、电话或地址时各只携带请求的角色。进程内替换为改前投影后，同一状态问句的 `evidence[].fields` 和 `evidence[].text` 各重新命中 3/3。两组 HTTP 执行的零外发守卫均记录 `external=0`。

## 验收对象

- 分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`。受查的是当前工作树。产品增量为 `service.py` 中 `_model_input` 的投影与联系角色常量复用，前一轮正文兼容逻辑及其它未提交改动仍在。
- `service.py` SHA-256 为 `4082574114F66E09AE1E426D4147CF6FC5BD043148C4D2DCBC6B1C01484EE5F0`。`test_r2_206b_contact_gate_increment.py` SHA-256 为 `57EC28C8CADA43F7F6C95513ABDAA2A00A5EF05949B73C38530CBA820DC1C80A`。
- 只审核产品和测试，未编辑其文件。初查发现既有凭据用例的零调用断言被误放到新成功用例，在新位置因模型替身被替换而无法证明拒答。开发方修正后，独立验收核对断言已回到凭据用例，并以最终文件重跑。另以独立探针检查拒答不进入传输层。
- 依据为本轮任务书及上一轮正文独立报告的模型输入观察。只使用仓库合成回归资料和自建 XLSX、DOCX。真实 R2 attempt5 保持暂停，最近真实结果仍为 attempt4 的 4/5。

## 执行证据

| 场景 | 实测与判定 |
| --- | --- |
| 只问店家状态 | 真实产品 HTTP 上传、解析、发布、自建员工会话问答。自建目标店与干扰店同表，目标行 5。适配器 POST 完整 JSON 命中联系哨兵 0/3，保留状态、店名、标识和实际来源 ID，`evidence[].text` 为空。正文正确，命中 0/3。 |
| 显式问联系角色与同义表头 | XLSX 使用「联系人姓名 / 联系电话 / 店家地址」。显式问联系人、电话、地址三题的 POST 分别只命中对应联系值 1/3，另外两项均未出现在完整 JSON，保留原表头、公开字段、来源 ID 和原值。最终答复正确。206b 新增的标准表头载荷 4 项亦通过。 |
| 改前对照 | 只在独立探针进程内将 `_model_input` 暂时替换为改前的不筛选投影，沿同产品 HTTP 与适配器路径实测。模型 POST 的 `fields` 与 `text` 分别命中 3/3。工作树源码未回退。 |
| 无结构化字段 | 使用合成 `SourceUnit` 直接进入输入边界。记录型回答投影保留原 ID，`fields={}` 和 `text=""`，原单元的文本和字段未改写。产品 HTTP 记录路径仍先校验结构化事实，无可回答事实时可返回未找到。此项直接探针证明投影，不断言纯原文记录一定会触发提供方请求。 |
| 普通文档与查询扩写 | 自建 DOCX 段落直答 POST 保留原段落，HTTP 来源正确。另用无初始命中的问题经 MockTransport 返回扩写词，实际依次发出一次扩写 POST 和一次回答 POST，扩写 POST 只含 `question`、`context_questions`、`entities`，随后回答 POST 保留文档原段。直接边界探针另验证文档模式同时保留结构化字段。 |
| 本地来源 | 目标 XLSX 的 SQLite 来源字段、原文和定位快照在问答前后逐项一致。已授权的来源详情仍返回完整原始字段。用户答复继续引用活动版本 1、正确工作表与第 5 行。 |
| 拒答、C29、C-1 | 凭据和「物品＋电话」两道独立对照返回 `not_found`、零引用、零适配器 POST。既有 206b 拒答和 C29 同形 9 项通过。另以自建两个 XLSX 跨店查询得到两个正确值与两条活动 v1 引用，各命中文档和工作表第 4 / 5 行，无串店或附带联系值，两个摘要均无 `locator.cells`，且零适配器 POST。 |
| 明问电话的用户正文 | 显式电话题的 POST 只携带电话。此前已约定的正文兼容行为继续实测命中同行联系人和地址。这两个字段来自本地原始取证行。 |

源码核对显示分支只在 `purpose == "answer"` 且 `plan.mode == "record"` 生效。记录角色按 `IntentPlan.requested_fields` 与既有 `resolve_requested_role` 解析，每个来源构造新的字段字典，清空原文副本。事实校验、引用整理和正文重建继续使用原始来源行。DeepSeek 适配器在回答路径序列化 `text` 与 `fields`，扩写路径不序列化证据。授权及拒答保持原有入口判定。

## 命令与状态

在仓库根执行。两个临时脚本与各次独占的测试根放在
`C:\Users\dell1712\.codex\visualizations\2026\11\18\01a1edc0-41f5-7d23-a727-f88ab41ec7bf`（下文 `$auditRoot`）。
Windows TestClient 的 HTTP 两批使用仅限此处本机离线执行的需提权工具权限。仓库 `t09_network_guard` 包住整个执行进程，真实 HTTP 传输被守卫阻断，适配器只通过内存 MockTransport，TestClient 走本机 ASGI。边界探针无网络动作。

```powershell
.\.venv\Scripts\python.exe -B (Join-Path $auditRoot 'store_echo_ia_pytest_7ec3.py') `
  backend/tests/integration/test_r2_206b_contact_gate_increment.py `
  backend/tests/integration/test_c29_reverify_20261118_independent.py `
  backend/tests/integration/test_source_access.py `
  backend/tests/integration/test_t09_d6_r1_record_phrasing.py `
  backend/tests/integration/test_chat.py::test_g08_at_most_one_expansion_then_one_answer `
  backend/tests/integration/test_chat.py::test_g08_expansion_without_hits_stops_and_does_not_call_answer `
  -q --tb=short -p no:cacheprovider --basetemp (Join-Path $auditRoot 'record-provider-ia-core-a86e')

.\.venv\Scripts\python.exe -B (Join-Path $auditRoot 'record_provider_ia_a86e.py') --boundary

.\.venv\Scripts\python.exe -B (Join-Path $auditRoot 'record_provider_ia_a86e.py')
```

| 执行 | 结果 | 退出码 |
| --- | --- | --- |
| 206b 32 项（含 4 个实际载荷测试）、C29 9 项、来源访问 3 项、记录措辞 9 项、查询扩写 2 项 | 55 passed，37.64 s，`NETWORK external=0` | 0 |
| 直接输入边界探针 | 无结构化字段、文档、扩写构造及范围外观察断言通过 | 0 |
| 独立真实序列化探针 | 8 个 MockTransport POST，覆盖四条记录题、一条改前对照、一次文档直答和一次扩写后答复的两阶段。另确认两类拒答及 C29 没有发送 POST，`NETWORK external=0` | 0 |

三条命令均出现 TestClient 关于 `httpx` 的弃用告警。合成探针观察的是该批数据的请求载荷和 HTTP 行为。

## 验收边界

- 承诺范围是传统记录型回答内、既有角色词表登记的联系列。直接探针观测到，若合成电话另外写在未登记业务列「备注」，该列仍保留。当前问题及历史用户问题中的手输内容也照常保留。此范围未做内容识别和全局脱敏。
- 原来源详情、已保存的既有正文和显式联系题正文遵循各自既有契约。联系角色之间的同行正文回显仍存在，详情实测仍保留完整授权原文。
- 未检查真实模型生成质量、生产数据、浏览器、入库嵌入、重排与外部传输链路。未使用私有材料、真实题面、真实外部服务、授权文件、GO 或预算账本。

