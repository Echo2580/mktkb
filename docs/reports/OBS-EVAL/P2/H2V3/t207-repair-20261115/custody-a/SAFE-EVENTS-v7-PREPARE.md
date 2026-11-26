# SAFE-EVENTS-v7-PREPARE

状态：待 B 核查数据出口；未运行真实投影，未读取真实证据或 key。

- `safe_events_v7.py` 沿用 v6 受控内存 loader、case/run/turn/日期/来源绑定检查、网络拦截和固定异常出口。新增投影不输出计划过滤值、状态值、单位 ID、问题或回答文本。
- 计划 path 仅 `rag` / `legacy` / `unknown`，mode 仅 `record` / `document` / `unknown`；固定过滤维度输出键是否存在。状态字段输出是否有非空值；跨轮只比较上一轮 saved 与当前 observed 的显式集合和标识是否相同，缺字段或事件重复为 `unknown`，相同不表示已证明继承。
- `reason` / `answer_source` 白名单在读取真实事件前固定于脚本，来源为 `backend/src/mktkb/rag/answer.py` 的静态 reason 和 answer_source 字面量、`backend/src/mktkb/rag/query.py` 的静态计划 reason、`backend/src/mktkb/conversations/service.py` 的静态 `_Result` reason，以及 `backend/src/mktkb/providers/types.py` 的 `MODEL_FAILURE_REASONS`。严格全值相等才输出；其余字符串为 `other`，缺失或类型不符为 `unknown`。这是安全出口白名单，不改变题库预先登记或评分。
- 各阶段单位只与保管目标的实体类型、实体键和过滤条件比较，调用 `p2_evidence_rescore_axes._target_matches`；仅在单位和目标身份完整时输出可比较及非目标布尔，缺失、重复、未解析及检索截断为 `unknown`。这是 matcher v2 路径的实体目标比较，**不证明来源 ref 的版本身份匹配**，不修改或重算评分；请 B 专门核查此语义与覆盖范围。
- `SAFE-EVENTS-v7-SELFTEST.json` 记录纯合成正常、重复冲突、任意原因文本不输出、错 run、目标匹配/不匹配/无法解析等检查；本机网络拦截正对照 3/3。真实依赖的其他原生输出渠道仍需 B 评估。
- 实际投影入口 `--project-after-b-review` 未执行；不涉及真实请求、评分或产品验收。
