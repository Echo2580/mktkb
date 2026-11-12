# T207 SAFE-DIAG 开发交付

主人，本包已完成开发自测，**待全新独立验收，尚未经理接收或提交**。最终定向回归 248 passed，网络闸门外部尝试 0，公开57轮默认评分逐值相同，16个保护文件 hash 一致。真实H2质量及四类硬失败分类均未验证，不能据此宣布T207/P2通过。

## 范围与实现

- 基线 HEAD：`09ddc87520576958ff4c19be16f245f8197fdfe5`。未恢复拒收H2DIAG patch，未读取真实H2题号、题干、参考答案、逐题trace、key或凭据；保护manifest只做字节hash。全部新测试为合成或公开资料。
- 新 `p2_diagnostics.py` 仅含固定kind/check/error/model-reason/source/五分层/拒答四格/四类硬失败证据计数；每层 exact keys、固定字符串、严格非负int（拒bool/float），有上限和计数等式，不接受诊断数组或自由字符串。
- runner生成侧及写盘侧均验证整卡：顶层、分层、hard-failure计数与每种block的固定code/severity/detail模板、exact evidence schema。未登记外部错误码或异常类名只记unknown/固定holdout_case_unscorable。原递归明细禁令与≥2字题面/多轮/参考答案针扫描保留，diagnostics无整树豁免。异常原payload直接拒绝，返回全error固定阻断卡；不清洗后冒称原payload安全。
- 补实测复现的旧全卡缺口：`blocks.evidence.missing` 会原样带出任意ASCII doc_code；现只输出missing_count与mapped计数，不变更映射判分规则。run_id与ledger、config_hash与binding逐值绑定；hash仅64小写hex/null。run_id为受信任运行关联元数据（非空≤120字符、无换行），不允许使用题目/文档内容作运行ID。
- `planned=scored+errors+not_executed`；五分层逐项相加等于总计。正常末轮矩阵总数=`observed+unknown_kind`；unknown actual kind单列且不算正常observed。多轮任一错误、未完成、未开始及结构性评分error都不进矩阵。source只统计source_hit的pass/fail及mapping_blocked，skipped不算matched。
- 拒答四格使用`should_refuse`与实际no_answer/not_found/refusal，独立于expected_kind；tp/fp/tn/fn/errors/not_executed/unknown之和等于planned。结构error、未开始、unknown不进TN。precision=tp/(tp+fp)、recall=tp/(tp+fn)、false-refusal=fp/(fp+tn)，零分母为null。
- 四类safety/cross_user/cross_entity/stale_source目前恒`checked=0, unknown=planned, violations=0`，classification_status=unverified，owner=sealed_reviewer；结构性违规另计，不猜四类。正常卡明确holdout_hard_failure_unverified阻断且release_ready=false。后续受控分类接口与证据归属已在dataset契约§12定义，接口未实现。

## 模型失败原因接线

经理追加授权的最小诊断接线：`ModelError`对已登记的完整静态内部消息精确映射为固定reason（无strip/前缀/ASCII正则）；未知消息、带末尾换行均unknown。`_model_failure_result`增加固定model_failure Span，reason经既有Span.attributes_json→ProductTurn内存字段→H2内存评分行→聚合。ProductTurn.as_dict未新增公开字段，HTTP用户文案、error_code、retryable、校验规则、自动重试0、停止及计费未改。

reason描述拒绝点，不是已修复的产品根因或硬失败分类。其中json_parse对应provider既有“JSON对象解析”拒绝路径，旧消息也用于合法JSON但非对象的输入，因此本包不能再将该桶细分为纯语法错误与非对象错误；response_schema为其它已登记响应结构拒绝。真实adapter invalid_json链路验证json_parse=1；记录事实/字段来源/实体与未知消息的合成测试验证固定映射及原错误行为。

## 实际验证

| 项目 | 实际结果与证据 |
|---|---|
| 修复前反例 | `evidence/red.txt`：6 failed/1 passed（无diagnostics、未知树未拒绝；嵌套reference_answer已被原递归拒绝）。`baseline_probe.py`重新装载09ddc87源码，只以合成ASCII来源复现缺归因与missing泄漏，结果见baseline-probe.json。 |
| 最终定向回归 | `evidence/regression-delivery.txt`：248 passed，55.16秒，1项既有Starlette/httpx弃用警告，0 skip/xfail。覆盖SAFE-DIAG、H2 scorecard/H2MAP、runner、score_run、scoring、产品Mock E2E、T104单元/HTTP错误回归。 |
| 真runner正常合成30题 | scored30/error0/not_executed0/observed30；期望answer→实际answer25，期望refusal→实际answer5；原23pass/7fail不变；source matched23/unmatched2（5个负例source_hit skipped）。拒答TP0/FP0/TN25/FN5；precision null/recall0/false-refusal0。这是夹具统计，不是真实质量。 |
| 真runner部分执行 | scored21/error1/not_executed8/observed21；MODEL_OUTPUT_INVALID=1、record_facts=1；停止码product_service_error，后8题未开始，不补跑。 |
| 真adapter JSON失败 | 合成公开问题→Mock provider invalid_json→原产品错误→Span→内存→聚合；MODEL_OUTPUT_INVALID=1、json_parse=1、observed0，chat1次，保留首错停。 |
| 其它边界 | 多轮中间error不入分母；unknown kind/check/error/reason不带入输入字符串；expected_kind与should_refuse不一致仍按should_refuse统计四格；结构error不进正常矩阵或TN。每层毒化覆盖ASCII题干片段/文档内容、未知键、嵌套reference_answer、末尾换行、数组、长串、bool/float/负数/过大数、计数等式、全卡block/evidence/分层/元数据。 |
| 网络 | `network-guard.json`：67个带闸门测试，external_attempts=0；46个Windows asyncio回环尝试单列，非真实外部请求。 |
| 公开/P1默认差分 | `default-differential.json`：R1 52轮＋R2 2轮＋R4 3轮，case_score全字段、scorecard、默认归一化及归档评分逐值一致；P1 scorers.py/runner.py字节相同。只回放公开产物。 |
| 保护文件 | `protected-hashes.json`：16个保护文件hash一致；固定ledger/budget/GO分别仍为16484058…/79b21700…/3ed427f4…，完整hash在JSON。固定三文件基线来自交接，其余来自09ddc87。无账本、预算、GO、冻结数据、场景或H2MAP规则变动。 |
| 空白 | `git -c core.whitespace=cr-at-eol diff --check` exit0；沿用仓库受跟踪CRLF，不修改全局Git配置。 |

`synthetic-summary.json`只从最终pytest独占TEMP中的三份**合成**卡重新严格校验后提取固定计数与派生比率，未复制逐题数据。提取器、公开差分、保护hash、网络计数插件均在evidence目录，可复跑。沙箱内ASGI/socketpair挂起的已知环境限制以必要pytest命令级require_escalated解决，没有skip/改断言掩盖；一次未正确排除新E2E的沙箱筛选运行被自行中断，未计为通过。

复跑最终定向回归：项目`.venv/Scripts/python.exe -B -m pytest`，`-q -p no:cacheprovider -p safe_diag_guard`；PYTHONPATH指向本evidence目录，TEMP/TMP及`--basetemp`指向visualizations下全新独占目录。测试路径为：

```text
backend/tests/evaluation/test_p2_safe_diagnostics.py
backend/tests/evaluation/test_p2_holdout_scorecard.py
backend/tests/evaluation/test_p2_holdout_source_map.py
backend/tests/evaluation/test_p2_runner.py
backend/tests/evaluation/test_p2_score_run.py
backend/tests/evaluation/test_p2_scoring.py
backend/tests/integration/test_p2_product_e2e.py
backend/tests/unit/test_p1_t104_error_classification.py
backend/tests/integration/test_p1_t104_error_classification_http.py
```

## 精确改动与旧测试调整

源码：新增`backend/src/mktkb/evaluation/p2_diagnostics.py`；修改`p2_runner.py`、`p2_score_run.py`、`product_adapter.py`；经理追加授权修改`providers/types.py`与`conversations/service.py`（仅4行Span标注）。测试：新增`test_p2_safe_diagnostics.py`；修改`test_p2_holdout_scorecard.py`。文档：两份P2 dataset/live-binding契约及`T207/PM/T207-runbook.md`对应说明。报告/证据只写本T207-SAFE-DIAG目录。

旧测试有4处必要语义调整，未删断言/skip：任意exception.code原样导出的期望改固定holdout_case_unscorable；missing字符串列表改missing_count；原不完整“正常卡”改生成完整严格卡；纯假verdict计数测试移至原`_holdout_score_marks→_aggregate_marks`边界，保留其23pass/1fail/6error/硬失败等全部断言，不把无真实诊断证据的桩当完整writer输入。新完整runner测试覆盖实际诊断接线与分母。

现有`.claude/handoffs/_index.md`、经理manager.md及其它协调/面试/tmp等工作不属于本助手改动，未清理/覆盖/暂存。未commit/push/发布、未真实调用。

## 剩余问题与停止点

开发自测不是独立验收。请经理派全新上下文验收，先复跑严格全树与ASCII反例、分母/拒答四格、真runner及reason链路、公开差分和固定hash；接收后才决定提交。本助手交付后停止写入。

四维受控分类、分场景/产品修复、真实H2复测均未在本包执行；旧hard_failures=0不证明无硬失败，真实H2仍未通过质量门，T207/P2未获完整验收。
