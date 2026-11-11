# T207-FIX-H2MAP 开发报告（待全新独立验收）

- 基线：codex/p2-e2e，d7728db35655ae67569aec84cc4ededeaf7f7c13；零真实调用、未 commit。
- 根因：runner 只覆盖基槽 doc_code；公开归一丢失产品 version_number，H2 的 V04/V06 无法匹配。
- 映射：V03→D01/v1、V04→D01/v3、V05→D01/v4、V06→D02/v2；依据 acceptance B0 初始化及原 H2 12 项上传顺序，不读取真实 H2。
- 依据差异：enterprise-20261101/manifest.json 的 V04/V05/V06 属另一套语料，不能推导本 H2 基槽；已在 source-map 明示。
- H2 内存复制 expected/relevant/forbidden refs，合并原 locator 与版本；普通基槽不额外要求版本，封存文件/金标不变。
- 版本只取产品 source 的正整数 version_number；缺失/错版不命中，locator/source_index 不能补足产品缺版，冲突稳定 source_version_conflict。
- 同一 citation 必须满足版本、原 locator 及 unit_key，不能跨 citation 拼凑；source_hit 指标同步反映错版不命中。
- _version_source_checks 仅替换 source_hit/source_forbidden；pass/fail 按既有 score_case 的“任一 check fail 即 fail”公式重算，不新增诊断 check，不清除其他质量失败；error/skipped 等非质量状态原对象返回。
- runner 真接线：校验 map schema/重复键/重复身份、实际上传顺序、expected/relevant 的基槽覆盖及引用版本文件已导入；异常沿用 unmapped，整包 error。既有文档名歧义码保留。
- 未引用的全局映射版本及禁止来源无需已导入；未改停止、重试、隔离、预算、GO、账本或业务代码。

## 验证（开发自测）

- TDD：初轮 12 failed/10 passed→22 passed；回归发现 forbidden_sources 不必已导入，补红例修正；source_index 版本冲突红例后修复；末尾 error/skipped 保持 2 red 后增加早返回保护。
- 最终命令：`.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider backend/tests/evaluation/test_p2_holdout_source_map.py backend/tests/evaluation/test_p2_score_run.py backend/tests/evaluation/test_p2_scoring.py backend/tests/evaluation/test_p2_holdout_scorecard.py backend/tests/evaluation/test_scorers.py -q`。
- 最终结果：190 passed，1 条既有 Starlette/httpx 弃用警告，6.08s；34 项新增合成测试含完整公共 H2 ingest 配方的 runner 评分边界接线。
- 使用独占可写 TEMP/TMP `.../t207-temp/h2map-dev`、-B、关闭 pytest cache；ASGI 定向回归经最小命令级沙箱例外执行，不以 skip/xfail 绕过环境。
- 最终源码修改后重跑 `evidence/default_diff.py`：R1 52/R2 2/R4 3 条逐题分数及 scorecard、57 轮默认归一逐值等于 d7728db，且逐题分数等于既有公开归档。
- P1 scorer/runner 规范化源码字节与基线一致；P1 scorer 定向回归已纳入190项；账本/budget/GO SHA256 与接手快照一致；git diff --check 通过。

## 限制与后续依赖

- 本包只证明版本来源身份及离线评分链；不证明真实 H2 达标，不替代独立验收，也不证明四类硬失败为零。
- 原完整配方 V05 发布后 D01 active=v4，V04/v3 为历史版本；经理受控聚合报告存在正向 inactive 来源契约阻断，本包未读取/独立复核冻结内容，留后续独立 scenario 契约包，不改金标/active。
- 未做 SAFE-DIAG、产品修复、真实复测、全仓测试或 scenario 功能；T207 完整质量及 P2 总验收仍未通过。

## 本包准确文件清单（相对仓库根，共12个）

1. backend/src/mktkb/evaluation/p2_runner.py
2. backend/src/mktkb/evaluation/p2_score_run.py
3. backend/src/mktkb/evaluation/p2_scoring.py
4. backend/tests/evaluation/test_p2_holdout_source_map.py
5. docs/evaluation/p2-holdout-v2.source-map.json
6. docs/evaluation/p2-dataset-v0_1.md
7. docs/evaluation/p2-live-binding-v0_1.md
8. docs/reports/OBS-EVAL/P2/T207/PM/T207-runbook.md（§8一句）
9. docs/reports/OBS-EVAL/P2/T207-FIX-H2MAP/report.md
10. docs/reports/OBS-EVAL/P2/T207-FIX-H2MAP/evidence/default_diff.py
11. docs/reports/OBS-EVAL/P2/T207-FIX-H2MAP/evidence/default-differential.json
12. docs/reports/OBS-EVAL/P2/T207-FIX-H2MAP/evidence/tests.txt
