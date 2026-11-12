# T207 SAFE-DIAG R1 开发返工交付

主人，本轮四个拒收反例已转绿，最终必要定向回归 **284 passed**。这是开发自测，**待全新独立复验，未经理接收、不提交；T207/P2 质量未通过**。真实 H2 质量与四类硬失败分类仍未验证。

基线 HEAD：`09ddc87520576958ff4c19be16f245f8197fdfe5`；日期：2026-11-11。以保留的未提交 SAFE-DIAG 实现为返工起点，读原 dev/verify/report/review 和独立反例。旧报告、独立证据均未覆盖；原反例及工具复制到本轮 `evidence/replayed-review/` 后重新执行，属于**开发重放**，不算新的独立验收。

## 最小改动

- `backend/src/mktkb/evaluation/p2_diagnostics.py`：总计及五分层严格 `scored=observed+unknown_kind`；拒答 `tp+fp+tn+fn=observed`、`unknown=unknown_kind`，保留原 errors/not_executed 等式、矩阵、固定枚举、严格 int/上限及 exact keys。正常 scored 缺末轮 outcome 或 should_refuse 不是 bool，直接失败封闭，不能假装正常证据。
- 整卡及每一分层的 passed 不得超过对应 observed；诊断分层 planned/scored/errors+not_executed 分别对齐卡片 total/passed+failed/errors，不能在分层之间调换 pass 遮蔽 unknown。
- 所有卡必须有 `holdout_hard_failure_unverified`。正常卡按现有标量校验 sample_missing / case_error / below_threshold / threshold_unapproved 必需阻断存在。只有严格全 error、scored=0、诊断 errors=total，且携带已登记兜底失败码、固定 detail/evidence 的卡，才允许由其兜底失败 block 表达这四种失败；它也必须保留 unverified。未增加阈值或放行条件。
- `backend/src/mktkb/evaluation/p2_runner.py`：仅给兜底卡增加同一固定 unverified block。
- `backend/tests/evaluation/test_p2_safe_diagnostics.py`：新增 11 项关联、分层、生成证据与必需阻断检查，均在修改源码前运行见红。
- `backend/tests/evaluation/test_p2_holdout_scorecard.py:1148`：经理追加授权后，仅将原兜底 block 精确集合期望增加 `holdout_hard_failure_unverified`。原断言仍用集合等号，原 leak block、30/0/30 全 error 和所有防泄漏断言均保留。理由是原“只能有 leak 一个 block”与本轮明确新增兜底未验证阻断要求冲突；未调整其他旧断言。

本轮源代码差分相对返工起点见 `evidence/r1-source.diff`；三个修改前快照保存在 evidence。未修改其余产品、评分器、分类器、场景、阈值或模型原因接线，没有新 skip/xfail、没有删除断言，没有全仓测试。

## 实际验证与证据

| 检查 | 实际结果 |
|---|---|
| 原四拒收反例先红 | `evidence/red-four.txt`：4 failed/21 deselected；unknown→TN、unknown→pass、删除 unverified、删除 threshold_unapproved 均复现原漏洞。三份原始 JSON 写盘结果另存 `evidence/red-counterexamples/`，没有随重放覆盖。 |
| 新增先红 | `evidence/red-added.txt`：11 failed/25 deselected；证明完整观察等式、坏 should_refuse/无 outcome、四标量和 unverified 必需阻断、unknown 分层 pass、跨树分层一致、兜底 unverified 缺口。 |
| 最小修复转绿 | `evidence/green-targeted.txt`：15 passed/46 deselected，覆盖原四例及新增11例。异常写盘均全 error、稳定 `holdout_scorecard_leak`，兜底保留未验证状态及 block。 |
| 最终定向回归 | `evidence/regression-final.txt`：284 passed，33.90秒，0 skip/xfail，1项既有 Starlette/httpx 弃用警告；项目9文件259项＋原独立探针副本25项。 |
| 首轮回归如实记录 | `evidence/regression-first.txt`：283 passed/1 failed，仅旧兜底 block 精确集合与新契约冲突；经理授权同步该一行后重跑同一必要链得到最终284通过。首轮 guard 单独保存，没有计作全通过。 |
| 真 runner 正常30题 | 重放探针 `runner-normal.json`：30pass、scored/observed30；TP5/TN25，其余拒答计数0；五分层10/5/5/5/5，source matched25；只是合成夹具。项目原正常30夹具的23pass/7fail及既有矩阵、source计数断言也通过。 |
| 真 runner 部分执行 | `runner-partial.json`：21评分=11pass+10fail，服务error1，not_executed8，observed21；TN16/FN5/errors1/not_executed8；第22题 MODEL_OUTPUT_INVALID/record_facts 首错停，后8题不补跑。卡的errors9为服务error1＋未开始8。 |
| should_refuse 与 expected_kind 不一致 | 合法四格 TP/FP/TN/FN各1，结构error/未开始/unknown分别单列；正常unknown仍保持observed0/unknown_kind1/拒答unknown1，不变TN或pass。 |
| 模型原因真实离线链 | `reason-json_parse.json`、`reason-record_facts.json`、`reason-unknown.json`：真实既有 Span→ProductTurn内存→runner聚合，错误码 MODEL_OUTPUT_INVALID、retryable true、chat1次、首错停，trace清理且自由message不出产物；公开as_dict不新增reason。 |
| 全树/全卡反泄漏 | 原开发和重放探针均通过：固定词表、未知键、嵌套 reference_answer、ASCII片段、换行、长串、数组、bool/float/负数/大数、坏等式、block/detail/evidence及绑定元数据；保留递归和needle审计，无diagnostics整树豁免。 |
| 公开57轮默认差分 | `evidence/replayed-review/default-differential.json`：R1=52/R2=2/R4=3，case_score全部字段、scorecard、归档评分及默认normalization逐值相同；P1 scorer/runner保护hash亦相同。 |
| 保护文件 | `evidence/protected-hashes-before.json` 与 `evidence/replayed-review/protected-hashes.json`：16文件均与固定交接或基线hash一致；sealed manifest/source-map/ingest-plan仅做字节hash，不解码。 |
| 外网闸门 | `evidence/network-guard-final.json`：92个带guard测试、external_attempts=0、pytest_exit_status=0；51个Windows asyncio回环尝试单列。首轮也是外网0，见 network-guard-first.json。 |
| 空白检查 | `git -c core.whitespace=cr-at-eol diff --check` exit0。 |

三固定保护值：ledger `1648405845fd5e19b593e610b92f8505fdfd78a9e57079648dc14673576785d7`；budget `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`；GO `3ed427f42ac2eeedff489505b94f730eadba1dc38f1b9adecf94d25750b02a7c`。

`evidence/synthetic-summary.json`只摘录本轮重跑的合成聚合卡与已修反例输出；`summarize.py`可重新核对，并证明四个重放工具副本仍与旧独立工具字节相同。原四反例中三项原来有JSON输出，删除 unverified 的第四项由保留的 pytest 断言/日志证明，本轮未伪称其有原始JSON。

## 复跑方法与执行边界

项目 `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider -p independent_guard`，`PYTHONPATH` 为 `backend/src` 与本轮 `evidence/replayed-review`。TEMP/TMP 及 `--basetemp` 仅使用当前 visualizations 的独占 `safe-diag-r1-dev` 子目录；最终为 `regression-final-01`，没有重用或删除业务/旧证据路径。必要离线 ASGI/runner 使用命令级 require_escalated 解决已确认 socketpair 沙箱限制，无 skip/xfail 或削弱断言。

最终回归精确路径：

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
docs/reports/OBS-EVAL/P2/T207-SAFE-DIAG-R1/evidence/replayed-review/test_independent_safe_diag.py
```

未读取真实 H2 题号/题干/答案/逐题trace或凭据；全部合成或公开。真实模型、真实费用、真实 H2、四维受控分类、发布均 NOT-RUN。四类证据仍全为 checked0/unknown=planned/violations0、classification_status=unverified、owner=sealed_reviewer，恒0不证明安全。API/停止/费用只由已有离线回归支持，不能替代真实服务验证。

**停止写入：交由另一全新助手独立复验，再由经理决定接收；本助手不commit、不启动真实复测。**
