# T-R2-OBS revision2 repair1 独立索引保护复验

**Verdict: PASS（仅本组真实离线索引与输出保护范围）。** 最终 capture 组合校验没有误拒本矩阵的真实候选事件。此结论不代表 repair1 总体验收通过，不证明真实 C29 根因、R2 或 T207 完成。SAFE/完整上下文与补丁包装由其他独立席位检查，本组未重复。

2026-11-18 使用项目 `.venv` 实际执行原有定向矩阵，退出 **0：1 passed in 17.68s**。seed/baseline/off/on/failure 五个有界子进程均 exit=0、已等待回收；当前无运行中的测试子进程、测试会话或后台写入。四变体各 19 场景，76 次场景执行，57 组业务等价比较全部 true。本次只执行这一原有节点，没有新增场景或扩大至 HTTP/全量测试。

## 探针与源码身份

先阅读本轮 `DEV-REPORT.md`、`VALIDATION.md`、`PROTECTION.md` 与 `patches/increment-source.patch`。本次产品增量只在 `evaluation_capture.py` 的 direct-rag 新事件候选组合检查；七源码身份与保护记录相符。

本目录探针复制自原独立验收目录。`test_index_acceptance.py` 与原文件逐字节相同；`index_probe.py` **只替换一处当前 capture SHA**，其他字节不变，行为断言未改。输出目录由新文件的 `__file__` 自然定位至本目录，临时目录独立为 `.tmp-r2-obs-acceptance-index-repair1/run1/`。复制差异的可逆核对与原文件 SHA 见 `COPY-PROVENANCE.json`。

本次仍使用 `.tmp-r2-obs-baseline/` 的四个开工脏树快照，不使用 HEAD。复制前、复制后都核对原 before SHA；独立 baseline 进程用精确四模块 loader 加载快照，其余依赖来自同一当前工作树。pytest 显式设置 `-o pythonpath`；子进程使用 `-I -B` 并显式设置源路径。四模块真实加载路径、SHA、新符号/源码负对照全部通过。

最终读取的七源码 SHA 如下，pre/post/final 完全一致：

| 源码 | SHA-256 |
|---|---|
| observability/evaluation_capture.py | 24a66783fb622164cf5c22ab79cffb211f7b44f7d97e4a9c6590e1cc7bd4b675 |
| conversations/service.py | 8f913cb3b7270c8e0fbf1b6720d95a3a388cf9364bd097d1b192c16f3bf0f6f5 |
| rag/answer.py | 9dd83f275aad5c02526ca2669df8520710e23871930b24774ade01cbeb8d7626 |
| rag/retrieval.py | 3d3c2c4cf475187afd19b3bfc4c76d4d9493c4e628dc5cf3420dd7024a001cd7 |
| rag/query.py | bedeedaba966209ea26a37fd3bee60fdb96fea21c87ac33dd7dce5ceb3db6fb0 |
| rag/facts.py | cf795cfd16fe15fdfa73f9bc12311cf9bcf55b2fafdb67a9a8f6719192dc7001 |
| qa/service.py | 627c328a62a77a81edd5fbf0b7fa293a63024a1f284bfcce2aece5e2cd9906b1 |

本组未修改任何产品源码或旧验收文件。原目录的两份探针、原 verdict、原完整运行记录、原最终身份记录和两份失败记录，共 7 项 SHA 在复制前与收口时均相同。具体布尔与 SHA 见 `FINAL-SOURCE-IDENTITY.json`，不扩大为未取得哈希的其他历史材料保护结论。

## 实际覆盖

下表为本轮 capture-on 实际结果。A/S/E 分别为真实 search 尝试数、成功返回数、新 retrieval 事件数。ask 指公开 `RagIndex.ask`；search 指合法构造 `QueryPlan` 后直接调用真实 `RagIndex.search`，没有替换 `_load`、检索返回或渲染输出。

| 固定场景码 | 边界 | 实际结果 | A/S/E |
|---|---|---|---|
| joined | ask，正常摄入 | joined | 1/1/1 |
| missing | ask，正常摄入 | store_row_missing | 1/1/1 |
| ambiguous | ask，正常摄入 | store_row_ambiguous | 1/1/1 |
| pagination | ask，正常摄入，3 回合 | roles_not_cross_level；has_more=true/true/false | 3/3/3 |
| large | ask，正常摄入 | count=521；列表=512；truncated=true；has_more=true | 1/1/1 |
| document | ask，正常摄入正文 | not_applicable；mode=document | 1/1/1 |
| empty | ask，真实空库 | count=0；empty=true；truncated=false | 1/1/1 |
| pre_refusal | ask | SECURITY_RESTRICTED_CONTACT；search 未执行 | 0/0/0 |
| search_exception | ask，真实 revision 漂移 | KNOWLEDGE_CHANGED | 1/0/0 |
| multi_item_ask | ask，正常摄入 | item_filter_missing | 1/1/1 |
| plan_not_record_or_enumerate | search，正常摄入 | not_record_or_enumerate | 1/1/0 |
| plan_roles_not_cross_level | search，正常摄入 | roles_not_cross_level | 1/1/0 |
| plan_item_filter_missing | search，正常摄入 | item_filter_missing | 1/1/0 |
| plan_multiple_items | search，正常摄入 | multiple_items | 1/1/0 |
| plan_multiple_stores | search，正常摄入 | multiple_stores | 1/1/0 |
| plan_item_row_not_unique | search，正常摄入 | item_row_not_unique | 1/1/0 |
| plan_store_value_missing | search，人工不一致 DB | store_value_missing | 1/1/0 |
| plan_store_value_ambiguous | search，人工不一致 DB | store_value_ambiguous | 1/1/0 |
| plan_already_present | search，人工不一致 DB | already_present | 1/1/0 |

公开 ask 共 12 回合，真实 search 尝试 11、成功 10、新事件 10。capture-on 各成功事件的候选去重集合、身份列表长度、empty、512 截断与分页标志均与同次原始 search 返回核对，sink 未失败。0 候选、521/512 截断、3 页均实际通过新 capture 组合校验。

直接 search 的 9 场景仅核验真实 diagnostics sidecar；新增 retrieval 事件在 answer 层成功 search 后发射，故直接 search 的 E=0 是明确入口边界。前置拒答和检索异常都无成功事件，未将缺事件等同空集合。

三个人工不一致 DB 场景沿用原限制：只在本组新建合成 DB 持久化异常元数据以执行真实索引算法。already_present 由店家块人为加物品键到达；store_value_missing 由删物品块规范门店键到达；store_value_ambiguous 由同记录身份多块人为持久化不同门店键到达。它们**不证明正常摄入可达**。正常摄入中 store 类型行缺 item 键，与联结入口非空 item 等值过滤互斥；同一记录各块继承同一规范字段。正常摄入的 562 块相关不变量违反数为 0。

search 异常仍由 SQL 执行通知在 search 开始后通过独立 SQLite 事务实际增加 revision，原 search 自己检测并抛异常；未伪造 revision 返回或 search 异常。

## 输出、状态与调用保护

四变体分别从相同 seed DB 逐字节复制，新建离线索引；各场景初始 DB SHA 与持久会话一致，使用相同问题序列。baseline 与当前 off/on/failure 的 57 组比较全部 true，涵盖：

- kind、reason、text、sources（直接 RagIndex 边界为 citations）、facts；
- total、returned、has_more、next_page、page、page_size、revision；
- 返回 state、实际持久化状态行、提交次数；
- search/load_state/save_state/lexicon_data/revision/离线 embed/rerank 调用计数；
- 直接 search 的 exact/lexical/vector/fused/evidence 与既有 store_join 业务载荷。

包装只计数并原样委托；revision 计数仍包含每答一次探针额外只读核验的固定开销，各变体相同，扣除后产品调用计数也相同。直接 search 不提交状态。

failure 变体仅让 sink 在新 retrieval emit 时抛固定异常：8 个存在成功 search 的公开 ask 场景实际 sink.failed，业务输出与基线/off/on 仍相同，事件没有冒充成功。分页首轮捕获失败后后续捕获关闭；拒答与检索异常未到该故障注入点，未计入 sink 故障覆盖。

## 零外发与终止证据

沿用已验证脚手架：产品导入前安装 socket 连接/发送/DNS、httpx Client/AsyncClient/transport、stdlib HTTP(S)/urllib、subprocess 与可用 os 进程启动入口守卫，并添加独立 Python audit hook 和 `.env*` 读取阻断。逐通道账本只记固定码与计数，不记参数。

最终五子进程 product 被阻断尝试数均为 **0**。每进程实际调用全部 40 个安装的包装入口，另用保存的原生 socket.connect 验证 audit hook，41 次正对照全部阻断；合计 **205**。不宣称全 Windows 系统调用审计。

显式 `provider_mode=offline` 使用 FakeEmbeddingProvider、LexicalReranker，正文为离线抽取；没有真实模型/embedding/OCR/judge/外部业务 API 调用。Windows 平台元数据沿用显式合成 uname 缓存，以免依赖导入启动 cmd 探测；它不替换业务数据。未读取真实私有材料、key、题答、计划、binding、合同或 `.env`。

驱动器启动的五个测试子进程与产品阶段账本分开记录，各 `timeout=90` 秒。实际各 exit=0，`subprocess.run` 返回后已回收；pytest 主进程亦 exit=0。`RUN-RECORD.json` 的每个实际 argv/exit/reaped 与 `FINAL-SOURCE-IDENTITY.json` 的 all_children_reaped=true 是本次终止依据，无遗留测试后台写入。

## 本次命令和证据文件

仓库根执行下列唯一测试节点：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& '.\.venv\Scripts\python.exe' -B -X utf8 -m pytest 'docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/repair1/independent-acceptance/index/test_index_acceptance.py::test_independent_real_index_matrix' -c 'backend/pyproject.toml' -o 'pythonpath=D:/GPT项目/市场部AI知识库/backend/src' --confcutdir='docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence/11-observability/revision2/repair1/independent-acceptance/index' -q -p no:cacheprovider --tb=short --basetemp='.tmp-r2-obs-acceptance-index-repair1/run1'
```

实际 exit=0，`1 passed in 17.68s`，本次没有测试失败或行为断言调整。首次读取 increment-source.patch 用错根级路径，随后按保护清单定位到 patches/；仅为只读定位错误，没有影响运行或修改文件。

- `RUN-RECORD.json`：完整五子进程实际 argv/exit、源码、逐场景哈希/计数、57 组等价结果和守卫账本。
- `FINAL-SOURCE-IDENTITY.json`：本次最终七源码 SHA、旧证据 7 项保护、关键结果/计数、回收状态。该收口核验命令本身 exit=0。
- `COPY-PROVENANCE.json`：原探针与证据 SHA、复制只改当前 capture 身份的精确字节证明。
- `index_probe.py`、`test_index_acceptance.py`：本次独立探针。

本组至此停止。HTTP 序列化/事务、prepared 跨层接线、SAFE 与完整上下文入口、补丁包装及真实质量不在本组新增结论内。没有写费用账本或重对账，没有运行私有诊断。
