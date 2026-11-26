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

- **2026-11-12新会话恢复，四状态已明确批准**：主人对恢复T207及scenario-expansion-decision.md四状态替换的答复“批准”。沿用T207内连续推进/每包全新开发及全新独立验收/经理接收后本地commit；完成T207暂停。旧双状态枚举及自动分配提示不得照用；不扩40/20、中心8.5/6.5/3/2、1600请求。
- 恢复只读核对：codex/p2-e2e / c3051056、暂存空；账本/budget/旧GO与两旧保管密文五hash全匹配交接，旧协调/面试/tmp改动保留。当前Host CLI不可用，沿用已批准内置助手；本树无旧子助手。任务书§12已取消5小时额度检查，不以技能默认覆盖。新真实/预留0。
- 已建立v0.2公共四状态JSON（原计划0基下标子序列、固定多可行优先序）及新保管schema，原v0.1不覆盖；派专门隔离`/root/custody_v2_annotator`按P2-T207-CUSTODY-V2-annotate.md重新标注。实体2/日期2旧缺口只有冻结语义可证时明确，否则保留unknown。该角色不看真实结果，经理仅收安全聚合。下一步全新独立保管复核后，串行SCENARIO/HARD-EVIDENCE。

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
- SAFE-DIAG本地commit **c3051056c4f0bb5a4481ea68ac77111eb8213293**。源/测试/契约严格空白检查通过；不可变原失败日志/patch及字节相同工具副本含固有尾随空白/EOF空行，按命令级证据格式例外检查（不改全局配置、不重写原证据）。受控staged扫描110文件exact真实id/≥12字完整题面回合参考答0命中；无任意子串审计声明。未push/合并/部署；新增真实0。
- 已为主人批准的专门保管角色落公共schema `docs/evaluation/p2-h2-custody-annotations-v0_1.md`；只有密文逐题附件，经理/开发/验收只聚合。下步先保管标注→独立保管复核，再依冻结附件串行SCENARIO/HARD-EVIDENCE开发及独立验收；不将附件或固定0当真实证据。
- 保管首份附件已完成，独立custody_review结构/绑定/保全PASS、语义FAIL：5分歧；双状态22/0/8、跨实体required28/unknown2、日期2缺口。仅密文纠正；原附件/金标不变，禁止冻结。公共替换四状态可覆盖30/30、内在金标冲突0，仅只读建议。
- 经理纯公开Mock预检替换四状态B8/9/11/13，总41，30题36回合公共合成形状185请求/worst1.676032元/OCR0，外网0，固定三hash未变。见T207-CUSTODY/public-snapshot-refined-preflight.json；新真实计划/GO未生成。
- **主人最新要求暂停/交接（2026-11-12 08:19起）**：对四状态批准问题答复为先暂停、要交接、新窗口接替，未批准四状态。所有子助手已completed/停止，未观察到python/node，HEADc3051056/暂存空/三固定hash不变；未新增真实调用/预留。后续只写暂停记录与交接校验，不开发/测试产品/commit。交接2026-11-12-081943-t207-quality-repair-paused.md。
- 环境复核：可写TEMP通过；默认沙箱socketpair与ASGI各10秒有界超时、自有子进程已退出。必要命令级沙箱外同一recovery_preflight.py两项exit0；recovery-preflight.json记录结果，固定三hash不变。属环境限制，不记产品失败；后续必要定向E2E沿此最小命令级权限，不skip/xfail。
- SCENARIO开发提示已整体更新为四状态v0.2与保管唯一归属，不再沿用旧双状态自动分组；包含发送前绑定/30唯一覆盖、四状态active与B、部分失败保留/安全组合、默认57差分的验收依据。待保管独立接收后派发。
- custody_v2_annotator安全中报：四状态已30同序唯一归属，scenario unknown0；原实体2处仍unknown、日期2处as_of缺口保留，无权限阻断。尚在自核/未独立复核，不能冻结或称质量通过。已明确禁止依据预测产品结果将未知改N/A；后续运行期真实无事实使用的可核性须由独立证据分类审查，不由保管者预判。
- 后续采集包提示P2-T207-EVIDENCE-CAPTURE-dev.md已准备（未派发）：默认no-op观察hook、实际CompletionInput/直接RAG/owner/生命周期/日期原值、独立DB投影与仓外认证密文绑定；分类重算另包。保持实际日期None，不在评测层事后补日期；不得额外模型/检索重放。须SCENARIO独立接收后才开发。
- 新标注正式交付：30同序唯一、scenario unknown0；新annotations-v0_2密文sha=3d60c27364244a6ff8df76f66994ee50e5037649ea346c4b538f1fb9175ce4d0，经理仅hash核验匹配/读取安全报告，未解密。标注角色已停止写入。
- 已派全新隔离/root/custody_v2_reviewer，依据P2-T207-CUSTODY-V2-review.md独立逐题复核语义/优先序/绑定/保全。标注自核不作为独立证据；四轴unknown或日期缺口仍需如实保留，真实质量未放行。
- 独立保管复核中遇自动审批拒绝：复核角色报告“隔离读取冻结逐题语义”工具动作被拒，理由为逐题打印冻结题干/答案/标注违反仅回传安全聚合限制。已要求不绕过拒绝，继续不依赖原文的结构/绑定核验，并依据semantic-custody-decision.md及v0.1保管操作§2原有两个隔离角色原文例外核证边界；若仍拒绝，语义必须NOT-VERIFIED，不以标注自核替代。经理未读取保管会话/原文，SCENARIO开发未派发。
- 上述审批边界已恢复：复核角色先核实主人决定，再提交原有授权/v0.1隔离显示条款/仅本角色可见说明，同一必要读取获准成功；未改名、分片绕过或扩大角色范围。独立语义复核继续，首次拒绝与核证恢复仍须报告披露。经理仍不读原文。
- **CUSTODY-V2经理限定接收**：全新独立复核structure/semantic_consistency=PASS、分歧0、四状态30/30且scenario unknown0；正式verdict/quality_readiness仍BLOCKED，实体unknown2/日期锚点缺口2保留。经理已读取安全报告/聚合、亲核新review密文sha=963918ffd51d717871470f1a7aea95bc6dc8c3e34062b259b8e41bd168eda2c3匹配；未解密，两个保管助手均停止。
- Ruling：仅冻结无分歧的scenario assignment用于离线实现，并接收诚实保留unknown的结构/语义一致性；不冻结为完整质量就绪，不授权真实、不更改独立BLOCKED。理由：30题归属、hash及固定优先序已独立核证，与尚未有实际证据的四轴质量是不同范围；若后续证据不足仍阻断。公开记录T207-CUSTODY-V2/manager-acceptance.json。
- CUSTODY-V2限定接收材料已本地commit a751889bd4673fe43ba9c631f4e2ea13ce4fe585，11文件仅公共契约/保管安全聚合/授权决定与环境证据；逐文件范围与空白检查通过，经理手工核公共内容未含逐题信息。两新密文仍仓外，不入Git；未提交协调/面试/tmp或旧CUSTODY目录。暂存空，三固定hash未变，未push/合并/部署。
- 派发SCENARIO前状态：源码/测试无未提交diff，所属仍T207，沿用批准的四状态设计及每包全新独立验收；实际语义证据缺口保留，不因本commit称质量通过。
- 已派唯一开发/root/scenario_v2_dev（内置继承当前模型/档位，非wb），BASE=a751889；完整依据P2-T207-SCENARIO-dev.md。写域仅scenario必要接线/测试/契约/本包报告，零真实、不commit/stage、不读真实附件，独立验收经理另派。下步等开发停止后全新SCENARIO独立验收；EVIDENCE-CAPTURE及HARD-CLASSIFY提示已备未派发。
- 后续真实凭据路由缺失：现有runbook仅仓外p2-live.env/p2-holdout.env占位路径；只查文件名（未读凭据）在封存目录/11月visualizations及临时目录未找到，临时目录部分子目录拒绝访问不冒称全搜。已异步向主人只询问白名单凭据文件绝对路径、不要求密钥值；离线开发/验收照常，未答复前不推进依赖凭据的真实步骤。未读取项目.env。
- 另只读核对官方DeepSeek/百炼价格页，现有chat高峰输入2/输出8、北京embedding0.5/rerank0.8元每百万token上界仍覆盖所列原价；已写pricing-check-20261112.md，非新plan/GO或供应商余额。未发模型API。
- SCENARIO开发中报（未接收）：已实际观察新增模块缺失红例，受控load_scenario_contract与opaque contract/subset/ingest_plan/build_plan/validate_run草案已实现；30/36完整身份、8bindings、两新密文hash及严格四轴结构接入。尚缺P2RunPlan/runner/live/CLI、组合、真Mock四库/首错停止与定向回归；无标准阻断、无真实内容读取/调用/资金文件改动。独立验收依据P2-T207-SCENARIO-verify.md已准备，等开发停止后派。
- **主人新指令（凭据问题答复）**：主人回答“我不知道，找不到就先不弄吧”。按该问题明确上下文，暂不做依赖凭据的真实复测、不再搜索凭据；已向主人说明继续当前离线开发及独立验收，完成后停在真实调用前。不得读项目.env、重建凭据或因旧GO恢复真实。T207完整质量仍未验证，后续真实须主人恢复。
- **主人提供凭据源**：在经理已说明项目.env须仅受控读取白名单/不显示密钥后，主人指定D:/GPT项目/市场部AI知识库/.env。按该具体输入将必要读取限定为受控进程内存：只筛ALLOWED_ENV_NAMES、用既有parse_env_text校验，不把内容给模型、不复制/另存env文件、不修改源文件。此前“找不到先不弄”的路径阻断已消除；原真实授权仍须离线接收/精确计划/新GO才执行，当前无真实发送。
- 本次CHECK_ONLY：文件存在、REQUIRED_ENV_NAMES缺失0、DeepSeek与DashScope host匹配，默认模型名与冻结deepseek-flash不一致（未输出任意配置值）。后续进程必须固定已批准计划model=deepseek-flash，不修改.env；不得因此调用其他默认模型。凭据值输出0/新凭据文件0/真实0。真正执行前还需把此源的内存白名单装配封装成可独立核验入口，保持既有包装器默认拒绝.env的行为，不让普通入口默认加载。
- **主人最新停止边界**：主人明确“真实复测我用另一个AI进行，你当前任务结束可以暂停，因为没有额度了”。已回复：完成当前SCENARIO离线包及必要全新独立验收后暂停，不启动EVIDENCE-CAPTURE/HARD-CLASSIFY/环境入口/真实包。已通知唯一开发收束必要实现/定向检查并停止写入，不为省额度降标准。后续真实由另一AI接替，需结果/未验证/剩余阻断/精确现场交接；不在本会话签新GO或真实发送。
- **2026-11-12 主人要求继续，恢复中断包收尾**：上一scenario_v2_dev明确因usage limit失败，未交付report/未独立验收；非产品失败、非已完成。当前内置树仅经理，未观察到python/node写入者（非全宿主审计）。HEAD仍a751889、三固定资金hash不变、暂存空；保护已有7个evaluation接线改动和新模块/测试，未重做。
- 已派全新唯一接续开发/root/scenario_v2_finish_dev，依据原P2-T207-SCENARIO-dev.md从实际工作区继续：最后32通过+3E2E红例仅旧自报，需实际收尾并定向核验/报告，之后全新独立验收。沿用最新停止边界：只当前SCENARIO离线包，真实另AI，不派后续采集/分类/环境/真实，不push/合并/部署。
- 接续开发实际中报：本次完整SCENARIO自测39项=36passed/3failed（11.40s）；四库CLI正常/首错停止/排除历史来源三项已通过。剩余nested enum TypeError、加载后dataset可变未拒绝、公共corpus hash未核验，正在必要修复；经理另提出组合入口须走既有全卡validator，防缺diagnostics/unknown→pass/非法execution_mode绕过跨层等式。上述均开发中、不称独立验收或接收。
- 接续开发中报：组合绕过等新增13项边界首跑11failed/2passed（evidence/red.txt，尚待正式交付）；已修删diagnostics、unknown→pass、删unverified、metadata未知键/bool/坏scope等；完整SCENARIO49passed（9.66s），真CLI四库/首错停/合成输出扫描通过。当前正跑必要定向链与57默认差分，未独立验收/未接收。
- SCENARIO开发正式交付并停止：report.md57行；新执行契约/runbook仅§13；本次最终346passed（SCENARIO52含在内）、guard346外网0/loopback65、57公开差分/默认plan/binding/config一致、10保护文件同基线。正常合成CLI30/36=5pass25fail/error0，首库ingest错误后3not_started/30error，均仅接线，不是质量通过。
- 已派全新独立/root/scenario_v2_review，读原verify依据/最终报告/经理review-package.diff，独立构造反例并执行必要定向检查与默认差分；只合成，不看真实题/附件/保管会话/凭据。经理新增controlled_binding_check.py仅薄封装既有loader→safe_summary/整体hash，交独立静态安全评审；通过前不执行真实附件加载，通过后经理仅零产品绑定核验。未stage/commit，后续任务不派。
- 全新SCENARIO独立review已正式PASS（spec/code quality PASS），255passed含新增29反例，guard外网0/loopback55、57默认/identity/10保护文件复算一致，验收已停止。其真实附件绑定运行明确NOT-VERIFIED，不能据此替代经理实际核验。
- 经理在独立静态PASS的受控脚本中首次加载真实附件，得到固定FAIL/actual_binding_check_failed，原字节保全actual-binding-check-initial-fail.json；未输出逐题内容、无产品/模型调用，未接收/暂存/提交。
- 为只定位安全固定原因，薄脚本增加28项闭合错误码枚举，经同一独立验收角色7项纯合成诊断安全探针PASS后执行，明确FAIL/scenario_targets_invalid。公共manager/review字段集合均完全匹配、12源公开hash差异0（未读私有内容）。
- 新controlled_target_shape.py仅输出整个附件7个固定布尔语法标志，不出逐题/轴分组/值/计数；正在交独立静态/合成评审，通过前不运行，以确定是否加载器对已冻结target结构有额外限制。所有冻结附件/schema/hash/金标保留，不因失败改金标/N/A/语义。
- controlled_target_shape.py经同一独立角色10项纯合成检查/静态安全PASS后，仅执行一次全附件语法诊断：entity_key空字符串存在为true，其余6项false（无null/其它类型/坏entity_type/filters形状或target键集合问题）。不含target值/数量/逐题或轴分组，未产品/模型调用，不再切片或反复差分。
- 已按systematic-debugging核根因：_axis额外要求entity_key非空，而冻结schema未声明该限制。Ruling：仅语法允许空字符串作未解析键占位，不将其当可信身份或清除unknown；不改原附件/标签/schema/冻结hash，所有其他类型/长度/filters/ref约束保留。
- 已派全新R1唯一开发/root/scenario_v2_r1_dev，依据P2-T207-SCENARIO-R1-dev.md，旧源码/测试快照保全在T207-SCENARIO-R1/evidence。先自建合成红例→最小一处兼容→必要定向检查/报告→全新R1独立验收→经理实际绑定核验。当前仍未接收/暂存/提交，无真实调用。
- R1开发正式交付并停止：T207-SCENARIO-R1/report.md43行；合成空键红例先准确FAIL，源仅_axis原1行条件拆为2行、契约1句，旧测试原字节前缀保留且追加24项。最终专项76passed、guard外网0、21保护件/12源hash不变；新增断言初次误要求safe_summary包含省略的零计数，已仅修新测试预期并披露，不改产品第二处。
- 已派全新R1独立/root/scenario_v2_r1_review，依据P2-T207-SCENARIO-R1-verify.md及r1-review-package.diff，重点空键不是可信身份/unknown与BLOCKED保留、类型/filters/ref等原限制及变更范围；仅合成、零真实附件读取，完成停止后经理再做一次受控绑定。当前仍不接收/提交。
- **SCENARIO R1正式独立PASS与经理实际绑定PASS**：全新R1验收113passed（当前专项76+自有37），spec/code quality PASS、外网0、21保护件/12源/旧失败与其余源码快照一致，已停止写入。经理已读完整50行review与受控脚本静态核结论，再运行既有受控绑定程序：PASS，30/36、四状态26/1/2/1；实体unknown2/日期缺口2、BLOCKED/unverified保留。输入前后hash一致、网络/产品/模型/新增预留0，没有输出逐题内容或目标值。
- 原generic/targets失败与一次语法诊断及所有独立安全补充保全，不以最终PASS删除失败。manager-acceptance.md在T207-SCENARIO-R1限定接收离线SCENARIO/R1；完整T207/P2未过，实际证据采集/四轴分类未派，准备本包本地commit后暂停。
- **SCENARIO离线包本地提交并暂停（2026-11-12 15:48，Asia/Shanghai核对）**：commit 97b0066726e5b8d6f94cbc0b63a890084550c106，74文件仅本包源码/新增测试/契约/runbook及两轮有限公共证据；CUSTODY-V2另已commit a751889。暂存空，源/测试/本包无未提交diff，三固定资金hash不变，未push/合并/部署。
- 最终范围检查与staged/working字节一致通过，未暂存私有cipher/key/env或协调/面试/tmp。源/测试/契约及非例外文件严格空白检查通过；8个原始日志/diff/已执行字节相同差分工具副本按固有空白格式命令级例外保全，不改全局配置，不声称全部新证据无提示。
- 当前所有助手completed/停止写入，未观察到python/node（非全宿主审计）。新真实产品/模型/付费/预留0，未签新GO。按主人要求停止，不派证据采集/四轴分类/环境/真实任务，不进T208/T209/T900。
- 最新交接.claude/handoffs/2026-11-12-150626-t207-scenario-offline-paused.md已更新为实际完成/暂停现场；提醒另一AI先补四轴真实证据前置与新计划GO，不能直接真实跑四库。完整T207/P2质量仍BLOCKED，实体unknown2/日期缺口2保留。
- 暂停交接最终校验完成：validator100/100 READY，无占位/潜在凭据/缺失引用，13文件引用验证。初跑1处简写证据路径误按repo根解析，已仅改完整路径后复验通过。此校验仅针对交接，不代表产品/真实质量通过。最终HEAD仍97b0066726e5b8d6f94cbc0b63a890084550c106、暂存空/本包无未提交diff，三资金hash再核相同。停止后未再派任务或运行产品测试。
- **2026-11-13 本会话 T207 连续任务单执行完毕并暂停**：01/02 A-R1 修复+独立验收 PASS（限定接收）；03 B 包 B-R1..R7 迭代，最终独立复验 FAIL-B 未闭合（单侧模型事件/信封级残余），限官方 CLI 使用；04 保管 v0.3 两角色 PASS 并冻结、04c 产品日期独立 PASS、限定准入；05 受控入口 R1/R2 修复（真实 .env 边界、模型钉住、明文清理、capture 归因、addendum 密文 sha）后限定接收；06 源码冻结/真实私有计划（30/36、26/1/2/1、B=8/9/11/13、185 请求/1.676032 元）/public fixtures B 预检/GO#1 正式签发/preflight production_ready；07 run0 在 57 real sends 后因 1 次 MODEL_OUTPUT_INVALID 首硬错误停止（aborted），run1-3 未开始；08 全新独立复核判 **T207 BLOCKED**（26/36 回合、15 pass/4 fail/1 error/6 not_executed、四轴 unknown 26/checked 0；新发现 live 信封 run_binding 与分类器白名单不兼容）。资金累计 835 请求/项目 21.9851529/40/P2 6.9142084/20；未越预算、无重试。最终报告 T207-H2-RETEST/final-report.md；暂停，不进 T208/T209/T900，不提交/推送。

### 2026-11-19 R3 修复与 T207 独立离线复验接收

- **经理限定接收 PASS，附 F-01。** 接收范围为 R3 修复与 T207 离线回归行为。独立验收交接的产品组为 289 passed、1 failed、exit 1，评测证据链为 899 passed、exit 0，新建独立探针 42 passed、exit 0。真实 R3、T207 正式质量和 P2 发布均待验收。`threshold_met` 和 `release_ready` 未放行。
- **现场亲核。** 接收前为 `codex/p2-e2e`、HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`、40 个已跟踪修改（4,786+/280−）、暂存 0。实际 Python 3.12.7、pytest 9.1.1，`mktkb` 从本仓 `backend/src` 导入。亲算 `intent.py` `10043115179457bd4b07f5a3863bb8a4157042c39adb0049ec5fff3db2fae102`、`query.py` `49ad6c783cfc435c7e0a330b661537e2ff5ebf754763de5b69f7b5d0b999af87`、`p2_hard_evidence.py` `9861c44ec34fb797fa0f02d44c053fe047a7046183b662b6d70bfc3808549624`，三项与交接相符，最后一项与 v0.6 契约批准摘要前缀相符。
- **经理复跑。** 从仓库根用 `.venv/Scripts/python.exe`、离线守卫和临时 `--basetemp` 执行三份 `backend/tests/independent/test_indep_*_20261118.py`，42 passed、exit 0。交接正文省略完整评测命令，经理按描述重建 17 文件评测组，899 passed、exit 0。两组非本机出站尝试均为 0。重建文件清单和守卫位于本会话可写可视化目录，文件名 `r3-manager-offline-groups-20261119.json` 与 `r3_manager_guarded_pytest_20261119.py`。
- **F-01 已亲证。** 单跑 `backend/tests/integration/test_r2_206a_contact_gate.py::test_g3_item_plus_contact_only_is_still_answered`，1 failed、exit 1、外发 0，唯一失败为 `_assert_byte_identical("g3", info)`。实际已返回联系人及同店店家来源。旧快照锁定仅回显物品行的缺陷态。整改只限 G3 探针及必要复跑证据，保留 G2/G4 保护。开发的 474 项是当时自选定向组，确实未纳入 `test_r2_206a_contact_gate.py`，无法覆盖本次独立产品组发现。
- **保留观察。** O-01 为嵌在标识里的数字缺结构证据时的评分行为，暂不更改冻结口径。O-02 为合法对接人查询显示同店公开字段的范围观察，独立探针确认电话与地址未进入正文或模型载荷，本轮暂不扩派。

- **F-01 已整改并由经理限定收口。** 开发仅退役 G3 的旧字节快照，以同店对接人值、唯一正确店家引用、正文及模型载荷无电话和地址替代。G2/G4 的字节快照保持。最终测试文件 SHA-256 为 `db65ce9aac3f129f549e70f2496a734e51ada5d593c96c2b3a02e72d1188c5cf`。开发实测 206a 10 passed、重建产品组 312 passed。全新独立窗口亲跑最终字节，31 文件重建产品组含完整 206a，312 passed、exit 0，三份独立交付 42 passed、exit 0，另有两条同店活动版本精确引用的合成 HTTP 探针通过。G3 断言敏感性为 1 个正例通过、9 个反例被拒。各批非本机出站尝试 0。原 29 文件组的完整命令未交接，其 289/1 历史结果保留。两角色均停止写入，暂存 0。

#### 下一授权窗口（待主人批准）

| 授权项 | 范围与交付 | 拟授权费用硬顶 |
|---|---|---:|
| 同轮证据确认 | 指定保管人及受控渠道。在受控进程中核历史 R3 封存，回传 C30 固定失败检查 ID、首次偏离边界，以及 C15/C20/C30 轴状态、原因码与来源。仅回传脱敏投影，零供应商调用。 | 0 元 |
| 真实 R3 | 指定保管人、执行者、GO 签发与安装责任。仅 `run3 / post_v05_without_v01` 5 题 6 回合和本计划的最少必要数据。供应商范围为 DeepSeek 的回答/扩写及百炼的嵌入/重排，拟计划请求 39。生成新 plan、binding、GO，完整预检后执行一次，首错停止、零自动重试，封存、独立复核与对账。 | 0.30 元 |
| T207 正式验收 | R3 收口后另行授权。同一最终代码、评分器与契约，30 题 36 回合不重不漏。四场景分别生成新 plan、binding、GO，拟计划请求合计 191，外发供应商范围同上。统一以本轮封存重建，≥24/30 且硬失败 0，独立复核再由经理接收。 | 1.70 元 |

用现行计划构造器、合成 ID 和公开的各场景回合/批次数（14/9、10/10、6/13、6/15）复算，R3 计划费用上界 0.296064 元，正式四场景合计 1.688320 元，单笔预留峰值均为 0.018688 元。上表是拟授权硬顶。受权角色须按实际新计划、现行账本和各成本中心余额重核，漂移超限时停在签发前。三个授权各自生效。当前没有新的真实运行、费用承诺或 GO。
