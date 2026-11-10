# T111 验收证据 03：独立探针结果与 live 复跑

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

命令（cwd=仓库根；只读账本/GO，不发请求）：

```text
.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T111\02-probe.py
```

## A. pilot 产物（独立读取，不引用 report）

```text
manifest live retrieval_only 10 b0:b0-2026-11-04:d958336c01fe 6889915267c5 6 08166b113481 mktkb.gate.v0.1
statuses Counter({'pass': 10}) rows 10
metrics {'Recall@10': 1.0, 'MRR@10': 1.0, 'nDCG@10': 1.0,
         'hard_filter_violation_rate': 0.0, 'empty_recall_rate': 0.0}
versions_complete True identical True
aborted False error_count 0
pilot True 10
```

pilot 数据集 `var/eval/pilot/b0-pilot10.jsonl` 恰 10 行，逐字节等于
`fixtures/evaluation/b0.jsonl` 前 10 行（b0 共 40 行）；manifest `case_count=10`；
`var/eval/runs/` 下只有这一个 live run。索引副本独立查询：6 documents / 42 units /
27 chunks / 27 embedding rows，revision=6；27 个向量均为 1024 维（4096 bytes float32）、
model=`text-embedding-v4`、provider=`bailian`、27 个互不相同；不是离线替身。

## B. 账本（pilot + 验收方复跑）

pilot `run_id=b0-live-20261108T194053896474Z-b224f9fb`：

```text
events 54 kinds {('reserved','embedding'):17, ('reserved','rerank'):10,
                 ('result','embedding'):17, ('result','rerank'):10}
charge 0.0026345 expected 0.0026345
all_succeeded True
chat_events 0
total_reservations 435 (pilot 结束时 408；验收方复跑 +27)
prefix_sha f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014
go_bound  f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014 match True
binding_ok True wrong_sha_ok False
```

账本逐笔：pilot 27 笔 reservation 的 `reserve_cny` 为 embedding 17×0.04096、
rerank 10×0.024（最大 0.04096 ≤ GO 0.05）；result 的 `conservative_charge_cny`
合计 0.0026345（embedding 0.0010345 + rerank 0.0016），`provider_billed_cny` 全 null。
账本全文件 sha 因追加而改变，但 GO 绑定的不可变历史前缀 sha 未变。

## C. GO/预算负例（真实 GO，零 HTTP）

```text
authorized P1-RETRIEVAL rag 3.0 1000 0.05 2026-11-30T23:59:59+08:00
refused service=chat        GO 未授权服务 chat
refused stage=S2-DEV        GO stage 'P1-RETRIEVAL' 与请求阶段 'S2-DEV' 不一致
refused binding             rag.embedding_model 运行期='text-embedding-v3' 与 GO 绑定='text-embedding-v4' 不一致
chat_fields '' '' ''        retries 0 True
estimate 0.2427765 27 7 10 10 0.04096 True () request_remaining 565
refused stage_tiny          ('stage_remaining_insufficient',)
refused cap_tiny            ('single_request_cap_exceeded',)
refused req_tiny            ('request_limit_insufficient',)
```

## D. 失败不写半成品索引（fake embedder 第 2 次调用抛错）

```text
refused CorpusError b0 live 索引 embedding 失败 D02: RuntimeError
index_exists False
index_db_exists False
manifest_exists False
summary_exists False
cases_exists False
```

`corpus.py:288-321` 在 live 建库失败时关闭索引，`runner.py:1127-1130` 删除整个
`<out>/index/`；探针确认目录及 manifest/summary/cases 均不存在。

## E. 验收方 live 复跑（10 题，新 out 目录）

```text
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
python -B -m mktkb.evaluation.live --suite b0 --dataset var\eval\pilot\b0-pilot10.jsonl `
  --pilot 10 --out backend\.pytest-tmp\T111-verify\live-rerun

run_id=b0-live-20261108T204503974423Z-d5a502f3 suite=b0 mode=live scope=retrieval_only cases=10
precheck_estimated_cny=0.2427765 precheck_requests=27 pilot=True
ledger_stage=P1-RETRIEVAL stage_accounted_before=0.0026345 stage_accounted_after=0.005269
reservations_before=408 reservations_after=435
provider_requests embedding=17 rerank=10 chat=0
metrics Recall@10=1.0 MRR@10=1.0 nDCG@10=1.0 hard_filter_violation_rate=0.0 empty_recall_rate=0.0
aborted=false
```

复跑产物独立核对：10 行全 `pass`；`versions` 与 manifest 一致；`live.chat_calls=0`、
`provider_requests` 仅 embedding 17 / rerank 10；账本该 run 54 事件全 `succeeded`，
charge 0.0026345、chat 0；未触发全量。复跑后账本 435/1000、P1-RETRIEVAL
0.005269 元、阶段剩余 2.994731 元（验收方消耗，需 PM 记账）。

## F. 残余

- pilot 10 题均为 b0 exact/lookup，单题 1 个 gold；`Recall/MRR/nDCG=1.0` 只证明运行器
  与真实调用闭环，不等于检索质量结论；企业语料/badcase/regression 的 live 分支尚未真实跑。
- GO `scope.bindings.rag` 的 `embedding_requests=7`/`rerank_requests=4` 与本次实际
  17/10 不一致；运行器只核对 provider/model/host/region/dimensions，未把请求计划计数
  当硬约束；`max_requests=1000` 仍是有效上限。T112 前应核对/重签请求计划。
