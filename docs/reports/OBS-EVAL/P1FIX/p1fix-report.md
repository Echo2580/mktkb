# P1 验收前遗漏修复报告（P1FIX / 2026-11-10）

> 本报告是**开发自测交付**，不是独立验收结论；不宣布 P1 通过、不把“执行成功”写成“答对”。
> 历史报告（`docs/reports/OBS-EVAL/P1/**`、`docs/reports/OBS-EVAL/P0/**`）未被覆盖。

## 0. 现场与改动清单

- 工作目录：`D:\GPT项目\市场部AI知识库`；分支 `p1/fix-retrieval`；**起始 HEAD `3eec866`**。
- **本次未创建 commit/push**：结束 SHA 仍为 `3eec866`，交付物为工作区改动 +
  本报告/证据（未提交）。本次改动 = 17 个自有 tracked 文件 + 新增测试/数据/文档（清单 §0.1）。
- 开工时工作树已有他人未提交产物：`.claude/handoffs/_index.md`（M）、
  `.claude/handoffs/2026-11-10-p1-takeover.md`（??）、`docs/面试/`（??）。
  **本次未修改、未清理、未提交**；收尾 `git status` 与开工时这三项状态一致。
- 未读 `.env`/密钥；未改 `var/**`、`docs/evidence/**`、GO/预算/账本、冻结 fixtures；
  未执行任何真实 provider 调用；未 push/合并/进入 P2。

### 0.1 本次改动清单

源码（13 文件）：`conversations/{intent.py,service.py}`、`copy.py`、`qa/service.py`（引擎版本号）、
`rag/{query.py,answer.py,retrieval.py,types.py}`、`evaluation/{report.py,baseline.py,cli.py}`（11 个后端）、
`frontend/src/{utils/format.ts,features/chat/MessageCard.tsx}`（2 个前端）。

测试（11 文件）：改动 4（`test_report.py`、rag/integration 的 `test_p1_t105_anaphora_field.py`、
`test_p1_t106_copy.py`）+ 新增 7（`test_p1_refusal_controls.py`、`test_p1_refusal_scope_http.py`、
`test_p1_source_bridge.py`、`test_p1_source_bridge_mapping.py`、`test_diff_release_gate.py`、
`test_baseline_portability.py`、`test_live_request_accounting.py`）。

数据/文档（新增）：`fixtures/evaluation/refusal-controls-2026-11-10.jsonl`（独立公开控制集）、
`docs/evaluation/{baseline-portability,live-request-accounting}-2026-11-10.md`、本报告与 `evidence/`。

`git diff --stat`（tracked，**含开工前他人 `_index.md` +2**）：18 files changed, +1411/−28；
本次自有 tracked 改动为 17 文件（11 后端源码 + 2 前端 + 4 测试），其余为 untracked 新增。

## 1. A：RG005/RG007 越界问题应拒答（已修复并自测）

- **原失败**（可复现）：`run --suite regression --mode local` → 5/7；RG005/RG007
  `kind=answer`（各自引用无关资料 X01/W09），`kind_correct/refusal_expected` fail。
- **根因**：意图层无语料不覆盖的“公司级经营/财务指标”语义；文档抽取层只要有弱相关证据
  （如命中“公司”）就作答；产品/内核两条路径都没有“检索后、模型前”的资料支持判定。
- **修改**：`rag/query.py` 增加财务指标同义词组 + `financial_metric_question()` +
  `texts_support_financial_metric()`（指标词+数值同窗才算支持；法规题不判越界）；
  `rag/answer.py` 检索后/答案生成前拒答（`UNSUPPORTED_FINANCIAL_METRIC`，无 citations）；
  `conversations/intent.py` 标记 + `conversations/service.py` 在 query_expansion/模型调用前做同一
  判定；`copy.py` 新增诚实文案。**不按题干硬匹配、不一律拒答**：有“指标词+数值”证据时仍走原路径。
- **验证命令/结果**：
  - 冻结 regression：`status_counts={'pass':7}`，RG005/RG007 均 `no_answer`，文案诚实、`citations=[]`；
  - `pytest backend/tests/evaluation/test_p1_refusal_controls.py` → **23 passed**：
    12 条同义改写/不同句式（营业收入/营业额/净利润/毛利率/净利率/市值/现金流/亏损/资产负债率/
    祈使句等）全部拒答；10 条正向控制（台账/法规/制度/价目表/KPI“销量”/未知区域/预算审批）仍可答；
    采购价格按既有冲突口径作答、未被误拒；
  - `pytest backend/tests/integration/test_p1_refusal_scope_http.py` → **3 passed**：
    spy（`EvidenceEchoGateway.calls`）证明 6 条越界拒答前后 **chat 调用数不增加**；正向台账题仍调用
    模型并返回来源。
- **剩余问题**：指标词表为语义类目，不含 GMV/ARR 等跨行业术语；当前公开语料不含同类指标，故
  “有资料支持的财务指标端到端作答”只用合成单测锁定，未做真实端到端验证。

## 2. B：多轮追问不再倾倒整批记录（已修复并自测）

- **原失败**（T105-R3 独立证据 #51）：上文问位置后追问「标准规格/价格标准/提交数量」仍
  answer 576 字、8 个「标识：」记录块；「报销规则」被台账备注字段吞成 22 字 not_found。
- **根因**：① 指代单字段分支被 `not policy_followup` 挡住（`标准/提交` 属泛化政策词）；
  ② `报销` 不在政策词表（`规则` 又被排除）；③ 计划落回产品 legacy 措辞面，把 8 条证据交给模型回显。
- **修改**：`rag/query.py` 新增强制度/流程话题词与 `POLICY_TOPIC_FOLLOWUP` 分支：泛化政策词
  + 明确字段词 → 仍单字段作答；强话题词 + 字段同形（报销规则）→ 正文检索，且保留
  “全部/列出/第 N 页”的枚举/分页优先级；`rag/answer.py` 正文计划要求证据里确有该话题词，
  否则诚实拒答；`copy.py` 新增 `POLICY_TOPIC_NOT_FOUND`。
- **验证命令/结果**：重跑 T105-R3 独立探针（同一脚本/夹具）→ **131/133**（2 条失败为脚本写死的
  T106 前旧文案“未记录”断言，非回归）；同场景前后：标准规格 **576→29 字/0 记录块**、
  价格标准 **576→23**、提交数量 **576→20**、报销规则 **22（记录式）→67（诚实正文缺失）**；
  陈列/扣分规则仍按台账字段 not_found、审批要求/权限/盘点规定 37/37/34 保持；分页/裸页/下一页/
  无上文澄清/显式“全部信息”/C3–C6 政策法规追问全部保持。新增 rag/HTTP 两层回归覆盖
  位置/数量/规格/价格/政策追问/未知门店/话题切换/无上文指代（B7）。
- **剩余问题**：单轮无上文的 legacy 题（T105-R3 D1“打印材质”，576/8）与基线相同，属旧措辞面
  既有项，本次未扩大改动（避免改 legacy 模型措辞面引入更大回归）。

## 3. C：文档答案来源与前端提示（已修复并自测；e2e 未验证）

- **原失败**（T105-R3 / #52）：制度/法规答案内核有 citations，但产品/API `sources=[]`；
  `not_found` 徽标恒为“无匹配资料”，与“记录存在但缺字段”正文不一致。
- **链路核实**：内核 `Citation` 无产品来源单元 ID → `_rag_turn_result` 只从 `facts` 取
  `source_unit_id` → 文档答案 `facts=[]` 丢来源 → `MessageSource`/`AskResult.sources` 为空。
  结论：**不是测试夹具独有现象，是真实转换丢失**。
- **修改**：`Citation` 增加 `unit_ids`（`_citation`/`_to_evidence` 填充）；`_rag_turn_result`
  对无 facts 的文档答案用 citations 来源映射产品来源，仍走 `_commit_result_impl` 的
  可见性/有效版本复核；`FIELD_NOT_RECORDED` 拒答带出 `missing_fields`；前端按
  `missing_fields>0` 显示“字段未记录”，其余 not_found 保持“无匹配资料”（既有 e2e 断言不变）。
  未伪造来源、未删答案、API 字段结构未变。
- **验证命令/结果**：同一 T105-R3 探针：C3/C4/C5/C6 sources **0→6/4/6/5**，H 系列 0→5；
  新增 `pytest backend/tests/integration/test_p1_source_bridge.py` → **3 passed**：来源归属
  （资料名/版本/active/定位）、来源详情接口 200 + 真实片段、他人访问 403/404、历史消息来源
  持久化、记录答案来源可访问、越界拒答无来源；单元映射 4 用例；
  frontend `npm run typecheck`+`vite build` exit 0。
- **剩余问题**：前端 e2e **NOT-RUN**（本环境无浏览器/服务）；徽标改动未做浏览器级验证。

## 4. D：门禁放行与当前配置/运行/审批一致性（已修复并自测）

- **原风险**（#59）：`diff_runs` 只比 `gate_version`，缺 gate、旧 gate、同版本改阈值、审批后
  配置漂移都可能 `release_allowed=True`。
- **修改**（仅 `evaluation/report.py`）：放行证据链统一判定——非跨版本 + baseline 已审批且
  gate 快照绑定具体 gate 结果 + 当前 gate 非空且 `run_id/suite/mode` 绑定当前 run + exit 0 +
  `gate_version` 与当前配置一致 + 当前 gate 质量层 `gate_config_hash==当前 config_hash` +
  **审批时刻配置哈希==当前配置哈希**（旧 schema 从 `run_dir/gate.json` 重核，缺失/被改 fail closed）；
  13 类稳定阻断原因码；`RunDiff`/`to_dict()` 结构不变；模块 docstring 写明“配置内容变→必须
  重新评估+重新审批，不得复用旧通过”。
- **验证命令/结果**：`test_diff_release_gate.py`（15 反例/合法）+ `test_report.py` 等 8 文件
  **283 passed**；真实 P1 产物只读复核：合法一致 → `release_allowed=True`；同 gate_version 改
  阈值 → `gate_config_drift`；旧 run gate → `current_gate_run_mismatch`；缺 gate →
  `current_gate_missing`（`evidence/data/D-verify-release-chain.json`）；p0 验收 CLI
  approve→diff 合法路径仍通过。**未修改/批准任何阈值，未降低门槛。**
- **剩余问题**：旧 schema baseline 依赖 run 目录 `gate.json` 作为审批证据（缺失即拒绝放行，
  有意的 fail closed）；后续可做 schema bump 把 `gate_config_hash` 写入 `BaselineGate`。

## 5. E：baseline 可移植性与证据留存（已修复并自测；“新基线”为待办）

- **原问题**：P1 baseline `bc6f6f906db1` 与 run 在 gitignored `var/eval/**`，fresh clone 不可见。
- **修改**：`evaluation/baseline.py` 新增 `archive_baseline/verify_archive/restore_baseline`；
  `cli.py` 新增 `baseline archive/verify/restore`；归档 6 文件（baseline/approval/run 三件套/gate.json）
  + `archive_manifest.json`（schema、六要素、逐文件 sha256/bytes、审批关系、源路径）；
  排除 traces/index/gate_proposal/holdout_audit，**holdout 相关一律拒绝**；restore 只重写
  `run_dir`，identity/approval/artifact/gate 快照逐键不变、不覆盖已存在目录；新增
  `docs/evaluation/baseline-portability-2026-11-10.md` 与 21 个隔离用例；真实
  `bc6f6f906db1` 归档→verify→restore→`baseline list approved=yes`、`load_baseline/load_run` 通过，
  源 `var/**` 摘要逐字节不变。
- **代码变化后的基线纪律**：行为语义变化已把 `QA_ENGINE_VERSION` `s2-a-1`→`s2-a-2`，
  新 run `pipeline_version=d3ca88d2c515`（旧 `08166b113481`）；旧 baseline 只能
  `compare_with` 跨版本分析（`release_allowed=False`），**不得冒充新 pipeline 发布基线**。
- **剩余问题/待办**：新 P1 release baseline 未建立（需真实 live run + gate 重评 + 主人重新审批）；
  零真实调用无法建立；归档产物入库位置需主人决策（本次未上传/提交）。

## 6. F：请求计数与验证口径（已核实，文档更正 + mock 负例）

- **核实**：GO `scope.bindings.rag.embedding_requests=7 / rerank_requests=4` 是 **S2-DEV 的 J2
  受控计划值**（`request_plan_sha256` 可反解唯一计划 15 次），**不约束 P1 live 检索路线**；
  P1 运行上限是 `scope.max_requests=1000`（累计）+ 阶段 3.0 元（实际 T112 505/1000、
  0.0143149/3.0 均在上限内）；两类计数语义不同，不是 GO 违规、也不是“声明未执行”的约束。
- **修改**：运行期代码零改动（live.py/live_authorization.py/controlled_execution.py 未改）；
  新增 `docs/evaluation/live-request-accounting-2026-11-10.md`（五类口径/字段语义/拒绝链/审计
  命令/#56 更正）；新增 `test_live_request_accounting.py` 5 个 mock 负例（累计上限跨 kind 拒绝且
  HTTP=0、账本不变；预检 request_limit_insufficient 在 index/provider 构造前拒绝；计划值 1/1
  不当运行上限；绑定键集合不含计划字段）→ **5 passed**；回归 46 passed。
- **剩余问题**：GO bindings 沿用 J2 计划块，未来重签 GO/升级 settlement_version 需重新对齐
  （本次不重签）；预检是上限估计，实际以账本量为准。

## 7. 测试与业务评测（分开记录）

- **测试用例**：全量 `pytest backend/tests`（仅跑 1 次）→ **2023 passed / 0 failed / 0 error，
  566.53s**；定向合并（本次新增/受影响 19 文件）→ **284 passed，103.59s**；前端 typecheck/build
  exit 0。改动前全量为 1933 passed（T900 独立验收记录）。
- **业务评测（local，确定性）**：b0 `29/3/8`、badcase `9/4` 对 P0 run **逐例签名 diff=0/40、0/13**；
  regression **5/7 → 7/7**（仅 RG005/RG007 fail→pass，逐条解释见 §1）；
  gate（local）三套 exit 3 / hard `[]` / quality unknown（不降低门槛，local 不能放行）。
- **Holdout（受限聚合，details=false）**：**30/30 执行成功、error=0**；**答案通过 7/30**
  （pass7/fail23，与改前 T900 聚合逐指标相同；拒答 TP3/FN3/FP3/TN21）；**“执行成功”≠“答对”**，
  7/30 如实保留，不编造阈值。旧 T108-R2 的 Recall 0.5154 属旧 pipeline，非本次改前基线。
- **门禁/放行**：合法一致场景 True；配置漂移/旧 gate/缺 gate/跨版本全部 False（§4、§5）。
- **API/schema/依赖**：`AskResult` 12 / `MessageView` 12 字段不变，`schemas.py` 零 diff；
  业务库/索引库 schema 零 diff；依赖清单零 diff；冻结 fixtures 零改动；新公开数据用独立文件。
- **NOT-RUN（未验证，如实）**：真实 live 检索重跑（T111/T112 式）与端到端答案评测、OCR 质量、
  扩充 live 套件、Holdout live、前端 e2e、基于新 pipeline 的 P1 release baseline——均需主人另行
  授权（真实调用）或既有 e2e 环境；本次零真实调用，不用源码阅读代替实测。

## 8. 逐项状态

| 项 | 状态 |
| --- | --- |
| A RG005/RG007 拒答 + 同义改写/正向控制 + spy 零 chat | **已修复并自测**（冻结 regression 7/7） |
| B 多轮字段/政策倾倒 | **已修复并自测**（T105-R3 探针同场景 576→29/23/20、报销规则诚实拒答；单轮 legacy D1 既有项未改） |
| C 内部引用→API→前端来源 + not_found 徽标 | **已修复并自测**（HTTP 来源/权限/版本/持久化；前端 typecheck/build 通过；**e2e NOT-RUN**） |
| D 放行与当前 run/配置/审批一致性 | **已修复并自测**（反例拒绝 + 合法放行；实产物复核） |
| E baseline 归档/恢复/重建流程 | **已修复并自测**（隔离验证通过）；**新 pipeline baseline 未建立=待办** |
| F 请求计数口径 | **已核实无需修改运行期代码**（文档更正 + mock 负例 5 passed） |
| 真实 live 重跑 /端到端答案/OCR/扩充套件/Holdout live /前端 e2e /新 release baseline | **未验证（NOT-RUN）** |
| 独立验收 | **未做**（由主人另行安排；本报告不是验收结论） |

## 9. 复跑指引（独立验收者可直接用）

```powershell
# 现场
git -C "D:\GPT项目\市场部AI知识库" status --short
git -C "D:\GPT项目\市场部AI知识库" rev-parse HEAD    # 3eec866（本次未提交）

# 测试（全量 1 次；定向见证据 08）
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
.\.venv\Scripts\python.exe -B -m pytest backend\tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\p1fix-full

# local 三套 + gate（离线、零真实调用）
foreach ($s in "b0","badcase","regression") {
  .\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite $s --mode local --out ".claude\handoffs\_scratch\p1fix\recheck-$s"
  .\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run ".claude\handoffs\_scratch\p1fix\recheck-$s"
}
# regression 期望 7/7；b0 29/3/8；badcase 9/4；gate 均 exit 3 / hard []

# A 控制集（offline 全量语料索引）
.\.venv\Scripts\python.exe -B -m pytest backend\tests\evaluation\test_p1_refusal_controls.py -q

# B/C 产品路径（含 T105 回归与来源链路）
.\.venv\Scripts\python.exe -B -m pytest backend\tests\integration\test_p1_t105_anaphora_field.py backend\tests\integration\test_p1_source_bridge.py -q

# E：baseline 归档/恢复（源只读，输出到临时目录）
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline archive --baseline bc6f6f906db1 --root var\eval\baselines --out .claude\handoffs\_scratch\p1fix\recheck-archive
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline verify --archive .claude\handoffs\_scratch\p1fix\recheck-archive
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli baseline restore --archive .claude\handoffs\_scratch\p1fix\recheck-archive --root .claude\handoffs\_scratch\p1fix\recheck-restore\eval\baselines

# D：真实产物放行证据链（只读）
.\.venv\Scripts\python.exe -B .claude\handoffs\_scratch\p1fix\verify_release_chain.py .claude\handoffs\_scratch\p1fix\recheck-release.json

# Holdout 受限聚合（不开启 details；labels 只经既有入口引用，不读内容）
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite holdout --mode local `
  --holdout-labels docs\evidence\LOCAL-R1-20261101\P1-HOLDOUT\labels.jsonl `
  --out .claude\handoffs\_scratch\p1fix\recheck-holdout

# 前端
Push-Location frontend; npm run typecheck; npm run build -- --outDir ..\.claude\handoffs\_scratch\p1fix\recheck-dist --emptyOutDir; Pop-Location
```

证据路径：`docs/reports/OBS-EVAL/P1FIX/`（本报告 + `evidence/A-scope-refusal.md` …
`evidence/F-request-accounting.md`、`evidence/08-tests-and-evals.md` 与 `evidence/data/`；
原始对照脚本与中间产物在 `.claude/handoffs/_scratch/p1fix/`，gitignored）。
