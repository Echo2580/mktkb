# P1「修复与检索评测」任务拆解与派单计划（2026-11-04，草案待主人审）

> 状态：**草案，未派单、未建分支、未改代码。** 设计口径见 `2026-11-04-p1-design.md`。
> 前置门：P0 T001–T009 独立验收通过并合入 `main`；P0 收口遗留项复核完成。
> 分支：`p1/fix-retrieval`（自届时 `main` HEAD 建），每包一 commit。
> 执行参数（沿用主人已定规则）：**一包一个新开发助手 + 一包一个新验收助手**；全部完成后开 1 个 PR；验收证据入 `docs/reports/OBS-EVAL/P1/`；业务代码只在 T101–T106 修改。

## 1. 前置任务（非开发包，主人/PM 执行）

| ID | 事项 | 产出 | 谁做 | 阻塞 |
|---|---|---|---|---|
| P1-PRE-1 | Holdout 30 命题与标注（分层 10/5/5/5/5，字段按 P0 设计 §7.1） | ✅ 已交付 2026-11-05：`docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/{questions.jsonl(sha a8c8aa7f…6738),labels.jsonl(sha 8f713a2a…c1bf),README.md}`；PM 结构验收 0 问题（见设计稿 §4 口径） | 主人指定的外部 AI 命题助手（提示词 `prompts/p1-holdout-author.md`）；PM 只做格式/隔离验收 | T108 起需要（已解除） |
| P1-PRE-2 | 预算划转与 GO 改版（`P1-RETRIEVAL` 3.0 元；GO 固定文件新增阶段与 rag 绑定） | 修订后的 `budget.json` + `S2-LIVE-GO.json`（主人签） | 主人（PM 出清单，不碰原件） | T111 起需要 |
| P1-PRE-3 | P0 收口遗留项复核（尤其 `legacy_with_rag_candidates` 口径、T001–T008 非阻塞项） | `_index.md` 遗留项收口记录 | PM | P1 开工前 |
| P1-PRE-4 | P1 兼容性授权 D-3（允许错误码/文案取值变化、字段结构不变） | 主人书面确认 | 主人 | T104/T106 |

## 2. 工作包总表

| 包 | 目标 | 交付物 | 依赖 |
|---|---|---|---|
| T107 | regression suite 与数据集契约扩展 | `fixtures/evaluation/regression.jsonl`（种子用例）、`evaluation/dataset.py` 扩展、gate 接入、测试 | P0 完成 |
| T101 | ERR-03 词表语境与法规优先 | 改 `conversations/intent.py`（及必要的 `rag/query.py` 一致性）；测试；regression 用例 | T107 |
| T102 | 组 A 状态继承（ERR-01/02/D5） | 改 `rag/query.py`；测试；regression 用例 | T101 |
| T103 | D4 记录路回落语义检索 | 改 `conversations/service.py`（+必要前端提示）；测试；regression 用例 | T102 |
| T104 | D1 异常原因透传 | 改 `conversations/service.py`；测试；regression 用例 | T103 |
| T105 | D6 指代/字段错配澄清 | 改 `rag/query.py`（+必要 answer 模板）；测试；regression 用例 | T104 |
| T106 | D3 文案统一（后端 + 前端） | 改 reason→文案映射、`frontend/src/features/chat/MessageCard.tsx`；测试/e2e | T105 |
| T108 | Holdout 支持与防污染 | `evaluation/dataset.py`/`runner.py`/`cli.py` 扩展、`holdout_audit.json`、测试 | T107 + PRE-1 |
| T109 | 多轮 `turns` runner 支持 | `evaluation/runner.py`、测试（多轮用例） | T108 |
| T110 | 检索金标与检索指标 | `evaluation/gold.py`/`scorers.py` 扩展、检索指标测试 | T109 |
| T111 | live 检索运行器与真实索引 | `evaluation/runner.py` live+retrieval_only、`evaluation/corpus.py` 真实索引、成本预检、测试 | T110 + PRE-2 |
| T112 | 门禁阈值校准与 P1 baseline | `docs/evaluation/gate_v0_2.json`、`evaluation/gate.py` 校准扩展、P1 baseline 审批、测试 | T111 |
| T113 | 监控 API（只读聚合） | `observability/routes.py`（4 端点）、权限、测试 | T107（可提前） |
| T114 | 监控 API 权限/负例/文档/契约测试 | 集成测试、`docs/接口与数据契约.md` 增补、OpenAPI 导出 | T113 |
| T900 | 独立验收与 P1 收口 | `docs/reports/OBS-EVAL/P1/{p1-report.md,review.md,evidence/}` | T101–T114 |

> 说明：T113/T114 只依赖 P0 trace 仓储，技术上可与修复并行；默认仍串行，若要并行须主人显式授权且 write scopes 不相交。

## 3. 每包任务单（摘要；派单时展开为 handoff）

### T107 · regression suite 与数据集契约扩展
- 目标：新增 `suite=regression` 数据集与加载/校验/门禁接入；种子用例覆盖 7 项必修缺陷（初始为 RED，修复后转绿）。
- 允许：`fixtures/evaluation/regression.jsonl`（新增）、`evaluation/dataset.py`、`evaluation/gate.py`（suite 枚举）、`backend/tests/evaluation/*`。
- 禁止：改 `b0.jsonl`/`badcase.jsonl`（冻结）、改业务代码、弱化既有断言。
- 验收：① regression 加载/校验通过，禁止 chunk_id/unit_id；② gate 默认覆盖 b0+badcase+regression；③ 种子用例逐条映射 `source_err_id`；④ 现有 b0/badcase 行为不变；⑤ 全量 pytest 无新增失败。

### T101 · ERR-03 词表语境与法规优先
- 目标：「价格」等词不再无条件判为采购价格；法规/制度类问题优先于缺失字段判定；同一词不再"支持字段/缺失字段"双登记打架。
- 允许：`conversations/intent.py`、必要的 `rag/query.py` 词表一致性修改、对应测试、`fixtures/evaluation/regression.jsonl` 追加用例。
- 禁止：改 API Body 字段结构、改判分器、放宽既有断言。
- 验收：① E118/E120/E087/E095 等场景 local 下不再被提前截断；② 价格题仍能取价目表数值；③ 回归用例入 regression；④ b0+badcase+regression 门禁无硬失败；⑤ 全量 pytest 无新增失败。

### T102 · 组 A 状态继承（ERR-01/02/D5）
- 目标：未识别门店/区域词（如「城西区」）必须澄清或拒答，不得静默沿用上一轮门店；政策/制度题不继承上一轮实体；`reset` 判定补话题切换。
- 允许：`rag/query.py`（+必要的 answer 模板）、测试、regression 用例。
- 禁止：改检索/embedding 行为、改 API 字段结构、跨包改动。
- 验收：①「城西区宣传海报」不得答城东店（答 C区2号货架第一层或澄清）；② 政策题答案不出现未提及实体；③ 多轮 follow-up 用例；④ P0 trace 的 path/outcome 仍正确（不破坏 trace_integrity）；⑤ 全量 pytest 无新增失败。

### T103 · D4 记录路回落语义检索
- 目标：宽泛流程/规范类问题命中"记录过多"时回落语义检索，不直接给无解澄清；确需澄清时说明命中量与缩小方式。
- 允许：`conversations/service.py`、必要前端提示文案、测试、regression 用例。
- 验收：① Q25/Q26/Q29/Q30/Q34/Q35/Q37/Q38 场景 local 下不再"无解澄清"；② 回落路径有 trace 降级标记；③ 候选为空时文案与真实原因一致；④ 门禁无硬失败；⑤ 全量 pytest 无新增失败。

### T104 · D1 异常原因透传（需 D-3 授权）
- 目标：预发送阶段异常按真实原因分类（provider/配置/预算/内部），不再统一包装 `MODEL_UNAVAILABLE`；说明可否重试。
- 允许：`conversations/service.py`、错误码/文案映射、测试、regression 用例。
- 验收：① 各异常类型映射用例（monkeypatch）；② 响应字段结构不变（仅错误码/文案取值变化，列入 P1 变更清单）；③ 正面模板与 ERR-07 一致；④ 全量 pytest 无新增失败。

### T105 · D6 指代/字段错配
- 目标：继承实体但不继承"问什么"时澄清要哪项信息，不倾倒整条记录全字段。
- 允许：`rag/query.py`（ANAPHORA/字段角色）、必要 answer 模板、测试、regression 用例。
- 验收：①「那个海报呢」不再吐全字段；② 有上文问位置时答位置；③ 指代无源时澄清；④ 全量 pytest 无新增失败。

### T106 · D3 文案统一（后端 + 前端）
- 目标：每种 outcome/reason 有唯一、诚实、可自救的文案；前端徽标与真实原因一致（"无候选"不再显示"历史未保存"）。
- 允许：后端文案映射、`frontend/src/features/chat/MessageCard.tsx`、前端相关测试、regression 用例。
- 验收：① 每种 reason 文案映射有测试；② 前端提示修正；③ 前端构建通过 + 受影响 e2e 通过（如环境允许，否则明确 NOT-RUN 并说明）；④ API 字段结构不变。

### T108 · Holdout 支持与防污染
- 目标：加载/校验 `holdout.jsonl`；默认聚合输出；`--allow-holdout-details` 才出逐题并写 `holdout_audit.json`；gate/CI 禁该 flag；缺 `label_version` 拒绝运行。
- 允许：`evaluation/{dataset,runner,cli,gate}.py`、测试、`holdout_audit.json` 生成逻辑。
- 验收：① 默认输出不含逐题；② flag 出详情 + 审计；③ gate 环境带 flag 硬失败；④ 未冻结/缺 label_version 拒绝；⑤ 全量 pytest 无新增失败。

### T109 · 多轮 turns runner
- 目标：`turns` 非空 case 顺序执行、逐轮 Trace、全部轮次通过才算通过；单轮行为不变。
- 允许：`evaluation/runner.py`、测试。
- 验收：① 多轮通过/失败判定正确；② 逐轮 trace_id 可关联；③ 单轮结果与 P0 一致；④ 全量 pytest 无新增失败。

### T110 · 检索金标与检索指标
- 目标：`relevant_units` 校验/派生；Recall@10/MRR@10/nDCG@10、`hard_filter_violation_rate`、`empty_recall_rate`；0/多匹配 fail closed；指标入 summary/gate。
- 允许：`evaluation/{gold,scorers}.py`、gate 指标接入、测试。
- 验收：① 手工可对照的小样本指标数值一致；② unit 去重后计算；③ 空召回/硬过滤违规可量化；④ local 模式可验证（不依赖真实 provider）。

### T111 · live 检索运行器与真实索引（需 PRE-2 GO）
- 目标：`mode=live`、`scope=retrieval_only`：真实 embedding/rerank、隔离索引、成本预检、失败 fail-closed、零重试、不调 chat。
- 允许：`evaluation/{runner,corpus}.py`、live 配置接线、测试；运行产物 `var/eval/runs/<run_id>/`（不入库）。
- 禁止：调用 chat 生成答案；绕过 GO/账本；把凭据写进证据。
- 验收：① 10 题 pilot 跑通且成本可核算；② provider spy 证明 chat 调用 = 0；③ GO/账本/预算校验生效（超限拒绝）；④ manifest 绑定 dataset/corpus/index/pipeline/gate/mode/scope；⑤ 账本记录与报告口径一致。

### T112 · 门禁阈值校准与 P1 baseline
- 目标：`gate_v0_2.json`（新增检索指标阈值、regression suite、min_sample、max_regression_pp）；`gate --calibrate` 提案→审批写入；P1 release baseline 建立。
- 允许：`docs/evaluation/gate_v0_2.json`、`evaluation/{gate,baseline}.py`、测试、`docs/reports/OBS-EVAL/P1/` 证据。
- 验收：① 校准提案可复现；② 审批缺 approver/reason 拒绝；③ exit code 0/1/2/3 在 P1 套件生效；④ P0 baseline 不混用、跨版本只分析；⑤ diff/report 生成。

### T113 · 监控 API（只读聚合）
- 目标：`/api/v1/observability/{traces/{id}, requests/{id}/traces, metrics, runs/{run_id}}`，admin 权限，只返回哈希/计数。
- 允许：新增 `observability/routes.py`、`main.py` 路由注册、测试。
- 验收：① admin 200；② 只读（无写路径）；③ 不返回原文；④ Holdout 明细不可达；⑤ OpenAPI 可导出。

### T114 · 监控 API 权限/负例/文档
- 目标：employee 403/未登录 401/不存在 404/时间窗与分页边界；接口文档与 OpenAPI 更新。
- 允许：测试、`docs/接口与数据契约.md` 增补、OpenAPI 产物。
- 验收：① 权限矩阵用例齐全；② 分页/时间窗边界；③ 文档更新；④ 全量 pytest 无新增失败。

### T900 · 独立验收与 P1 收口
- 全新上下文验收者，按 P1 设计 §9 七条 + 各包验收标准逐条复跑（不引用开发报告作为证据），输出 `docs/reports/OBS-EVAL/P1/{review.md,p1-report.md,evidence/}`；随后 PM 交主人人工门（四选一），主人决策前不合并 PR、不进下一阶段。

## 4. 验收节奏

| 阶段 | 触发 | 重点 |
|---|---|---|
| V-P1-107 | T107 | regression 契约、冻结套件不变 |
| V-P1-101…106 | 每修一项后 | 该项回归用例转绿、门禁无硬失败、全量 pytest 无新增失败、行为变化入变更清单 |
| V-P1-108/109/110 | 各自完成后 | 防污染审计、多轮、检索指标正确性 |
| V-P1-111 | T111 | 零 chat 调用、成本可核算、GO/账本硬绑定、pilot 成功 |
| V-P1-112 | T112 | 校准可复现、baseline 审批、退出码 |
| V-P1-113/114 | 各自完成后 | 权限、只读、不泄漏、文档 |
| T900 | 全部完成 | P1 §9 七条全量复核 + 全量 pytest |
| 人工门 | T900 后 | 主人四选一（通过/有条件通过/返工/改需求） |

## 5. 预算与成本纪律

- `P1-RETRIEVAL` 阶段额度 **3.0 元**（待主人签）；pilot（10 题）→ 全量（b0/badcase/regression/holdout 约 113 + 30 题）分两段；超剩余即拒绝。
- 只有 T111/T112 允许真实调用；其余包一律零真实调用（provider spy / socket guard 证明）。
- 成本、请求数、账本 sha 写入 `docs/reports/OBS-EVAL/P1/evidence/`；报告只写保守口径，不写"实际账单"。
- 验收方复跑 live 只跑 ≤10 题子集；全量复跑只在 T900 做一次（预算内）。

## 6. 现在不做的事

- 不建 `p1/fix-retrieval` 分支、不创建任何 P1 代码/测试/fixtures、不派单、不写 P1 handoff 与四段提示词；
- 不跑真实调用、不改 `budget.json`/GO/账本；
- 等主人审过设计稿与本文，且 P0 T009 通过后，才进入 P1 的 G0/G1。
