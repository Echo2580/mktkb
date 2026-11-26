# SAFE-EVENTS-v8-PREPARE

状态：等待 B 核查；未读取真实证据或 key。

- 保留 v6 的受控 loader、case/run/turn/日期/来源绑定检查，以及 v7 的固定 reason 和 answer_source 白名单。计划 path、mode、固定过滤键存在性仍可按已有 capture 字段输出。
- 状态字段须通过 capture 与 conversation/request 的用户及会话身份一致性检查；observed 要求记录存在且存储身份一致，saved 按原代码语义允许首次保存前记录不存在，但须与唯一的投影状态行一致。缺失、冲突、截断、重复或身份不明为 `unknown`。跨轮只在前一轮 saved 与当前 observed 身份一致时比较；标识相同不代表已证明继承。
- 阶段目标比较全部固定为 `unknown`：尚未证明阶段 scope/purpose、单位重复、缺失过滤值、投影截断、未解析单位、空集合和目标身份能够共同形成完整证据。直接 RAG 引用层与事实来源层分别标为 `direct_rag_citations`、`direct_rag_facts`，两者均不冒充完整阶段结果。此版本没有输出目标匹配布尔，也没有运行 matcher 或改变评分。
- `SAFE-EVENTS-v8-SELFTEST.json` 记录合成正常及 B 提出的反例；本机零出站正对照 3/3。固定 `unknown` 是保守限制，不能用于推断实际阶段不存在非目标单位。
- 尚未运行 `--project-after-b-review`；不涉及真实请求、重打分或产品验收。依赖库的其他原生输出渠道仍需 B 核查。
