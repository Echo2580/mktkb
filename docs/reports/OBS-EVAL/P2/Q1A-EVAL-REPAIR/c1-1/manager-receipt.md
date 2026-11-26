# C1-1 补量具收口回执

- 日期：2026-11-14；分支 `codex/p2-e2e`；HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`；暂存空、0 commit。
- 依据：主人 2026-11-14 决定 **D1=C1（要数字）** → 先补量具（零调用），再定是否签 C1-2 复跑。
- 本回执**不写** T207 通过/质量通过/release/threshold；不构成 C1-2 授权。

## 1. 六个包结果

| 包 | 内容 | 结果 |
|---|---|---|
| C1-P1 | 合同 v2：实体 targets / shared_background / record_code 规则 | 已接收（PASS_WITH_DISAGREEMENTS；cross_entity 可匹配 0→16/30） |
| C1-P2 | 空集闭包全覆盖 | 已接收（PASS_WITH_DISAGREEMENTS；**对分数贡献≈0**；class C 硬条件） |
| C1-P3 | 采集契约 v0.3 | 已接收（PASS_WITH_DISAGREEMENTS；167 字段/49 码；1 个防御码开发漏测） |
| C1-P4 | 消费侧适配 v2 | 已接收（PASS_WITH_DISAGREEMENTS；两条红线实测干净；**IR-01 fail-open 待修**） |
| C1-P5 | 零调用复跑收益预判 | 完成；硬结论 **C1-2 不值得签 GO** |
| C1-P6 | 逐源生命周期可行性 | **NOT-RUN**（12/12 源无任何生命周期端点） |

## 2. 净收益（零调用已兑现）

| 项 | 结果 |
|---|---|
| `cross_entity` 可判 | **1 → 13/30**（键空间 aligned 13 / incompatible 0 / 缺字段 3），且 13 全 pass |
| `cross_entity` 乐观上界 | 16/30 |
| `stale_source` 可判 | **0/30**（第 5 个缺口：源侧生命周期证据全缺） |
| **题级 pass（现实）** | **0/30** |
| **题级 pass（乐观上界）** | **3/30** |
| 24/30 | **两种口径下均不可达** |

**题级为 0 的机制**：`stale_source` 是 30 题**全部 required**，它只要不可判，任何一题都不能被判为合格。cross_entity 判出 13 个也翻不动题级。

## 3. 第 5 个缺口（本轮新发现，一票否决）

- **缺什么**：源侧 `published_at` / `effective_from` / `effective_to`（被比较的一侧；`as_of` 不缺）。
- **缺到什么程度**：12 个源 **完整窗口 0/12、仅一端 0/12、无任何端点 12/12**。语料可见文本生命周期词命中 0；manifest / README / ingest plan / source map / scenario 契约**一致只记顺序与版本号、零日期字段**；source map 自述 "not an active-version assertion"。
- **不能用什么代替**：active-version 断言、addendum `business_date`、`manifest.built_at`（全语料同一常量 `2026-10-27`，对 V03/D01/V04/V05 一视同仁）。
- **只有谁能提供**：主人裁定（见 §5），或保管角色转述 runbook §8（但 source map 对 §8 的转述只含版本号，很可能仍无日期）。

## 4. C1-2 结论

**不签 GO。** 约 108 次真实请求换不到可用干净分数：`cross_entity` 的 1→13 已由零调用兑现，复跑不增加可判化；`stale_source` 结构性为 0。

## 5. 主人的下一步选项

| 选项 | 做法 | 代价 | 结果 |
|---|---|---|---|
| **A** | 下发**权威逐源生命周期表**作为新冻结件（主人裁定数据） | 需你提供或授权生成 | stale 有望可判，题级 pass 才可能上去 |
| **B** | **改 stale 判据口径**：用「是否使用了非该 scenario 的 active 版本」代替日期比较 | 属改评分口径，需你批准 | 零调用可做，但改变判定语义 |
| **C** | **转 C2（换 H2 v3）**：承认当前题库 stale 口径无法支撑判定 | 重做题库/标签，周期长 | T207 本轮 19/30 永不被解释清楚 |

经理建议：**先 A**（数据到位最干净、不改语义）；拿不到数据再 **C**。**不建议 B**——改判据会让本期分数失去可比性。

## 6. 必须记住的待修项

- `M-C1P4-01`：P4 适配器 11 个站点在非标量枚举时抛 `TypeError` 逃逸（fail-open）。**用 P4 做任何判定前必须先修**，否则不得作为判定依据。
- `IR-05/06`：合同 sha 仅标签钉扎（改 1 字节仍收）；v2 改名 v1 会被冻结 v1 消费者接受。
- 阶段一已确证的量具缺陷仍然成立：r0 safety 假阳性、locator-only 匹配使 stale 虚高 pass、旧 13 个 stale pass 在新口径下无 lifecycle 证据兜底。

## 7. 保全（终态）

C 冻结 12/12；15 tracked modified 路径逐条不变；暂存 0；0 commit；HEAD/分支不变；合同 v1/v2、Q1a-1/1b 模块与契约、P3/P4 模块、旧卡/账本/GO 全部未改；零真实调用（netguard 正对照）。

**停止：等主人选 A / B / C。不签 GO、不真实复跑。**
