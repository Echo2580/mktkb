# P2-T208-OFFLINE：Ragas 受控适配契约（v0.1）

> 状态：**OFFLINE 工程 / 开发自测待独立验收**。本契约只覆盖 T208 的离线 Mock 能力；
> 真实有限 judge sample、真实费用与 H2 辅助评分均未执行，T208 完整状态仍待真实阶段。
> 所有样例均为公共/自建合成输入；不读取、不导出真实 H2 题面、标签、逐题输出或密文。

## 1. 目标与边界

- 只读**已存在的公共/合成答案**（`RagasRun`），不重新生成产品答案、不调用产品问答路径。
- 使用实际安装并锁定的 Ragas 框架计算两个辅助指标，分别输出，不合成一个“总分”。
- 所有框架内 LLM/embedding/分解/批次调用都经同一 `JudgeBudgetGateway`；自动重试固定 0。
- 预算使用**临时合成账本**（stage=`P2-RAGAS-OFFLINE`），不接共享真实账本、预算或 r3 GO。
- 结果版本化；框架异常/非法值/预算拒绝一律 `unknown` 或 `blocked`，不记 0 分、不算通过。
- 软分只作辅助，不产生通过/发布判定，不能抵消 safety/跨用户/跨实体/失效来源等确定性硬失败。
- 模块默认关闭、`ragas` 惰性导入；缺依赖时既有评测模块和测试不被绑死。

## 2. 执行时版本矩阵（实际安装，不是范围）

| 组件 | 版本/身份 | 说明 |
|---|---|---|
| Python | 3.12.7（Windows x86_64） | 项目 `.venv` 同版本；隔离评测 venv 独立 |
| Ragas | **0.4.4** | 执行时 PyPI 最新稳定版；`requires_python >=3.9`；实际安装成功 |
| pytest | 9.1.1 | 与项目开发环境一致 |
| httpx | 0.28.1 | 与生产锁一致；测试网络闸门也依赖它 |
| numpy | 2.5.4 | 与生产锁一致 |
| pydantic | 2.14.1 | 隔离环境按生产锁解析；Ragas 0.4.4 兼容 |
| instructor | 1.3.2 | Ragas 0.4.4 的 `InstructorBaseRagasLLM` 结构化输出依赖 |
| langchain / langchain-core | 1.5.0 / 1.8.0 | Ragas 0.4.4 传递依赖（隔离环境） |
| openai | 1.109.1 | Ragas 0.4.4 传递依赖；**未构造客户端、未发请求** |
| pandas / scipy | 3.1.1 / 1.18.1 | Ragas 0.4.4 传递依赖（隔离环境） |
| tiktoken | 0.14.0 | Ragas 0.4.4 传递依赖（隔离环境） |

完整解析结果见 `backend/requirements-ragas-eval.lock`（独立评测锁；**不是**生产锁）。
生产锁 `backend/requirements.lock`、`backend/requirements-dev.lock` 未修改。

官方文档核对（执行时）：

- 指标目录：<https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/>
- Faithfulness：<https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/>
- Factual Correctness：<https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/factual_correctness/>
- 自定义模型/LLM 适配：<https://docs.ragas.io/en/stable/howtos/customizations/customize_models/>
- LLM adapters：<https://docs.ragas.io/en/stable/howtos/llm-adapters/>
- v0.3 → v0.4 迁移：<https://docs.ragas.io/en/stable/howtos/migrations/migrate_from_v03_to_v04/>

## 3. 实际使用的 Ragas API

0.4.4 的 `ragas.metrics` 旧入口已弃用（DeprecationWarning），本适配器使用
`ragas.metrics.collections` 的“modern components”实现：

```python
from ragas.llms.base import InstructorBaseRagasLLM
from ragas.metrics.collections import Faithfulness, FactualCorrectness

class _BudgetedInstructorLLM(InstructorBaseRagasLLM):
    async def agenerate(self, prompt: str, response_model: type[T]) -> T: ...

faithfulness = Faithfulness(llm=_BudgetedInstructorLLM(gateway))
factual = FactualCorrectness(
    llm=_BudgetedInstructorLLM(gateway),
    mode="f1",
    atomicity="low",
    coverage="low",
)
```

- `Faithfulness.ascore(user_input, response, retrieved_contexts) -> MetricResult`
  - 内部先 `StatementGeneratorOutput`，再 `NLIStatementOutput`；分值=支持语句/总语句。
- `FactualCorrectness.ascore(response, reference) -> MetricResult`
  - `mode="f1"`：先 response→reference（分解 + NLI），再 reference→response（分解 + NLI）；
  - 分值由 Ragas 按 TP/FP/FN 计算并 `round(..., 2)`；本适配器不重写公式。
- `InstructorBaseRagasLLM.agenerate(prompt, response_model)` 是唯一 judge 传输入口；
  适配器要求返回 `response_model` 实例，否则 `judge_output_invalid`。
- 未使用 LangChain wrapper、`llm_factory`、OpenAI 客户端或任何真实 provider 构造。

## 4. 接口

```python
async def score_ragas(
    run: RagasRun,
    *,
    judge: SyntheticJudgeTransport,
    authorization: RagasAuthorization | None,
    clock: Callable[[], datetime] | None = None,       # 测试注入；生产默认 UTC
    cost_per_call_cny: float = 0.0005,                  # 合成费用，不是报价
) -> RagasScoreResult: ...
```

### 4.1 `RagasRun` / `RagasCase`

- `RagasRun(run_id, plan_id, plan_sha256, source, cases)`；
  `source ∈ {"synthetic", "public_fixture"}`，`holdout` 一律拒绝（`run_source_not_allowed`）。
- `RagasCase(case_id, question, answer, contexts, reference, refusal=False, hard_failure=None)`；
  只允许已存在的公共/合成答案；适配器不生成、不修改、不重跑。
- `run.digest = sha256(canonical(run/cases))`；结果只带 digest，不带题面/答案/上下文/参考原文。

### 4.2 `RagasAuthorization`（离线合成授权）

| 字段 | 约束 |
|---|---|
| `authorization_id` / `run_id` / `plan_id` | 非空字符串，≤96 |
| `plan_sha256` | 64 位十六进制 |
| `judge_id` / `judge_version` | 必须与注入 judge 逐字一致 |
| `issued_utc` / `expires_utc` | 时区感知；`expires > issued` |
| `max_calls_per_case` | 正整数；实际 cap=min(该值, 6) |
| `max_calls_total` | 正整数；同时作为合成账本 `max_requests` |
| `max_cny_per_call` / `max_cny_total` | 有限正数；同时作为合成预算上限 |
| `mode` | 只能是 `offline_synthetic` |
| `production_ready` | 只能是 `False` |

该 DTO **不能**冒充 `P2Authorization`/真实 GO；适配器只接受本类型。真实阶段需要另立
授权与契约，不得复用本离线授权绕过 GO/账本/请求上限。

### 4.3 judge 传输

```python
class SyntheticJudgeTransport(Protocol):
    judge_id: str          # 与 authorization.judge_id 一致
    judge_version: str     # 与 authorization.judge_version 一致
    execution_mode: str    # 只能是 "synthetic"
    async def complete(self, prompt: str, response_model: type[T]) -> T: ...
```

`execution_mode != "synthetic"`、身份/版本不一致、缺 `complete` 一律 blocked。

### 4.4 结果

`RagasScoreResult`（schema=`p2-ragas-result/v0.1`）字段：

- `adapter_version`、`run_id`、`run_digest`、`status`、`complete`、`reason_code`；
- `ragas_version`、`python_version`、`metric_specs`（类/模块/版本/模式/每 case 调用数）、
  `prompt_digest`（实际 prompt 类/instruction/examples 的 sha256）；
- `judge` / `authorization` 摘要（无 key/无路径）；
- `cases[]`：`case_id/status/faithfulness/factual_correctness/reason_code/judge_calls/
  embedding_calls/charged_cny/hard_failure/metric_call_sequence`；
- `counts`（cases/scored/unknown/blocked/judge_calls/embedding_calls）；
- `cost`（currency=CNY, synthetic=True, per_call_cny/reserved_cny/charged_cny）；
- `ledger`（stage/synthetic/event_count/limit_cny/max_calls，不含路径）；
- `declared_worst_case_judge_calls=6`、`hard_failures`。

`status` 固定四值：`scored`（全部 case 有有效双指标）、`partial`（部分 scored）、
`unknown`（无 scored）、`blocked`（前置校验失败/依赖不可用）。`coverage_complete` 仅在
`status=="scored"` 时为 `True`（只表示评分覆盖完整）；`complete` 还要求
`hard_failures` 为空，因此任何确定性硬失败都会让 `complete=False`，软分不能抵消。
`auxiliary_only=True`、`quality_decision=None`。结果**没有** `passed`/`release_ready` 字段。

## 5. 指标与调用上界（先声明）

| 指标 | 框架调用序列 | 每 case 最坏调用数 |
|---|---|---|
| Faithfulness | `StatementGeneratorOutput` → `NLIStatementOutput` | 2 |
| FactualCorrectness(f1) | `ClaimDecompositionOutput` → `NLIStatementOutput` → `ClaimDecompositionOutput` → `NLIStatementOutput` | 4 |
| 合计 | — | **6** |

- `RAGAS_WORST_CASE_JUDGE_CALLS = 6`；网关实际 cap=`min(auth.max_calls_per_case, 6)`。
- 第 7 次同 case 调用在**预留前**停止，原因码 `case_call_ceiling_exceeded`。
- 总调用数达到授权/账本上限时停止，原因码 `call_budget_exhausted`/`budget_exhausted`。
- 自动重试固定 0：任何 judge 传输异常立即 `settle_failure` 并置 `stopped`；后续调用
  一律 `gateway_stopped`，不会隐式重试。
- 本轮两个指标都不使用 embedding，`embedding_calls` 恒 0；如未来接入 embedding 指标，
  必须同样走网关，不能绕过。

## 6. 预算网关与合成账本

每次 `agenerate`：

1. `begin_call`：检查 stopped/case 上下文/case cap/总调用数/单调用上界/授权时间；
2. `BudgetLedger.reserve`：在**临时合成账本**预留固定合成费用 `0.0005` 元，绑定
   run/case/metric/sequence/prompt digest；
3. `confirm_call`：发送前再次核对授权时间，并通过注入的 `post_reserve_guard` 真正复核账本
   （reserved 行唯一存在、该 reservation 尚未结算、预留金额/绑定字段未被篡改、
   累计请求/阶段金额/中心金额未超授权上限；失败 → 保守留账并停止，不发送）；
4. 调用注入的 synthetic judge；
5. `settle_success` 或 `settle_failure`；同一 ticket 二次结算 → `duplicate_settlement`。

合成账本由 `open_synthetic_ledger()` 在**系统临时目录下、由本进程新建**的空目录创建：

- `budget.limit_cny = authorization.max_cny_total`；
- `stages["P2-RAGAS-OFFLINE"] = authorization.max_cny_total`；
- `max_requests = authorization.max_calls_total`；
- 必须先校验 resolved 路径位于系统临时目录、目标目录尚不存在（本进程 `mkdir(exist_ok=False)`），
  并拒绝任何包含 `docs/evidence` 或 `LOCAL-R1-20261101/budget|PM` 路径段的目录；
- 拒绝写入共享真实账本、预算或 GO；评分结束即随临时目录删除；结果只保留聚合费用与事件数。

注意：`0.0005 元/次`是**合成演示费用**，不是供应商价格、不是本轮真实花费，也不代表 T208
真实 judge 预算。

## 7. 失败语义与原因码

| 场景 | 结果 |
|---|---|
| 授权缺失/类型错误/过期/未生效/跨 run/旧计划/非离线/非 production_ready | `blocked` + 对应 `authorization_*` 码，0 调用 |
| judge 缺失/非 synthetic/身份版本不一致 | `blocked` + `judge_*` 码，0 调用 |
| 单调用费用超上界 | `blocked` + `per_call_budget_exceeded`，0 调用 |
| 依赖缺失/版本不符 | `blocked` + `ragas_not_installed`/`ragas_version_mismatch`，0 调用 |
| 拒答 | case `unknown` + `refusal_not_applicable`，0 调用，不记 0 分 |
| judge 服务异常 | case `unknown` + `judge_service_error`，异常原文不进入结果 |
| judge 返回非 response_model | case `unknown` + `judge_output_invalid` |
| 分值为 NaN/Inf/非数值/越界 | case `unknown` + `invalid_metric_value` |
| 指标层返回分数但没有该指标**精确**的结构化调用序列（Faithfulness 2 次 SG→NLI；FactualCorrectness(f1) 4 次 Claim→NLI→Claim→NLI；0 次、1 次、反序或额外调用均不算） | case `unknown` + `framework_bypass_detected`（必须 FAIL） |
| 预算耗尽/case 调用上限/预留后失效 | 停止；当前/剩余 case `unknown` + 稳定码 |
| 确定性硬失败 | 保留 `hard_failure`，高分不清除；`auxiliary_only=True` |

所有原因码在 `RAGAS_REASON_CODES` 固定集合内；`score_ragas` 不抛出自由异常文本。
`_blocked_result`/`_auth_summary`/`_judge_summary`/`run.digest` 均用安全 getattr/兜底构造，
因此 `object.__new__(RagasAuthorization)` / `object.__new__(RagasRun)` 这类“isinstance 为真、
字段残缺”的伪造 DTO 也只会得到 `blocked` + 固定原因码，不会二次抛 `AttributeError`。
`score_ragas` 的最外层还有安全兜底：意外异常 → `blocked` + `adapter_internal_error`。

## 8. 安全默认

- `ragas` 只在本模块的 `_load_ragas()` 中惰性导入；模块 import 不导入 ragas、不构造 provider、
  不读 `.env`/key、不联网。
- 缺少 ragas 时，`mktkb.evaluation.ragas_adapter` 仍可 import；`score_ragas` 返回
  `blocked/ragas_not_installed`；既有评测测试不受影响。
- 只接受 `execution_mode="synthetic"` 的 judge；不调用产品 `QaEngine.answer` /
  `conversations.service.ask` / 任何真实模型、embedding、rerank、OCR、检索、鉴权或余额接口。
- 结果/日志/证据不含题面、答案、上下文、参考原文、key、异常原文或 `repr`；
  测试用合成哨兵核验 0 命中。

## 9. 测试与证据

定向测试（隔离评测 venv，实际安装 ragas 0.4.4）：

```powershell
cd backend
$env:MKTKB_NO_DOTENV='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:RAGAS_DO_NOT_TRACK='true'
& D:\mktkb-t208-ragas-venv\.venv\Scripts\python.exe -m pytest `
  tests/evaluation/test_p2_judge_budget.py tests/evaluation/test_p2_ragas_adapter.py `
  -q -p no:cacheprovider
```

结果与命令/退出码/collect/guard/spy 证据见
`docs/reports/OBS-EVAL/P2/T208-OFFLINE/dev-report.md` 与同目录 `evidence/`。

## 10. 未执行（NOT-RUN）与后续门

- **NOT-RUN**：任何真实 judge/模型/embedding 请求；真实费用/账本/GO；真实 5 条公共
  sample 校准；真实 H2 辅助评分；Langfuse 导出（T211）。
- **BLOCKED（待真实阶段）**：`real_judge` 授权模式、真实供应商价格/结算策略、真实
  rate-limit/超时语义；本契约不覆盖，也不得以本离线结果替代。
- 本契约和离线测试通过只表示工程能力可验证；不得写 `T208_OFFLINE_PASS`（由经理限定接收
  后记录），不得宣称 T208 完整通过或 P2 质量通过。
