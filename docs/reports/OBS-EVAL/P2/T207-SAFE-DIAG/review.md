# T207 SAFE-DIAG 独立验收

主人，结论：**FAIL，退回修复，不接收、不提交。** 固定词表、合成计数及真实离线原因链已通过，但写盘边界仍有4个独立反例。真实H2质量与四类硬失败均未验证。

基线：09ddc87520576958ff4c19be16f245f8197fdfe5；日期：2026-11-11。依据本包verify/dev提示、经理补充与report。本次重新执行，未用开发248passed代替验收。仅写本review及evidence/independent/；未改源码/开发测试/契约/旧报告/账本预算GO，未commit、未真实调用、未读真实H2题号/题面/答案/逐题trace/密钥。

## 四个阻断反例

均从公开合成单题真实生成合法卡，再只改聚合字段，经真实 `_holdout_scorecard_artifact` 写盘前最后审计。规范测试保留为失败，未改成“预期漏洞成功”。

1. **unknown→TN（高）**：原卡planned1/scored1/observed0/unknown_kind1，矩阵kind_answer→kind_unknown1。只将refusal_confusion的unknown1移到tn1，保持sum1，实际仍接受，未全error。`p2_diagnostics.py:196`只联结拒答sum/errors/not_executed，遗漏与正常观察分母的联结。证据：`counterexample-unknown-to-tn.json`。
2. **unknown→pass（高）**：同类卡passed0/failed1改为passed1/failed0，同步by_stratum及below-threshold固定模板/evidence，诊断仍observed0/unknown_kind1，实际接受passed1。`p2_diagnostics.py:77`联结executed=scored，但未禁止未知观察进入pass。证据：`counterexample-unknown-to-pass.json`。total1的threshold仍false，不是发布通过反例。
3. **删除未验证block（中，违反本包标准）**：删除正常卡的holdout_hard_failure_unverified，实际仍接受errors0。checked0/unknown=planned、classification_status=unverified、release_ready=false仍在，但要求保留的显式阻断丢失。测试：`test_review_unverified_block_must_remain`。
4. **删除标量必需block（中）**：thresholds_approved=false，删holdout_threshold_unapproved仍被接受。代表性检查，未扩大穷举。证据：`counterexample-required-block.json`。与第3项同根因：validator只校验已有block，不校验必需block存在。全error审计失败兜底可使用其稳定审计失败block；反例针对正常卡被删block后仍作为正常卡接受。

以上证据均在evidence/independent/，JSON包含input与实际writer_output。此处4反例只证明计数/阻断证据契约不完整，不声称release_ready变为true。

## 本次实际执行

| 检查 | 结果 | 证据/界限 |
|---|---|---|
| 项目9文件必要回归 | PASS，248项 | 本次合并首轮265passed/6failed，所有失败均为自有探针；项目248项无失败。regression.txt，34.39秒，1项既有弃用警告。 |
| 最终自有探针 | **4failed/21passed** | probes-final.txt，25项，5.44秒，0skip/xfail；失败只对应上述4反例。 |
| 独立生成/整树/整卡毒化 | PASS | ASCII题干片段/文档内容、未知kind/check/error、末尾换行、每层未知键、嵌套reference_answer、数组/长串、bool/float/负数/过大整数/坏等式；含blocks列表内dict、code/detail/evidence、top、分层及未绑定run_id/config_hash。生成只unknown，writer全error固定原因、不出原文。无整子树豁免。 |
| 旧missing doc_code漏串 | PASS | 自造REVIEW_DOCUMENT_CONTENT期望来源，只出missing_count1；映射阻断不进observed。 |
| 拒答/错误观察分母生成 | PASS | expected_kind故意与should_refuse不一致，TP/FP/TN/FN各1；结构error/未开始/unknown分别单列，observed4。中间轮MODEL_TIMEOUT不进observed/TN。 |
| 真runner正常30题 | PASS | 自有脚本产品观测+真run_p2/adapter/灌库/建会话/产物：30pass，observed30，五分层10/5/5/5/5，TP5/TN25，source matched25；是夹具统计。runner-normal.json。 |
| 真runner部分执行 | PASS | 21评分=11pass+10fail，第22题MODEL_OUTPUT_INVALID/record_facts首错停，后8题未开始；observed21，TN16/FN5/errors1/not_executed8。runner-partial.json。 |
| 真Span→ProductTurn内存→aggregate | PASS | JSON坏响应得json_parse；公开D01裸精确位置值通过精确值检查后触发真实记录事实拒绝，得record_facts；MockTransport注入任意ASCII异常message+换行得unknown。三项均MODEL_OUTPUT_INVALID/retryable=true/chat1次/首错停，trace关闭后清理，产物无任意message，as_dict不公开reason。reason-*.json。 |
| 四类硬失败 | 正常生成PASS；writer保留FAIL | 正常/部分卡均checked0/unknown30/violations0、unverified/sealed_reviewer、未验证block与release_ready=false。结构违规未猜四类归属；第3反例证明writer仍可删除block。恒0不证明安全。 |
| 公开/P1/API/停止/费用回归 | PASS（离线） | 指定回归含公开run不写H2卡、产品Mock E2E、T104字段/错误码/文案/幂等、停止、money split与settle断言；服务源码只增固定span，原返回表达式不变。真实计费NOT-RUN。 |
| 公开57默认差分 | PASS | R1=52/R2=2/R4=3，case_score全字段、scorecard、归档评分与normalization逐值等于基线；P1 scorers.py/runner.py字节相同。default-differential.json。 |
| 保护hash/网络/空白 | PASS | 前后16保护文件一致（含固定ledger/budget/GO）；最终25探针guard外网0、Windows asyncio回环5次单列；git -c core.whitespace=cr-at-eol diff --check exit0。首轮同样启用guard且无闸门失败，其计数文件被末次输出覆盖，不虚报首轮guard数量。 |
| 真实H2/真实模型/受控四类分类/发布 | **NOT-RUN** | 零真实，不等于T207/P2质量通过。 |

summary.json仅提取自有聚合卡：normal precision/recall1、false-refusal0；partial precision=null/recall0/false-refusal0，零分母null，未新增阈值。

首轮6失败中3项为独立写盘反例，另3项是自有夹具错误：产品不支持继续的refusal结局、重复合成多轮题面索引覆盖、记录事实探针先触发精确值拒绝。只改自有探针，分别使用既有not_found、选择无冲突的11个通过样本、公开D01裸精确值；末次又补列表内block/evidence毒化和合法整数坏等式。最终只有4项真实边界红灯。保留首轮日志，不将夹具错误算产品缺陷，不重复全链。

## 旧测试调整判断与执行边界

4处调整均合理保留：任意exception.code改固定holdout_case_unscorable仍保total30/passed0/errors30及不泄漏；missing列表改计数仍保映射失败passed0；不完整卡换严格完整卡仍保多轮/短题面needle断言；假verdict测试移至 `_holdout_score_marks→_aggregate_marks` 仍保23pass/1fail/6error/executed24/hard_failure1、blocks、身份与不泄漏断言，只证明内部汇总语义。本次真runner和writer反例补查新边界，当前须修4反例后重验。

项目回归9文件：test_p2_safe_diagnostics.py、test_p2_holdout_scorecard.py、test_p2_holdout_source_map.py、test_p2_runner.py、test_p2_score_run.py、test_p2_scoring.py、test_p2_product_e2e.py、test_p1_t104_error_classification.py、test_p1_t104_error_classification_http.py。

环境为项目.venv的python -B，pytest -q -p no:cacheprovider -p independent_guard；PYTHONPATH指向backend/src及independent；TEMP/TMP与--basetemp只用本会话visualizations下safe-diag-review独占全新子目录。必要离线ASGI命令级require_escalated只解决已确认socketpair沙箱限制，无skip/xfail。最终自有测试路径为evidence/independent/test_independent_safe_diag.py，basetemp为probes-final-02。

default_diff.py/check_hashes.py/independent_guard.py为审阅后复制到独立目录的工具源码副本，本次重执行，输出仅写independent；所有反例、runner/reason探针为重新构造。保护manifest/source-map/ingest-plan仅hash，不解码；没有全仓测试或真实H2逐题读取。

**停止：FAIL退回。独立验收助手完成落盘后停止写入；下一步只修已批准计数联结与必需block契约，不授权产品行为/真实调用/预算GO/冻结数据变更。**
