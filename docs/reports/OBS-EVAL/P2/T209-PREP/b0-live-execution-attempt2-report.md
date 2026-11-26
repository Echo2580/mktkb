# T209 正式 B0 更正环境后单次续跑 · 执行回执（attempt 2）

2026-11-20，Asia/Shanghai。执行角色：真实运行执行 AI。工作树 `D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`。

**执行状态：`COMPLETE`**（唯一一次真实运行成功，退出 0，40/40 题完成，无 stop_code）。
**准入状态：`BLOCKED`**（只读 `p2-admit` 退出 3，`b0_hard_gate_blocked`，唯一失败门 `trace_integrity`）。
**质量结论（单列）：38/40 通过，精确 24/24，OCR 执行 8/8。** 不构成基线准入通过，原因见 §7。

## 1. 摘要

| 项 | 值 |
| --- | --- |
| 运行 ID / 计划 ID | `p2-t209-b0-20261120-01` / `P2-T209-B0-20261120-01-DRAFT` |
| 计划规范 / 文件 SHA-256 | `c3dbbafa2a1baa9b447495dc1bab06a8f6322e5b376a87a7c12ae563abec3228` / `41e408fb0e4b4c83ab866f796330c8149294cbbfd9a4b7bc5fdeb70f693090b3` |
| 本轮 GO 文件 / 规范 SHA-256 | `37109d9849d6a2ffd69b97b1a0710da60e311a346d7ae88b947329e2d7d5baa2` / `b33931f06f0e904b0968dbb9ebd6154f65eb3a87a45bc612c1c0edfdaa70f474` |
| GO 生效 / 到期（UTC） | `2026-11-20T08:35:51+00:00` / `2026-11-20T11:35:51+00:00`（nonce 32 字符，值未打印） |
| 固定槽恢复后摘要 | `43e0f6229efeae77334e821b91548b7024a1aefdf5824a9586f4c8d12330aaad`（逐字节等于签发前原件） |
| 执行开始 / 结束（UTC） | `2026-11-20T08:35:51.8468374Z` / `2026-11-20T08:42:44.6867131Z`（412.83 s） |
| 执行退出码 | **0**（`status=succeeded`，`stop_code=null`） |
| 准入退出码 | **3**（`b0_hard_gate_blocked`） |
| 实发 / 预留 / 结算 | 112 次出站 / 112 笔预留 / 112 笔结算（待结算 0） |
| 费用（保守＝供应商口径） | **5.7197526 元**（≤ 上限 7.464016 元） |

## 2. 冻结输入复核（全部一致）

- 19 项冻结工件 SHA-256 与任务书快照逐项相同（0 处漂移）；绑定计划双摘要与冻结值逐字相同。
- `build_b0_plan_binding` 原位重算与 `plan.b0_binding` 逐键相等；`pipeline_source_sha256=6fbde812…`、`corpus_sha256=9ea5a422…`、`gate_config_hash=7fa6f47a…`。
- 该 run ID 在共享账本中的预留/发送记录为 **0 条**；`var/eval/runs/p2-t209-b0-20261120-01` 事先不存在。
- 工作区 `.env` 原字节保留（SHA-256 `87a411664f0f0ca6a247ad8faeb7b728bd90c5f71b244db46ffeb8a8f2001fde`，运行前后一致）。

## 3. 同环境预检（签发 GO 之前，任务书 §2 原样脚本）

- 隔离注入：先清空继承的 8 个供应商键与 1 个总限额键，再从 `.env` 同源注入 7 个白名单变量；仅把有效 `MKTKB_MODEL_NAME` 锁定为 `deepseek-flash`，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=40.0`。值不打印、不复制到第二个文件。
- 原生进程入口 `load_live_env()` 输出与期望逐值相等：

```json
{"chat_model": "deepseek-flash", "chat_host": "api.deepseek.com",
 "embedding_host": "dashscope.aliyuncs.com",
 "ocr_region": "ap-guangzhou", "ocr_enabled": true}
```

- 预检退出码 **0**；随后签发新 GO，并**在同一进程环境**执行唯一一次 `p2-run`。

## 4. 本轮 GO

- 固定槽原字节（T207 r3 旧 GO，`43e0f622…`，1306 B）先存档，再原子写入新 GO。
- 候选在隔离位置通过全部结构/范围检查；从固定文件重读 `authorize_p2` 得 `production_ready=true`、plan/scope 匹配、`budget_ledger_sha256` 绑历史前缀 `f4710b18…`。
- 收尾已封存本轮 GO 原字节并**按签发前副本恢复固定槽**，恢复后摘要 `43e0f622…`，逐字节等于原件。
- 首轮封存 GO（`61a30569…`）保持历史状态未动。

## 5. 执行实测

```text
{"ok": true, "mode": "live", "status": "succeeded", "stop_code": null,
 "requests_planned": 194, "requests_sent": 40, "production_ready": true,
 "execution": "live", "attempts_reserved": 144,
 "by_center_cny": {"answer_retrieval": 0.062352, "ocr": 0.0, "judge": 0.0, "independent": 0.0}}
```

| 项 | 实测 |
| --- | --- |
| 题量 | 计划 40 / 执行 40 / 错误 0 / 未执行 0 |
| 出站实测 | 112 = chat 40 ＋ embedding 36 ＋ rerank 24 ＋ ocr 12；`mock_intercepted=0` |
| 尝试回执 | 144 条（reserve/settle 成对），`by_operation`：index_embedding 12、query_embedding 24、rerank 24、ocr 12、answer 40、query_expansion **0** |
| run 门 | 8 项检查全 ok，`real_sends_allowed=true`，`artifact_validation.ok=true`，引用证据 complete |
| 延迟 | min 542 ms / 中位 7036.5 ms / max 8500 ms / 合计 195.8 s |
| Token | **不可得**：`requests.jsonl` 与 trace 的 `token_usage_json` 均无 token 字段，不按 0 记 |
| 费用 | `billed_cny` 0.062352（chat 逐轮实计）＋ OCR 保守计费 5.65 → 合计 5.7197526 |

计划 194 与实发 112 的差异属预期口径：22 批索引是**配额**，实际分批量 12；只有走 RAG 候选路径的 24 轮回调 embedding/rerank（另 16 题走 `legacy` 纯文本路径）；`query_expansion` 本轮未被执行（0 次）。全部在 194/7.464016 上限内。

## 6. 账本与对账

| 项 | 运行前 | 运行后 | 增量 |
| --- | --- | --- | --- |
| 账本文件 SHA-256 | `67418058…` | `9a17f417b389530e3e0fc00ead2dc2fa4a586816aa4d214580b96007f63e7a1f` | 追加事件 |
| 历史前缀 SHA-256 | `f4710b18…` | `f4710b18…` | **未变** |
| 预算文件 SHA-256 | `79b21700…` | `79b21700…` | **未变** |
| 预留 / 结算 | 2455 / 2455 | 2567 / 2567 | +112 / +112 |
| 待结算 | 0 | **0** | 0 |
| P2 阶段占用 | 10.65397 | 16.373722599999827 | **+5.7197526** |
| answer_retrieval | 4.446982 | 4.516734600000017 | +0.0697526 |
| ocr | 6.15 | 11.8 | **+5.65** |
| judge | 0.056988 | 0.056988 | 0 |
| independent | 0 | 0 | 0 |

- 零出站预留 0；重试 0；失败结算 0；拒绝轮 0。
- 逐笔核对：`receipt_count=144`、`reservations=72`、`gate_reserved=expected_reservations=112`，与账本 +112 一致。
- 预算目录仅 `budget.json`、`live-ledger.jsonl` 两个文件，无残留锁或临时文件。

## 7. 准入与阻断（交回经理的核心项）

`p2-admit` 只读执行：

```text
ERROR: B0Error: b0_hard_gate_blocked
admission exit = 3
```

复算结果：

| 项 | 值 |
| --- | --- |
| 执行 / 计分 | 40 / 40 |
| 通过 / 失败 / 错误 / 未执行 | 38 / 2 / 0 / 0 |
| 精确题 | 24 / 24 通过 |
| OCR | 计划 8 / 执行 8 / 通过 7 |
| `min_sample` / `scored_count` | 32 / 40 |
| 八项硬门禁 | `exact_value_contract=pass`、`citation_required=pass`、`trace_integrity=fail`，其余 5 项 `not_applicable` |
| hard_failures / unknowns | `["trace_integrity"]` / `[]` |
| 门禁整体 exit_code | 1 |

**根因（单一且系统性）**：40 条 trace 中有 **24 条**的 `index_revision=12`，另 16 条为 `11`；而 run_manifest 与绑定记录的 `index_revision=11`。`trace_integrity.version_binding` 要求逐条相等，24 条不等的 trace 各报一次 `version_binding`（`mismatched=["index_revision"]`）。

**它与执行路径一一对应**：24 条 `=12` 的 trace 全部是 `legacy_with_rag_candidates` 路径，16 条 `=11` 的全部是 `legacy` 路径；这 24 条也正好对应 24 次 query_embedding 与 24 次 rerank。即**走 RAG 候选分支的回合把运行期实际的索引修订号写进了 trace，而未走该分支的回合写的是绑定值**，两侧口径不一致。

本项属运行接线的一致性缺陷，不在本轮授权范围内修改（未动任何源码）。请经理决定返工归属与是否重开一次真实运行。

**另有一处需一并复核的计费分歧**：`run_result.by_center_cny.ocr = 0.0`（12 次 OCR 的逐请求计费为 0），而账本与 `money_split` 的 OCR 保守计费为 **5.65 元**。两者口径不同，本轮按账本口径计入 5.7197526 元；实际供应商账单未知。

## 8. 质量明细（38/40）

| 失败题 | 层 | 失败检查 | 证据 |
| --- | --- | --- | --- |
| Q25 | text | `value_hit` | 期望 3 个值，缺 `["领取时登记数量"]` |
| Q33 | ocr | `source_hit` | 期望 1 个来源，缺 index 0 |

其余 38 题全部通过；OCR 8 题中 7 通过（Q33 即在此列）；无 refuted 误判、无 `value_no_fabricated` 失败。

## 9. 运行件与摘要

`var/eval/runs/p2-t209-b0-20261120-01/p2-run`：

| 工件 | 字节 | SHA-256 |
| --- | --- | --- |
| `run_manifest.json` | 244840 | `7546444a12235d23a600da75ba297c68aa162af34cb69a6033094b0ec6bdb927` |
| `summary.json` | 206237 | `9788f6c838fe6b32e75d77e85c28aabf619b5cac162ff05bc03de52e49325122` |
| `dataset.jsonl` | 28943 | `264ce1f019e5ac9be0265676e9b9cd1aa6ce1598e3e87a0bc7d8b73f3f0dcee1` |
| `cases.jsonl` | 190482 | `96baf999a25609ee256ef3b525ee95d7a638dec1560e6561a07188b25c2e14d4` |
| `requests.jsonl` | 52257 | `2c26cd120aa30d45480d33b3ff7de16974bb4d8c23d4bd8a873efc4f59b21845` |
| `gate.json` | 103931 | `279a6a1a1342da2c0416ed61ecbdd7c729ec5d55d6bff1e65d796ada1b4b7ed3` |
| `run_result.json` | 978 | `70a2baaa07d865343f9dbf9373c5af38f82bef2bcb3b603975be10e0cc5cb46a` |
| `data/observability/qa-traces.sqlite3` | 233472 | `a9805079dd57b9d0ef29919f3059ab29eab6249d3eaae0bcdc8ccda03711f0b3` |

## 10. 偏差与自证

- **本次续跑之前有一次我自己的工具失败**：08:35:18 首次签发时，我写的 GO `authorization` 文本超过 200 字符上限，`_check_go_payload` 拒绝（`text_invalid`）。该失败发生在**写入固定槽之前**（隔离校验阶段），固定槽、账本、预算均未变，未发生任何发送；我把文本改到 172 字符后重跑整套流程。该次签发的候选文件与旧 GO 存档一并留证。
- 只发出**一次** `p2-run` 调用；未续跑、未补跑、未并发、未扩配额。
- 未删除、截断或手改共享账本与预算；未改生产源码、仓内测试与 Git 记录。
- 未回显或复制任何凭据值；GO nonce 仅记长度。

## 11. 后续影响（供经理排程）

运行后 `preflight_p2` 对**同一计划**已不通过：

```text
reasons = ["stage_budget_insufficient", "center_budget_insufficient:ocr"]
stage_remaining = 3.6262774 元（< 计划 worst_case 7.464016）
ocr 中心剩余 = 0.2 元（< 需 5.65）
项目剩余 = 8.5553329 元
```

即：不加预算/不调额的情况下，本计划不能再次真实运行。若因 `trace_integrity` 需重跑，须先经批准调整阶段与 OCR 中心额度。

## 12. 证据路径

`var/eval/t209-prep/b0-live-20261120-attempt2/`（git 忽略，UTF-8）：

| 文件 | 内容 |
| --- | --- |
| `run-once-attempt2.ps1` | 单进程入口（清同名键 → 同源注入 → 环境预检 → 签发 GO → 唯一一次 p2-run → 记录摘要） |
| `logs/env-preflight-source.py` / `logs/env-preflight.txt` | 任务书 §2 原样预检脚本与输出 |
| `logs/mint-go.json.txt` | GO 签发、隔离校验、固定槽重读授权 |
| `go/P2-LIVE-GO.before-t209-b0-20261120T083518Z.archived.json` | 首次（失败）尝试的旧 GO 存档（`43e0f622…`） |
| `go/P2-LIVE-GO.before-t209-b0-20261120T083551Z.archived.json` | 正式签发的签发前原字节（`43e0f622…`） |
| `go/P2-LIVE-GO.candidate-20261120T083518Z.json` | 被拒的候选（超长 authorization，留证） |
| `go/P2-LIVE-GO.t209-b0-20261120-01.attempt2.sealed.json` | 本轮 GO 封存原件（`37109d98…`） |
| `logs/p2-run.stdout-stderr.txt` | 真实 stdout/stderr |
| `logs/attempt2-run.meta.json` | 起止时间、耗时、退出码、前后账本/预算/GO 摘要 |
| `logs/seal-go.json.txt` | 封存、固定槽恢复、对账、七件工件与 trace 摘要 |
| `logs/p2-admit.json.txt` | 只读准入的真实输出与退出码 |
| `logs/diagnose-admission.json.txt` | 复算评分、逐题状态、八项硬门禁与失败证据 |

## 13. 交回经理

- 执行：`COMPLETE`。真实运行成功，资金 5.7197526 元在授权内，账本零悬账。
- 准入：`BLOCKED`，唯一原因 `trace_integrity`（24/40 trace 的 `index_revision` 与绑定值不一致，且严格对应 RAG 候选分支）。
- 质量：38/40（≥36）、精确 24/24、OCR 8/8 执行，达质量门；不达准入门。
- 建议下一步：由经理定性 `trace_integrity` 是重打分口径问题还是运行接线缺陷；若需重跑，先批额度（当前阶段剩余 3.6262774 元、OCR 中心剩余 0.2 元）。正式基线接收、`p2-approve` 与 P2 发布本轮均未触碰。
