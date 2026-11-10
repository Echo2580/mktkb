# T103 独立验收证据 03：evaluation local run / gate 与 RG004 诚实性

- 命令（仓库根，`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`、`PYTHONPATH=backend/src`）：
  `python -B -m mktkb.evaluation.cli run --suite <suite> --mode local --out %TEMP%\t103-verify\<suite>`，随后 `gate --run <同一路径>`。
- 未写仓库 `var/`；`mode=local` 由 runner 强制 `provider_mode="offline"`（`backend/src/mktkb/evaluation/runner.py:314-318`），零真实模型/embedding/rerank/OCR。

## A. b0 / badcase（当前 vs P0 基线）

```text
b0      run_id=b0-local-20261105T184502843716Z-58fd8eef
        status={'pass':29,'fail':3,'skipped_requires_ocr':8}；fails={Q25,Q26,Q31}；skipped={Q33..Q40}
        gate exit=3, hard_failures=[], trace_integrity=pass
badcase run_id=badcase-local-20261105T184508058177Z-4c79f4ea
        status={'pass':9,'fail':4}；fails={N05,N06,N09,N11}
        gate exit=3, hard_failures=[], trace_integrity=pass
```

逐例投影 `(status, outcome.kind, outcome.reason, failed check ids, path)` 对照只读 P0 基线（`var/eval/runs/p0-b0`、`p0-badcase`）：

```text
b0      ids_equal=True  case_diffs=0
badcase ids_equal=True  case_diffs=0
```

- 与 P0 基线、与开发 report 的“0 差异”一致：**无新增 hard failure，无 case 级变化**。b0/badcase 文本中无「符合条件的记录过多」「该历史消息未保存候选明细」。

## B. regression（当前）

```text
run_id=regression-local-20261105T184533849425Z-578680d8
status={'pass':4,'fail':3}；gate exit=1；hard_failures=['security_leak']；trace_integrity=pass
```

| case | status | kind | 失败 checks | 文本（截断） |
| --- | --- | --- | --- | --- |
| RG001 | pass | answer | — | 自 2022年7月1日起施行…《关于商品和服务实行明码标价的规定》…《禁止价格欺诈行为的规定》同时废止。 |
| RG002 | pass | clarification | — | 资料中没有收录“城西区”这个门店/区域，请补充准确的门店名称后再查询。 |
| RG003 | pass | answer | — | 根据资料，档期物料须提前 21 天提报。 |
| RG004 | pass | no_answer | — | 资料“物料领用通知”未收录，未使用其它资料替代。 |
| RG005 | fail | answer | kind_correct, refusal_expected | 根据资料，启沣饮品（苏城）有限公司 市场部｜启市字〔2026〕41号 |
| RG006 | fail | answer | value_forbidden, kind_correct | 根据资料，滨江店的宣传海报（标识：QF01）位于店内外侧，数量 40 张。 |
| RG007 | fail | answer | kind_correct, refusal_expected | 根据资料，第一条 新品指… |

- RG001–RG003 PASS；RG005–RG007 仍 RED，失败 check 集合与 T102 收口记录（`verify/T102/02-eval-runs.md:45-51`）逐条相同。
- gate 只保留既有 `security_leak`（RG006），无新增 hard failure 名称；`citation_required`/`trace_integrity` 均 pass。

## C. RG004 新口径不是“本应 answer 被收口为 refuse”

- trace：`path=rag`、`outcome_kind=no_answer`、`reason=DOCUMENT_NOT_FOUND`、`latency_ms=13`、`retrieved=[]`、无模型 span；解析 span `mode=document, terms=5`。
- 本地语料 `corpus/enterprise-20261101` 实际装配 49 份（E/L/P/V/W/X），扫描件 C01–C08 因 `subset_group:scan` 全部 skipped；对已装配单元检索：
  `物料领用通知` 0 命中、`登记表` 0、`领取` 0、`先填写` 0；`填写` 仅 2 条无关（W02 报损单、W05 销售记录），`物料领用` 仅 P06「原《物料领用规范（2023 版）》同时废止」。
- 结论：本地离线可达范围内不存在可回答「物料领用通知图片要求先填写什么」的正文；`no_answer` 是诚实拒答，不是把本可 answer 的结果收口为 refuse。RG004 的 `should_refuse=true` 与 local 实际 `no_answer`（`refused=true`）一致。
- `regression.jsonl` 逐 case 对比父提交：**仅 RG004 一行变化**；`forbidden_values` 原样保留 `["该历史消息未保存候选明细"]`；其余 6 行字节级不变。

结论：**PASS**。
