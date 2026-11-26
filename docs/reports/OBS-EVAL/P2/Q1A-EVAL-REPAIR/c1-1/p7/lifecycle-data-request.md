# C1-P7 权威逐源生命周期表：数据请求规格

> **2026-11-14 状态更新：本请求已作废（NOT-NEEDED）。** 主人说明本知识库为**测试项目、从未真实投入业务运营**，12 份语料为合成文档，**源侧生命周期日期本质上不存在**，不得事后编造。
> 主人已批准改走 **P1：`stale_source` 判据改为版本态比较**（用 scenario 契约已编码的 active 版本 + source map 版本号，不依赖日历）。本文件保留仅为记录曾评估过的数据路径，不再据此索取数据。

- 目的：补上第 5 个缺口（源侧 `published_at` / `effective_from` / `effective_to`），使 `stale_source` 从 0/30 可判。
- 背景：P6 实测 12 源**完整窗口 0/12、仅一端 0/12、无任何端点 12/12**；manifest / ingest plan / source map / scenario 契约一致只记顺序与版本号，零日期字段。
- 本件只是**请求规格**，不含任何真实数据；数据到位后另立新冻结件。

## 1. 需要的数据（最小集）

每行 = 一个「源 × 版本」（不是只到 doc_code）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `source_id` | str | 是 | ingest plan 的源标识（如 V03/V04/V05/V06 与 D01/D02 slot 的组合），按 12 源配方顺序 |
| `doc_code` | str | 是 | 该源的文档码（如 D01 / D02） |
| `version_number` | int | 是 | 该源的上传/发布版本号（source map 已给：V03→D01 v1、V04→D01 v3、V05→D01 v4、V06→D02 v2） |
| `published_at` | date `YYYY-MM-DD` \| null | 是（可空但须声明语义） | 该版本**对外发布**日 |
| `effective_from` | date \| null | 是（可空但须声明语义） | 该版本**开始生效**日 |
| `effective_to` | date \| null | 是（可空但须声明语义） | 该版本**失效/被取代**日 |
| `basis` | str | 是 | 该行日期来源：`runbook_s8` / `business_ledger` / `owner_ruling` / `corpus_metadata` |
| `note` | str ≤200 | 否 | 歧义说明（不得含题面/答案/目标值） |

## 2. 必须一并明确的语义（否则不能用）

1. **区间开闭**：是否按半开区间 `[effective_from, effective_to)` 解释？若否，请指明。
2. **null 的含义**：`null` = 未知（不可判），还是 = 无限（至今有效）？两者判定后果完全不同，必须区分。
3. **时区/业务日**：按 `Asia/Shanghai` 业务日解释，还是 UTC 日期？
4. **是否随 scenario 变化**：同一源在不同 scenario 下有效期是否不同？若不同，请按 `(scenario_id, source_id)` 给。
5. **同日边界**：`as_of` 恰等于 `effective_to` 或 `published_at` 时算不算违规？给一条规则。
6. **被取代关系**：某版本失效是因为「新版本发布」还是「业务下架」？`stale_source` 的语义只认前者还是两者都认？

## 3. 你可以选三种提供方式

| 方式 | 你要做的 | 我这边 |
|---|---|---|
| **A1 直接给表** | 按 §1 填 JSON（模板见 §4），附一句来源声明 | 冻结 → 保管 B 独立复核 → 零调用重算 → 给最终分数 |
| **A2 授权取源** | 明确授权「保管 A/B 可读 `T207-runbook.md` §8 及你指定的其他权威件」并指明清单 | 保管只提取日期、不转述其他内容 → 其余同 A1 |
| **A3 混合** | 一部分你给、一部分授权取 | 同 A1/A2 |

> 注意：P6 已提示 source map 对 runbook §8 的转述**只含版本号**，A2 有可能取不到日期。若 A2 取不到，我会立刻回报 NOT-RUN，不硬凑。

## 4. JSON 模板（12 行；`null` 请按 §2-2 先声明语义）

```json
{
  "schema_version": "p2-source-lifecycle/v1",
  "interval": "half_open_effective_from_to",
  "null_semantics": "unknown | infinite",
  "business_day_timezone": "Asia/Shanghai",
  "per_scenario": false,
  "sources": [
    { "source_id": "<V03|D01>", "doc_code": "D01", "version_number": 1,
      "published_at": null, "effective_from": null, "effective_to": null,
      "basis": "owner_ruling", "note": "" }
    // ... 共 12 行，按 12 源配方顺序
  ]
}
```

## 5. 数据到位后的处理（全部零真实调用）

1. 冻结为新件 `docs/evaluation/p2-source-lifecycle-v1.json` + SHA256；**不改**任何旧件。
2. **保管 B 独立复核**：逐行核来源声明、区间语义、与 source map 的版本号一致性；分歧保留。
3. 用该表 + 合同 v2 + P4 适配器（**先修 `M-C1P4-01` 的 fail-open**）在**旧证据**上重算 `stale_source`。
4. 产出新四轴与题级 pass → 这才是“干净分数”的候选。
5. 只有拿到该数，才讨论 C1-2 是否值得 108 请求。

## 6. 硬边界

数据表不得含题面/答案/目标值/私有密文/key；不改变 30 题/标签/阈值/四状态/评分标准；不改 C 冻结 12 与旧卡/账本/GO；零真实调用；不 stage/commit。
