模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

# T111 独立验收：live 检索运行器与真实索引（pilot）

验收对象：分支 `p1/fix-retrieval`，交付 `735bb93`（父 `1552a9e`），HEAD `0469601`（PM 簿记）；
初始 `git status --porcelain` 为空；结束仅新增本 review/证据（untracked），交付物无改动。
**结论：PASS（技术/交付；非阻断残余见 §3）。**
验收方 live 复跑 10 题后账本由 408 增至 **435/1000**（+0.0026345 元），见 §1.2/§3.6。

## 1. 逐项判定

| # | 项 | 判定 | 独立依据（命令 / `文件:行`） |
| --- | --- | --- | --- |
| 1 | pilot 真实结果 | **PASS** | 独立读 `var/eval/runs/b0-live-20261108T194053896474Z-b224f9fb/`：manifest `mode=live/scope=retrieval_only/case_count=10/dataset_version=b0:b0-2026-11-04:d958336c01fe/corpus_sha=688991…/index_revision=6/pipeline=08166b113481/gate=mktkb.gate.v0.1`；summary `status_counts={"pass":10}`、R/MRR/nDCG=1.0、hard=0、empty=0、`aborted=false`、`error_count=0`；10 行 CaseResult 的 11 个版本字段齐全且与 manifest 同值。数据集恰 10 行且等于 `fixtures/evaluation/b0.jsonl` 前 10 行；`var/eval/runs/` 仅此一个 live run。`runner.py:1037-1208`、`live.py:641-657` |
| 2 | 成本/账本 | **PASS** | 预检 0.2427765 元、27 请求、单笔 0.04096≤0.05；账本 stage `P1-RETRIEVAL` 0.0→**0.0026345 元**、381→**408**、27 笔 reservation + 27 result 全 `succeeded`（embedding 17/rerank 10/chat 0）、charge 合计 0.0026345、`provider_billed_cny` 全 null；GO 绑定历史前缀 sha `f4710b18…` 与账本前缀一致（整本 sha 因追加已变，未使用）。负例 stage 0.001 / 单请求 0.01 / 请求 5 均被拒；runner 预检拒绝时不建索引。`live.py:487-558/641-657`、`live_authorization.py:408-421`、`test_live_runner.py:402-459` |
| 3 | 零 chat | **PASS** | 按 run_id 过滤账本：54 事件仅 embedding/rerank、chat 0；`provider_requests.attempts={embedding:17,rerank:10}` 且 outcomes 各 17/10（零重试）；`RagConfig.chat_model/chat_api_key/chat_base_url` 全空；live 只调 `index.search(plan, limit=10)`（`runner.py:779/859`），`RagIndex.ask` 仅在 local/replay 分支。spy 测试（`DeepSeekChatProvider.__init__/complete`、`RagIndex.ask` 各 0 次）通过：`test_live_runner.py:258-301`；配置空 chat：`live.py:329-367`；运行期 chat 计数拒绝：`runner.py:1171-1175` |
| 4 | GO/绑定/失败语义 | **PASS** | 真实 GO 下 `service=chat`→“未授权服务”、`stage=S2-DEV`→阶段不一致、`embedding_model=text-embedding-v3`→binding 不一致、错误账本 sha→false，均拒绝；provider 错误→case `error`、后续行显式 `run_aborted_after_failure`、不静默跳过且 rerank 仅 1 次（零重试）：`test_live_runner.py:467-486`、`runner.py:921-976/1152-1161`；fake embedding 第 2 次失败时 `<out>/index/` 被删且无 manifest/summary/cases：`corpus.py:288-321`、`runner.py:1127-1130` |
| 5 | 验收方 live 复跑 ≤10 | **PASS** | 同 GO/账本、新 out 目录跑 `--pilot 10`：10 行全 pass、R/MRR/nDCG=1.0、hard/empty=0、`aborted=false`；27 请求（17 embedding+10 rerank）、chat 0、零重试；账本 408→435、P1-RETRIEVAL 0.0026345→**0.005269 元**。未超 10 题、未触发全量。命令/输出见 `03-probe-results.md §E` |
| 6 | 回归/预算/形式 | **PASS** | 本包 **11 passed**；`backend/tests/evaluation` **420 passed**；全量 `backend/tests` **1823 passed / 0 failed / 0 error**（476.42s，峰值 RSS≈465MB<2GB）。b0 40/40、badcase 13/13、regression 7/7 对修正后的父提交基线 `signature diffs=0`、retrieved 0；对 P0 b0/badcase 亦 0；gate 三套 exit 3、hard `[]`、unknown 42/94/80。`735bb93` 恰 9 文件全允许路径；report 63 行、证据 4 份；无 skip/xfail/删断言/新依赖；var 0 跟踪；未改 fixtures/conversations/intent/API/gate_v0/O baseline/账本/GO（详见 `04-test-eval-runs.md`） |
| 7 | T112 风险记录 | **PASS（记录）** | 复跑后 435/1000、剩余 565 次；regression live 索引 49 docs/5066 chunks，batch=5 约需 1014+ 次 embedding，超过剩余；全量前须缩小语料/调 batch/重签 GO。阶段金额剩余 2.994731 元。未自行跑全量、未改 GO |

## 2. 关键独立探针（不引用 report）

- pilot 索引副本：6 documents / 42 units / 27 chunks / 27 embedding rows，revision=6；
  27 个向量均 1024 维（4096 bytes float32）、model=`text-embedding-v4`、provider=`bailian`、
  互不相同——真实 embedding，不是离线替身。
- 账本逐笔：pilot 27 笔 reserve 为 embedding 17×0.04096 + rerank 10×0.024（最大
  0.04096≤0.05）；result charge 0.0010345+0.0016=0.0026345；`provider_billed_cny` 全 null。
- 失败不写半成品：fake embedder 第 2 次抛错→`CorpusError`，`index/` 与
  manifest/summary/cases 均不存在（02-probe）。
- 负例：未授权 service/stage、binding 不符、错误账本 sha、阶段/单请求/请求数超限均被拒。
- 文档小瑕疵：`T111/01-scope-and-commands.md` 写“10 条 fake/负例”，实际 **11** 条；
  report §2/证据 04 正确。非功能问题。

## 3. 残余 / 观察（不阻断 T111 技术验收）

1. **指标证据强度有限**：pilot 10 题均为 b0 exact/lookup、单题 1 个 gold，
   `Recall/MRR/nDCG=1.0` 只证明“真实 embedding/rerank→检索→指标”闭环，不是检索质量结论；
   Q09/Q10 分别返回 6/5 个 unit，其余 1 个。全量结论留 T112。
2. **pilot 索引范围**：真实索引是 b0 `fixtures/acceptance` 的 6 docs/27 chunks，不是
   `corpus/enterprise-20261101`；badcase/regression 的企业语料 live 分支未用真实 provider
   跑过。T112 必须覆盖。
3. **GO 请求计划计数未绑定**：GO `scope.bindings.rag` 声明 `embedding_requests=7`/
   `rerank_requests=4`，本次实际 17/10（27 请求）；运行器只核对 provider/model/host/
   region/dimensions（`live.py:306-326`），未把计划计数当硬约束。`max_requests=1000`
   仍生效；T112 前应核对/重签计划，消除“计划 11 次、实跑 27 次”的口径差。
4. **`CaseResult.status` 语义**：live 执行成功即 `status="pass"`（`runner.py:668-678`），
   检索质量只在 metrics/gate（empty recall、hard filter）体现；解读“10/10 pass”时不得
   当作 10 题质量全对。
5. **基线方法自纠**：`git archive` 不含 gitignored `docs/evidence/.../subset-policy.json`，
   首次父基线误解析 boundary/scan（54 docs/10442 units）；复制既有策略后父树
   49 docs/5380 units，与当前 0 diff。属验收方基线构造问题，不是 T111 缺陷。
6. **账本记账**：验收方复跑新增 27 请求 / 0.0026345 元（P1-RETRIEVAL 0.005269 元、
   435/1000）；PM 的“pilot 后 408”需按本结果更新；这不改变 T111 交付结论。

## 4. NOT-RUN / 边界

- 未跑全量 live（b0 40 / badcase / regression / holdout 均未 live）；未主动读取/使用
  Holdout 内容（全量测试按既有用例执行，未查看其内容）；未读 `.env`（live 运行时由既有
  配置体系内部读取，未打印）。
- 未用真实 provider 制造失败（会消耗请求/改账本）；失败语义用 fake/负例验证。
- 未跑 OCR 题、未做 gate 阈值校准/审批（T112）。
- 未覆盖 badcase/regression 企业语料 live 索引；未验证 T112 请求上限方案。
- 未 commit/push/切分支/stash/reset；未改交付物；仅新增本 review 与 `verify/T111/` 证据，
  以及 gitignored 的 live 复跑产物/账本追加。

结论：**PASS（技术/交付）**。残余交 PM/T112；“请求上限不足”为 T112 非阻断前置风险，
不得在本包自行跑全量或改 GO。证据：`docs/reports/OBS-EVAL/P1/evidence/verify/T111/`
`{01-verdict,02-probe.py,03-probe-results,04-test-eval-runs}`。
