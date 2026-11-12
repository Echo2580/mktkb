# T207 SCENARIO 独立离线验收

主人，正式结论：**PASS（本包离线范围）**；spec=PASS；code quality=PASS。
真实H2质量、真实附件绑定运行及四轴运行证据=**NOT-VERIFIED**；T207/P2完整质量仍BLOCKED。
日期2026-11-12；BASE/HEAD均为a751889bd4673fe43ba9c631f4e2ea13ce4fe585；对象为最终未提交工作区。
已完整读取派发判据、开发任务/报告、review-package.diff、最终源码、v0.1/v0.2 schema、公共配方和V2安全批准/复核。
开发自测346条不作为本独立结论；本次实际执行255条，全部通过，0 skip/xfail，1项既有Starlette/httpx弃用警告。

## 独立证据

全部证据位于`evidence/independent/`；正式交付后停止写入。

|判据|结论与实际证据|
|---|---|
|严格附件/覆盖/冻结|PASS：完整30/36、同序唯一、refs边界、日期/枚举/未知键、cipher/schema/recipe/corpus绑定；专项及另写bool/负索引/重复ref/嵌套ASCII/重复JSON键反例全部拒绝。|
|预发送绑定|PASS：新增12项逐字段binding篡改、跨subset/ingest/plan、直接API缺contract拒绝；CLI实际生成计划并拒绝评分run_manifest坏plan hash。|
|四库状态|PASS：重跑真实CLI Mock上传/worker/索引链，D01 active2/2/3/4、D02 active1/1/2/2，V01/V07存在/排除与B8/9/11/13均断言通过；多轮同库。|
|H2MAP/active|PASS：历史V03/V04/V05/V06映射、locator/unit_key与版本合取、不能跨引用拼接及active检查定向链通过；排除的历史relevant/forbidden不强制加库，positive expected缺失阻断。|
|严格组合|PASS：四个冻结subset同序完整身份，缺/重run、错subset/plan/shared provider/gate/config拒绝；只重算已证明subset数量门槛，通用unknown与安全block保留。|
|经理发现的整卡绕过|PASS：另写缺diagnostics、嵌套ASCII、unknown→pass、缺unverified block、自由error evidence五反例，均固定scenario_scorecard_invalid；最终源码确实先调用validate_scorecard。|
|首错停/partial|PASS：真实CLI正常四库及首ingest失败；另写batch首MODEL_OUTPUT_INVALID服务错误，只有首库1次ask/1个run_manifest，后3库not_started、30error/0pass；既有真实runner21scored/1error/8未开始也通过。|
|安全产物/purge|PASS：上述CLI及独立service-stop扫全部合成case ID/题面/参考答案无泄露；SAFE-DIAG闭词表/全树验证及live接线purge定向测试通过；release_ready=false、threshold unapproved、四轴checked0/unverified/unknown保留。|
|出站实测|PASS：network-guard.json记录255个用例均启guard，external_attempts=0，55次Windows asyncio回环单列；不是真实模型请求。|
|57公开默认逐值差分|PASS：独立重跑public R1=52/R2=2/R4=3，与BASE及归档case_score逐值、scorecard、normalization一致；见default-differential.json。|
|默认identity/保护件|PASS：独立重跑无scenario序列化、plan_sha、binding/config差分；10个保护件tracked内容一致，固定ledger/budget/GO精确hash一致；见default-binding-differential.json。|
|代码质量|PASS：必要接线沿用原DTO/gate/runner/scoring，零新生产依赖；合成29项独立探针及受影响定向链未发现阻断缺陷；源码/交付diff hash见source-review.json。|

## 经理受控程序静态评审

`evidence/controlled_binding_check.py`静态结论：**PASS**；本验收角色没有执行该程序，也未读取任何真实私有附件/密钥/逐题内容。
核查实际链：设置MKTKB_NO_DOTENV后，load_p2_dataset→load_scenario_contract→safe_summary；明文仅进程内存。
safe_summary来源仅固定scenario枚举/四轴适用性计数/固定gap及BLOCKED常量；输出无case ID、逐题归属/hash、目标、题干或答案。
其它输出仅受保护整文件SHA256、固定状态/计数；异常统一固定FAIL code，无异常原文/traceback输出。
导入链未构造app/adapter，未调用runner/provider/网络或凭据服务；只有受控loader读取既定key文件，不输出key，不读.env。
connect/connect_ex/create_connection在导入loader前被阻断；该静态结论限定本脚本实际调用链，不作为通用Python沙箱证明。
经理仍需在接收源码独立结论后自行执行真实绑定核验；本报告不把该未运行步骤写成PASS。

## 实际命令与数量

项目`.venv/Scripts/python.exe -B`；MKTKB_NO_DOTENV=1；pytest `-q -p no:cacheprovider -p scenario_guard`。
TEMP/TMP及--basetemp为本次visualizations下`t207-temp/scenario-independent-20261112/pytest`独占目录。
仅必要pytest命令级require_escalated，用于已有socketpair/ASGI沙箱限制；未skip/xfail或修改产品绕过。
pytest对象：independent/test_independent_scenario.py（新增29项）、test_p2_holdout_scenarios.py（52项）及以下174项定向回归：
`test_p2_holdout_source_map.py`、`test_p2_safe_diagnostics.py`、`test_p2_holdout_plan.py`、`test_p2_runner.py`、`test_p2_score_run.py`、`test_p2_live_wiring.py`。
结果：**255 passed in 77.76s**；完整命令对应本段文件列表；日志pytest.txt。
另实际执行独立目录内default_diff.py、default_binding_diff.py与`git -c core.whitespace=cr-at-eol diff --check`，均exit0。
差分脚本只复制至独立目录执行，未覆盖开发证据；没有为凑数量重跑开发全部346项。

## 未验证与停止点

NOT-VERIFIED：真实H2/模型/服务/付费/预留、真实附件零产品绑定运行、实际GO签发、四轴受控分类、发布与全仓测试。
实体2/日期2缺口、四轴实际证据缺口继续保留；离线PASS不表示真实质量达标，不授权T208/T209/T900。
仅新增review.md及independent自有合成探针/日志；未改源码/旧测试/开发证据/冻结件/资金文件，未stage/commit、未派子助手。
本包无独立验收阻断；后续接收与暂停决定由经理作出。
