> 生成命令：`.venv\Scripts\python.exe -B docs\reports\OBS-EVAL\P1\evidence\verify\T109\02-probe.py`（2026-11-09，零真实 provider 调用；合成语料仅 E11）。

# T109 独立探针结果

合成语料：corpus/enterprise-20261101/excel/E11（仅此一份）；零真实 provider 调用。

## A. regression local（当前 703b7e0 vs 父提交 ebfe956）

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| manifest 语料可比 (index_revision=49, corpus hash 相同) | PASS | revision=49; corpus=5f41b1b811a5 |
| 当前 manifest 多轮标记 3 cases / 6 turns | PASS | 3/6 |
| 父提交 manifest 无多轮字段（旧产物） | PASS | keys absent |
| 行集合 7 个且 key 顺序 = 父键 + turn_traces | PASS | turn_traces 尾插 |
| case_diffs 仅 RG006 | PASS | diffs=['RG006'] |
| 除 RG006 与多轮字段外，逐字段一致（去 volatile） | PASS | unexpected={} |
| RG002/RG003 多轮后仍 pass 且 outcome 不变 | PASS | RG002 clarification / RG003 answer |
| RG005/RG007 失败集不变（均 fail） | PASS | fail/fail |
| RG006 末轮 answer 含 40、不含未问字段 | PASS | text='根据资料，滨江店的宣传海报的数量：40张。' |
| RG006 fixture expected_kind=answer / expected_values 含 40 / 未问字段 forbidden 保留 | PASS | forbidden=['店内外侧', 'QF01'] |
| RG006 移除滨江店有 turn1 明问依据、未放宽未问字段 | PASS | 滨江店=turn1 被问主体 |

## B. b0 / badcase（对父提交严格行 + 对 P0 签名）

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| b0 行数 40、对父提交严格一致、对 P0 case_diffs=0 | PASS | strict=0; sig0=0 |
| b0 单轮字段 turns_executed=1 / claimed=False / 1 条 turn_trace | PASS | all rows |
| b0 gate hard=[]（当前与 P0） | PASS | hard=[] |
| badcase 行数 13、对父提交严格一致、对 P0 case_diffs=0 | PASS | strict=0; sig0=0 |
| badcase 单轮字段 turns_executed=1 / claimed=False / 1 条 turn_trace | PASS | all rows |
| badcase gate hard=[]（当前与 P0） | PASS | hard=[] |

## C. 多轮 local / replay trace 链

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| RG002/RG003/RG006 两轮 trace 存在、链接上一轮、trace_id=末轮 | PASS | 3 cases x 2 turns |
| local 每轮 trace question_hash 对应本轮问题 | PASS | sha256(text) |
| replay 逐轮 trace（2 条/多轮 case、链源轮、仅末轮 outcome） | PASS | 3 cases |
| replay vs local 7 cases 实质字段一致（去 volatile） | PASS | diffs={} |
| 单轮 b0 replay 对父提交 40 行实质一致、turns_executed=1/claimed=False | PASS | vs_parent={}; vs_P0_sig=[] |
| 旧源单轮 run 遇多轮 case：明确错误（handoff §3.5/§5） | FAIL | 实际静默单条 replay: {'RG002': {'source_has_turn_traces': False, 'replay_turns': 1, 'replay_claims_multi': True, 'replay_trace_count': 1, 'replay_error': None}, 'RG003': {'source_has_turn_traces': False, 'replay_turns': 1, 'replay_claims_multi': True, 'replay_trace_count': 1, 'replay_error': None}, 'RG006': {'source_has_turn_traces': False, 'replay_turns': 1, 'replay_claims_multi': True, 'replay_trace_count': 1, 'replay_error': None}} |

## D. 合成多轮用例（E11 单文档语料）

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| A 顺序执行/同一 conversation+user/末轮只答 40 | PASS | conv=regression-local-20261108T162754656788Z-882ff5d5:A; statuses=['ok', 'ok'] |
| A 只对末轮 score_case 一次（中间轮不判分） | PASS | scored=[('A', 'answer', '根据资料，滨江店的宣传海报的数量：40张。', True)] |
| B 对照：无上文单轮「那个海报呢」= clarification（证明 A 的答案来自状态继承） | PASS | kind=clarification |
| C/D 中间轮 kind=error/service_error -> case fail；末轮 checks 仍全通过 | PASS | status=fail, error=None（报告称有 turn n/N 明细，实际无） |
| E 中间轮异常 -> fail、error 含 turn 2/3、只执行到失败轮 | PASS | error={'code': 'execution_error', 'message': 'turn 2/3: RuntimeError: probe boom'} |
| F 末轮 checks fail -> case fail，轮 trace 均 ok | PASS | value_hit fail |
| G 中间轮 checks 若判分会 fail，但 case 仍 pass（中间轮不参与通过） | PASS | pass |
| H 末轮 error 结局 -> case fail | PASS | fail |
| I 中间轮 Trace 不可读 -> case fail（turn_traces[0]=error） | PASS | fail |

探针 FAIL 项：1
- 旧源单轮 run 遇多轮 case：明确错误（handoff §3.5/§5）

