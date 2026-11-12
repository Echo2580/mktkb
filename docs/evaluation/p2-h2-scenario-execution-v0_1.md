# H2 四状态受控执行契约 v0.1

本契约只定义已冻结 scenario 归属的离线接线；原30题/36轮、金标、阈值和12source原计划不变。保管元数据来自 `T207-CUSTODY-V2/manager-acceptance.json`，其中 assignment 仅批准离线实现，完整质量仍 BLOCKED，实体/日期缺口各2。它不构成真实执行 GO。

## 受控加载与身份

`load_scenario_contract(dataset, *, annotation_path, key_file, review_path, manager_path=..., review_aggregate_path=..., scenario_path=..., ingest_path=..., source_map_path=..., schema_path=...) -> ValidatedScenarioContract` 接受完整 holdout `P2Dataset`。先核公共配方、经理/独立复核元数据、公开语料及密文hash，再仅在受控内存解密附件；附件必须严格按完整dataset顺序覆盖全部case。坏结构/枚举/日期/ref、缺重case、未知scenario、坏hash与未批准归属均抛固定 `ScenarioError`，不回显输入。

`targets.entity_key` 允许空字符串表示尚未解析的占位，不能作为可信实体身份，原有 unknown/质量 BLOCKED 及运行期证据未产生的结论不变；`entity_type` 仍须为非空字符串，两者长度均不得超过256。

附件、复核密文、key、含case的计划和scenario运行目录必须在工作区外。contract及subset的repr不展示题面；case身份只驻内存或受限仓外运行目录，公共输出仅允许绑定hash/固定计数。已加载dataset的嵌套内容若改变，后续subset/plan/执行检查拒绝；不得运行期按产品输出或分数重分配。

`contract.scenario_ids` 顺序固定为下表；`subset(name)` 返回 `P2RunDataset`，保留原manifest/declared_case_count=30，同时如实记录subset实际case/turn/strata及scenario binding。`ingest_plan(name)` 仅取原计划0基下标子序列，不改path/name/document_ref：

| scenario | source_indices | B | D01/D02 active版本 | 独立通知 |
|---|---|---:|---|---|
| base_b0 | 0,1,4,6,7,8,9 | 8 | 2/1 | 无 |
| base_b0_plus_v01 | 0,1,4,6,7,8,9,10 | 9 | 2/1 | V01 |
| pre_v05_without_v07 | 0,1,2,4,5,6,7,8,9,10 | 11 | 3/2 | V01 |
| post_v05_without_v01 | 0,1,2,3,4,5,6,7,8,9,11 | 13 | 4/2 | V07 |

`build_plan(name, *, plan_id, created_utc, plan_version='v0.1', max_requests=1100)` 将assignment/custody/review/公共契约/原与子序列ingest/subset/full-cases/manifest/schema/source-map的hash绑定进原 `P2RunPlan`。`created_utc` 仍参与正常plan_sha；每状态使用独立计划/目录/会话/新门，实际GO必须另行绑定各自plan_sha。`validate_run(plan, dataset, ingest)` 对三者逐值校验；`ProductEvalAdapter`、`run_p2`、`build_live_adapter`、`run_live_p2` 均要求匹配contract，不能仅移除CLI参数绕过。

既有H2MAP保持V03→D01/v1、V04→v3、V05→v4、V06→D02/v2。已知历史 relevant/forbidden refs 可指向本scenario主动排除的源；positive expected源缺失仍阻断。引用仍需原locator/unit_key与版本合取，版本相等不代表active，不跨版本拼接。

## CLI与组合

`p2-h2-plan --scenario-id ...` 读取完整受限dataset与冻结附件，生成仓外计划；`p2-run` 和 `p2-score` 的scenario路径要求显式scenario-id、计划及完整附件参数。参数为 `--scenario-annotations`、`--scenario-review`、`--scenario-key-file`，经理/复核聚合默认指向公共V2目录，可用 `--scenario-manager`、`--scenario-review-aggregate` 显式指定受控合成测试件。`p2-score` 另核run_manifest与plan身份。

`p2-h2-scenarios-run` 仅提供串行Mock装配，参数包括按表顺序给四次 `--plan`、`--snapshot`、`--holdout-manifest`、`--ingest-plan`、附件参数及新仓外 `--out`。`run_scenario_batch(contract, plans, *, out_dir, snapshot, gate_config)` 在首次构造前校验全部计划，各状态独立adapter与授权；首个执行异常/阻断后不启动后续状态，不重试。该命令无live模式，不写固定ledger/budget/GO。

`compose_scenario_runs(contract, runs)` 只接收恰好四个顺序绑定part（plan/aggregate/status/run_id/turns_executed/binding），核完整唯一assignment/subset身份、独立run/plan与公共pipeline/provider/gate config。一切实际卡先经现有 `validate_scorecard` 全卡安全校验，保留diagnostics跨层等式、固定词表和必需block。缺诊断、unknown冒充pass、坏计数、错绑定或中止后又开始均拒绝。

仅能证明来自subset数量的sample_missing/below_threshold阻断可在完整30题组合后重算；其它阻断均保留，不过滤通用unknown。not_started/error/partial如实计入，未执行不补pass。输出独立schema `p2-h2-scenario-composition/v0.1`，包含原manifest/full-cases/assignment及各run/plan/aggregate hash、固定分层与诊断。四轴仍checked=0/unknown=planned、unverified，`holdout_hard_failure_unverified` 与threshold-unapproved不解除，`release_ready=false`。

无scenario时可选binding不序列化，原计划与默认公开/P1评分路径保持原值。本包合成/公开离线测试不能代替真实H2复测、四轴分类或T207/P2验收。
