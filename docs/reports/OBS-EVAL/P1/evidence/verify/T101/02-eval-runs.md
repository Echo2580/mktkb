# T101 独立复跑证据 02：evaluation local run / gate

- 环境同证据 01；`PYTHONPATH=backend/src`；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；全部 offline，无真实 provider 调用。
- 命令：`python -B -m mktkb.evaluation.cli run --suite <suite> --mode local --out <%TEMP%路径>`，随后 `gate --run <同一路径>`。
- P0 基线读取：`var/eval/runs/p0-b0`、`var/eval/runs/p0-badcase`（只读 `cases.jsonl`/`gate.json`）。

## A. b0 / badcase（当前）

```text
b0 run_id=b0-local-20261105T161508356004Z-16a29909
b0: pass 29 / fail 3 / skipped_requires_ocr 8；失败 {Q25,Q26,Q31}
b0 gate: exit 3, scored=32/32, hard_failures=[]

badcase run_id=badcase-local-20261105T161513252321Z-42492cd6
badcase: pass 9 / fail 4；失败 {N05,N06,N09,N11}
badcase gate: exit 3, scored=13/13, hard_failures=[]
```

与 P0 基线逐例比较（脚本只读 `cases.jsonl`）：

```text
b0 ids_equal=true, case_diffs=[], old_fail=[Q25,Q26,Q31], new_fail=[Q25,Q26,Q31]
badcase ids_equal=true, case_diffs=[], old_fail=[N05,N06,N09,N11], new_fail=[N05,N06,N09,N11]
```

`case_diffs` 为空表示逐例 `(status, outcome.kind)` 相同、且失败 checks 相同；两套 gate 的 `hard_failures` 均为 `[]`。

## B. regression（当前）

```text
run_id=regression-local-20261105T161620162223Z-0dbcbb6b
RG001 pass / answer
value_hit: expected 3, missing []
value_forbidden: checked 1, pass
value_no_fabricated: checked 3, pass
source_hit: expected 1, matched 1
kind_correct: expected answer, actual answer
citations: L02 paragraph:38 / paragraph:39（同一整段文本）
text: 根据资料，第二十七条 本规定自 2022年7月1日起施行。2000年10月31日…第8号发布的《关于商品和服务实行明码标价的规定》、2001年11月7日…第15号发布的《禁止价格欺诈行为的规定》同时废止。

RG002 fail: value_hit, source_hit, kind_correct
RG003 fail: value_hit, source_hit, kind_correct, pagination_total, pagination_returned, pagination_has_more
RG004 fail: kind_correct, refusal_unexpected
RG005 fail: kind_correct, refusal_expected
RG006 fail: value_forbidden, kind_correct
RG007 fail: kind_correct, refusal_expected

gate: exit 1, scored=7/None, hard_failures=['security_leak', 'pagination_contract']
```

## C. 修复前 regression（独立复跑，非开发方报告）

用 `git archive a7282b3^` 导出旧源码到 `%TEMP%\t101-base-src`，以旧源码 `PYTHONPATH`+旧 regression 数据集运行同一 CLI（corpus 未变）：

```text
run_id=regression-local-20261105T162041725476Z-393e87f5
RG001 fail / clarification；fails = value_hit, value_no_fabricated, source_hit, kind_correct
RG002 fail: value_hit, source_hit, kind_correct
RG003 fail: value_hit, source_hit, kind_correct, pagination_total, pagination_returned, pagination_has_more
RG004 fail: kind_correct, refusal_unexpected
RG005 fail: kind_correct, refusal_expected
RG006 fail: value_forbidden, kind_correct
RG007 fail: kind_correct, refusal_expected
gate: exit 1, scored=7/None, hard_failures=['security_leak', 'pagination_contract']
```

结论：RG001 确为 `fail/clarification → pass/answer`；RG002–RG007 失败 checks 与修复前及证据 01 逐条一致；regression 门禁硬失败集合未变。
