# T207 质量修复经理记录

## 范围和完成标准

2026-11-11 主人恢复 T207：离线修复、全新独立验收后，现有 40/20 元及中心预算内必要受控真实复测。只本地提交接收包，不 push/合并/部署；完成或明确阻断后暂停，不进入 T208/T209/T900。
报告收口不等于实际质量通过。目标：新真实 H2 完整 30 题、至少 24 pass、错误/未执行 0、四类硬失败 0 且分类证据可信。保留旧失败与费用；gate_v0_3 不擅自 approved。

## 接手现场

- HEAD d7728db35655ae67569aec84cc4ededeaf7f7c13；分支 codex/p2-e2e。已有未跟踪协调/面试/tmp 文件和 _index.md 修改不动，不整体暂存。
- 固定账本 / budget / GO SHA256 与交接一致，分别 1648405845fd5e19b593e610b92f8505fdfd78a9e57079648dc14673576785d7 / 79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e / 3ed427f42ac2eeedff489505b94f730eadba1dc38f1b9adecf94d25750b02a7c。
- 无 codexhost CLI / CODEXHOST_CLI_PATH，按交接使用内置独立助手，不声称使用 wb。Get-Process 未发现 python/node 旧写入者；CIM 查询不可用，不宣称全宿主进程审计。
- get_usage_limits 可读：300 分钟 used53% / remaining47%；任务书 §12 原授权已取消额度检查，读数仅作现场信息。
- 可写 TEMP 已通过；默认 socketpair 和 asyncio/ASGI 各 22 秒有界预检超时，栈均在 socket._fallback_socketpair.accept；属环境阻断，非产品失败。仅中断自有预检。

## 串行修复包与验收依据

1. H2MAP：可信导入配方映射版本代号，保留版本/locator；V04→D01/v3 正例、v2/v4/缺版本反例；映射缺失/冲突/坏 schema 阻断；普通来源及公开/P1 默认逐值不变，runner 真接线。零真实。开发与验收全新上下文。
2. SAFE-DIAG：新设计严格结构/枚举，不恢复拒收 patch；ASCII片段、嵌套字段、换行、数组/长串/未知键 fail-closed。四类硬失败需要真实证据归属，unknown 不算零。
3. PRODUCT：按安全聚合归因，以公开/自建合成反例修真实根因；保持 schema/来源/active 校验、MODEL_OUTPUT_INVALID 停止、自动重试0。
4. LIVE：离线独立验收后才新计划/新 GO/新门；重算费用/请求、先消除环境和冻结数据契约阻断。首错停，失败先归因，不盲重跑。
5. QUALITY-REVIEW：独立复核真实质量及受影响公开回归，分别记录开发自测/经理复核/独立验收/真实验证。

## 事件

- 接手与环境预检已完成；H2MAP 提示已去除“会含 H2DIAG 提交”的过时前提，并补 runner 必要接线写域。
- 命令级沙箱外只读预检获准后 socketpair/ASGI 均 exit0，确定原挂起是沙箱限制。第一次脚本在两项预检后因快照 API 方法名写错退出；改用 as_dict 后全脚本 exit0。预算新快照与交接一致，仓外元数据三 hash 匹配。见 preflight.json。
- 已派全新内置开发 h2map_dev；旧协调文档/面试文件保持不动。H2MAP 可信映射依据必须是 fixtures/acceptance 配方及本次 H2 ingest-plan，不能误用 enterprise 同名 V 文件。
- 经理受控 contract_audit.py 只导出固定计数：30题中1个正向 case 的 expected_sources 要求 inactive 版本（公开终态 D01 active4，V04=v3 superseded）。已派全新 contract_review 独立核实；未改冻结文件、未逐题调参、未新真实调用。此冲突不能以映射修复掩盖，待独立证据后提出具体数据契约决定。
- contract_review 独立核验与经理一致，且确认该1题没有active期望替代。主人已明确选择“授权补充分场景契约（推荐）”；按 contract-decision.md 实施，冻结30题/金标/阈值不变。新增SCENARIO包在H2MAP接收后串行推进；SAFE-DIAG与产品修复仍须离线独立验收后才真实复测。
- H2MAP开发已停止写入，自测最终190passed，57轮公开默认差分逐值不变。全新h2map_review独立验收确认阻断反例：product.version3/raw locator.version4被非空source_index的locator遮蔽后错误pass；index.version4对照才阻断。独立证据 `T207-FIX-H2MAP/evidence/independent/`。本包尚未接收/commit，已准备全新R1修复提示，等待独立review完整落盘后串行返工。
- H2MAP首轮独立review正式FAIL，212passed/2failed，2红例即双版本冲突；真runner合成30题全部执行（30fail/0error，仅执行/隔离证明，不代表质量正例），网络0、57公开默认值与固定hash一致。已派全新h2map_r1_dev，严格只修H2显式定位冲突，旧反例保留。不以190自测掩盖拒收。
- 依赖细化：H2MAP R1接收后先SAFE-DIAG再SCENARIO，以便分场景合并能按最终严格诊断schema保留错误和安全unknown，避免后补聚合接口。只是同一批准范围内串行实现顺序调整，不改两场景决定或任何质量标准。
- **H2MAP R1经理接收**：全新h2map_r1_review PASS，255passed（含独立新增19边界及原B1两个分支）；57公开默认逐值差分、真runner Mock E2E、guard external=[]、三固定hash与16保护文件hash一致。经理已读review、复核最终diff与空白、亲核三固定hash，接收仅离线版本来源映射修复；真实H2质量NOT-RUN，四类硬失败未证明0。准备仅本包及本次P2接手证据本地commit，不含协调/面试/tmp。
- H2MAP本地commit **09ddc87520576958ff4c19be16f245f8197fdfe5**，38文件仅列明P2修复/证据；暂存空。提交前经理受控扫描38 staged blobs：真实H2 exact case_id及≥12字完整题面/回合/参考答匹配0（不冒称任意子串审计）；空白检查0。Git必要命令级写入获当前宿主批准，不是沿用上次d7728db例外。未push/合并/部署。
- 已派全新safe_diag_dev（提示P2-T207-SAFE-DIAG-dev.md），零真实，H2MAP源码基线09ddc87。SAFE-DIAG尚未交付/验收；下一SCENARIO及产品根因/真实验证未开始。
- 经理只读conversations/service.py发现MODEL_OUTPUT_INVALID还覆盖来源/原值/实体/记录事实准入（不只是JSON解析/schema），旧HTTP200+该码不能唯一归因。SAFE-DIAG补充允许最小固定reason枚举接线：providers/types、conversations失败标注、product_adapter读固定枚举；未知message只unknown，不改错误码/文案/判定/计费/停止/重试。已在当前开发提示和消息明确，独立验收必须验证行为不变及未知文本不外泄。
- SAFE-DIAG开发报告首轮严格边界6red/1green；新结构/固定枚举与既有trace reason接线进行中。经理允许最小更新一项旧测试“任意exception.code原样导出”的不安全期望为固定登记code/unknown，必须保留全error/阻断/分母断言并新增ASCII秘密code不出盘反例；这是安全契约收紧，不得借机删断言或声称测试语义完全未变。
- 经理源码审查指出旧blocks.evidence.missing可外泄任意doc_code，开发已用ASCII合成反例确认并改missing_count；全卡exact顶层/分层/block code/detail/evidence校验及身份绑定收紧进行中。unknown actual kind已从正常observed分母分离。Trace顶层不支持扩展attrs，必要reason改用固定model_failure span内登记枚举；没有API/业务/停止变更。以上尚待独立验收，不能先称安全通过。
- SAFE-DIAG开发停止，自报最终248passed；已派全新safe_diag_review独立验收。经理发现待核跨字段计数缺口并交独立探针；已独立证实unknown_kind=1/observed0可被篡改为TN1、或passed1并被writer接受，删除unverified block也未拒。首轮本包尚不接收/commit，R1提示已备，等待review正式落盘后全新上下文返工。结构白名单本身不能代替分母和必需阻断语义。
- SAFE-DIAG独立基础248项无失败；自有探针最终20passed/4failed，4项为unknown→TN、unknown→pass、删除unverified、删除threshold_unapproved。自有normal30、21评分11pass10fail+1error+8未开始、JSON/record_facts/未知ASCII错误三条真reason链、外网0、公开57差分和16保护hash均通过。测试夹具开发期3项错误已仅修自有探针，不当产品缺陷；本包仍FAIL，非248通过即可接收。
- SAFE-DIAG首轮review正式落盘并停止，最终独立自有25项=21passed/4failed（末尾新增代表block删除例），基础248独立无失败。已派全新safe_diag_r1_dev，仅修跨字段等式及必需阻断，保留旧FAIL报告/反例，未commit或真实调用。
- 同时派hard_evidence_audit做只读前置可行性审计：只查公开owner源码/字段，明确四类证据/unknown界线，不碰源码/真实H2/真实调用。实际修复包仍串行；SAFE-DIAG的unverified不是最终交付目标，SCENARIO之后还需按可核证据落实受控四维分类，缺证据不能冒充0。
- SAFE-DIAG R1首轮283passed/1failed，唯一旧测试要求兜底block集合只含leak，与明确新增unverified契约冲突。经理授权最小同步该一行expected集合增加unverified，保留集合等号及所有原error/leak/防泄漏断言并在report披露，需定向重跑；不扩大其他旧测试改动。
- hard_evidence_audit已完成只读报告，指出实际context provenance、生命周期deleted/effective date、实体/安全语义归属、业务日期None和多轴接口缺口；不声称已实现/测试。经理已给出semantic-custody-decision.md具体方案，并向主人请求仅专门保管标注/保管复核角色的原文可见性例外，经理/开发/验收仍聚合。该决定待明确答复，不因等待时间默认授权；未读取或开放任何真实原文。
- **SAFE-DIAG R1经理限定接收**：全新safe_diag_r1_review独立302passed，原4反例及18新边界、normal30/partial21+1+8、三条真离线reason链、公开57差分、16保护hash/外网0通过；旧一行expected集合最小同步合理、原断言保留。经理已读完整review并亲核三固定hash。只接收安全诊断，不代表四轴/真实质量通过。
- **主人明确授权专门保管标注与复核**（2026-11-12接续）：按semantic-custody-decision.md的两个隔离保管角色例外，原金标/30题/阈值不变，其他角色仍聚合。当前未新开放原文；先完成已接收SAFE-DIAG本地commit，再派保管。接续核HEAD09ddc87、暂存空、未发现旧python/node，三固定hash未变；客户端日期已11/12，后续计划/GO需重新生成，不复用旧created_utc。
