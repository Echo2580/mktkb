# T306 独立验收记录（集成验收与候选交付）

> 验收人：项目经理（MainAgent）；日期：2026-11-22；基线 HEAD `0d6ba61`（工作区 P3 改动未提交）。
> **结论：PASS（正式）。C1 已于 2026-11-22 15:20 整改、15:45-15:47 经我独立复核关闭，见 §八。**
> 三列状态：开发自测 PASS；独立验收 **PASS**；真实环境 NOT-RUN（须主人单独授权）。
> 本验收零 git 写操作、零业务代码改动、零 `var\` 写入；复跑日志与包装器均在 `T306-acceptance-rerun-*.txt` / `T306-acceptance-evidence/`。

## 一、独立复跑结果（不采信自报）

| # | 命令（工作目录） | 退出码 | 通过/失败/跳过 | 我的日志 | 与自报 |
| --- | --- | --- | --- | --- | --- |
| 1 | `..\.venv\Scripts\python.exe -B -m pytest tests/operations -q`（backend） | 0 | 69/0/0 | T306-acceptance-rerun-operations.txt | 一致 |
| 2 | P2 最小回归五路径（backend） | 0 | 450/0/0 | T306-acceptance-rerun-p2.txt | 一致 |
| 3 | `npm.cmd run build`（frontend） | **2** | — | T306-acceptance-rerun-build.txt | **不一致 → C1** |
| 4 | `npx.cmd playwright test --config=playwright.operations.config.ts` | 0 | 26/0/0 | T306-acceptance-rerun-t303.txt | 一致 |
| 5 | `... playwright.operations-qa.config.ts` | 0 | 19/0/1 | T306-acceptance-rerun-t304.txt | 一致（skip 为 desktop Q10 设计性） |
| 6 | `... playwright.operations-assets.config.ts` | 0 | 20/0/0 | T306-acceptance-rerun-t305.txt | 一致 |
| 7 | `... playwright.operations-integration.config.ts` | 0 | 16/0/0 | T306-acceptance-rerun-integration.txt | 一致 |
| 8 | 双复算包装器（只读脚本原样执行、输出改验收目录） | 0 | T301 19 项全一致；集成 consistent=true | T306-acceptance-rerun-recompute.txt | 与开发 JSON **逐字节一致** |
| 9 | 性能探针包装器（只读、输出改验收目录） | 0 | 计划/规模与开发一致；中位最大 0.028ms、单查询最大 0.106ms、无全表扫描 | T306-acceptance-rerun-perf.txt | 一致（阈值 <0.05ms 成立） |

我的复跑轮次（reporter 只新增）：T303 `rounds/2026-11-22T07-09-26-983Z`、T304 `07-11-34-722Z`、T305 `07-12-32-854Z`、T306 `07-13-20-080Z`；JSON stats 分别 26/0/0、19/1/0、20/0/0、16/0/0。

启动核对未重跑（重跑需起服），以三重互证代替：`logs/launcher-offline.txt`（8077/5673 healthz 200、隔离数据目录、离线提示、回车清理退出码 0）+ `var-before.json` 与 `var-after.json` SHA256 一致（15071 文件）+ `tools/start_local.py` 静态实读（离线分支强制 `rag_provider_mode=offline`、清空模型三键、`ocr_disabled=True`；无 `--data-dir` 参数）。结论：离线隔离试跑成立，`--owner-live` NOT-RUN。

## 二、必改项 C1（阻塞转正式 PASS 与发布提请）

**C1：当前候选 build 失败（退出码 2）。** `frontend/e2e/operations-integration.spec.ts` 两处 TS6133 未使用声明：
- L116 `openRequest` helper 定义后从未调用；
- L216 `const employee = summary.accounts.employee;` 声明后未使用（login 内部自取账号）。

证据时效问题一并指出：开发 `logs/frontend-build.txt` 生成于 14:28:52，早于该 spec 最后修改 14:39:00，属**过期证据**；自报 build 0 与当前代码状态不符。Playwright 不做类型检查，故四套用例仍绿，但 build 门禁独立失败。

修复要求（仅动 T306 独占新文件，不得碰业务代码/冻结文件）：
1. 删除上述两处未使用声明（或改为实际使用），不改任何断言与用例语义；
2. 复跑 `npm.cmd run build` 至退出码 0，**在最终代码状态之后**重新生成 `logs/frontend-build.txt`；
3. 因 spec 被触碰，复跑集成套件至 16/0/0 并新增轮次目录；
4. 交回后我复核 build 日志时间戳晚于 spec 修改时间、复跑退出码与用例数，转正式 PASS。

## 三、边界实核（开工/收工一致）

- git M 集合 9 文件与基线完全一致（含 `.claude/handoffs/_index.md`、P2 manager.md 等非 P3 在途改动，保留）；HEAD `0d6ba61` 未变；零 git 写操作。
- `backend/src/**`、`frontend/src/**` 无任何文件 mtime 晚于 T306 开工（11-22 14:20）；`package.json/lock` 仍 02:23；e2e 晚于开工的仅 integration seed/spec；`tools/start_local.py` 与两个 `.cmd` 均 11-21（P3 前提交态）。
- 三配置整改范围与裁决一致：T303 testMatch 收窄 + 轮次 reporter + gracefulShutdown + 直启 vite（端口/数据目录/projects/超时未动）；qa 保留双栈与 T304_STACK、testMatch 未动；assets 仅加轮次 reporter。
- `var\` 三库时间戳未变（11-21 16:42:50 / 11-05 20:52:22）；var 快照哈希前后一致。
- T301 冻结库主库 11-21 23:42:48、WAL 0B 未变；仅 `-shm` 被只读连接重建（15:11，32KB）——WAL 只读打开的正常现象，数据零变化，记观察项非违规。
- T303/T304/T305 旧 `playwright-*.json` mtime 仍 04:18/13:51/14:11，未被覆盖；轮次目录只新增。
- 收工端口 8288-8293/5299-5304/8077/5673 全部释放；无新依赖、无付费调用、无 CREATE INDEX。

## 四、集成用例质量实读

`operations-integration.spec.ts` 全文实读：期望值全部读 seed-summary.json，不手抄接口数据；I1 趋势点击→since/until=当日+总数==今日完成量+抽屉引用卡；I2 冲突两方值/名称/版本/active+引用 0+资产抽屉生效版本；I3 失败下钻+「查看关联问答」document_id 串联+总数==related_requests_count；I4 三页门禁+六接口 403 ROLE_REQUIRED（用例标题写"五个接口"实为 6 个，小瑕疵不阻塞）；I5 关闭栈 5304+主栈 not_recorded；I6 空窗口计 0/无 NaN/无假百分比+assets 引用全 0+无匹配筛选空态；I7 mobile 断言视口走通 I3 链；I8 分母/状态/holdout 扣留/无发起入口/leak-into-ui 不出现。断言均为种子真实值，无伪造。

## 五、上报事项裁决

- **A（I6 空窗口资产口径张力）：接受开发建议，维持 T305「当前库存」口径与现测法。** 理由：与 T305 验收已接受口径一致；改窗口过滤需动后端查询，超出 P3 只读范围；I6 已如实断言「空窗口引用全 0 + 无匹配筛选空态」，未伪造 0 行。若主人后续要求资产列表按窗口回溯，另立任务改口径并重跑 T305/T306。
- **B（perf_probe.py 引用缺口）：接受，记文档措辞瑕疵。** 我派单原文要求新建于 `T306-evidence/scripts/`，产物位置与方法符合派单；开发「dispatch 引用 T302 不存在」的表述有偏差，不影响结论。后续任务书引用真实路径。
- **C（D5 冲突持久 2 行）：沿用 T301-D5 裁决（查询侧排除为正式口径），产品行为缺口继续挂待决，不阻塞 P3 发布。** 复算仍为 2 行且与冻结预期一致，口径未私改。
- **D（启动器无 --data-dir）：接受现状，不阻塞发布。** 离线试跑已显式隔离；建议后续任务给启动器加显式数据目录参数或在 `.cmd` 固化 `MKTKB_DATA_DIR`。**发布说明须写明：双击 `.cmd` 默认写真实 `var\`。**
- **E（T303 配置头注释一行）：接受，属收窄说明，范围内。**
- **T302 补充单：同意暂不立单。** 触发阈值采纳开发建议：单窗口完成量接近 400 行或需 30 天逐条对账；资料数超约 200 份或需按最新版本排序/精确筛选。是否立单转主人拍板。

## 六、发布条件对照（任务书 §4）

1. 三页与查询可用、三场景过独立验收：T303/T304/T305 已 PASS；I1/I2/I3 双 project 我复跑 PASS；**待 C1 关闭后本项闭环**。
2. 汇总可复算、异常有状态：双复算我独立复跑逐字节一致；Trace 关闭/未记录/partial 状态齐备 → PASS。
3. 员工门禁、无 P2 回归：六接口 403+三页门禁复跑 PASS；P2 450/0 → PASS。
4. 候选/环境/替身/待验证/回退已记录：`T306-release-candidate.md` §1/§3/§5 齐备 → PASS。

## 七、下一步

1. 开发窗口按 §二 关闭 C1（两处删除+build 0+集成复跑+刷新 build 日志），交回我复核转正式 PASS。
2. C1 关闭后，我将发布候选（4 组提交拆分+三列证据+剩余限制+回退方式）提交主人作 P3 发布决定；A/D/补充单三项随附请主人拍板。
3. 真实环境验证（`--owner-live`、真实模型/OCR/Ragas）全程 NOT-RUN，须主人单独授权后另立验证单。
4. git 提交/回退一律主人批准后执行；本验收与开发窗口均零 git 写操作。

## 八、C1 关闭复核（2026-11-22 15:45-15:47，转正式 PASS）

- 改动范围实读：`operations-integration.spec.ts` 仅删除原 L116-119 `openRequest` helper 与原 L216 `const employee` 声明（现文件 357 行，I1-I8 断言与整改前逐行一致，仅行号平移）；e2e/src/配置中晚于开工的改动仍仅 integration seed/spec 与四配置，spec mtime 15:20:06 为 C1 唯一代码改动。
- build：开发日志 15:20:15 晚于 spec 15:20:06（过期证据问题已消除）；我独立复跑 `npm.cmd run build` 退出码 0（`T306-acceptance-rerun-build-c1.txt`）。
- 集成：开发新轮次 `rounds/2026-11-22T07-20-21-478Z` stats 16/0/0；我独立复跑 16 passed 退出码 0，新轮次 `07-45-46-367Z` stats 16/0/0（`T306-acceptance-rerun-integration-c1.txt`）。
- 其余回归/复算/性能/启动证据 mtime 均 14:41-14:45，早于 C1，§一 独立复跑结论继续有效；开发六份回归日志数字与自报一致（69/450/26/19+1skip/20/16）。
- 收工边界：M 集合 9 文件、HEAD `0d6ba61`、var 三库时间戳均未变；端口全释放；轮次只新增。
- **C1 关闭，独立验收转正式 PASS；提请主人作 P3 发布决定（§七.2）。**

## 九、主人裁决记录（2026-11-22）

- 主人回复「A」。按上报清单理解为对 **上报 A 的裁决：接受现测口径**——维持 T305「当前库存」口径与 I6「空窗口引用全 0 + 无匹配筛选空态」测法，不改代码、不另立任务；与 §五 PM 裁决一致，至此 A 闭环。
- B/C/D 与 T302 补充单按 §五 建议维持（接受/挂待决/暂不立单），均不阻塞发布；D 的发布说明义务（双击默认写 var）保留。
- **P3 发布决定与 git 提交仍未获明确批准**：本次未执行任何 git 写操作、未改任何代码。待主人明确「批准发布」后，按 `T306-release-candidate.md` §1.5 四组拆分执行提交并回报 sha；真实环境验证仍须单独授权。