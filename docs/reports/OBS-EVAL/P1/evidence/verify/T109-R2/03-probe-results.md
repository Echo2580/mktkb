> 生成命令：`.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T109-R2\02-probe.py`（2026-11-09 01:22, 零真实 provider 调用）

# T109 R2 独立探针结果

零真实模型/embedding/rerank/OCR 调用；合成语料仅 E11；父提交 run 为 ebfe956 产物。

## A. B1 replay fail-closed（源=父提交单轮 run，行无 turn_traces）

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 源 run 为父提交 ebfe956 的 local 产物，RG002/RG003/RG006 无 turn_traces | PASS | run=regression-local-20261108T155006434105Z-7638e33c |
| 三行 status=fail / multi_turn_source_missing / turn_traces=[] / turns_executed=0 | PASS | {"RG002": {"status": "fail", "code": "multi_turn_source_missing", "turns": 0, "traces": 0, "claimed": true}, "RG003": {"status": "fail", "code": "multi_turn_source_missing", "turns": 0, "traces": 0, "claimed": true}, "RG006": {"status": "fail", "code": "multi_turn_source_missing", "turns": 0, "traces": 0, "claimed": true}} |
| 无 status=pass 或单条 turn_trace 冒充多轮 | PASS | 3 rows |
| fail-closed 行仅保留 case 级 provenance trace（不入 turn_traces，spans=0） | PASS | RG002:spans=0:turn_traces=0;RG003:spans=0:turn_traces=0;RG006:spans=0:turn_traces=0 |
| 声明层不把 fail-closed 多轮当已验证（verified=False/轮数 0/error ids 3） | PASS | verified=False turns=0 |
| fail-closed replay 不 crash：gate hard=[]（exit 3） | PASS | hard=[] |
| 同源单轮行沿用父口径（1 轮/1 条 replay/status 不变） | PASS | RG001/RG004/RG005/RG007 |

## B. B1 源多轮但轮数不足（RG002 turn_traces 截为 1 条）

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| RG002 fail / multi_turn_source_incomplete / 轮数 0 / 无 turn_trace | PASS | fail/multi_turn_source_incomplete/turns=0/traces=0 |
| 同源其余多轮行仍逐轮 replay（RG003/RG006 各 2 条） | PASS | RG003/RG006 |

## C. 合法多轮源 replay（当前 local -> 当前 replay）+ R3 逐轮题面

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| RG002/RG003/RG006 replay 逐轮 2 条、链源轮、无源 trace 复用、仅末轮 outcome | PASS | 3 cases x 2 turns |
| R3：replay 每轮 question_hash = 该轮题面 = local 对应轮（两轮不同） | PASS | sha256(turn.text) |
| replay vs local 7 cases 实质字段一致（去 volatile） | PASS | diffs={} |

## D. R1：轮级 error 明细（合成多轮，E11）

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 中间轮 kind=error/service_error -> fail + error{answer_error, turn 1/2} + 实际 2 轮 | PASS | error={'code': 'answer_error', 'message': 'turn 1/2: 答案结局 kind=error（要求无 error）'}; turns=2; scored=1 |
| 中间轮 Trace 不可读 -> fail + error{trace_missing, turn 1/2} + 2 轮 | PASS | error={'code': 'trace_missing', 'message': 'turn 1/2: Trace 不可读（trace store 无该轮记录）'} |
| 中间轮 Trace status=error -> fail + error{trace_error, turn 1/2} | PASS | error={'code': 'trace_error', 'message': 'turn 1/2: Trace status=error（要求 Trace 完整）'} |
| 末轮 kind=error -> fail + error{answer_error, turn 2/2} | PASS | error={'code': 'answer_error', 'message': 'turn 2/2: 答案结局 kind=error（要求无 error）'} |

## E. R2：首轮前失败的多轮行（turns_executed 非默认 1）

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| malformed 多轮（空题/非 user 轮）-> turns_executed=0、turn_traces=[] | PASS | blank=turn_question_missing/0; role=turn_role_unsupported/0 |
| 非 mapping 轮在 runner 层仍 fail closed（turn_invalid） | PASS | code=turn_invalid |
| gold 解析失败的多轮行 -> error(gold_unresolved)/turns_executed=0/turn_traces=[] | PASS | error/gold_unresolved/turns=0 |
| 单轮 gold error 保持父口径（turns_executed=1、1 条 error trace） | PASS | turns=1 traces=1 |

## F. 上轮 PASS 抽查（local 多轮 + 单轮不变 + RG006）

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| A 顺序执行/同一 conversation+user/末轮只答 40/不含未问字段 | PASS | conv=regression-local-20261108T172211351691Z-399bc7c8:A; statuses=['ok', 'ok'] |
| A 只对末轮 score_case 一次（中间轮不判分） | PASS | scored=1 |
| B 对照：无上文单轮「那个海报呢」= clarification（状态继承成立） | PASS | kind=clarification |
| G 中间轮 checks 若判分会 fail，但 case 仍 pass（中间轮不参与通过） | PASS | pass; score once |
| b0 对父提交 strict 0（仅多 turn_traces）/ 对 P0 case_diffs=0 | PASS | strict=0; sig0=0; extra={('turn_traces',)}; gate=True |
| badcase 对父提交 strict 0（仅多 turn_traces）/ 对 P0 case_diffs=0 | PASS | strict=0; sig0=0; extra={('turn_traces',)}; gate=True |
| 单轮 b0 replay 对父提交 40 行实质一致 / 对 P0 replay 签名 0 / 1 轮 1 trace | PASS | vs_parent=0; vs_P0_sig=0 |
| regression case_diffs 仅 RG006；其余逐字段不变 | PASS | diffs=['RG006']; unexpected={} |
| RG002/RG003 多轮后仍 pass；RG005/RG007 fail 集不变 | PASS | RG002/3 pass; RG005/7 fail |
| RG006 末轮 answer 含 40、不含未问字段；fixture kind=answer/values 含 40/forbidden 保留 | PASS | text='根据资料，滨江店的宣传海报的数量：40张。'; forbidden=['店内外侧', 'QF01'] |
| gate 当前/父提交均 hard=[]（无新 hard） | PASS | hard=[] |

探针 FAIL 项：0
