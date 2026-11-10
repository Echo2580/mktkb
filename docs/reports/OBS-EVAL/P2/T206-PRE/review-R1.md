# P2-T206-PRE-R1 独立复验报告（review-R1）

- 角色：全新上下文独立复验助手（非开发/非经理），证伪优先；只写本文件与 `evidence/verify-r1/`。
- 现场：`codex/p2-e2e` @ HEAD `1e422e9`；R1 未提交：允许清单内 6 文件（p2_scoring +31/-4、product_adapter
  +203/-1、test_p2_runner +125、test_p2_scoring +74、契约 +39/-9、report +36）+ `test_p2_gate.py` +11/-7
  （经理已批准夹具例外）+ 经理簿记 `_index.md`（会话前已改）；新增证据 04/05/06。
- 边界：全 Mock/离线；未读 `.env`/H1/H2、未联网、未跑全仓、未改源码/测试/报告/契约、未 commit/push。
- **结论：PASS**（无阻断。R-1/R-2/R-3 均按代码路径 + 自写探针复现；2 条非阻断残余、4 条限制见 §3/§4）。

## 1. 逐条判定

| # | 复验项 | 判定 | 本机证据（探针/复跑） |
|---|---|---|---|
| R-1 | scorecard 缺/异 `config_hash` fail-closed、双侧各判 | **PASS** | `config_hash_unbound`：双侧缺=2 条、只补一侧=1 条、manifest 缺=1 条（不重复）；异 hash=`config_hash_binding_mismatch` 1 条；全部 severity=unknown、`release_allowed=False`、quality exit≠0；两侧声明一致时无 `config_hash_*` 阻断 |
| R-1b | `test_p2_gate.py` 仅夹具对齐、断言未降 | **PASS** | diff 仅 `public_card/holdout_card` 增 `config_hash` 形参并在 3 个用例传入 manifest 摘要；无断言删改、无 skip/xfail（numstat +11/-7 全为形参与调用行） |
| R-2 | gate 行 `retrieved` = 产品真实检索只读重放（非 citations） | **PASS** | 独立用产品 API 重算（rag：`parse_query`+`candidate_unit_ids`；legacy：`parse_question`+`_load_context`+`_retrieve`）逐轮等于记录：P01 2/2、P02#1 2/2、P03 4 候选（引用 2 + 未被引 2）、P05#1 2/2、P05#2（多轮 legacy 上下文）1/1；候选全部解析到本 run 文档的真实 `SourceUnit`，`unit_key/locator` 非空 |
| R-2b | 判定未放宽：citation⊆retrieved 才 pass；缺/异 fail | **PASS** | 正例 `citation_required=pass`；drop / foreign / partial（只删 1 个被引单元）/ 整键缺失 → 全部 `fail`，硬失败列出且 check=`citation_not_in_evidence`；非作答轮（P04、P02#2 `not_found`）不采集、无检索调用、gate 不要求引用 |
| R-2c | 只读、失败即空、零真实调用 | **PASS** | 采集前后 product revision 2→2、SourceUnit 16→16；revision=None / 未知 path / rag 无 state / 坏 legacy 会话 → 均返回 `()` 不抛；两次 run `config_hash` 同为 `58caf4a2…b01e`；`real_requests=0`、`billed_cny=0` |
| R-3 | 契约 §8 顺序与代码一致 | **PASS** | 原生 manifest → `run_manifest_incomplete`（构建期）；补全清单、trace `config_hash` 置 NULL → `trace_integrity=fail` 且 check=`version_binding`；§8 首行/第二行与新 §2b/§3 文字一致；runner 的 trace 六元组与 manifest 同源（缺一项整体不绑） |
| 回归 | T203/T201/T204/T205/gate | **PASS** | 本机 exit 0：35、70、18、56、109（105=35+70，与经理印核一致）；未跑全仓 |
| 范围 | 只改允许文件 + 已批准例外 | **PASS** | 禁改面 porcelain 为空（fixtures/gate.py/p2_ingestion.py/conversations/main.py/observability/.env）；无其他 tracked 改动 |
| 账本 | 共享账本/预算/GO 未变 | **PASS** | live-ledger.jsonl 958277B/`1f46d1b9e846528d`、budget.json 1444B/`084ba9acb4ee9037` 与 06 全等；`P2-LIVE-GO.json` 不存在 |
| 真实性 | report/evidence 与复跑一致 | **PASS** | 9 个文件 sha256[:16] 与 06 全等（行数为其“含末尾空行”口径，内容同一）；04 计数、05 探针输出逐值复现；report `## R1` 的 P01 2/2、P03 4/2、P04 0、config_hash、real=0 均与实测一致 |

## 2. 关键实现核对（代码层面）

- R-1：`evaluate_p2_gate` 5c 段对每张 card 判：`None` 且 manifest 有 hash → `config_hash_unbound`；声明且 manifest 无 → unbound；不等 → mismatch；manifest 自缺只记 1 条。空字符串由 scorecard 构造期 `config_hash_invalid` 拒绝，无法绕过。
- R-2：`ask_turn` 在 POST **前**快照 revision + rag 状态；作答轮才采集；重放分别走产品 rag/legacy 检索入口，异常一律吞成空集（fail-closed）；`retrieved` 只写 `product.retrieved`，评分侧 `normalize_product_outcome` 在无显式夹具候选时用它填 `outcome.retrieved`，gate 仍按 unit 级 `cited ⊆ retrieved` 判；`gate.py` 未改。
- R-3：`build_gate_run` 必填字段先拒；清单补全后 `_gate_trace_integrity` 按 `_TRACE_BINDING` 比对，None 即 `version_binding`。

## 3. 非阻断残余（建议 T206 GO/ pilot 前知悉）

1. **gate 层无法识别“伪造的 retrieved”**：探针把 citations 抄进 retrieved → gate `pass`（`copy_citations_passes_gate_trust_boundary`）。gate 的独立价值在抓 drop/foreign/缺失；“来自真实检索”的保证在适配器代码路径 + 用例，不在 gate 二次推导。同源旁路：评分侧 `score_public_case(..., evidence=...)` 可显式覆盖候选（仓内只有测试用它；pilot 驱动默认不传即安全）；pilot 驱动若把引用当 `evidence` 传入，等于自证。消费方不得把 gate pass 当“候选来源已证”。
2. **rag 候选是召回并集**（exact/lexical/vector/fused），可宽于 `fused[:top_k]` 返回证据；本夹具实测相等（2/2，`candidates_not_returned=0`）。契约 §2b 写“检索候选”，语义一致，但不是“模型实际看到的那一页”。

## 4. 限制 / 未覆盖

- `ask_turn` 的“发送前状态快照”无差分证据：mock 下 rag 持久状态不推进（5/5 轮前后 state 相同），顺序仅由代码位置（快照在 POST 前）核对；多轮 legacy 上下文重放已由 P05#2 实测。
- legacy 重放用 `limit=100`，真实作答路径先 20、截断才升 100：未截断时同为全集；截断时产品自己也用 100（record）；本夹具未见放宽，但“20/100 语义差”未逐分支覆盖。
- 未跑 live 链、H2 端到端（无 case_id 路径）、全仓；未回跑历史 verify 探针——T205/R2 探针仍断言“未声明 config_hash 的 scorecard 可放行”，与 R-1 新行为冲突（report §R1 ④ 已披露），建议在下次引用前标注 superseded。
- 无仓内驱动调用 `evaluate_p2_gate`，R-1 把“必须传 config_hash”前置到 pilot 驱动（契约 §3 已写明），属预期而非缺陷。

## 5. 放行意见

- **PASS**：3 项收尾均达标且 fail-closed 语义未被放宽；回归/账本/范围/真实性一致；无硬违例。
- 建议：接受 R1；T206 pilot 前把 §3-1/§3-2 写入 pilot 报告的限制段，并在 pilot 驱动显式传 `config_hash`。
- 证据入口（3）：`evidence/verify-r1/{probe_verify_r1.py,01-r1-probe-output.json,02-regressions-scope-evidence.txt}`。
