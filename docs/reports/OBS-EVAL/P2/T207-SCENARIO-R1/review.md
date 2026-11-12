# T207 SCENARIO R1 独立离线复验

主人，正式结论：**PASS（R1离线范围）**；spec=**PASS**；code quality=**PASS**。
真实冻结附件实际绑定、真实H2质量和四轴运行证据=**NOT-VERIFIED**；T207/P2完整质量仍**BLOCKED**。
日期2026-11-12；BASE/当前HEAD均为`a751889bd4673fe43ba9c631f4e2ea13ce4fe585`；对象为最终未提交工作区。
开发已停止后独立执行；开发76项、旧346/255项不充作本轮独立实测结果。

## 判据与证据

|判据|本轮结论与证据|
|---|---|
|准确范围|PASS：生产源码对before逐字节仅替换_axis字符串条件；原52项测试字节保持为前缀；执行契约只增加一句及空行。|
|原验收对象延续|PASS：before源码/原测试hash吻合原255验收source-review.json；其它原接线源码hash一致；评分源码受保护未改。|
|空键与身份边界|PASS：独立合成30条四轴全部放空键，保留实体unknown=2、原轴标签及N/A，safe_summary前后逐值相同；原dataset标签字节不变。|
|未解析质量|PASS：实体/日期缺口仍各2、quality BLOCKED、runtime_axis_evidence_produced=false、release_ready=false；严格组合保留holdout_hard_failure_unverified。无目标字段或实体身份补造。|
|类型/长度/周边约束|PASS：独立反例覆盖key的None/list/dict/bool/数值/257字，type空串/错误类型/257字，坏filters/嵌套值/空或超长键；未知/缺字段、bool/负/重复ref、坏日期均固定错误码；256个Unicode字符及合法标量filters仍接受。|
|固定失败重放|PASS：用独立合成同一空键附件，当前loader先成功，再仅于内存AST替换为before的_axis，准确抛scenario_targets_invalid；未修改生产源码或覆盖旧真实失败。|
|绑定拒绝|PASS：空键加载后修改dataset，后续subset拒绝scenario_dataset_changed；仅读取时模拟公开语料字节变更，解密前固定scenario_corpus_binding_invalid。原hash/schema/完整覆盖/计划/严格整卡反例本轮亦实际通过。|
|实际CLI Mock|PASS：原正常四库/首ingest错停专项通过；另用两个空键+unknown合成附件直接执行CLI两分支，正常36轮、四库状态/B8/9/11/13及首错仅1个run_manifest/后3库not_started断言通过，unknown/BLOCKED仍保留。|
|安全输出|PASS：CLI原有逐文件合成case ID/题面/答案泄露断言通过；独立四轴空键组合无合成目标标记。|
|保护件|PASS：21保护件及12公开源hash与开发前/公共冻结hash逐值一致；两版schema、原manifest/source-map/配方/计划、V2批准/复核、旧报告/review和固定ledger/budget/GO不变。两新密文对应公共冻结hash未变；未读取密文原件。|
|旧失败保全|PASS：initial实际FAIL/actual_binding_check_failed与后续FAIL/scenario_targets_invalid均保留；一次全附件7布尔安全聚合仅empty_entity_key_string_present=true，不视为绑定成功。|
|出站实测|PASS：111项及追加2项全部启guard，external_attempts=0；5次Windows asyncio回环单列，无真实模型/产品请求。|
|静态受控程序|PASS：controlled_binding_check.py hash=e56a85688c5ea3b9c43685008df3b17ebf145df6304669e0732c146a951248e2、controlled_target_shape.py hash=cdb876587a01fe8005d0784f152e008fd37594b1742c0ce63279fbbd71a017b9，分别匹配已独立通过的诊断增量/shape记录，程序本轮未改。|
|代码质量|PASS：最小共享语法修复，保持原错误码、数据结构、依赖与接口；独立反例及专项未发现本轮阻断缺陷。|

静态追踪`load_p2_dataset → load_scenario_contract → safe_summary`：明文仅内存；summary只取固定scenario/axis适用性计数、固定gap与BLOCKED常量，完全不取targets值。
固定错误码白名单整值匹配，未知异常回退固定FAIL，无str/repr/traceback导出；输出仅安全聚合及整文件hash。
MKTKB_NO_DOTENV在loader导入前设置，socket connect/connect_ex/create_connection先阻断；实际调用链未构造app/adapter、未运行runner/provider或凭据服务。
shape仅全附件七个固定bool、无轴分组/逐题/值/数量；本轮仅静态核，不执行任何controlled main，不延长一次shape授权。

## 实际命令与数量

自有证据均在`evidence/independent/`；保护核验`audit_scope.py before/after`实际exit0，`scope-audit.json`记录精确差分与hash。
环境：项目`.venv/Scripts/python.exe -B`，MKTKB_NO_DOTENV=1、PYTHONDONTWRITEBYTECODE=1；pytest `-c backend/pyproject.toml -q -p no:cacheprovider -p r1_independent_guard`。
TEMP/TMP固定本次visualizations下`t207-temp/scenario-r1-independent`；两次--basetemp分别`pytest-final`、`pytest-cli-empty`，均独占新目录。
第一次对象：`backend/tests/evaluation/test_p2_holdout_scenarios.py`及`evidence/independent/test_r1_independent.py`当时35项；**111 passed in 24.94s**，日志`pytest.txt`。
追加最后2项空键CLI反例后同两文件加`-k empty_key_cli_mock`：**2 passed/111 deselected in 13.03s**，日志`pytest-cli-empty.txt`。
合计独立实际**113项通过=当前专项76+独立新增37**；0 skip/xfail，两个批次各有1项既有Starlette/httpx弃用警告。
网络分别见`network-guard-primary.json`（111/0外部/3回环）、`network-guard.json`（2/0外部/2回环）。
仅上述必要ASGI pytest命令级require_escalated用于已证socketpair沙箱限制；未改产品或skip/xfail绕过。
`git -c core.whitespace=cr-at-eol diff --check`实际exit0；两轮后audit再次通过，开发证据与旧失败记录hash一致。

## 未验证与停止点

NOT-VERIFIED：真实附件绑定成功、真实H2/模型/服务、付费/预留、实际GO、四轴运行分类、全仓测试、发布与owner验收。
本轮未读真实H2/附件/保管会话/.env/凭据；未执行controlled_binding_check或controlled_target_shape的main。
仅写本review及independent自有合成探针/有限日志；未改源/项目测试/开发证据/资金/GO，未stage/commit、未派子助手。
离线PASS不能覆盖经理旧真实FAIL，真实绑定须经理受控另核；真实复测交另一AI按另行授权执行，不进T208/T209/T900。
本角色验收完成并停止写入；经理决定接收并暂停。
