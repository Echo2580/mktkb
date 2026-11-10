# T111 证据 04：测试、本地回归与合规

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 测试（命令口径：`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`，cwd=仓库根）

```text
python -B -m pytest backend/tests/evaluation/test_live_runner.py -q
  -> 11 passed

python -B -m pytest backend/tests/evaluation -q
  -> 420 passed

python -B -m pytest backend/tests -q
  -> 1823 passed, 1 warning in 500.60s（0 failed / 0 error；轮询峰值 RSS 约 412MB < 2GB）
```

`test_live_runner.py` 覆盖：预检接受/阶段剩余不足/单请求上限/请求数不足、GO provider
binding 不符、零 chat spy（`DeepSeekChatProvider.__init__`/`complete` 与
`RagIndex.ask` 均 0 次）、provider 错误 fail closed + 零重试、pilot ≤10 与精确子集、
manifest/逐行版本字段、OCR 显式跳过、多轮顺序状态、httpx proxy env 恢复。

## B. 本地 P0 对照（改后最终跑，均只读 P0 baseline）

```text
b0        rows 40/40  signature diffs=0  gate exit 3  hard=[]  unknown=42
          status {'pass':29,'fail':3,'skipped_requires_ocr':8}
badcase   rows 13/13  signature diffs=0  gate exit 3  hard=[]  unknown=94
          status {'pass':9,'fail':4}
regression rows 7/7   signature diffs=0  gate exit 3  hard=[]  unknown=80
          status {'pass':5,'fail':2}（与 T109-R2 验收 run 一致）
```

签名 = `(status, outcome.kind, [(check_id,status)...], error.code)`，不比较 metrics/
trace_id/duration 等易变字段。b0/badcase 检索指标与 T110 收口值一致（b0 Recall 0.96875 /
MRR 0.96875 / nDCG 0.96875；badcase 0.7855614973 / 0.85 / 0.7499953095）。
gate exit 3 均为既有 `min_sample_missing` + `thresholds_unapproved`（T112 负责），
无新增 hard failure。

## C. 合规

- 证据不含凭据/`.env` 值/GO 原文/答案原文；只含聚合指标、公开哈希与账本计数。
- `var/eval/runs/*` 与 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`
  均被 `.gitignore` 覆盖，不 commit；未改 P0 baseline、未读 Holdout、未 push/amend。
- 未改业务代码/API/检索算法/conversations/intent；未改 `gate_v0_2.json`/阈值。
- 无 skip/xfail/删断言；新增测试只加强断言。
- 真实调用只有 embedding + rerank：27 笔账本预留/结果，chat 0；零重试。

## D. 交接给 T112 的风险提示（不属 T111 改动）

当前共享账本累计 408/1000 次预留，剩余 592 次。regression live 索引（49 文件 /
5066 chunk，batch=5）单独约需 1033 次 embedding 请求；全量 b0+badcase+regression+
holdout 的请求数会超过剩余上限。T112 放行全量前必须解决请求上限：缩小 live 索引语料
（只建被 gold 引用的资料/共享企业索引）、调整 embedding batch（注意 settlement cap），
或在主人授权下重新签发 GO/账本策略；阶段金额剩余 2.9973655 元不是当前唯一约束。
