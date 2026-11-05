# T102 独立验收证据 02：evaluation local run / gate 与基线对照

- 环境/分支/HEAD 同证据 01；`PYTHONPATH=backend/src`；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；全部 offline，0 真实调用。
- 命令：`python -B -m mktkb.evaluation.cli run --suite <suite> --mode local --out %TEMP%\t102-verify\<suite>`，随后 `gate --run <同一路径>`。未写仓库 `var/`。
- P0 基线只读：`var/eval/runs/p0-b0`、`var/eval/runs/p0-badcase`（`cases.jsonl` + `traces.sqlite3`）。

## A. b0 / badcase（当前 vs P0）

```text
b0  run_id=b0-local-20261105T174233788288Z-2417ace0
    status={'pass':29,'fail':3,'skipped_requires_ocr':8}; fails={Q25,Q26,Q31}; skipped={Q33..Q40}
    gate exit=3, hard_failures=[], gate_status.trace_integrity=pass
badcase run_id=badcase-local-20261105T174256652350Z-1e80ed14
    status={'pass':9,'fail':4}; fails={N05,N06,N09,N11}
    gate exit=3, hard_failures=[], gate_status.trace_integrity=pass
```

逐例对照（本人脚本，只读基线）：投影=`(status, outcome.kind, outcome.reason, failed check ids, path)`：

```text
b0      p0=40 current=40 ids_equal=True  case_diffs=0
badcase p0=13 current=13 ids_equal=True  case_diffs=0
skipped_requires_ocr ids identical: Q33,Q34,Q35,Q36,Q37,Q38,Q39,Q40
```

trace 对照（`traces` 表全部字段，剔除 `trace_id/request_id/http_request_id/run_id/created_at/latency_ms`；span 比 `name/status/error_code` 多重集）：

```text
b0      trace_field_diffs=0, spans p0=367 cur=367
badcase trace_field_diffs=0, spans p0=129 cur=129
```

→ 与 P0 基线、与开发证据 01/02 的 b0/badcase 前后对照一致：**PASS**（无新增 hard failure、无 case 级变化）。

## B. regression（当前）

```text
run_id=regression-local-20261105T174337218586Z-fdff5e1b
status={'pass':3,'fail':4}; gate exit=1; hard_failures=['security_leak']
gate_status: citation_required=pass, trace_integrity=pass, security_leak=fail, 其余 not_applicable
```

| case | status | kind | 失败 checks | 文本（截断） |
| --- | --- | --- | --- | --- |
| RG001 | pass | answer | — | 根据资料，第二十七条 本规定自 2022年7月1日起施行。…《关于商品和服务实行明码标价的规定》…《禁止价格欺诈行为的规定》同时废止。 |
| RG002 | pass | clarification | — | 资料中没有收录“城西区”这个门店/区域，请补充准确的门店名称后再查询。 |
| RG003 | pass | answer | — | 根据资料，档期物料须提前 21 天提报。 |
| RG004 | fail | no_answer | kind_correct, refusal_unexpected | 资料“物料领用通知”未收录，未使用其它资料替代。 |
| RG005 | fail | answer | kind_correct, refusal_expected | 根据资料，启沣饮品（苏城）有限公司 市场部｜启市字〔2026〕41号 |
| RG006 | fail | answer | value_forbidden, kind_correct | 根据资料，滨江店的宣传海报（标识：QF01）位于店内外侧，数量 40 张。 |
| RG007 | fail | answer | kind_correct, refusal_expected | 根据资料，第一条 新品指… |

关键 check 细节：

```text
RG001 value_hit pass(expected 3,missing []); value_forbidden pass(1); source_hit pass(1/1); kind_correct answer
RG002 value_forbidden pass(checked 2: 店内外侧,滨江店); source_forbidden pass(1); kind_correct clarification
RG003 value_hit pass(expected 1=[21 天]); value_forbidden pass(checked 2); source_hit pass(1/1); kind_correct answer
```

- RG002 文本不含 `城东店`/`B区1号货架`/`滨江店`/`店内外侧`；来源为空。
- RG003 文本含 `21 天`，不含 `卓刀河店`/`马克杯`。
- RG004–RG007 失败 check 集合与 T101 收口记录（verify/T101/02 §B）逐条相同，未被改弱或“顺手修好”。
- gate 允许收敛：`['security_leak','pagination_contract'] → ['security_leak']`；无新 hard failure 名称。

结论：**PASS**。
