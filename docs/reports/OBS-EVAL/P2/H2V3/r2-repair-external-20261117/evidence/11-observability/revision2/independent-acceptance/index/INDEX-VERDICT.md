# T-R2-OBS revision2 独立验收 A：真实离线索引

**Verdict: PASS（仅本组索引观测与业务等价范围）。** 本结论不构成 revision2 总体验收通过，也不证明真实 C29 原因、R2 或 T207 完成。其他组发现的 schema/SAFE 缺陷应由经理单独汇总。本组未改产品源码、开发测试、旧证据、预算、账本或私有材料。

最终定向节点退出 **0，1 passed in 16.23s**。这一个节点编排了独立 seed 和 baseline/off/on/failure 五个有界子进程；四个变体各执行 19 个场景，76 次场景执行，57 组跨版本/捕获条件业务等价比较全部为 true。正常产品阶段守卫账本均为 0；五进程合计完成 205 次实际拦截正对照。全部子进程已由 `subprocess.run` 等待回收，无超时、无未完成会话或后台写入。

## 证据与基线

- 可复现探针：`index_probe.py`、`test_index_acceptance.py`。
- 逐进程命令、退出码、守卫逐通道账本、逐场景摘要、比较结果与源码 SHA：`RUN-RECORD.json`。
- 保留的失败装配记录：`RUN5-FAILED-RECORD.json`、`RUN6-HARNESS-EXPECTATION-RECORD.json`；更早独立临时目录保留在 `.tmp-r2-obs-acceptance-index/run1` 至 `run4`。
- 最终运行数据：`.tmp-r2-obs-acceptance-index/run7/test_independent_real_index_ma0/matrix/`。数据全部由探针创建，不含真实题答或实体。
- 使用项目 `.venv`。未运行全量测试、HTTP 链、真实 provider、付费模型、OCR、judge 或外部业务 API，未读取 `.env`、真实题答、私有计划/binding/合同、密文或 key。

基线来自开工脏树字节快照 `.tmp-r2-obs-baseline/`，**不是 HEAD**。执行前逐一核对四文件 before SHA 与 `PROTECTION.md` 相同，再复制至本组临时目录。baseline 子进程通过精确四模块 `MetaPathFinder` 加载改前文件；其余模块仍来自同一工作树。pytest 显式 `-o pythonpath`，子进程 `-I` 且显式加入源目录，不依赖环境 `PYTHONPATH`。四模块加载后的 `__file__` 与 SHA 均断言到预期文件；旧版没有 `safe_roles`、`store_join_observed`、新增 `MAX_LIST_ITEMS` 引用的负对照为 true。`conversations/service.py` 仅验证导入身份；本组未执行其 prepared-plan HTTP 接线。

七项源码执行前后 SHA 完全相同，且与交付 `PROTECTION.md` after 相同；详见 `RUN-RECORD.json` 的 `pre_source_sha256`、`post_source_sha256`。四个改前文件的 SHA 亦硬编码为独立断言，未应用任何回滚补丁，未修改主工作树以切换版本。源码包装补丁内容已阅读，未应用。

## 19 个场景覆盖矩阵

下表 `A/S/E` 为开启捕获时的真实 search 尝试 / 成功返回 / 新 retrieval 事件数量。`ask` 是公开 `RagIndex.ask`；`search` 是合法构造 `QueryPlan` 后直接调用真实 `RagIndex.search`。所有行均走真实 SQLite、摄入生成的索引及原始 `_load`，没有检索结果或 `_load` 替身。

| 固定场景码 | 边界 | 实际观测码/结果 | A/S/E | 数据条件 |
|---|---|---|---|---|
| joined | ask | joined | 1/1/1 | 正常摄入：1 物品、1 店家 |
| missing | ask | store_row_missing | 1/1/1 | 正常摄入：1 物品、0 店家 |
| ambiguous | ask | store_row_ambiguous | 1/1/1 | 正常摄入：1 物品、2 店家 |
| pagination | ask，3 回合 | roles_not_cross_level，page_has_more=true/true/false | 3/3/3 | 正常摄入：25 物品 |
| large | ask | roles_not_cross_level，candidate_count=521，truncated=true，page_has_more=true | 1/1/1 | 正常摄入：520 物品 + 1 店家 |
| document | ask | not_applicable，effective_mode=document | 1/1/1 | 正常摄入正文，离线抽取 |
| empty | ask | not_applicable，empty=true，candidate_count=0 | 1/1/1 | 真实空库 |
| pre_refusal | ask | SECURITY_RESTRICTED_CONTACT | 0/0/0 | 前置拒答，检索未执行 |
| search_exception | ask | KNOWLEDGE_CHANGED | 1/0/0 | 真实数据库 revision 在 search 内被独立事务修改 |
| multi_item_ask | ask | item_filter_missing | 1/1/1 | 正常 parser 清除单物品过滤，先命中此前置条件 |
| plan_not_record_or_enumerate | search | not_record_or_enumerate | 1/1/0 | 正常摄入，record + enumerate=false |
| plan_roles_not_cross_level | search | roles_not_cross_level | 1/1/0 | 正常摄入，仅一侧角色 |
| plan_item_filter_missing | search | item_filter_missing | 1/1/0 | 正常摄入，物品过滤缺失 |
| plan_multiple_items | search | multiple_items | 1/1/0 | 正常摄入，多目标状态 + 合法物品过滤 |
| plan_multiple_stores | search | multiple_stores | 1/1/0 | 正常摄入，多门店状态 |
| plan_item_row_not_unique | search | item_row_not_unique | 1/1/0 | 正常摄入，同物品 2 记录身份 |
| plan_store_value_missing | search | store_value_missing | 1/1/0 | **人工不一致元数据**：删物品块规范门店键 |
| plan_store_value_ambiguous | search | store_value_ambiguous | 1/1/0 | **人工不一致元数据**：同记录身份的两个块持久化不同门店键 |
| plan_already_present | search | already_present | 1/1/0 | **人工不一致元数据**：店家块另加物品过滤键 |

公开 ask 共 12 回合，真实 search 尝试 11、成功 10、新事件 10。前置拒答和 search 异常各无成功事件，不能解释成候选为空。直接 `RagIndex.search` 边界只生成 diagnostics sidecar；新增 retrieval 事件的发射位置是 `answer_question` 成功 search 后，因此 search 表项 E=0 是明确边界，而非伪报事件计数通过。

`already_present` 已在真实 SQL 索引上到达，但**未证明正常摄入可达**。正常 `_entity` 只有 store 非空、item 缺失才把行归类为 store；同时具备两者的行归类为 item，规范过滤字段由同一组字段生成。联结入口要求非空 item 等值过滤，故正常 store 块不会已经出现在该次初始精确集合里。正常摄入的 562 个持久化块检查到 0 个相关不变量违反；人工元数据正例只证明实际索引算法分支可达。`store_value_missing` 与 `store_value_ambiguous` 同样只在明确标记的不一致元数据边界执行，不能冒充正常摄入路径。

search 异常用 SQLAlchemy SQL 执行通知，在真实 search 开始后、首次读取块时，用另一 SQLite 事务将真实 revision 加 1；不替换 revision 返回值或 search 返回。真实 `KnowledgeChanged` 由原 search 末尾检查抛出，公开 ask 返回固定错误并提交状态。回调刻意避开 parse 前 lexicon 读取，保证异常发生于检索内部。

## 业务输出等价

各场景从同一 seed 文件逐字节复制出独立 DB，打开前核对 SHA；持久化初始会话相同，初始 turn 为非零固定值。四变体使用同一问题序列与配置。比较如下部分的实际数据哈希或固定值：

- `kind`、`reason`、`text`、`sources`（本边界为 `RagAnswer.citations`）、`facts`；
- total、returned、has_more、next_page、page、page_size、revision；
- 返回 state、实际 DB 的完整状态行与状态提交次数；
- search、load_state、save_state、lexicon_data、revision、离线 embed/rerank 的计数；
- 对直接 search，额外比较 exact/lexical/vector/fused/evidence 及既有 `store_join` 业务载荷哈希。

以上 19 场景 × off/on/failure 对 baseline 的 **57 组全部相同**。方法包装只计数并原样委托返回；没有替换业务结果。revision 计数包含每次回答后探针追加的一次只读 revision 核验；此固定开销各变体一致，扣除后产品调用计数仍相同。直接 search 的 9 场景均未提交会话状态。

sink 故障由 `CaptureSink` 子类仅在 `retrieval_observed` emit 时抛固定异常。8 个含成功 search 的公开 ask 场景均实际到达 sink.failed，结果仍等价，未将其记为观测成功；分页场景首轮失败后 sink 保持失败，后续捕获关闭。拒答/检索异常没有触发该注入点，不能记为“已模拟 sink 失败”。

候选 ID 仅在合成内存里比较，不写公开材料；事件的候选数量、512 列表上限、empty、page_has_more 与同次原始返回集合核对。大集合 candidate_count=521 是 exact/lexical/vector/fused 的去重并集，包含一个店家候选；不是只数页面的 10 条或只数 520 个物品。未据此评价召回质量或真实题目准确性。

## 零外发动态守卫

守卫在导入产品前安装，覆盖 socket connect/connect_ex/send/sendall/sendto、DNS/连接便利函数、httpx Client/AsyncClient send 与同步/异步 transport、stdlib HTTP(S)/urllib、subprocess 启动便利入口，以及可用的 os system/popen/startfile/spawn/exec 入口。额外 Python audit hook 拦 socket.connect/sendto/DNS、subprocess.Popen、os.system/exec/spawn 事件，并阻止 `.env*` 文件读取。逐通道计数在 `RUN-RECORD.json`；参数不记录。

最终 seed 与四变体各自 product 阶段被阻断尝试数 **0**；各进程逐一调用 40 个实际安装的包装入口、另用保存的原生 socket.connect 验证 audit hook，正对照各 **41** 次都先被阻断，总计 **205** 次。没有发送真实网络请求，没有产品启动的子进程。独立驱动器主动启动的 5 个测试子进程与产品阶段账本分开记录，每个 timeout=90 秒，实际都 exit=0 并回收。正对照只证明列出通道有效，未宣称 Windows 全系统调用级审计。

Windows 依赖装配先加载 stdlib asyncio，避免替换 Popen 后破坏其类继承。SQLAlchemy 导入所用的 `platform.uname` 缓存明确设为合成 Windows 平台元数据，防止其启动 cmd 探测宿主版本；这仅隔离依赖的主机元数据，不替换索引、SQL、parser 或业务结果。离线 embedder/reranker 为产品显式 offline 配置选中的 `FakeEmbeddingProvider`/`LexicalReranker`；正文使用离线抽取，不调用聊天模型。

## 实际命令与装配失败

最终命令在仓库根执行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& '.\.venv\Scripts\python.exe' -B -X utf8 -m pytest 'docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/independent-acceptance/index/test_index_acceptance.py::test_independent_real_index_matrix' -c 'backend/pyproject.toml' -o 'pythonpath=D:/GPT项目/市场部AI知识库/backend/src' --confcutdir='docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/independent-acceptance/index' -q -p no:cacheprovider --tb=short --basetemp='.tmp-r2-obs-acceptance-index/run7'
```

退出 0：`1 passed in 16.23s`。每个子进程的完整实际 argv、退出码、输出哈希、timeout 与 reaped 布尔见 `RUN-RECORD.json`，未打印环境。此节点不调用 backend 既有 conftest；显式 confcutdir 防止无关 app/HTTP 测试装配进入本组。

同一命令在 run1 至 run6 的退出均为 1，只更换独立 basetemp。具体情况公开保留：

| run | 原因/结果 | 处置 |
|---|---|---|
| 1 | basetemp 父目录不存在，setup error | 创建本组获准新目录 |
| 2、3 | 首次包装 Popen 早于 asyncio 导入，TypeError | 调整本组装配导入先后；run3 加入安全栈定位 |
| 4 | platform 依赖尝试启动 cmd，被子进程守卫拦截 | 使用显式合成平台元数据；无实际启动 |
| 5 | 真实 revision 注入过早落在 lexicon 阶段，未到 search 异常 | 将本组注入限于 search 已开始；未改产品 |
| 6 | 五子进程均 exit0、19×3 等价均 true；探针预估多物品码错误 | 按源码真实判定顺序更正为 item_filter_missing；同时将大并集预估 520 更正为 521，保留记录 |
| 7 | 最终节点 exit0 | 源码零变更，57 组等价与全部守卫断言通过 |

run6 的预估修正不是产品修复，也没有减少覆盖：multiple_items 继续由合法 QueryPlan 经真实 search 单独执行。未隐去装配失败或声称首次运行即通过。

## 限制和停止点

本组证明的是当前源码快照、上述合成输入和直接 RagIndex 边界；不覆盖 HTTP 的 sources 序列化/状态事务、prepared/effective 跨层绑定、所有历史 envelope、私有捕获保管侧诊断或真实质量。人工不一致 DB 三项的来源限定已逐项列出。没有真实费用发生，未写费用账本，也未重新对账。当前组工作到此停止，等待经理汇总与安排必要返工。
