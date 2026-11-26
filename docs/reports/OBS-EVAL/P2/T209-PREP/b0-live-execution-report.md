# T209 正式 B0 单次真实运行 · 执行回执

2026-11-20，Asia/Shanghai。执行角色：真实运行执行 AI。工作树 `D:\GPT项目\市场部AI知识库`，分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`。

**执行状态：`BLOCKED`**，阻断发生在首个发送之前。本轮**零请求、零预留、零费用**，共享账本与预算字节未变。质量结论单列：**本轮无质量数据**（未执行，非不达标）。

## 1. 一句话结论

绑定、资金、预检、GO 全部通过；真实 `p2-run` 在 `load_live_env` 的模型授权检查处被拒（`live_chat_model_not_authorized`），原因是工作区 `.env` 里 `MKTKB_MODEL_NAME=deepseek-chat`，而任务书冻结的计划与代码钉住的模型是 `deepseek-flash`。按任务书"配置前置无法证明即停在发送前、禁止重试"执行：记录阻断、封存 GO、恢复固定槽，未做第二次调用。

## 2. 摘要

| 项 | 值 |
| --- | --- |
| 运行 ID | `p2-t209-b0-20261120-01` |
| 计划 ID | `P2-T209-B0-20261120-01-DRAFT` |
| 计划规范摘要 | `c3dbbafa2a1baa9b447495dc1bab06a8f6322e5b376a87a7c12ae563abec3228` |
| 计划文件摘要 | `41e408fb0e4b4c83ab866f796330c8149294cbbfd9a4b7bc5fdeb70f693090b3` |
| 本轮 GO 文件摘要（已封存） | `61a30569b24ad75eacb4c7890cbcdf36facdbf52f082db6ba4807ce08f2a8561` |
| 本轮 GO 规范摘要 | `83a67b30a13730176cf3c71a9988988c70075629b36b26e99ec5c96f4cd71dee` |
| GO 生效 / 到期（UTC） | `2026-11-20T08:21:56+00:00` / `2026-11-20T11:21:56+00:00` |
| GO nonce | 32 字符（值未打印、未落盘明文以外位置） |
| 固定槽恢复后摘要 | `43e0f6229efeae77334e821b91548b7024a1aefdf5824a9586f4c8d12330aaad`（= 签发前原件） |
| 执行开始 / 结束（UTC） | `2026-11-20T08:22:26.7758657Z` / `2026-11-20T08:22:28.4880797Z`（1.71 s） |
| 执行退出码 | **3**（发送前拒绝） |
| 准入退出码 | **NOT-RUN**（无 run 目录，未执行 `p2-admit`） |
| 实测请求 / 预留 / 费用 | **0 / 0 / 0 元** |

## 3. 发送前复核（全部通过）

- 分支 `codex/p2-e2e`、HEAD `97b0066…`；工作树 43 项已跟踪修改、0 暂存，与任务书接续状态一致，未新增/删除任何跟踪文件。
- 19 项冻结件逐文件 SHA-256 与任务书快照一致（0 处漂移）；绑定计划双摘要与任务书逐字相同。
- `build_b0_plan_binding("p2-t209-b0-20261120-01")` 原位重算，与 `plan.b0_binding` **逐键相等**：`business_date=2026-10-28`、`dataset_file_sha256=bd4f0f7c…`、`dataset_sha256=bd4f0f7c…`、`corpus_sha256=9ea5a422…`、`gate_config_hash=7fa6f47a…`、`pipeline_source_sha256=6fbde812…`。
- 题集 40 题（Q01–Q40）、`fixtures/evaluation/b0.jsonl` 摘要 `bd4f0f7c…`；配方 12 源、10 槽位（D01 三版本同槽，V04 `publish=false` 未发布），语料投影摘要 `9ea5a422…`，与冻结值一致。
- 已批准配置 `gate_v0_3_approved.json` 文件摘要 `b1094cc7…`、加载器摘要 `7fa6f47a…`、`gate_version=mktkb.gate.v0.3`、`status=approved`。
- 输出目录 `var/eval/runs/p2-t209-b0-20261120-01` 事先不存在；共享账本中该 run ID 的预留/发送记录为 **0 条**。

## 4. 资金与账本前置（只读）

| 项 | 实测 |
| --- | --- |
| 账本文件摘要 | `674180582c87c2096731968e901a1c1c0ac4038328cc1fbe047a197068ad96c1` |
| 历史前缀摘要（GO 绑定值） | `f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014` |
| 预算文件摘要 | `79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e` |
| 预留 / 结算 | 2455 / 2455（待结算 0） |
| 项目总上限 / 已占用 | 40.0 元 / 25.7249145 元 |
| P2 阶段上限 / 已占用 / 余额 | 20.0 / 10.65397 / **9.346030 元** |
| 分中心已占用 | answer_retrieval 4.446982、ocr 6.15、judge 0.056988、independent 0 |
| 项目余额 | **14.2750855 元** |
| `preflight_p2` | **ok**，reasons `[]` |

以上与任务书引用的经理快照逐值一致。

## 5. 本轮 GO

- 固定槽 `docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json` 原为 T207 r3 的旧 GO（`43e0f622…`，1306 B，plan `P2-H2V3-20261115-r3-post_v05_without_v01`，已于 `2026-11-20T02:51:29Z` 过期）。已按任务书**先保存原字节**到受控目录。
- 候选 GO 在隔离位置验证结构：`document/schema/stage` 正确，12 个顶层键与 7 个 scope 键精确，`operations` 恰为六种，四成本中心 `answer_retrieval=6.50 / ocr=12.00 / judge=0.50 / independent=1.00`，`stage_limits_cny={"P2-LIVE":20}`、`max_requests="unlimited"`、`max_request_cny=0.50`、`budget_total_limit_cny=40`、`budget_ledger_sha256` 绑历史前缀。
- 原子写入固定槽后从固定文件重读并 `authorize_p2`：`production_ready=true`、plan/scope 匹配、账本绑定成立、预算 `payload_sha256=891263d8…`。
- 收尾已封存本轮 GO 原件并**按签发前副本恢复固定槽**（恢复后摘要 `43e0f622…`，逐字节等于原件）。

## 6. 执行与阻断

一次性命令（仓库根，`tools/rag_eval.py p2-run` 原样参数）：

```text
.\.venv\Scripts\python.exe -B -X utf8 tools\rag_eval.py p2-run --mode live --visibility public ^
  --run-id p2-t209-b0-20261120-01 ^
  --plan docs/reports/OBS-EVAL/P2/T209-PREP/b0-request-plan.bound-draft.json ^
  --gate-config docs/evaluation/gate_v0_3_approved.json ^
  --cases fixtures/evaluation/b0.jsonl ^
  --ingest-plan docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-R1.json ^
  --out var/eval/runs/p2-t209-b0-20261120-01
```

主进程环境仅注入白名单变量（变量名：`MKTKB_MODEL_API_KEY`、`MKTKB_MODEL_BASE_URL`、`MKTKB_MODEL_NAME`、`DASHSCOPE_API_KEY`、`MKTKB_OCR_SECRET_ID`、`MKTKB_OCR_SECRET_KEY`，另加 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=40.0`），值不打印、不落盘、不复制到第二个文件。

真实结果：

```json
{"ok": false, "mode": "live", "status": "blocked",
 "error_code": "live_chat_model_not_authorized",
 "detail": "chat 模型必须是已核模型 deepseek-flash",
 "requests_sent": 0, "real_requests": 0}
```

- 退出码 **3**，耗时 **1.71 s**，run 目录未创建，零出站。
- 失败点在 `run_live_p2` 的 `load_live_env`，**早于** `open_live_gate`、早于首个预留、早于任何 HTTP。因此本轮 GO 未被"使用"，也未被消耗。

### 最小复现

```text
# 环境里有 MKTKB_MODEL_NAME=deepseek-chat（工作区 .env 原值）
.\.venv\Scripts\python.exe -B -X utf8 -c "import sys;sys.path.insert(0,'backend/src');from mktkb.evaluation.p2_live import load_live_env;load_live_env()"
→ P2LiveConfigError: live_chat_model_not_authorized: chat 模型必须是已核模型 deepseek-flash
```

只读复核（不发送、不建门）：把同一组变量中的 `MKTKB_MODEL_NAME` 换成计划钉住的 `deepseek-flash` 后，`load_live_env` 通过——`chat_host=api.deepseek.com`、`dashscope_host=dashscope.aliyuncs.com`、`ocr_region=ap-guangzhou`、`ocr_enabled=true`。即除该模型名外，其余环境前置均就绪。

## 7. 逐类请求与账务差额

| 操作 | 计划 | 实发 | 差额 |
| --- | --- | --- | --- |
| index_embedding | 22 | 0 | −22 |
| query_embedding | 40 | 0 | −40 |
| rerank | 40 | 0 | −40 |
| query_expansion | 40 | 0 | −40 |
| answer | 40 | 0 | −40 |
| ocr | 12 | 0 | −12 |
| **合计** | **194** | **0** | **−194** |

账务：预留 +0、结算 +0、待结算 0、保守占用 +0 元、零出站预留 0、供应商请求数 0、重试 0。账本文件摘要、预算文件摘要、P2 阶段占用（10.65397）与分中心占用前后完全一致；预算目录无残留 `.lock` 或临时文件。

## 8. 证据与可复核路径

隔离证据目录 `var/eval/t209-prep/b0-live-20261120/`（git 忽略）：

| 文件 | 内容 |
| --- | --- |
| `precheck.py` / `precheck/precheck.json.txt` | 发送前只读复核（绑定、题集、语料、配置、快照、预检、凭据就绪） |
| `mint_go.py` / `logs/mint-go.json.txt` | 旧 GO 存档、候选验证、原子写入、固定槽重读授权 |
| `go/P2-LIVE-GO.before-t209-b0-20261120T082156Z.archived.json` | 签发前 GO 原字节（`43e0f622…`） |
| `go/P2-LIVE-GO.candidate-20261120T082156Z.json` | 本轮候选 GO（写入固定槽的同一内容） |
| `go/P2-LIVE-GO.t209-b0-20261120-01.sealed.json` | 本轮 GO 封存原件（`61a30569…`） |
| `run-once.ps1` | 一次性执行入口（白名单注入、捕获 stdout/stderr 与退出码） |
| `logs/p2-run.stdout-stderr.txt` | 真实输出（UTF-8） |
| `logs/p2-run.meta.json` | 起止时间、耗时、退出码、执行前后账本/预算/GO 摘要 |
| `seal_go.py` / `logs/seal-go.json.txt` | 封存、恢复固定槽、只读对账 |
| `env_probe.py` / `logs/env-probe.json.txt` | 环境只读复核（原样拒绝；对齐计划模型后通过） |

run 工件：`var/eval/runs/p2-t209-b0-20261120-01/p2-run` 下七份工件与 `data/observability/qa-traces.sqlite3` **均不存在**（未创建），故无 SHA-256 可算，属预期缺失而非丢失。

## 9. 合规声明

- 只发出**一次** `p2-run` 调用；失败后未续跑、未补跑、未重试、未并发、未扩大配额。
- 全程未删除、截断或手改共享账本与预算；未改动生产源码、仓内测试与 Git 记录。
- 未回显或复制任何凭据值；GO nonce 仅记录长度。
- 正式基线接收、`p2-approve`、P2 发布与 T900 未触碰。

## 10. 交回经理

**阻断原因属环境前置，不属代码或接线缺陷**：任务书冻结的模型是 `deepseek-flash`，工作区 `.env` 给的是 `deepseek-chat`；两者不一致时执行在发送前被拒，这是门禁的预期行为。

两条可选处置（均需主人/经理决定，本轮未擅自执行）：

1. **授权一次带更正环境的执行**：不改 `.env`，仅在执行进程内把 `MKTKB_MODEL_NAME` 对齐到计划钉住的 `deepseek-flash`（其余变量、供应商、主机、价格与配额完全沿用）。已用只读探针验证该组合可通过 `load_live_env`。需重新签发本轮 GO（上一枚已封存、固定槽已恢复）。
2. **先更正工作区 `.env` 的模型名**，使其与已批准计划一致，再另行授权执行。

若不接受以上任一路径，本轮按 `BLOCKED` 结案：资金零消耗，账本与 GO 现场均已复原，可在同一授权额度下另行安排。
