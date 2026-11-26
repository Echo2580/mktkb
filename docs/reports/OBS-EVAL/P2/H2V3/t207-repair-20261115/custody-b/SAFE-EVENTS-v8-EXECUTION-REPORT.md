# SAFE-EVENTS-v8-EXECUTION-REPORT

- A 的四个 case 与 B 在受控内存中复现的投影一致。复现使用同一 loader 与投影代码，是独立复跑而非不同实现交叉验证；未输出或保存私有中间内容。
- 脚本 SHA256 `b1fbc8528970451137e0c9b9f4ddeb088ef3c37fe8cad82224d375cab275ccf4`、投影 SHA256 `94c24193846acc641155bf2da906b6077ec8b9d2688c738cf9db5eeef3b76a49` 与执行回执一致；脚本与 B 先前审查记录一致。来源 SHA256 `1987dfcf5920513aa639fe2da4c459f8ac28658fe64eaea5d34487690e3a97cd` 一致；复现完成 case/run、plan/run、turn index 和收据日期绑定检查。
- 可供开发使用的四 case 逐轮固定码、枚举、布尔和 `unknown` 见 `SAFE-EVENTS-v8-EXECUTION-CHECK.json`；逐层出口白名单校验通过。
- `plan_path`、`plan_mode` 与 `filter_keys_present` 表示捕获计划事件的固定码或键是否存在，不给出过滤值；`reason` 和 `answer_source` 仅为静态白名单的全值匹配，`other` 不揭示原值。
- 状态字段只表示事件中非空状态是否存在；跨轮布尔只比较前一 saved 与当前 observed 的显式字段，标识相同不证明继承。缺失或无法确认仍为 `unknown`。
- 各阶段目标关系全部为 `unknown`，不能推断是否使用非目标单位；直接 RAG 引用和事实来源分列但均无确定匹配结果，不等于版本身份匹配或新评分。`target_count` 是标注目标数，不能当作运行时槽位数。
- 本机出站拦截正对照 3/3；账本和预算哈希一致。来源 C26/C28 安全轴保留旧判定；本次不构成新产品复测或验收。
