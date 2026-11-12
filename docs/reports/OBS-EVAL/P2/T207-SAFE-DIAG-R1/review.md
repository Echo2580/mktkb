# T207 SAFE-DIAG R1 独立复验

主人，结论：**PASS（仅安全诊断返工范围），本轮未发现新阻断，可交经理决定接收；不提交。** 原4个拒收反例全部失败封闭；本次独立执行 **302 passed**。真实 H2 质量 **NOT-RUN**，四轴分类仍 **unverified**，本结论不表示 T207/P2 质量通过。

日期：2026-11-11。HEAD：`09ddc87520576958ff4c19be16f245f8197fdfe5`，验收对象为当前未提交工作区。已读原 dev/verify/report/review、R1 dev（含经理一行旧测试同步授权）、R1 report、R1 source.diff、最终源码及契约差分。本次新上下文执行，开发284passed未用作独立证据。只写本review及本轮 `evidence/independent/`；未改源码、项目测试、旧报告、冻结文件、预算/GO/账本；未commit，未真实调用，未读取真实H2题号/原文/答案/逐题trace或凭据。

## 关键拒收点复验

| 检查 | 本次结果 |
|---|---|
| unknown→TN | PASS。保持拒答总和的篡改经真实writer变为executed0/passed0/errors1，固定holdout_scorecard_leak，未验证block仍在。counterexample-unknown-to-tn.json。 |
| unknown→pass | PASS。同步全卡及分层passed/failed和below_threshold模板仍拒绝，输出全error。counterexample-unknown-to-pass.json。 |
| 删除unverified | PASS。正常卡删除后全error；新探针另查全error兜底卡删除后validator拒绝、writer重建保留unverified。 |
| 删除threshold_unapproved | PASS。正常卡删除后全error。counterexample-required-block.json。 |
| 跨层观察/拒答/通过关联 | PASS。总计和五分层scored=observed+unknown_kind；TP+FP+TN+FN=observed，unknown=unknown_kind；整卡/各分层passed不得超observed，分层planned/scored/errors+not_executed对齐卡片。合法四格按should_refuse，与expected_kind不一致仍各1；unknown、error、未开始不混TN或pass。 |
| 其他必需阻断与兜底 | PASS。新混合卡分别删除sample_missing/case_error/below_threshold/threshold_unapproved/unverified，均全error。混合卡附加合法兜底block并删除正常必需block仍拒绝，只有严格全error兜底可以使用固定失败block表达失败；兜底保留unverified/checked0/unknown=planned。 |

本轮新造 `test_r1_independent_boundaries.py` **18项**：5题混合状态（正常pass、unknown、服务error、未开始、正常fail）有效卡精确保留；保持全局总和但交换诊断分层、把pass移到unknown分层、unknown矩阵列调换、缺失scored观察证据、unknown→TN、伪装兜底均拒绝；另含五种必需block删除、兜底删除unverified及5种非bool should_refuse。生成拒绝坏should_refuse发生在计数变更前。项目定向链另覆盖scored无outcome的生成拒绝。

旧独立25项探针及3个工具经审阅后复制到本轮独立目录**重新执行**，字节相同校验见summary.json；它们是旧反例的新运行，不冒称新设计。新增18项由本独立助手构造。原独立证据未覆盖。

## 本次实际执行与证据

| 检查 | 结果与界限 |
|---|---|
| 必要定向链 | **302 passed，34.18秒，0 failed/skip/xfail**，1项既有Starlette/httpx弃用警告。项目9文件259项＋原独立探针25项＋本轮新探针18项，regression.txt。无失败，不再重复或扩大全仓。 |
| 真run_p2/adapter正常30 | PASS。30pass/0fail/0error，scored=observed30，五分层10/5/5/5/5，TP5/TN25，source matched25。runner-normal.json；为合成产品观测夹具，非真实质量。项目既有正常30夹具23pass/7fail及其原统计断言也通过。 |
| 真runner部分执行 | PASS。21评分=11pass+10fail，首个MODEL_OUTPUT_INVALID/record_facts后停，服务error1＋not_executed8，card.errors9，observed21、TN16/FN5。runner-partial.json。 |
| 真实既有reason链（离线） | PASS。JSON解析、记录事实拒绝、任意ASCII异常message分别经真实Span→ProductTurn内存→runner聚合为json_parse/record_facts/unknown。3次合成链各chat1次，MODEL_OUTPUT_INVALID/retryable=true/首错停，公开as_dict无新增reason、trace清理、自由message不出产物。reason-*.json。 |
| 旧schema与ASCII反泄漏 | PASS。旧全树/全卡毒化探针、项目安全诊断链：未知顶层及嵌套键、reference_answer、ASCII片段、末尾换行、数组/长串、bool/float/负数/大数/坏等式、block code/detail/evidence、未绑定身份；原payload被拒绝后固定全error，不清洗后声称安全。未知kind/check/error和missing doc_code只出固定unknown或计数，递归及needle审计保留。 |
| API/停止/费用/P1 | PASS（离线范围）。必要链含公开run不出H2卡、Mock产品E2E、T104错误码/文案/幂等、首错停、money split/settle；源码原因标注为additive，未改原产品返回表达式。真实服务/费用NOT-RUN。 |
| 公开57默认差分 | PASS。R1=52/R2=2/R4=3，case_score所有字段、scorecard、归档评分和默认normalization逐值等于基线；P1 scorer/runner字节相同。default-differential.json。 |
| 保护hash | PASS。protected-hashes-before.json与protected-hashes.json逐值相同，16文件均与固定交接或HEAD基线一致；封存manifest/source-map/ingest-plan仅字节hash，不解码。 |
| 网络guard | PASS。network-guard.json：110个带guard测试，external_attempts=0，pytest_exit_status=0；51个Windows asyncio回环尝试单列。公开差分脚本另安装拒绝socket连接的闸门。 |
| 空白检查 | PASS。`git -c core.whitespace=cr-at-eol diff --check` exit0。 |

三固定hash保持：ledger `1648405845fd5e19b593e610b92f8505fdfd78a9e57079648dc14673576785d7`；budget `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`；GO `3ed427f42ac2eeedff489505b94f730eadba1dc38f1b9adecf94d25750b02a7c`。

`summary.json`由summarize_r1.py重新校验本次normal/partial/mixed三个合成聚合卡及新输出后生成，仅包含聚合与固定状态；原三份counterexample JSON均证明writer现在全error，删除unverified第四例由pytest原断言及新增兜底探针证明，未虚构其原始JSON。

必要链精确为test_p2_safe_diagnostics.py、test_p2_holdout_scorecard.py、test_p2_holdout_source_map.py、test_p2_runner.py、test_p2_score_run.py、test_p2_scoring.py、integration/test_p2_product_e2e.py、unit/test_p1_t104_error_classification.py、integration/test_p1_t104_error_classification_http.py，加本目录两份独立test文件。项目`.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider -p independent_guard`；PYTHONPATH为backend/src及本独立目录，PYTHONDONTWRITEBYTECODE=1。TEMP/TMP与--basetemp使用当前visualizations独占safe-diag-r1-independent/regression-01。按授权仅此必要离线ASGI命令使用require_escalated解决已确认socketpair沙箱限制，未skip/xfail或削弱断言。

## 差异与剩余边界

R1源码范围符合授权：p2_diagnostics.py增加语义联结和必需block检查，p2_runner.py兜底增加固定unverified；相关新增测试对应原缺口。旧test_p2_holdout_scorecard.py:1148相对R1前快照只在精确集合期望增加unverified，集合等号、leak/error与防泄漏断言保留，符合经理追加授权；本次全链实跑通过。未发现本轮额外改产品判定/阈值/放行/四轴分类。

本包只解决安全诊断证据契约。四轴仍classification_status=unverified、owner=sealed_reviewer、checked0/unknown=planned/violations0，release_ready=false；恒0不证明安全。真实H2、真实模型、真实费用、受控四轴分类、发布均 **NOT-RUN**。本助手落盘后停止写入；由经理决定本包接收及后续，未授权真实复测。
