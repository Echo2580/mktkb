# T207 SCENARIO 离线开发交付

主人，本包开发收尾完成，最终必要定向回归 **346 passed**；待全新独立验收，未经理接收、未提交。真实H2质量与四轴分类仍未验证，T207/P2未通过完整质量验收。

基线：`a751889bd4673fe43ba9c631f4e2ea13ce4fe585`；日期：2026-11-12。接续额度中断后的现有未提交接线和合成测试，未重做已完成部分。未解密/查看真实H2、真实附件、保管会话、逐题trace或凭据；只用合成sealed dataset/附件及公开fixtures。无真实调用、预留或固定账本/预算/GO写入。

## 实现与接口

- 新 `p2_holdout_scenarios.py`：`load_scenario_contract(dataset, *, annotation_path, key_file, review_path, manager_path=..., review_aggregate_path=..., scenario_path=..., ingest_path=..., source_map_path=..., schema_path=...)` 返回不可打印逐题内容的 `ValidatedScenarioContract`。完整30题/36轮、固定顺序唯一归属、冻结hash/复核批准/公开语料hash及严格结构先校验；私有附件受控内存解密，所有错误固定code。公共冻结元数据限定CUSTODY-V2的离线归属批准，完整quality仍BLOCKED。
- contract提供 `scenario_ids`、`subset(name)`、`ingest_plan(name)`、`binding(name)`、`build_plan(name, *, plan_id, created_utc, plan_version='v0.1', max_requests=1100)`、`validate_run(plan, dataset, ingest)`、`safe_summary()`。subset实际计数如实保留，declared30与full身份不伪造；加载后嵌套题目内容变化即拒绝。
- 四库严格按原12source子序列，B=8/9/11/13；D01 active=2/2/3/4、D02=1/1/2/2，V01仅第二/三库，V07仅第四库。原path/name/document_ref与H2MAP前驱版本映射保留。已知历史relevant/forbidden可指向主动排除源，positive expected缺源仍阻断；版本/locator/unit_key合取和active判断保留。
- 原 `P2RunPlan` 可选scenario_binding进入正常plan_sha（含created_utc），绑定assignment/custody/review/配方/原与子序列ingest/subset/full/manifest/schema/source-map。无scenario不增加序列化键。adapter、runner、live装配与直接API均强制contract/plan/subset/ingest匹配；仓内私有路径发送前拒绝。
- CLI：`p2-h2-plan`、`p2-run`、`p2-score`增加显式scenario参数与绑定校验。新 `p2-h2-scenarios-run` / `run_scenario_batch(contract, plans, *, out_dir, snapshot, gate_config)` 只串行Mock，各状态新adapter/目录/会话/门；首失败不开始后续，无live选项、自动重试0。
- `compose_scenario_runs(contract, runs)` 严格四part/顺序/唯一run/subset与共有pipeline/provider/gate身份；每个实际卡先调用现有SAFE-DIAG `validate_scorecard`。缺diagnostics、unknown冒充pass、缺必需block及非法mode均拒绝。只重算可证明subset数量型sample_missing/below_threshold，其余阻断保留；partial/error/not_started/unknown不消失，release_ready=false。四轴仍unverified/checked0/unknown，未补分类器。
- 新契约：`docs/evaluation/p2-h2-scenario-execution-v0_1.md`；runbook只追加§13，未改旧执行授权。

## 实际验证

| 检查 | 结果 / 证据 |
|---|---|
| 收尾初跑 | 36 passed/3 failed：nested enum泄TypeError、加载后dataset变化未拒、corpus hash未核验。CLI四库/首错停/历史排除来源当时已通过。 |
| 安全边界红例 | `evidence/red.txt`：13项中11 failed/2 passed，复现上述3项及缺diagnostics、unknown→pass、缺未验证block、metadata未知键/bool/坏scope/坏gap；mode/分层置换原已拒绝。后补3项metadata嵌套计数/未知键/assignment一致性。 |
| 最终11文件回归 | `evidence/regression.txt`：**346 passed，43.95秒，0 skip/xfail**；1项既有Starlette/httpx弃用警告。SCENARIO专项52项包含在内；不以旧开发自报替代本次结果。 |
| 真CLI正常Mock装配 | 合成30题/36轮同库完整覆盖，四状态全部succeeded；真实上传/worker/索引/active版本/V01/V07及B均由测试断言。夹具评分5pass/25fail/error0，是接线观测，不是质量达标。 |
| 真CLI首错停 | 首库ingest合成错误，首run blocked，其余3个not_started，只建1个run_manifest；合并0executed/30error/0turn。两种运行安全输出逐文件扫描合成case_id/题面/参考答案均无泄漏。`evidence/synthetic-summary.json`只提固定计数。 |
| 出站闸门 | `evidence/network-guard.json`：346个用例全启guard，external_attempts=0；65次Windows asyncio回环单列，不是真实请求。 |
| 公开57默认差分 | `evidence/default-differential.json`：R1=52/R2=2/R4=3；case_score全字段、scorecard、默认normalization及归档评分逐值一致；P1评分器/runner归一化源码字节一致。仅公开产物回放。 |
| 默认plan/config | `evidence/default-binding-differential.json`：合成默认计划生成、旧DTO序列化、plan_sha、runner binding/config hash均与a751889逐值一致；10个保护文件与基线tracked内容无差异，当前字节hash入证据。 |
| 固定资金文件 | 默认差分脚本另核固定ledger/budget/GO精确hash仍为16484058…/79b21700…/3ed427f4…，无修改。 |
| 空白检查 | `git -c core.whitespace=cr-at-eol diff --check` exit0；新模块/测试由最终pytest实际导入。 |
| NOT-RUN | 真实H2/模型/服务/付费/预留、真实保管附件加载、实际GO签发、四轴受控分类、发布及全仓测试。 |

复跑：项目 `.venv/Scripts/python.exe -B`，`MKTKB_NO_DOTENV=1`；TEMP/TMP与`--basetemp`使用当前visualizations的全新独占 `t207-temp/scenario-finish/` 子目录。`PYTHONPATH`指本包evidence目录，pytest使用 `-q -p no:cacheprovider -p scenario_guard`，测试文件为：

```text
backend/tests/evaluation/test_p2_holdout_scenarios.py
backend/tests/evaluation/test_p2_holdout_plan.py
backend/tests/evaluation/test_p2_holdout_scorecard.py
backend/tests/evaluation/test_p2_holdout_source_map.py
backend/tests/evaluation/test_p2_safe_diagnostics.py
backend/tests/evaluation/test_p2_runner.py
backend/tests/evaluation/test_p2_score_run.py
backend/tests/evaluation/test_p2_scoring.py
backend/tests/evaluation/test_p2_live_wiring.py
backend/tests/evaluation/test_cli.py
backend/tests/integration/test_p2_product_e2e.py
```

ASGI/socketpair在默认沙箱挂起的已确认环境限制，仅以必要pytest命令级require_escalated解决；没有skip/xfail或改变产品来绕过。`default_diff.py`、`default_binding_diff.py`与`collect_synthetic.py`均用同一venv/-B复跑；后者只扫本次合成pytest目录。额外默认binding探针初次因合成identity缺suite字段失败，只修探针fixture后通过，不算产品缺陷。

## 文件与停止点

源码：新scenario模块；必要接线仅cli、p2_contracts、p2_holdout_plan、p2_live、p2_runner、p2_score_run、product_adapter。测试：只新增test_p2_holdout_scenarios.py，未改旧断言。文档：新执行契约/runbook追加及本报告有限evidence。

原有协调/manager/面试/tmp/%SystemDrive%等工作保留，未清理、暂存、commit或push。10个保护文件覆盖固定资金三件、原manifest/source-map/12source计划/公共配方/schema/CUSTODY-V2批准与复核聚合。

开发自测不等于独立验收。交经理全新上下文验收后暂停；真实复测由另一个AI按另行授权执行。当前完整质量仍BLOCKED（实体2/日期2及四轴运行证据缺口保留），不启动后续采集/四轴分类/T208/T209/T900。本开发停止写入。
