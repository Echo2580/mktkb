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
