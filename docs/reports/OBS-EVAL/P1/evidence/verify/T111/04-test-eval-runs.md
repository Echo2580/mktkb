# T111 验收证据 04：测试、回归、门禁与合规

模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`

## A. 测试（cwd=仓库根；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）

```text
python -B -m pytest backend/tests/evaluation/test_live_runner.py -q
  -> 11 passed, 1 warning in 1.65s

python -B -m pytest backend/tests/evaluation -q
  -> 420 passed, 1 warning in 91.38s

python -B -m pytest backend/tests -q
  -> 1823 passed, 1 warning in 476.42s (0 failed / 0 error)
```

全量运行期间轮询 python 进程 WorkingSet：约 381–465 MB（峰值 465 MB < 2 GB）。
新增测试无 `pytest.mark.skip/xfail`；提交只新增 `test_live_runner.py`，未删改既有测试断言。

## B. b0 / badcase / regression 本地复跑（当前 HEAD 0469601，内容=735bb93）

```text
python -B -m mktkb.evaluation.cli run --suite <b0|badcase|regression> --mode local --out <tmp>
```

| suite | rows | status | unknown | gate |
| --- | ---: | --- | ---: | --- |
| b0 | 40/40 | pass 29 / fail 3 / skipped_ocr 8 | 42 | exit 3, hard `[]` |
| badcase | 13/13 | pass 9 / fail 4 | 94 | exit 3, hard `[]` |
| regression | 7/7 | pass 5 / fail 2 | 80 | exit 3, hard `[]` |

签名 `(status, outcome.kind, sorted(check_id,status), error.code)` 对比：

```text
cur vs p0-b0        signature_diffs=0  retrieved_diffs=0
cur vs p0-badcase   signature_diffs=0  retrieved_diffs=0
cur vs parent2-b0   signature_diffs=0  retrieved_diffs=0  revision 6/6
cur vs parent2-badcase  signature_diffs=0 retrieved_diffs=0 revision 4/4
cur vs parent2-regression signature_diffs=0 retrieved_diffs=0 revision 49/49
```

**基线方法说明（验收方自纠）**：用 `git archive 1552a9e` 建父提交基线时，`docs/evidence/`
被 `.gitignore` 排除，导致 `tools/rag_experiment.py` 读不到
`docs/evidence/LOCAL-R1-20261101/S1-DEV/R2/subset-policy.json`，父树误把 boundary/scan
也解析（54 docs / 10442 units，revision 54），与当前 49 docs / 5380 units（revision 49）
不可比。把该既有策略文件复制进父树后重跑，父树同样 49 docs / 5380 units，签名与
retrieved 均 0 diff；上表使用修正后的 parent2 基线。此为验收方法问题，不是 T111 缺陷。

## C. 门禁

`gate --config docs/evaluation/gate_v0_1.json` 对三套本地 run 均 `exit 3`，
`hard_failures=[]`，`quality=unknown`/`config_status=unapproved`（既有 min_sample +
阈值未审批，T112 负责）；unknown 集合数量 42/94/80，与交付证据一致。

## D. 形式与合规

- `git diff --name-status 1552a9e 735bb93` 恰好 9 文件：`runner.py`、`corpus.py`、
  `live.py`、`test_live_runner.py`、`report.md`、证据 4 份；全部在 handoff 允许路径。
- `report.md` 63 行（≤80）；证据 4 份；首行模型标注。
- 无 `fixtures/`、`conversations/`、`intent.py`、业务 API、`gate_v0_2.json`、P0 baseline、
  账本/GO 的提交改动；`pyproject.toml`/lockfile 无 diff；无新依赖。
- `git ls-files var` = 0；pilot 与验收方复跑产物均在 gitignore 的 `var/` 或
  `backend/.pytest-tmp/`；共享账本被 `docs/evidence/` gitignore 覆盖。
- 验收方未读取 `.env`（live 运行时由既有配置体系内部读取，未打印）；未读取 Holdout；
  未 commit/push/切分支/stash/reset；未改交付物。
- 证据/本文件只含聚合指标、公开哈希与账本计数，不含凭据、GO 原文或逐题答案原文。
- 文档小瑕疵（非阻断）：`T111/01-scope-and-commands.md` 写“10 条 fake/负例”，
  实际 `test_live_runner.py` 为 11 条（report §2/证据 04 均写 11）。

## E. T112 非阻断风险（验收方只记录，未跑全量、未改 GO）

验收方复跑后账本 **435/1000** 次预留、P1-RETRIEVAL **0.005269 元**、阶段剩余
2.994731 元。regression live 索引为 49 docs / 5066 chunks，按 batch=5 逐文档建库约
需 1014+ 次 embedding 请求，超过剩余 565 次；b0+badcase+regression+holdout 全量更会
超。T112 放行前必须缩小 live 索引语料、调整 batch（注意 settlement cap）或由主人
重签 GO/请求上限；阶段金额剩余不是当前唯一约束。
