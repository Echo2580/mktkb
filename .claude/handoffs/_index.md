# 协调区索引（_index.md）

> 唯一事实源；状态一律用门编号（G0–G6）。「待审」列有且最多一个「是」。
> 当前阶段：**P0 已通过（主人 2026-11-05 G5 决策：通过）**，T009 G6 已收口；**PR #1 已合并**（2026-11-05 21:38，merge commit `083eaef`，父 `8e44158`+`35815c3`；P0 38 个交付 commit sha 保留）。P0 三项可选项（阈值审批 / 真实 baseline / 设计 §7.2 回写）仍未执行。下一阶段 **P1 待 PRE-2 两个文件落盘**（`budget.json` + `S2-LIVE-GO.json`；成品草稿就绪于 `p1-gate-drafts/`）。
> 基线：`main` @ **`083eaef`**（P0 已并入；原基线 `8e44158`，tag `v0.1-local-20261104`）；P1 将自 `083eaef` 建 `p1/fix-retrieval`。
> 已确认参数（主人 2026-11-04）：一包一个新开发助手 + 一包一个新验收助手；全部完成后开 1 个 PR；允许继续拆分（见下表 T003a–T008b）；分支基线 `8e44158`；`fixtures/` 既有只读、允许新增 `fixtures/evaluation/**`。
> 人工门：主人已接管验收节奏（2026-11-05 起）；P0 T009 收口门保留待主人决策。

| ID | 任务 | 状态 | 轮次 | 待审 | 阻塞 |
|---|---|---|---|---|---|
| T001 | Trace 契约与版本绑定 | G4 通过（review PASS；dev commit `7b02f40`） | 0 | 否 | — |
| T002 | SQLite Trace 仓储 | G4 通过（review PASS；dev commit `2ac976f`） | 0 | 否 | T001 ✅ |
| T003a | tracer 内核（contextvar/Span/finish） | G4 通过（review PASS；dev commit `dea4d5d`） | 0 | 否 | T002 ✅ |
| T003b | 配置 + 中间件接线（X-Trace-ID） | G4 通过（review PASS；dev commit `d41d19f`） | 0 | 否 | T003a ✅ |
| T003c | RAG 路径埋点（index/retrieval/answer） | G4 有条件通过（review 仅 §5.4 FAIL：检索前拒答核对契约缺口；代码不返工，移交 T003d；dev commit `776497f`） | 0 | 否 | T003b ✅ |
| T003d | QA/legacy 路径埋点 + 契约修订 | G4 通过（R1 定向复验 PASS：`review-R1.md`；dev commits `b811f9f`+`71756f5`；全量 1307 passed） | 1 | 否 | T003c 有条件通过 ✅ |
| T004a | 评测数据集 + gold 解析 + fixtures | **G4 通过**（独立验收 PASS：`review.md`，§5.1–5.8 全 PASS；3 MEDIUM/2 LOW 非阻断；dev commit `574e288`；验收方全量 1377 passed） | 0 | 否 | T003d R1 ✅ |
| T004b | scorer（值/来源/kind/分页/拒答/检索） | **G4 通过**（独立验收 PASS：`review.md`，§5.1–5.8 全 PASS；3 MEDIUM/5 LOW 非阻断；dev commit `f126598`；验收方全量 1377 passed） | 0 | 否 | T004a ✅ |
| T005 | Replay / Local Runner + 运行清单 | **G4 通过**（独立验收 PASS：`review.md`，§5.1–5.6 全 PASS；2 MEDIUM/3 LOW 非阻断；dev commit `80fd092`；验收方全量 1397 passed） | 0 | 否 | T004b ✅ |
| T006a | 门禁硬层（8 项）+ 退出码 | **G4 通过**（R1 定向复验 PASS：`review-R1.md`；dev commits `f6bb3c4`+`90d7133`；全量 1477 passed） | 1 | 否 | T005 ✅ |
| T006b | 门禁质量层 + 校准 + 豁免 | **G4 通过**（独立验收 PASS：`review.md`，§5.1–5.6 全 PASS；3 MEDIUM/5 LOW 非阻断；dev commit `5a4c054`；验收方全量 1506 passed） | 0 | 否 | T006a ✅ |
| T007 | Baseline + Diff + 报告 | **G4 通过**（R1 定向复验 PASS：`review-R1.md`；dev commits `6447b85`+`08536ed`；全量 1551 passed） | 1 | 否 | T006b ✅ |
| T008a | CLI 与 P0 全流程 run | **G4 通过**（独立验收 PASS：`review.md`；exit 4 端到端 NOT-RUN 记为 GAP；dev commit `f2c0209`；全量 1586 passed） | 0 | 否 | T007 ✅ |
| T008b | P0 七条验收测试 + p0-report | **G4 通过**（独立验收 PASS：`review.md`；5 LOW 非阻断；dev commit `2f7b174`；全量 1593 passed） | 0 | 否 | T008a ✅ |
| T009 | 独立验收与 P0 收口 | **G6 已收口**（主人 2026-11-05 决策「通过」；总验收「有保留 PASS」`docs/reports/OBS-EVAL/P0/review.md`；全量 1593 passed） | 0 | 否 | T008b ✅ |
| T100 | P1 前置：基线测试耦合修复（硬编码旧真实配置） | **G6 已收口**（dev commit `b35ae72`；独立验收 PASS `review.md`；全量 1593 passed；主人 2026-11-05 批准新增） | 0 | 否 | PRE-2 ✅ |
| T107 | regression suite 与数据集契约扩展 | **G6 已收口**（dev commit `36fe095`；独立验收 PASS `review.md`；regression 7/7 RED；全量 run2 `1603 passed`，run1 为既有 flake `test_lifecycle[v05]`、隔离 3/3 过） | 0 | 否 | T100 ✅ |
| T101 | ERR-03 词表语境与法规优先 | **G6 已收口**（dev commit `a7282b3`；独立验收 PASS；RG001 RED→PASS；b0/badcase hard `[]` 与 case 级不变；全量 1614 passed；PM 裁定 A 两处窄改已核） | 0 | 否 | T107 ✅ |
| T102 | 组 A 状态继承（ERR-01/02/D5） | G1 已派单（开发中；最高风险） | 0 | 否 | T101 ✅ |

## P1 开工门（2026-11-05，PM；详见 `2026-11-05-p1-kickoff-gate.md`）

| 门 | 状态 |
|---|---|
| P1-PRE-1 Holdout 30 | ✅ 已交付并 PM 结构验收（sha 实测一致：questions `a8c8aa7f…6738` / labels `8f713a2a…c1bf`） |
| P1-PRE-2 预算划转 + GO 改版 | ✅ **已签并验签通过**（2026-11-05 21:5x，主人授权 PM 写入；budget sha `084ba9ac…`、GO sha `39070de5…`；旧 GO 备份 `S2-LIVE-GO-20261104.json`；GO 有效至 2026-11-30；零 HTTP/零账本写入） |
| P1-PRE-3 P0 遗留复核 | ✅ 完成（kickoff §4：无阻塞项；8 项带入 P1 handoff；§7.2 口径已由主人定：不回写、T110 引用追认） |
| P1-PRE-4 D-3 兼容授权 | ✅ 已书面确认（2026-11-05；T104/T106 可开工） |
| G0 P1 分支基线 | ✅ **已解除**：PR #1 已合并 `083eaef`，P1 自 `main@083eaef` 建 `p1/fix-retrieval` |
| G0 基线测试耦合 | ✅ **已批准 T100**（主人 2026-11-05）：修 1 条硬编码旧真实配置的测试（`test_s4_stage_limit.py`），待发令开工后派单 |

> 节奏（主人 2026-11-05 定）：**T111 pilot（10 题）跑完停一次**给主人过目再放全量；**零 live 包不提前开**；**PRE-2 落盘后先等主人发令开工**。`_scratch` 已按主人授权清理。
> 子智能体模型（主人 2026-11-05 定）：开发/验收均 `wb / cn:deepseek-v4.1-flash`，**推理档统一 `max`**（开发/验收/T111/T900）；详见 kickoff §12；与项目 20 元账本无关。
> P1 执行（2026-11-05 开工）：分支 `p1/fix-retrieval`（自 `main@083eaef`）；T100/T107/T101 已收口；T102 开发中；串行 `T107→T101→T102→T103→T104→T105→T106→T108→T109→T110→T111→T112→T113→T114→T900`；T111 pilot 后停一次给主人过目。

> PM 只读核对（2026-11-05 21:0x）：账本累计 **15.0566296 / 20**（S2-DEV 已占 15.0266296 / 18.4，381 预留/381 结果，剩余 4.9433704）；holdout 完好；P1 脚手架未创建；P0 三项可选项仍未执行。**PRE-2/PRE-4 签署且分支基线确定前不派单。**

## 遗留项（非阻塞，T009 时逐条复核是否仍存在）

1. T001 report 写"每文件测试数 25/23"，实测为 36/32（`review.md` §6 已更正；不影响 §5 判定）。
2. T001 证据 04/05 为 amend 前 commit `6680f85` 的快照，最终 HEAD 为 `7b02f40`（report 已披露折中）。
3. `legacy_with_rag_candidates` 在设计与 §6.4 表中的组合未明示——T003c/T006a 前须给出显式口径（当前 T001 实现为共用 legacy 规则）。
4. T001 基线 1018 passed 未由验收方独立重跑（以"0 failed/0 error + 新增 68 + 既有测试零改动"等价论证）。
5. `pipeline_version()` 首次调用延迟 import 有秒级开销（P0 仅 run 级调用，可接受；T005/T006 运行时留意）。
6. `config_hash` 白名单需随行为字段扩展；`token` 命名规则使 `max_output_tokens` 类字段不能进白名单（T005/T006 前评估）。
7. T003a 验收非阻断：内核 `_coerce_mode` 接受 `mode=live`（P0 禁止）→ T003b 已硬约束中间件不传 live；T006a 门禁不得依赖内核拒绝。
8. T003a：`annotate()` 可覆盖启动参数字段（mode/scope/replayed/path/outcome_kind）→ T003c/d 只写数据字段，gate 把 trace 当不可信输入。
9. T003a：`*_json` 属性为非法 JSON 时条件 Span 校验 fail-open → T006a 门禁加 JSON 合法性校验。
10. T003a：`replayed=True` 且缺 outcome 时 status 优先 `replayed`（设计 §6.1 口径），T003b/c/d 知悉。
11. T003a：dev 证据 05 为 amend 前 stat，最终 HEAD stat 由验收方证据 04 补采（非返工）。
12. 既有全量测试会向 gitignore 的 `docs/evidence/` 写测试产物（既有行为，不入 commit）。
13. T003b：中间件先落 `path=rag`、`request_id=None`、`status=incomplete` → T003c/d 必须用 `set_path/set_request_id/set_outcome` 覆盖；HMAC 透传与默认 DB 路径端到端断言由 T003c/d/验收补测。
14. T003b：QA POST 端点内失败（401/422）也会写一条 incomplete trace → T006a 门禁按 outcome/error 过滤，不把失败请求算进产品成功样本。
15. T003b：既有 flake `test_g08_short_budget_cancels_inflight_model_call`（时序敏感，非本阶段引入）复跑可过；全量回归时以重跑为准并记录。
16. **PM 裁决（2026-11-05）**：T003b 的 `test_middleware.py` 边界断言（`spans == []`、`request_id is None`、`status=incomplete`、`path` 默认）在 T003c/T003d 埋点后按"最小修改、只增强不削弱、精确 diff 留证"更新；授权写入 T003c/T003d handoff §4，验收方须核对只改指定断言。
17. **T003c 验收 FAIL 项（§5.4，移交 T003d 契约修订）**：`rag+no_answer` 在业务"检索前拒答"（reason=DOCUMENT_NOT_FOUND/UNKNOWN_STORE/RECORD_ONLY）时只有 `parse+commit`，与 T001 冻结表要求的 `recall/fuse` 冲突；T003c 不伪造 Span 正确。T003d 负责把 `required_spans`/`validate_required_spans` 改为 **reason-aware**（向后兼容），更新 `docs/evaluation/trace_schema_v0_1.md`，补早退路径 validate 断言与 rerank 失败断言；T006a 门禁按新口径实现。T003c 记为"有条件通过"，代码不返工。
18. T003c 验收其他非阻断：证据 05/08 为 amend 前 C1 快照（最终 HEAD `776497f` 15 文件）；`test_middleware.py` 注释仍写"spans 为空"（T003d 顺手更正注释，不改强度）；M5 rerank 失败未标 error 未被开发测试覆盖（独立探针证明实现正确），T003d 补一条断言。
19. **PM 裁决（2026-11-05，legacy 契约缺口）**：legacy 解析级早退 `not_found` 缺 `retrieve`、`legacy+conflict`/`legacy+knowledge_changed` 未定义；按 T003c §5.4 同构处理——`required_spans` 扩 reason-aware + 补齐可达 outcome 行（证据驱动、不伪造、不可达保持 fail-closed），文档与测试同步。已写入 T003d handoff §5.11/§7；T006a 门禁按新表实现。
20. **T003d 执行异常（2026-11-05 04:19）**：开发助手在提交前执行会话 failed，遗留未提交改动（已含 24 个新测试、全量 1240 passed、证据 00–07、五段报告）；已由全新上下文接续助手接管收尾（补 §5.11 + 单 commit），未丢工作、未产生第二提交。
21. 团队 8 席位已满，后续每包改用全新上下文的 subagent 执行（一包一新助手、验收独立，流程与证据链不变）。
22. **主人指令（2026-11-05 08:3x）**：停止自动推进；T004（T004a+T004b）运行完即停；余下任务完成后不再做独立验收，主人后续用其他 AI 验证。PM 已相应收窄 goal。
23. 验收证据目录 `docs/reports/OBS-EVAL/P0/evidence/verify/**`（T001–T003c 的验收方复跑证据）目前未入库（验收方不 commit）；待主人重启验收时由 PM 统一收口提交，避免遗漏。
24. T003d 证据 `01-tdd-red.txt` 为二进制（UTF-16 输出未转码）；不影响判定，属证据精度小瑕疵，T009/主人复核时注意。
25. **提速策略（主人 2026-11-05 采纳 A/C/D）**：A 测试策略——开发只跑本包+受影响目录，全量仅提交前 1 次；验收只跑 1 次全量+定向探针，不重跑旧基线全量（用 0 failed/新增数/改动范围证明）；C 证据瘦身——每包 ≤4 份关键证据、报告 ≤80 行；D 机器——提醒主人释放内存（此前空闲仅 0.6–1.5GB，曾因资源导致测试中断/flake）。自 T004b 起生效；T004a/T003d 按旧策略执行中。
26. **T003d 验收 FAIL（2026-11-05，R1 待返工）**：§5.11 唯一 MEDIUM——legacy 解析级早退后在 **commit 阶段** revision 复核升级为 `knowledge_changed`（未执行 retrieve）时 Span 实际为 `{intent_parse, commit}`，但 contracts 该行要求含 `retrieve`，validate 返回 `['retrieve']`。修法（窄、不改业务代码）：把 `legacy+knowledge_changed` 做成 reason-aware（如 reason=KNOWLEDGE_CHANGED 且未执行 retrieve → `{intent_parse, commit}`）或该行整体降为 `{intent_parse, commit}`，同步 `trace_schema_v0_1.md` §6.1.2 与回归测试。其余 §5.1–5.10、边界、非空转、全量 1266 passed 均 PASS。
27. T003d 验收 LOW/INFO：证据 `10` 的 sha256 清单漏列 `06`（其余 19/19 一致）；`09` 为 amend 前 stat、`01` 为 UTF-16（已知口径）；重放用 `annotate(replayed=True)` 写启动字段（行为正确、与 §4 字面冲突），**T006a 必须跳过 replayed 的完整性校验**；commit 阶段异常（RequestCancelled 等）仍 outcome=None，未做注入验证。
28. **P0 暂停交接（2026-11-05 10:20）**：HEAD `f126598`，分支 `p0/obs-eval` 共 9 个 commit，全量 1377 passed；T004a/T004b 未验收，T005 起未开工；验收证据 `evidence/verify/**` 与 PM 交接/提示词/review 仍未入库（工作树未跟踪）；交接说明见 `2026-11-05-p0-pause-handoff.md`。主人 2026-11-05 采纳的提速策略已写入 project-manager 技能 §11。
29. **簿记入库（2026-11-05 11:0x，主人授权）**：一次 bookkeeping commit `9d52b7c`（`chore(p0): bookkeeping`），只含 `.claude/handoffs/**`（54 文件）与 `docs/reports/OBS-EVAL/P0/evidence/verify/**`（114 文件），零代码改动；此后 `.claude/handoffs/**` 与验收证据随包入库，不再积压。
30. **T004a 验收 PASS 遗留（2026-11-05，验收方 `review.md` §2，非阻断）**：
    - MEDIUM-1：`locator` 范围型与设计 §7.2 字面（"0 个或多个 unit → GoldUnresolved"）不一致；**PM 追认**为"`unit_key` 身份型严格唯一 / `locator` 范围型返回 unit 集合"，但设计文档 §7.2 需在 T009 前补一句正式口径；范围命中目前无上限。
    - MEDIUM-2：`record_code` 只校验不解析——`{"doc_code":"D01","record_code":"P01"}` 解析为 D01 全部 9 unit（`gold.py:200-208`）。fixtures 未用；**T005 必须防御式 fail closed**（已写入 T005 handoff §7）。
    - MEDIUM-3：badcase N06 也依赖 N04/N05 上下文，但 `turns=[]` 且 notes 未说明（报告只记了 N11）。T005 单轮执行须显式声明，不得当多轮验证。
    - LOW-1：N05 `expected_min_total=1` 只在 notes，`expected_pagination=null`；T005/T006 不得声称 badcase 覆盖分页语义。
    - LOW-2：T004a 报告引 `__init__.py:1-38`，实际 28 行（文档引用瑕疵）。
31. **T004b 验收 PASS 遗留（2026-11-05，验收方 `review.md`：4 MEDIUM / 5 LOW，非阻断）**：
    - MEDIUM-1：`value_no_fabricated` 过严且覆盖不全（合法答案里的"第 2 层""共 3 张""D09""v2.1"都被判编造；`1,000` 连带 `value_hit` 失败；`-12` 对 `12` 符号盲）。**PM 裁决：T006a 只作软指标/诊断，不得映射为 `exact_value_contract` 或 `security_leak` 硬门禁。**
    - MEDIUM-2：`refusal_metrics` 把 `error`/`service_error` 计为 TN（稀释 false_refusal_rate），`knowledge_changed` 未定义归属。**T006a 必须把三者移出拒答 2×2（记 unknown/排除）。**
    - MEDIUM-3：缺 `unit_ids` 时 fail closed 为 0 而非 unknown（`citation_precision=0`、Recall/MRR/nDCG=0，但 `source_hit` 仍可过）。**T005 必须由 chunk 真实归属填充并持久化；缺 unit_ids 的 gold case 显式 `unknown/error`。**
    - MEDIUM-4：`source_forbidden` 在引用只有 `unit_ids`、forbidden ref 用 `unit_key` 时漏报（`scorers.py:588-600`）。**T005 交付记录同时写 `doc_code`+`unit_key`/`locator`（T005 handoff §7.5）；T006a 的 `security_leak` 必须按解析后 unit 映射比对，无法解析即 unknown（退出码 3）。**
    - LOW-1：`record_code`-only 期望来源被当整篇命中 → T005 防御式 fail closed（已写入 T005 handoff §7）；T006a 不得接受 record_code-only。
    - LOW-2：`CaseResult` 未带设计 §7.3 版本字段 → T005 的 `cases.jsonl`/manifest 补齐。
    - LOW-3：`expected_pagination=null` 但实际有分页时只验契约、不要求"无分页" → T006a 写清口径。
    - LOW-4：单检索项含多 unit_ids 时按相邻名次展开，nDCG 可能高估 → T006a 明确"同 chunk 同排名"。
    - LOW-5：`value_no_fabricated` 符号盲、千分位不归一。
    - 四处口径判定（验收方）：`EvalOutcome.retrieved` 可接受偏离（仅本地 dataclass，未改业务类型）；拒答集合以 `OutcomeKind` + `should_refuse` 为 canonical（`refusal` 只是兼容别名，非枚举成员）；`docs/evaluation/` 尚无 `gate_v0_1`，T006a 定义冲突时先改文档再改实现。
32. **T005 验收 PASS 遗留（2026-11-05，验收方 `review.md`：2 MEDIUM / 3 LOW，非阻断）**：
    - MEDIUM-1：`summary.metrics_scope.cases_in_denominator` b0=40 含 8 道 OCR，真实可评分 32；badcase=10。**T006a 的 `min_sample` 必须用 `scored_count`（32/10），否则正常 run 会被误判样本不足。**
    - MEDIUM-2：`record_code` + 空 `locator` 仍静默扩为整篇（实测 9 unit）；规范 `record_code`-only 已正确 error。**T006a 对 gold 引用 fail closed（unknown→3）。**
    - LOW：replay 的 `outcome.trace_id` 指向源 local run；b0 `range_gold_case_ids` 含 OCR Q33–Q40；replay 只校验持久化 gold/checks 自洽；`cases.jsonl`/manifest 的字节与 hash 因 duration/trace_id/run_id 非确定性。
    - 验收实测指标（T006b 校准基线）：b0 Recall@10/MRR@10/nDCG@10 = 0.96875 / 0.869792 / 0.895458；badcase = 0.767914 / 0.716667 / 0.685102；b0 local 3 fail（Q25/Q26/Q31，经直调 `RagIndex.ask` 复核非 runner 引起）；badcase local 4 fail（N05/N06/N09/N11）。
    - **PM 裁决（T006a 口径）**：硬门禁"数据集无该类 case" = `not_applicable`（不影响退出码）；"有 case 但缺字段无法判" = `unknown` → exit 3。避免 P0 永远无法 exit 0。
33. **T006a 验收 PASS 遗留（2026-11-05，R1 复验 `review-R1.md`，非阻断）**：
    - 首轮 3 HIGH fail-open（`security_leak` 缺 outcome、`citation_required` 缺 kind、`trace_integrity` 不读 `schema_meta`）+ 2 MEDIUM 已由 R1 `90d7133` 修复并定向复验 PASS。
    - LOW：`GateConfig.to_dict` 仍输出旧 `min_sample` 键（loader 只认 `hard_gate_min_sample`）；`GateResult.to_dict` 只暴露 `scored_count`（与 `evaluated_count` 同值）；`05-r1-*` 证据头 base 提交标签过期（数字已独立复现）。
    - 口径定稿：硬门禁分母 `evaluated_count` = b0 32 / badcase 13；质量检索分母 = badcase 10；两者不得混用（已写入 T006b handoff）。
34. **T006b 执行中断与接续（2026-11-05 14:1x–14:3x）**：开发会话在全量测试收尾阶段被外部暂停（非代码失败），工作树保留完整成果（`gate.py` 质量层 + 29 个测试 + 3 份证据）；按 §S 由全新上下文接续者接管收尾（核实→补跑→写报告→单 commit），未丢工作、不产生第二个同义 commit。
35. **T009 总验收保留项（2026-11-05，「有保留 PASS」，主人 G5 决策输入）**：
    - 设计 §7.2 的 `locator` 范围型正式口径**尚未回写设计文档**（T004a 验收 MEDIUM-1 的 PM 追认只记录在 `_index` 与本条；实现与测试已按该口径）。
    - `refusal_recall` 零样本时 `status=pass` 的展示有误导性（b0 无拒答题；分母 0、observed=None）；不得读作"拒答召回通过"。
    - T006b `calibrate_gate` 的 per-stratum 建议不能直接写入单值 `MetricSpec`，审批时需人工按最小非零 stratum 取值。
    - NOT-RUN（review §5）：`mode=live→4` 端到端、真实 baseline/阈值审批（主人人工门）、真实 OCR/embedding/rerank/模型、P1/P2 质量、HTML 渲染、`cross_entity`/`stale_bypass` 真实 case 类、`pagination` 真实期望值。
36. **P0 收口与 PR（2026-11-05）**：分支 `p0/obs-eval` 已 push，**PR #1**：https://github.com/Echo2580/mktkb/pull/1 （base `main` @ `8e44158`；38 个交付/簿记 commit + 收口提交；工作树干净）。**合并前主人人工门项**：阈值审批（`gate_v0_1.json status`）与真实 baseline 建立、设计 §7.2 口径回写；PR 描述含 NOT-RUN 清单与建议阈值。（**2026-11-05 21:38 主人授权 PM 合并**：merge commit `083eaef`，P0 commit sha 保留；三项可选项仍未执行）
37. **主人 G5 决策（2026-11-05 晚）：P0 通过**。T009 记为 G6 收口；`_index` 待审列已清空。主人用网页实测（离线+trace 启动）通过第 1 步问答（D01 来源正确、回答为离线抽取式），并确认同一套启动方式可用。**未执行（主人未下指令）**：阈值审批、真实 baseline 建立、设计 §7.2 回写、PR #1 合并——三项均为可选收尾，PR 保持 OPEN 等主人决定。
38. **P1 开工前置（新窗口执行）**：`P1-PRE-2` 预算划转与 GO 改版（`P1-RETRIEVAL` 3.0 元，自 S2-DEV 划转，总上限仍 20；主人签 `budget.json` + `S2-LIVE-GO.json`）、`P1-PRE-3` P0 遗留复核（PM）、`P1-PRE-4` D-3 兼容授权（主人书面确认，T104/T106 需要）。PRE-2 未签前 T111 及任何 live 调用一律不得开工。（**2026-11-05 进展**：PRE-3 完成、PRE-4 已确认、参数全部确认、成品草稿就绪；仅剩两个文件落盘）
39. **P1 开工门完成 + 新增 T100（2026-11-05 21:5x）**：PR #1 已合并 `083eaef`；PRE-2 经主人授权由 PM 写入并只读验签通过（budget sha `084ba9ac…`、GO sha `39070de5…`，旧 GO 备份 `S2-LIVE-GO-20261104.json`，GO 有效至 2026-11-30，账本零写入）；`_scratch` 已清理；主人定 T111 pilot 后停一次、零 live 包不提前开、落盘后先等发令开工。**新增待办**：`backend/tests/rag/test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan` 硬编码旧真实配置（S2-DEV 18.4），签名后 1 failed（定向实测：1 failed / 21 passed），建议新增前置小包 **T100** 修复（1 文件，保留测试意图）；全量 pytest 因空闲内存 1.01GB 暂未跑（§11D）。详见 kickoff §10/§11。
40. **P1 新 flake（2026-11-05，T107 验收发现）**：全量 `backend/tests` run1 出现 `integration/test_lifecycle.py::test_concurrent_publish_and_global_revision_cas[v05]`（`:759`）失败；该文件自 `366046d`（v0.1 冻结）未改、不导入 `mktkb.evaluation`；隔离复跑 3 次均 `2 passed` → 既有并发时序 flake，非 P1 引入。P1 全量遇到按 §11A 隔离复跑 1 次并记录，不重跑整套、不据此返工。
41. **T107 验收非阻断观察（2026-11-05）**：① RG003「给出所有内容」同时触发 `pagination_contract` 硬失败（report §4 未单列，证据 01 有说明）；② `corpus.py` badcase 装配校验由"集合相等"放宽为只查 missing（`only_codes` 固定，实际行为未变；后续包不得依赖该放宽）；③ T107 全量执行 2 次（超出 §11A 的 1 次，因 flake 复跑，已在证据披露）。
42. **PM 裁定（2026-11-05 23:1x，T101 现场范围冲突）**：允许 T101 在 `rag/answer.py` 的 `_document_fallback` 增加**极窄**法规题分支（仅 `is_regulation_question` + offline 命中时返回命中子句所在完整段落；非法规题/默认路径逐字节不变），理由：RG001/E120 三值在 P0 单句抽取下无法同时命中，改弱断言/降级 RG001 违反"不放宽"纪律。硬约束：新分支需单测（法规段落 + 非法规仍单句）、report §4 单列偏离（文件/函数/净增行数）、附 b0/badcase 修复前后 hard_failures 与 case 级对照证明零新增硬失败，否则回滚该文件。裁定已写入 `T101-vocab-context/handoff.md` §4。
43. **T101 第二次 PM 裁定 + 验收非阻断（2026-11-06 00:2x）**：① 允许补全 RG001 `reference_answer`（发布日 2000-10-31/2001-11-07、施行日 2022-07-01），不改 `expected_values/sources/forbidden/kind`、不动 RG002–RG007——属"数据补全非放宽"（scorer 数值白名单派生自 reference，缺日期会把逐字原文误判编造）；② T101 验收 PASS（`review.md` 37 行；旧源码 `git archive a7282b3^` 独立复跑证明 RG001 RED→PASS 且门禁未放宽；answer.py 仅 +29/−1，探针证非法规题仍单句、53 题法规判定 0 误报）；③ 非阻断瑕疵：单测夹具 `test_p1_t101_document_answer.py:26` 把真实「第15号」写成「第9号」，不影响分支逻辑，记录不修。

- 任务拆解与验收口径：`2026-11-04-p0-task-breakdown.md`（分包粒度以本表拆分版为准）
- PM 交接提示词：`prompts/p0-pm-handoff-20261104.md`（长版）、`prompts/p0-pm-handoff-short-20261104.md`（简版）
- 方案：`docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md`、`docs/superpowers/plans/2026-11-04-mktkb-observability-evaluation-p0.md`
- 冻结基线证据：`docs/evidence/LOCAL-R1-20261101/TEST-20261104/`（本地，不入库）
- 流程材料：`.claude/handoffs/T<NNN>-<slug>/`；入库验收证据：`docs/reports/OBS-EVAL/P0/`
- **P1 方案（已按 2026-11-04 主人决策更新；未立项，开工门 = P0 T009 通过）**：`2026-11-04-p1-design.md`、`2026-11-04-p1-task-breakdown.md`
- **P1-PRE-1 Holdout 命题（✅ 已交付并通过 PM 结构验收，2026-11-05）**：`docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/`（questions sha256 `a8c8aa7f…6738` / labels `8f713a2a…c1bf`，30 题 10/5/5/5/5，`label_version=holdout-2026-11-04`，不入库、开发禁用）；3 个待拍板项已按设计稿 §4 口径关闭
