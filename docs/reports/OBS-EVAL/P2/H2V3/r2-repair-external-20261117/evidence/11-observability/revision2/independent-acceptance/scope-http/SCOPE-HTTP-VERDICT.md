# SCOPE-HTTP 独立验收结论

主人，本验收席位的结论为：源码范围与限定文件保护 PASS；补丁 hunk 的原生行尾精确字节重建 PASS；交付裸补丁的默认 Git 应用 FAIL；HTTP INCOMPLETE。当前交付不能获得本席位的无条件接收。该结论不替代其他席位的索引矩阵、schema、SAFE 或 IO 结论，不改变真实 R2 4/5 和 C29 根因未定位的状态。

## 1. 范围与证据边界

- `SCOPE=PASS`：SOURCE/ROLLBACK 均只涉及获准的 4 个产品文件，各 16 个 hunk。相对 `.tmp-r2-obs-baseline/` 的脏树开工字节，SOURCE 精确重建当前 4 文件；没有拿 HEAD 当开工基线。
- `PROTECTION_LOCAL=PASS`：4 份 baseline SHA 与 PROTECTION.before 一致；7 文件当前 SHA 与 PROTECTION.after/保护 SHA 一致。当前源码的旧业务 hunk 在上述重建中保持，未发现本批产品变更超出纯观测职责。
- `PROTECTION_ALL_OLD_EVIDENCE=INCOMPLETE`：本席位没有所有旧报告、旧脚本、封存等的开工哈希快照，不能用 mtime、开发自述或本次单点摘要证明其全部未变。本席位未写这些材料。
- `ROLLBACK_HUNKS=PASS`：按每文件原生 EOL 严格重建后，4 文件回滚字节全部等于 baseline。
- `ROLLBACK_DEFAULT_GIT=FAIL`：交付原始 LF 补丁在 3 个 CRLF 文件上默认检查失败；不能把开发的 `--ignore-space-change` 检查称为字节精确回滚。
- `HTTP=INCOMPLETE`：没有完成原 HTTP 节点，不能给产品 HTTP PASS，也不能把环境挂起判成产品行为 FAIL。

所有创建内容仅在本报告目录和仓内 `.tmp-r2-obs-acceptance-scope-http/`。没有对主源码应用 SOURCE/ROLLBACK；没有 Git 写、全量测试、真实外部连接、真实模型/OCR/judge 调用或安装操作。HTTP 诊断只在独立子进程设置守卫/元数据替身，不修改系统、依赖或主进程环境。

## 2. 补丁范围与旧业务语义复核

| 文件 | 本批 hunk 职责 | 限定复核 |
|---|---|---|
| `conversations/service.py` | 已有 prepared 计划事件增加安全角色及 stores 状态/计数 | 只改观测 import 与事件构造，原问答分支和调用保持 |
| `observability/evaluation_capture.py` | 可选字段、固定码、安全投影及类型/计数检查 | 属 capture 协议；旧 payload/SAFE 的动态正确性由另一验收席位负责 |
| `rag/answer.py` | 同次 search 成功返回后的受控事件 | 未增加检索；原拒答/异常分支及 `_result_diagnostics` 原调用保留；新增事件块有失败隔离 |
| `rag/retrieval.py` | `_StoreJoin.observed` 属性及实际分支 sidecar | 二元组内容、既有 status、查询、过滤、唯一性守卫、去重和旧 `store_join` 业务载荷原 hunk 保留 |

`_store_join_chunks` 的现有成功返回仍带旧 joined status；只有新增 observed 属性标识 rows_found。`_exact_recall` 仍按旧逻辑实际追加未见 chunk；新增 sidecar 再将 rows_found 区分 joined/already_present。原 missing/ambiguous 的旧业务 payload 没有被 sidecar 取代。该判断是定点源码与精确差异复核，不代替真实索引输出等价矩阵。

`rag/query.py`、`rag/facts.py`、`qa/service.py` 未进入补丁；其 SHA 与保护表一致。此处保护结论仅覆盖有摘要证据的文件，不扩展为所有脏树文件均已独立验真。

## 3. 字节重建与可操作性缺口

实际执行：

```powershell
& .\.venv\Scripts\python.exe -X utf8 .tmp-r2-obs-acceptance-scope-http/scope_probe.py
```

退出码 0。机器证据见 `scope-evidence.json`；探针源位于仓内验收临时目录。探针：

1. 直接读取 4 份开工快照及 7 个受查文件的原始字节，匹配 PROTECTION 的 before/after。
2. 将 before/after 分别复制到独立临时树，执行默认 `git apply --check SOURCE.patch` / `git apply --check ROLLBACK.patch`，两项均退出 1。
3. 独立解析统一差异，逐 hunk 按原坐标精确匹配上下文与删除行；不允许空格差异或偏移。只按每个文件既有的统一 LF/CRLF 重建插入行，前向和反向各 4 文件 SHA 全匹配。
4. 将重建结果保存在独立临时树，复核主树 7 文件仍为开始时的 after/保护 SHA。

两份补丁均为 LF，283 行。三个业务文件 before/after 为纯 CRLF，capture 文件为纯 LF。默认 Git 检查在 conversations:60、answer:15、retrieval:18 的首个 hunk 失败。精确上下文重建全部通过，说明该失败属于补丁 EOL 表达与目标字节不匹配，未发现额外上下文漂移。独立重建明确包含原生 EOL 适配步骤，因此不能冒称原始补丁默认 Git 已可用。

| 字节对象 | SHA-256 |
|---|---|
| SOURCE.patch | `2a8e2ad71bc3afc0e7076e58857805924f594d713d016c27eabf3633262f4f4f` |
| ROLLBACK.patch | `e0c68e59d861e116ffd210746fd9c9c1e8354102788153bf7ca1b262296cadab` |

完整四文件 before/current/reconstructed/rollback SHA 及三个保护文件 SHA 在 `scope-evidence.json`，不重复抄写。

此缺口阻塞“交付回滚包可按默认 Git 直接操作”的无条件接收，不否定 hunk 的逻辑可逆性。应由开发另行修正补丁包装或交付明确且经精确哈希验证的原生 EOL 应用步骤。本席位没有修补原交付。

## 4. HTTP/socketpair 有界独立执行

使用项目 venv；诊断脚本为 `.tmp-r2-obs-acceptance-scope-http/http_probe.py`。父进程对子进程逐个使用 communicate(timeout)，超时后仅 kill 自己的 Popen 子进程，再 communicate/wait 确认退出；没有按名称或进程树杀其他进程。下列退出 1 的超时项为父进程终止结果，不是断言失败。

实际命令：

```powershell
& .\.venv\Scripts\python.exe -B -X utf8 .tmp-r2-obs-acceptance-scope-http/http_probe.py raw_socketpair raw_asyncio guard_socketpair
& .\.venv\Scripts\python.exe -B -X utf8 .tmp-r2-obs-acceptance-scope-http/http_probe.py raw_testclient guard_testclient guard_controls
& .\.venv\Scripts\python.exe -B -X utf8 .tmp-r2-obs-acceptance-scope-http/http_probe.py http_original
& .\.venv\Scripts\python.exe -B -X utf8 .tmp-r2-obs-acceptance-scope-http/http_probe.py http_no_plugins
& .\.venv\Scripts\python.exe -B -X utf8 .tmp-r2-obs-acceptance-scope-http/http_probe.py http_platform_stub
```

上述驱动命令退出均为 0，表示驱动已收集结果，不能当作被驱动 HTTP/asyncio 通过。逐子进程结果为：

| 模式 | 子进程 exit | timeout | 终止已确认 | 结果 |
|---|---:|---|---|---|
| raw_socketpair | 1 | true，12 秒 | true | 原生 socketpair 在 accept 挂起 |
| raw_asyncio | 1 | true，12 秒 | true | coroutine 未开始，事件循环 self-pipe 创建挂起 |
| guard_socketpair | 1 | true，12 秒 | true | T09 守卫下实际 socketpair bind/connect 已放行，各 1 次，随后 accept 挂起 |
| raw_testclient | 1 | true，12 秒 | true | 最小合成 ASGI 路由未完成，后台 self-pipe 挂起 |
| guard_testclient | 1 | true，12 秒 | true | 带守卫同一栈；bind/connect 各放行 1 次 |
| guard_controls | 0 | false | true | 外部连接与子进程正对照各被拦截 1 次，blocked=2 |
| http_original | 4 | false | true | pytest 导入装配中的平台信息子进程尝试被阻断，未执行节点 |
| http_no_plugins | 4 | false | true | 仅关闭第三方插件自动装载，仍在平台信息子进程处被阻断 |
| http_platform_stub | 1 | true，22 秒 | true | 明确标识的元数据诊断替身；原 HTTP 节点进入登录夹具后 self-pipe 挂起 |

原 HTTP 节点为 `tests/integration/test_r2_202d_uniqueness.py::test_same_store_one_row_still_joins`，通过 pytest.main 执行：`-vv -s -p no:cacheprovider -o faulthandler_timeout=7 --tb=short`，basetemp 仅指向本席位临时目录。没有改该节点和开发测试。

原始最小复现不装 T09 或独立审计守卫，代码只调用本地 socketpair/空 coroutine/静态 ASGI 路由，没有外部业务连接入口。受守卫诊断除既有 T09 外还加进程内 audit hook：仅在标准库 `_fallback_socketpair` 调用栈中允许精确本地 socketpair 的 bind/connect，其他 socket bind/connect、DNS 和子进程均拦截；不是一般 loopback 放宽。原始 socketpair 没有被替换。

### 安全线程栈摘要

- 原生 socketpair：`accept:295 -> _fallback_socketpair:627`。
- 原生 asyncio：上述栈经 `_make_self_pipe:787 -> new_event_loop -> Runner._lazy_init`，未进入空 coroutine。
- 最小 TestClient：后台同一 socketpair/self-pipe 栈；主线程 `wait/result -> start_blocking_portal -> TestClient.__enter__`。
- 原 HTTP 节点，元数据诊断替身运行：后台同一栈；主线程 `TestClient.handle_request -> login:47 -> _write_session:291 -> chat_admin:303 -> pytest_fixture_setup`。因此没有到达本节点的业务断言。
- 原环境平台信息被阻断：`subprocess._execute_child -> run/check_output -> platform._syscmd_ver -> _win32_ver -> uname -> machine`。禁止了实际创建该子进程。

`http_platform_stub` 仅把进程内 `platform._syscmd_ver` 设为固定空元组返回，以越过被禁止的版本信息 shell 查询；这是诊断替身，不是产品修复，也不等同原环境 HTTP 验证。它没有替换 socketpair、asyncio、TestClient、产品检索或问答。其他诊断和原环境结果分别保留。

每项安全摘要、退出码、超时、原 stdout/stderr SHA 和函数栈计数均见对应 `*-evidence.json`。没有持久化原始端点、候选身份、题答、实体或认证材料。

## 5. 可证结论与余项

已独立证明：无 T09 守卫的最小 socketpair/asyncio 也会挂起；带守卫时用于 self-pipe 的本地 connect 确实放行；正对照能在 OS 连接/子进程创建前阻断。不能从这些事实推出更深的 Windows、沙箱或安全软件根因，也不能证明所有 HTTP 通道零外发。超时项没有结束的守卫 teardown 不能冒称完整零外发账本通过。

本席位不修产品，不扩大网络例外，不修改全局环境或依赖。HTTP 端到端仍待可用运行环境验证。旧证据全量保护与其他席位职责不在本结论内。修正补丁包装后可只复验该产物及精确哈希关系，无需为了该包装问题重复已经复现的 HTTP 挂起。
