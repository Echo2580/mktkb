# T109 证据 03：实跑与对照（b0 / badcase / regression）

命令口径（cwd=仓库根，`$env:PYTHONPATH="backend/src"`，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`）：

```text
python -B -m mktkb.evaluation.cli run  --suite <suite> --mode local --out backend\.pytest-tmp\T109\eval\<label>
python -B -m mktkb.evaluation.cli gate --run backend\.pytest-tmp\T109\eval\<label>
```

对照脚本（临时，不入库）：`backend/.pytest-tmp/T109/{compare_runs,strict_compare,trace_evidence}.py`。
`compare_runs` 逐例比 `(status, outcome.kind, 每个 (check_id,status), error.code)`；
`strict_compare` 追加「去掉 volatile 字段后的**整行逐字段相等** + 键顺序 + manifest/summary」。

## A. b0 / badcase（对 P0 冻结基线 `var/eval/runs/p0-b0`、`p0-badcase`）

| suite | 本轮 run_id | 状态 | gate | 对 P0 逐例 |
| --- | --- | --- | --- | --- |
| b0 | `b0-local-20261108T151905251584Z-ed5fe092` | pass 29 / fail 3 / skipped 8 | exit 3，hard `[]` | **case_diffs=0/40** |
| badcase | `badcase-local-20261108T151909474037Z-8990c5bf` | pass 9 / fail 4 | exit 3，hard `[]` | **case_diffs=0/13** |

严格对照（b0、badcase 各一组，父提交 `ebfe956` 同代码跑出的行 vs 本轮）：

```text
rows=40 strict_diffs=[] (n=0)      order_diffs=[] (n=0)      ← b0
rows=13 strict_diffs=[] (n=0)      order_diffs=[] (n=0)      ← badcase
manifest changed keys (excluding run_id/time/paths): []
manifest added keys: {'multi_turn_case_count': 0, 'multi_turn_turns_executed': 0}
summary status_counts: {'fail': 3, 'pass': 29, 'skipped_requires_ocr': 8}  ← 前后一致
metric diffs: ['p95_latency_ms']  ← 仅计时噪声
```

- 键顺序：既有键相对顺序不变，唯一新增键是行尾 `turn_traces`（`order_diffs=[]`）。
- 对 P0 冻结基线另有 Q31 / N06 / N10 / N12 / N13 的自由文本差异（如 UNKNOWN_STORE 文案
  加了「请核对门店名称后重新查询。」），**父提交同代码也如此** → 属 T106 文案统一遗留，非本包；
  逐例签名 `case_diffs=0` 不受影响。
- gate 的 unknown 集合（`min_sample_missing` + 各 `thresholds_unapproved`）与 P0/父提交一致，无新 hard。

## B. regression：父提交 `ebfe956` vs 本轮（含 RG006 更新）

| 版本 | run_id | 状态 | gate |
| --- | --- | --- | --- |
| 父提交（单轮，RG006 旧行） | `regression-local-20261108T151309992264Z-3610698c` | pass 5 / fail 2 | exit 3，hard `[]` |
| 本轮（多轮，RG006 新行） | `regression-local-20261108T151824473835Z-812686c9` | pass 5 / fail 2 | exit 3，hard `[]` |

```text
cases=7 case_diffs=1
  DIFF RG006: base=('pass','clarification', value_hit=skipped, value_no_fabricated=skipped, …)
              cur =('pass','answer',        value_hit=pass,    value_no_fabricated=pass,    …)
gate base: exit=3 hard=[] unknown_ids=[min_sample_missing + 15×thresholds_unapproved]
gate cur : exit=3 hard=[] unknown_ids=[同上，完全一致]
```

- RG001/RG002/RG003/RG004/RG005/RG007：`status`/`kind`/每个 check/`error` **完全不变**
  （RG002 仍 `pass/clarification`、RG003 仍 `pass/answer` 21 天；RG005/RG007 仍 fail）。
- 唯一变化是 RG006：`pass/clarification` → `pass/answer`；`value_hit`/`value_no_fabricated`
  由 `skipped`（无 expected_values）变为 `pass`（含 40 且无编造数字），`kind_correct` 前后均 pass。
- `index_revision=49`、`corpus_manifest_sha256`、`pipeline_version`、`config_hash` 两侧一致；
  `dataset_sha256` 因 RG006 一行更新而变化（预期）。
- 基线口径注意：`tools/rag_experiment.py` 读 `docs/evidence/LOCAL-R1-20261101/S1-DEV/R2/subset-policy.json`
  （`.gitignore` 忽略）。干净 worktree 缺该文件会让语料装配变成 54 文档（boundary/scan 变解析失败），
  基线不可比。本轮把该文件按原字节复制进 worktree（只复制、不读内容），两侧 `index_revision=49` 才对齐；
  worktree 运行后 `git -C <wt> status --short` 仍为空，主工作树未受影响。

## C. 逐轮 trace（本轮 regression run，`trace_evidence.py` 实查 trace store）

```text
RG002: pass turns=2 claimed=True trace_id=5c83bbf6…
    turn 1: ok  mode=local record=ok previous=None      spans=12 (parse…commit)
    turn 2: ok  mode=local record=ok previous=4edbf7c6… spans=2  (parse, commit)
RG003: pass turns=2 claimed=True trace_id=175de9c3…
    turn 1: ok  previous=None      spans=12
    turn 2: ok  previous=632ba71b… spans=11
RG006: pass turns=2 claimed=True trace_id=29f17436…  kind=answer text=根据资料，滨江店的宣传海报的数量：40张。
    turn 1: ok  previous=None      spans=12
    turn 2: ok  previous=5ba0d7e8… spans=12
RG001/RG004/RG005/RG007: turns=1 claimed=False，单 trace，行为与父提交一致
```

## D. replay（实跑：本轮 regression run → replay）

```text
python -B -m mktkb.evaluation.cli run --suite regression --mode replay \
  --from-run backend\.pytest-tmp\T109\eval\regression-current \
  --out backend\.pytest-tmp\T109\eval\regression-replay
run_id=regression-replay-20261108T154009097819Z-aaf848ba  gate exit=3 hard=[]
compare_runs(regression-current, regression-replay): cases=7 case_diffs=0
```

逐轮 replay 实查（`trace_evidence.py`）：

```text
RG002: pass turns=2 → turn1 mode=replay replayed=True previous=4edbf7c6… spans=0
                            turn2 mode=replay replayed=True previous=5c83bbf6… spans=0
RG003: pass turns=2 → 两条 replay trace，分别 previous=632ba71b… / 175de9c3…
RG006: pass turns=2 → 两条 replay trace，status=answer「…40张。」
RG001/RG004/RG005/RG007: turns=1，单条 replay trace，previous=对应 local trace
```

即：3 条多轮 case 各有 2 条 replay trace（不是只跑首轮），每条链到**源轮** trace，spans 为空
（replay 口径不变）；重评分与 local 逐例一致（`case_diffs=0`）。

## E. RG006 before / after（仅该行；before 值取自父提交字节）

| 字段 | before（父提交） | after（本轮） |
| --- | --- | --- |
| `expected_kind` | `clarification` | `answer` |
| `expected_values` | `[]` | `["40"]` |
| `forbidden_values` | `["店内外侧","40 张","QF01","滨江店"]` | `["店内外侧","QF01"]` |
| `reference_answer` | 「local 单轮等价于无上文（turns 被忽略）：应澄清要问位置、数量、规格还是价格…」 | 「多轮口径（PM 裁决）：上文问「滨江店的宣传海报的数量」后，「那个海报呢」只答该字段——40 张；不得倾倒位置（店内外侧）、标识（QF01）等未问字段。」 |
| `notes` | 「T105/ERR-06：多轮指代题；local 单轮（turns 被忽略）等价无上文…多轮完整复现依赖 T109…」 | 「…turns 两轮真实逐轮执行…末轮只答数量 40 张。expected_kind 由 clarification 改为 answer、expected_values 含 40；未问字段禁止值保留…「40 张」由禁止值改为期望值（不能自相矛盾）、「滨江店」是本轮被问主体…故移出 forbidden，非放宽。」 |
| `expected_sources` / `relevant_units` | `[]` | `[]`（PM 只允许改上述 5 个字段） |

语义核对：`forbidden_values` 里**未问字段值全部保留**（位置=店内外侧、标识=QF01）；
`40 张`从禁止值改为期望值（两者不能并存）；`滨江店`是 turn1 明问的主体、末轮答案的继承对象，
不是「未问字段」，故移出 forbidden——移除范围仅这两项，且都不放宽任何未问字段。
