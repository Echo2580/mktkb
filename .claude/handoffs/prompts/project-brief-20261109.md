# 市场部 AI 知识库（MKTKB）项目说明提示词

> 用法：把本文件**全文**粘贴给另一个 AI（或作为其系统提示），它即可在不读仓库的情况下准确理解本项目，并就代码、评测、文档、P1 收口提供帮助。
> 安全：本文件**不含任何凭据/密钥/答案原文/Holdout 逐题内容**；仍属项目内部资料，请勿公网发布。
> 最后更新：2026-11-09 21:1x（P1 暂停中）。信息以 `.claude/handoffs/_index.md` 为唯一事实源；与 README 冲突时以本文/`_index` 为准（README 冻结于 v0.1，未回写 P0/P1）。

## 0. 一句话

MKTKB（市场部 AI 知识库）是一个**面向企业部门场景的本地 RAG 知识库**：管理员上传资料 → 系统解析、建索引、按版本发布 → 员工自然语言提问 → 返回**带来源引用**的答案；资料里没有就明确返回「未找到」，不猜。项目为个人作品/学习项目（非 SaaS），**全部语料为模拟数据**，在 Windows 本地运行。

## 1. 定位、原则与边界

- 目标用户：管理员（上传/发布/看原件）、员工（提问/看来源）。
- 三条设计原则：
  1. **能精确就别语义**：门店/物品/字段值走结构化精确检索；流程/制度/正文走语义检索，两条路各有门禁。
  2. **答案必须可溯源**：回答必须引用已发布资料的具体单元；无引用、伪造值、跨实体、失效来源一律拒绝。
  3. **知识有版本**：资料可替换/删除/按版本发布；回答与引用绑定当时的知识库 revision，不「穿越」到新版本。
- 合规边界：模拟/虚构数据；3 份法规原文来自公开政务网站；未部署公网、无 HTTPS/域名；真实供应商实账未核对（账本为保守口径，不等于账单）。
- 历史基线：v0.1 冻结于 2026-11-04（tag `v0.1-local-20261104`），当时 948 pytest、真实 40 题矩阵 31/40（精确题 24/24、语义/扫描件 7/16）。**这些数字是历史值，不是当前状态。**

## 2. 已实现功能

- **资料管理**：xlsx/docx/PDF/png/jpg；单文件 ≤20MB、PDF ≤50 页、Excel ≤5000 数据行、图片 ≤2000 万像素；上传即建**持久处理任务**（worker 租约 + 心跳续期 + 检查点恢复）；解析预览/重试/报告；版本化与发布/取消/逻辑删除；原件受保护（管理员可看，员工只能通过引用访问，服务端校验归属）。
- **检索问答**：混合召回 = 结构化精确检索（门店/物品/字段）＋ 中文全文 FTS5（jieba 本地词典）＋ 向量召回 → **RRF 融合** → 可选 **rerank**；业务日期过滤（历史版本不串台）；事实门禁（伪造值/跨实体/跨字段/无引用/失效来源）；六类结果 `answer / clarification / not_found / conflict / service_error / knowledge_changed`；引用溯源；多轮会话（槽位继承 + 短追问）。
- **工程化**：请求幂等（`(conversation_id, client_request_id)` 唯一 + 在途防护 + 迟到结果 fencing）；提交事务前重检 revision/归属/引用有效性；**预算账本**（预留→结算、失败留账、阶段额度、请求上限、零自动重试）；SQLite 单机 + Alembic；Windows 一键启动。

## 3. 技术栈与架构

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · Uvicorn（默认 `127.0.0.1:8077`） |
| 数据 | SQLite（WAL + FTS5）· SQLAlchemy 2 · Alembic |
| 配置 | Pydantic 2 · pydantic-settings；凭据只在本机 `.env` |
| 解析 | openpyxl · python-docx · pdfplumber · pypdfium2 · Pillow |
| 中文检索 | jieba 0.42（本地词典）· FTS5 · numpy 向量矩阵 |
| 模型服务 | DeepSeek Chat（httpx 0.28）· DashScope `text-embedding-v4`(1024) · `gte-rerank-v2` · 腾讯云 OCR |
| 前端 | React 19 · TypeScript 5.9 · Vite 8 · React Router 7（默认 `127.0.0.1:5673`） |
| 测试 | pytest（当前 **1933 passed**）· Playwright 1.64 |

**三库分离**（物理隔离）：`var/mktkb.sqlite3`（业务/会话/引用）、`var/rag-index.sqlite3`（精确索引/FTS/向量）、`var/observability/qa-traces.sqlite3`（Trace，P0 新增）。

**Provider 模式**：`offline`（默认，确定性替身，零真实调用）/ `local`（本地真索引，Mock 外部 provider）/ `live`（真实 API，受预算账本与 GO 约束）。真实调用**默认关闭**，只有 `启动-真实问答.cmd` 或显式 `MKTKB_RAG_PROVIDER_MODE=live` 才发生。

## 4. 仓库地图

```text
backend/
  src/mktkb/             # auth 认证会话角色 / documents 资料版本发布 / ingestion 上传任务解析
                         # conversations 问答编排提交事务 / qa 产品问答引擎 / retrieval 混合检索RRF rerank
                         # rag RAG内核事实门禁预算 / sources 引用 / providers 模型OCR适配
                         # evaluation 评测(P0/P1) / observability Trace与只读监控API
  migrations/            # Alembic 0001→0005
  tests/                 # unit / integration / rag / acceptance / evaluation / observability
frontend/                # React 19 + TS + Vite；e2e 用 Playwright
tools/                   # 语料生成、受控真实调用、启动器、探针、rag_eval CLI
fixtures/
  acceptance/            # 冻结验收语料（D01–D10、边界样本）
  evaluation/            # 评测数据集 b0.jsonl/badcase.jsonl/regression.jsonl/holdout-questions.jsonl
corpus/enterprise-20261101/   # 企业模拟资料库（含 3 份法规原文）
docs/
  superpowers/specs/     # 评测与可观测性设计（P0，P1 复用口径）
  superpowers/plans/     # P0 实施计划
  evaluation/            # trace_schema_v0_1.md / eval_data_v0_1.md / gate_v0_1.json / gate_v0_2.json
  reports/OBS-EVAL/P0|P1/  # 证据（入库）：开发证据 evidence/T<NNN>/、验收证据 evidence/verify/T<NNN>/
  接口与数据契约.md       # API 契约、错误码、六类结果结构（T114 新增 §8 监控接口）
var/                     # 运行时：业务库/索引库/Trace/评测 run（gitignored，不入库）
docs/evidence/           # 本地证据与账本/GO（gitignored，不入库；含 Holdout，开发禁用）
.claude/handoffs/        # 项目流程协调区：任务单/报告/验收/提示词/_index（PM 工作流）
```

## 5. 评测与可观测性子系统（P0 + P1，重点）

- **Trace 契约 v0.1**：每次执行尝试一条 Trace（`trace_id`）；`request_id` 对产品请求 1:N；`content_mode=off|hash|redacted|full`（真实默认 hash，不存原文）；span 名称/必需 span 按 `path+outcome` reason-aware；gate 校验 `required_spans`。
- **评测器**：`replay`（读冻结 run，验证确定性评分）/ `local`（本地真索引 + Mock provider）/ `live`（仅 `scope=retrieval_only`，P1 用）；`run` 产物 = `run_manifest.json` / `cases.jsonl` / `summary.json` / `gate.json` / 报告。
- **双层门禁**：8 项硬门禁（`security_leak`、`cross_entity`、`stale_bypass`、`conflict_not_rejected`、`exact_value_contract`、`pagination_contract`、`citation_required`、`trace_integrity`）+ 质量层（按 stratum 报告、不设综合分；指标见下）；退出码 **0 通过 / 1 硬失败 / 2 质量回退 / 3 数据/配置/gold/样本不足 / 4 live 未授权**。
- **质量指标**：检索 Recall@10/MRR@10/nDCG@10/hard_filter_violation_rate/empty_recall_rate；答案 value_hit/source_hit/kind_correct/citation_precision/citation_recall；拒答 refusal_recall/false_refusal_rate/refusal_precision；运行 P50/P95/tokens/单题成本/重试/degraded。每指标含 `direction`/`min_sample`/`absolute_min|max`/`max_regression_pp`。
- **Baseline**：`baseline_id = sha256(dataset_version + pipeline_version + mode + scope + gate_version + corpus_sha256)`；发布放行只接受同 pipeline 的 release baseline；首次建立只用绝对阈值；跨版本比较 `explicit_cross_version` 只分析不放行；无 copy 命令；`baseline approve` 现场重算门禁并写 `approval.json`。
- **P1 专项**：7 项缺陷修复（ERR 编号 T101–T106）、regression suite、Holdout 30（防污染：默认只聚合、`--allow-holdout-details` 默认拒绝）、多轮 turns runner、检索金标与指标（同 chunk 同排名）、live retrieval_only 运行器（真实 embedding/rerank、零 chat、零重试、fail-closed、隔离索引）、`gate_v0_2.json`（检索阈值 + regression suite）、P1 release baseline、监控 API（4 个只读 GET：`/api/v1/observability/{traces/{trace_id}, requests/{request_id}/traces, metrics, runs/{run_id}}`，admin 权限，只返回哈希/计数，不暴露 Holdout 明细）。
- **预算/GO**：共享账本 `docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl`（每次真实请求预留/结算）；GO `docs/evidence/LOCAL-R1-20261101/PM/S2-LIVE-GO.json`（阶段 `P1-RETRIEVAL` 3.0 元、services=["rag"]、max_requests=1000、单笔 ≤0.05 元、有效期至 2026-11-30）；运行必须 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`。

## 6. 当前状态（2026-11-09 21:1x，重要）

- **分支**：`p1/fix-retrieval`（自 `main@083eaef`，P0 已合并 PR #1）；HEAD `d6e632c`；工作树 clean；**未 push**（远端无 p1 分支）；**P1 PR 未开**。
- **进度**：P0 已 G5 通过并合并；P1 的 T100/T107/T101–T106/T108–T114 **全部 G6 收口**，T112（门禁阈值校准与 P1 baseline）已收口。**唯一剩余 = T900（P1 独立总验收 + 1 个 PR 不合并）**。
- **P1 关键产物**：`gate_v0_2.json` **approved**（仅检索层，主人 2026-11-09 批准：`min_sample=8`；Recall/MRR/nDCG `absolute_min=0.855`；hard_filter `absolute_max=0.02`；empty_recall `absolute_max=0.145`；`max_regression_pp=2.0`；answer/refusal/runtime 仍 unapproved）；**P1 release baseline `bc6f6f906db1`**（b0 live 40 题，gate exit 0/quality pass）；监控 API 已交付（T113/T114）。
- **真实调用现状**：账本 **505/1000 请求预留**（S2-DEV 381 + P1-RETRIEVAL 124）；P1-RETRIEVAL 阶段已计约 **0.0142293 / 3.0 元**；总 accounted ≈15.07/20；`provider_billed_cny=null`；GO 前缀 sha `f4710b18…` 未变。b0 live 指标（all/exact/text）：Recall=MRR=nDCG = 0.96875 / 1.0 / 0.875，hard_filter 0，empty_recall all 0.03125 / text 0.125。
- **测试**：当前全量 `pytest backend/tests` = **1933 passed / 0 failed / 0 error**（Windows 单进程约 8–13 分钟）。
- **暂停状态**：主人指令 **T112 完成后暂停**（2026-11-09 20:0x）；恢复第一步 = 派 T900 总验收（handoff/prompt 已备：`.claude/handoffs/T900-p1-closeout/handoff.md`、`prompts/T900-verify.md`）。
- **已知残余（非阻塞，详见 `_index` #51–#59）**：T105 政策词+字段词组合可能整条倾倒（P2）；T106 `not_found` 徽标/INVALID_QUERY e2e 未跑；T108 3 道拒答题分数 fail、report 超行数；T109/T110/T111 口径与展示类残余；T111 GO 计划计数与实际有差；T113 OpenAPI 无 securitySchemes（文档已声明以 401/403 表达）；T112 diff 放行路径不重新核对 gate 配置哈希（审批后改阈值需另行治理）；P1 §9 第 4 条只覆盖 b0 live，badcase/regression/holdout live 为 **NOT-RUN**（主人方案 A 请求上限决策）。

## 7. 硬约束 / 红线（任何 AI 协助时必须遵守）

1. **零真实调用**：除主人显式放行的 live（T111 pilot、T112 b0 baseline 已发生）外，不调用真实模型/embedding/rerank/OCR；不读 `.env`、不打印凭据；不把密钥写入文档/证据/命令历史。
2. **Holdout 保护**：不读 `docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/` 逐题内容、不写入库、不在报告中泄露题干/答案；只允许使用仓库内无答案导出与聚合结果。
3. **不改契约**：不改业务 API 请求参数/响应 Body 字段结构；不改业务库/索引库 schema；不新增生产依赖。
4. **不动只读区**：`docs/evidence/**`、`var/**`（业务数据/账本/GO）、冻结 fixtures（`fixtures/evaluation/{b0,badcase,regression}.jsonl` 既有内容）不写；**不 commit 账本/GO**。
5. **不越权**：不 push main、不合并 PR、不杀外部服务（如 AstrBot）；P0 三项可选项（阈值审批/真实 baseline/设计 §7.2 回写）保持冻结（P1 的 gate_v0_2/baseline 是 P1 产物，不等于解冻 P0 项）。
6. **测试口径**：先 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"`；命令 `.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`；**同一工作区禁止并发跑两套 pytest**；全量前空闲内存 ≥2GB；两个既有 flake（`test_g08_short_budget_cancels_inflight_model_call`、`integration/test_lifecycle.py::test_concurrent_publish_and_global_revision_cas[v05]`）隔离复跑 1 次即过，不据此返工。
7. **诚实呈现**：区分「已验证 / 未跑（NOT-RUN） / 环境阻断（BLOCKED）」；不把未跑写成通过，不伪造 review/证据；`NOT-RUN` 必须说明原因。
8. **门禁/审批不可代签**：阈值、baseline、PR 的人工审批由项目主人做；AI 只能产出提案/证据。

## 8. 关键文档阅读顺序（给接手者）

1. `README.md`（产品、功能、快速开始；注意其状态表是 v0.1 历史值）
2. `docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md`（评测/可观测性设计，§8 门禁、§9 basline、§11 P0 七条）
3. `.claude/handoffs/2026-11-04-p1-design.md` §9（**P1 七条验收**）、`2026-11-04-p1-task-breakdown.md`
4. `docs/接口与数据契约.md`（API/错误码/六类结果/§8 监控接口）
5. `docs/evaluation/{trace_schema_v0_1.md, eval_data_v0_1.md, gate_v0_1.json, gate_v0_2.json}`
6. **`.claude/handoffs/_index.md`（唯一事实源：逐包状态/PM 裁定/残余 #30–#59）**
7. `.claude/handoffs/2026-11-06-p1-pause-handoff.md` §15/§16（最新现场与恢复步骤）
8. 各包 `.claude/handoffs/T<NNN>-*/{handoff.md, report.md, review.md}`（任务单/开发自述/独立验收）

## 9. 常用命令

```powershell
# 全量测试
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY = "20.0"
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider --basetemp backend\.pytest-tmp\label

# 启动（推荐）：双击 一键启动.cmd（后端 8077 / 前端 5673，offline 模式）
# 真实问答：启动-真实问答.cmd（live 模式，写入预算账本）

# 现场核对（任何时候先做）
git branch --show-current; git log --oneline -5; git status --short
Get-Content .claude\handoffs\_index.md -Encoding UTF8 | Select-Object -First 12

# 评测（零真实调用；CLI 细节以 --help 为准）
.\.venv\Scripts\python.exe -B tools\rag_eval.py run --suite b0 --mode local --out var\eval\runs\<label>
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run var\eval\runs\<label> --config docs\evaluation\gate_v0_2.json

# live 检索（受 GO/账本约束；当前仅有历史产物，除非主人放行否则勿重跑）
.\.venv\Scripts\python.exe -B -m mktkb.evaluation.live --suite b0 --dataset fixtures\evaluation\b0.jsonl --allow-full-live --dry-run
```

## 10. 如何帮忙 / 不要假设

- **不要假设 README 路线图是现状**：P0/P1 已落地但 README 未回写；以 `_index` §6 为准。
- **不要假设测试数/指标**：README 的 948、31/40 是 v0.1 值；现行 1933。
- 改动前先读对应 `handoff.md` 的「允许路径/验收标准」与 `_index` 的 residual；不确定的边界先问项目主人。
- 输出结论必须带证据：命令 + 退出码 + `文件:行`；区分「我亲自复跑」与「读到的报告」。
- 拒绝为了通过而放宽门禁/改断言/删测试/写假证据；发现问题先出可执行的返工条件。
- 若在当前 AI 助手中继续开发包：子智能体模型约定 `wb / cn:deepseek-v4.1-flash`，`reasoning_effort=max`；一包一开发 + 一包一全新上下文验收；PM 只写 `.claude/handoffs/**`。

## 11. 术语表

| 术语 | 含义 |
|---|---|
| `trace_id` / `request_id` | 单次执行尝试 / 产品请求（1:N） |
| 六类结果 | answer / clarification / not_found / conflict / service_error / knowledge_changed |
| B0 / badcase / regression / holdout | 40 题主评测集 / 13 题 Bad Case / 7 题回归集 / 30 题留出集（开发禁用逐题） |
| 双层门禁 | 8 硬门禁（exit 1）+ 分 stratum 质量层（绝对阈值/回退检测） |
| gate v0.1 / v0.2 | 冻结门禁配置 / P1 检索阈值与 regression suite 的生效配置（v0.2 已 approved） |
| release baseline | 同 pipeline 版本发布放行基准（P1 = `bc6f6f906db1`，b0 live） |
| GO | live 授权文件（阶段/服务/额度/请求上限/账本 sha/有效期） |
| `T<NNN>` 包 | 项目任务包编号（T100–T114 开发包、T900 收口包） |
| G0–G6 | PM 工作流门：接单/派单/开发完成/验收启动/验收/人工审核/收口 |
| NOT-RUN / BLOCKED | 未执行（附原因） / 环境或前置阻断（不等于通过） |
