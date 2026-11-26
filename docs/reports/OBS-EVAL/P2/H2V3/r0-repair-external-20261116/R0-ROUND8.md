# 第八轮真实 r0（2026-11-16 21:5x）——取码轮，质量仍 11/12

- 计划 `plan_sha256 18664a5c…525d`、`code_version 0800f16a…9867`（含候选丢弃原因采集：合成值 + 按面两键）。
- check-only 16/16；执行 `succeeded`，38 次真实发送，结算 **0.140808 元**，封存 clean。
- 质量 **11 pass / 1 fail**：唯一 fail = **C12**（与第七轮相同）。`requests_used 1692`，阶段剩余 **11.0738506 元**。

## C12 的按面取码结果（SAFE，仅固定码）

| 案/轮 | scope | 合成 | record 面 | document 面 | empty | units |
|---|---|---|---|---|---|---|
| C01/t0（pass 对照） | rag_candidate_upper_bound | term_miss | term_miss | **vector_unavailable** | false | 25 |
| C12/t6 | rag_candidate_upper_bound | term_miss | term_miss | **vector_unavailable** | false | 6 |
| C12/t6 | legacy_retrieve_initial | — | — | — | false | **1** |

**解读**：
1. document 面本轮**只有 lexical 通道**（`vector_unavailable`），向量召回没参与；
2. 候选上界有 6 个单元，但 legacy 自己的检索只留下 **1** 个 —— 丢失可能发生在 **legacy 过滤**（候选里有、legacy 筛掉），也可能期望来源根本不在那 6 个里（lexical 未命中 + 无向量）；
3. 这两者还需一步 SAFE 投影才能区分：**"期望来源的 (doc_code, unit_key) 是否出现在候选 6 元集合里"**（只出布尔与计数，不出内容）。

## 下一步（未执行）
1. 做上述一步投影（离线、0 元）→ 判定 `in_candidates=true`（修 legacy 过滤）还是 `false`（修 recall：lexical 词面 / 向量可用性）。
2. 按结论做最小修复 + 合成红绿。
3. 用掉本批最后 1 轮真实 r0 验证 12/12。

## 追加：A/B 判定的第一次尝试——**不可判定**（2026-11-16 22:0x）

用第八轮证据做"期望来源是否在候选集合里"的布尔投影，结果**不可判定**：

- C12 的 `db_projection.units` 只有 **1 行**（被引用的那一行），而候选上界有 **6** 个 id；
- 因此 `candidate_id -> unit_key` 映射对其中 5 个 id **无法解析**，`exp_in_cand=0/2` 是缺行 artifact，不是真结论；
- 同一原因导致 `exp_in_legacy=0/2` 也不可信。

**结论**：当前采集从不保留"候选单元的身份"，只保留被引用的单元。要判 A/B，需要再补一个枚举/身份级字段（例如 `candidate_unit_keys`：候选单元的 `unit_key` 列表，属标识符、非正文），或在 `retrieval_observed` 里记"期望来源是否命中候选"的布尔（但那需要评测侧把 gold 传进检索层，侵入更大）。

**建议的下一步（供决策）**：
1. 补 `candidate_unit_keys`（可选键、固定格式、非正文）→ 1 轮取码（≈0.14 元）→ 判 A/B；
2. 按 A/B 修 legacy 过滤或 document 面召回；
3. 用本批最后 1 轮真实 r0 验证 12/12（≈0.14 元）。

预算：阶段剩余 11.07 元，两步合计约 0.28 元。
