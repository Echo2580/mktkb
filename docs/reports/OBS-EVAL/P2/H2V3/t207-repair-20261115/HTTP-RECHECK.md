# T207 定向 HTTP 开发自测（非独立验收）

## 结果

通过正式 `sandbox_permissions=require_escalated` 执行后，Windows 本机回环可用，原先卡在 TestClient portal 的指定单例 **1/1 passed**；随后仅补运行同一测试文件的安全、无害请求和跨轮实体范围相关用例，**6/6 passed**。两组均退出 0、正对照 4/4 被本进程网络守卫拦截、非回环出站尝试 0。之前受沙箱回环限制的挂起和手动中止仍是历史事实，不把当时中止的运行改记为通过。

这是开发自测，不是独立验收或真实 H2 重测；不能证明 C13/C22/C26/C28 已修复。指定旧 HTTP 测试覆盖既有合成策略和用户请求路径，但本轮新加的“多来源组合”“换题后裸追问”“全字段枚举含联系字段”等独立新反例尚未单独做 HTTP 端到端测试，仍以已有离线单元 / RAG 内核测试为证。

## 范围与隔离

- 运行前只读核对 `backend/tests/integration/test_v3_safety_fix_e2e.py`：测试生成合成 XLSX 并由临时应用 worker 解析；`chat_model` 是 `EvidenceEchoGateway` 可控替身。`backend/tests/conftest.py` 的 `settings` 使用 `_env_file=None`、临时 `store.root` 内 SQLite，且会话级 fixture 禁用 Settings 默认 dotenv；未打开真实 `.env`、真实 key、真实题面或私有材料。
- 子进程环境按名称移除代理、所有 `MKTKB_` 项及 pytest 自动附加参数，再设置 `MKTKB_NO_DOTENV=1`、`MKTKB_OCR_DISABLED=true`、`MKTKB_RAG_PROVIDER_MODE=offline`，关闭 pytest 插件自动加载；不读取或打印环境值。每组使用独立新 `--basetemp`，临时数据库/文档由测试 fixture 在其中创建；没有安装依赖或运行真实入口。
- 既有 `netguard_plugin` 拦截非回环 `socket.connect/connect_ex/create_connection/getaddrinfo` 并记录回环；正对照分别为 DNS、保留 IP 直连、`urllib.ProxyHandler({})`、`httpx.Client(trust_env=False)`，未访问 example.com。新增 `http_recheck_guard.py` 对进程中的 `httpx.Client` 和 `httpx.AsyncClient` 强制 `trust_env=False`，分别输出次数；该插件不改变产品源码。
- 守卫观察范围是测试 Python 进程及所列 socket 路径；不能据此声称覆盖整机其他进程或所有可能的网络原语。测试使用 Starlette ASGI/TestClient 与离线 provider，没有真实 provider 调用；本机 socketpair 回环仅用于 Windows 事件循环。

## 实际运行与回执

共同执行环境：仓库根目录，项目 `.venv\Scripts\python.exe`，`-q -o faulthandler_timeout=30 -p netguard_plugin -p http_recheck_guard -p no:cacheprovider`；`PYTHONPATH` 包含 `backend/src`、`docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence`、本目录；输出分别由 `NETGUARD_OUT` 与 `HTTP_RECHECK_TRUST_RECEIPT` 指向下列文件。两个命令均通过 `require_escalated` 执行；未收到自动审批拒绝。

| 命令的测试目标 | collect / 结果 | 守卫与 trust 回执 |
|---|---|---|
| `backend/tests/integration/test_v3_safety_fix_e2e.py::test_rag_kernel_path_also_refuses_restricted_contact` | 1 collected、1 passed、exit 0；1 条既有 Starlette/httpx 弃用警告 | `http-escalated-single-netguard.json`：4/4、外部 0、回环 10；`http-escalated-single-trust.json`：强制 false，sync 3、async 0 |
| `backend/tests/integration/test_v3_safety_fix_e2e.py::test_restricted_contact_request_is_refused_before_model`、`::test_item_location_still_answers`、`::test_two_store_phone_still_answers_both_targets`、`::test_bare_item_followup_keeps_inherited_store_scope` | 6 collected、6 passed、exit 0；其中第一个为 3 个参数化用例；1 条同样的弃用警告 | `http-escalated-targeted-netguard.json`：4/4、外部 0、回环 61；`http-escalated-targeted-trust.json`：强制 false，sync 13、async 0 |

隔离临时目录分别为本目录下 `tmp-http-escalated-single` 与 `tmp-http-escalated-targeted`，均为新路径。两个执行会话均已结束并返回 0；完成后 `Get-Process -Name python,pytest` 未列出进程。未重跑已有 123/26/6 组。

## 保全

账本 SHA256 前后均为 `e007fee3456e5d13f737a82ed29af45eb4707e3576c444e3520d9ca941dc2899`，预算 SHA256 前后均为 `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`。完整保护件前后比较和交付 SHA 清单随本轮 `build-delivery.py` 更新；历史 GO 与旧快照的差异及缺失开工 GO 哈希限制不因本次测试改变。
