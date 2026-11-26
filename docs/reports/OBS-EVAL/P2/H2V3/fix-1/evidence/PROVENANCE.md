# evidence 出处与口径（v3-fix-1）

本目录只放**计数、固定码、摘要与合成数据**；不含真实 H2 题面、参考答案、目标值、私有密文或 key。

## 1. 改前 / 改后机读证据

| 文件 | 何时产生 | 说明 |
|---|---|---|
| `probe_planner.py` | 会话早期（改前）与修复后（改后）各跑一次 | 合成问题 + 产品 `rag.query.parse_query` / `conversations.intent.parse_question` / `service._rag_owns_turn` 纯函数探针；脚本自装 socket 守卫 |
| `probe_planner_before.json` | **任何代码改动之前**运行同一脚本的输出，原文照录 | 改前行为：Q2 由 legacy 判澄清、Q3 `ITEM_AMBIGUOUS`、Q4 澄清、Q5 已可枚举 |
| `probe_planner_after.json` | 修复后运行同一脚本的输出 | Q2/Q3/Q5 → `MULTI_TARGET_ENUMERATE` + `rag_owns_turn=true`；Q4 仍 `ITEM_AMBIGUOUS` |
| `probe_business_date_filter.py` / `probe_business_date_before_after.json` | 修复后 | 同一合成 legacy 库上 `as_of=None`（改前行为）与四个业务日的对比；含顺序保持与不误杀布尔量 |
| `probe_run2_record_facts.py` | 修复后 | §2a 最小复现：用产品 `_facts/_record_facts` 重放 dryrun `echo-all` 替身输出（形态 A 复现、形态 B 对照） |
| `probe_doc_title_prefix.py` | 修复后 | §2b 最小复现：标题带/不带 `D01_` 前缀时 `_document_core` 与 `parse_query` 的差异 |

`probe_planner_before.json` 的唯一的"非重生成"性质：修复后无法再运行改前代码（改前工作树含未提交既有改动，无法用 `git show HEAD` 复原），故该件按改前运行原文保存；字段结构、问题文本、脚本与 `probe_planner_after.json` 完全一致，差异仅在代码行为。

## 2. 零调用守卫（`netguard_plugin.py`）

- 导入即删除 `*_PROXY` / `NO_PROXY` 等代理环境变量（本次实测删除 5 个），正对照因此**不经本机代理**；
- 接管 `socket.connect / connect_ex / create_connection / getaddrinfo`：非回环一律拦截并计数，**回环放行并计数**（Windows 上 anyio 阻塞 portal 用 loopback socketpair 实现，属进程内通信，不是业务出站）；
- 会话开始跑 4 个正对照（DNS / 直连 / urllib `ProxyHandler({})` / httpx `trust_env=False`），记录是否被拦；
- 退出时写 `netguard-run.json`（`proxy_env_removed`、`positive_controls`、`external_attempts*`、`loopback_attempts_total`、`counts`、`exitstatus`）。
- 局限：只证明**本进程**没有外部出站，不覆盖外部进程/其他会话；回环计数不区分用途。

## 3. pytest 日志

`pytest-*.log` 均为 `tee` 原文（PowerShell 默认 UTF-16）；对应命令写在 dev-report §5.2。`pytest-baseline.log` 是**被中止**的全量基线片段（25 分钟 12%），只作过程记录，不作为门禁。

## 4. 保全核对

`preservation-check.json` 逐条给出 16 条 tracked modified 的基线 SHA-256 与当前 SHA-256：14 条逐字节相同，2 条（`rag/query.py`、`conversations/service.py`）为修复涉及文件，已标 `fix_involved`。
