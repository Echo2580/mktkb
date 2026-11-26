# 第九轮真实 r0（2026-11-16 22:2x）——取码轮，**A/B 判定已完成 = A**

- 计划 `plan_sha256 1807bc65…299b`、`code_version 2631ac3f…5932`（含 `candidate_unit_keys` 采集）。
- check-only 16/16；执行 `succeeded`，38 次真实发送，结算 **0.14098 元**。
- 质量 **11 pass / 1 fail**：唯一 fail = **C12**（三轮保持不变）。

## 决定性判定：**A（期望来源在候选里，被 legacy 筛掉）**

投影（SAFE，只出计数）：

| 项 | 值 |
|---|---|
| C12 期望来源数 | 2 |
| 候选上界单元数（`candidate_unit_keys`） | 6（未截断） |
| **期望来源落在候选集合里** | **2 / 2** |
| legacy 自己保留的单元 | 1（`legacy_retrieve_initial`） |
| document 面原因 | `vector_unavailable`（只有词面通道） |

→ 两条期望来源**都在候选上界里**，但 legacy 的过滤只留下 1 条。**召回不是瓶颈，legacy 过滤才是。** 目标收敛到 `backend/src/mktkb/retrieval/service.py` 的实体/角色过滤。

## 下一步
1. 定位 legacy 过滤里丢掉第二条期望来源的那一处（离线、0 元）。
2. 最小修复 + 合成红绿 + 安全反例。
3. 真实 r0 验证 12/12 —— **需要主人再批一轮**（本批两轮已在第八、九轮用完）。

## 重要更正：A 判定的对象可能是**错的回合**

评分取多轮题**末轮**（`p2_scoring.py:823-836`）。C12 有 t6/t7 两个 executed 回合。刚才逐轮回读第九轮证据：

| 回合 | `candidate_unit_keys` | 期望来源命中候选 | `legacy_retrieve_initial` |
|---|---|---|---|
| t6 | 6 | **2/2** | 1 |
| **t7（末轮，评分取它）** | **无该事件** | **不可测** | **无该事件** |

→ **t7 根本没有进入检索路径**（没有候选上界事件、没有 legacy 初始检索事件）。因此：
- 我先前"A：候选里有、被 legacy 筛掉"的结论**只对 t6 成立**，对评分实际使用的 t7 不成立；
- C12 的真实机制更可能是：**末轮走了不检索的分支**（状态继承/指代/拒答类路径），导致期望来源永远不会被引用。

这条更正**作废** R0-C12-LEGACY 里基于 t6 的"legacy 过滤"目标，并把目标改回"**t7 为什么没检索**"。

## 修正后的下一步
1. 判定 t7 走的是哪个产品分支（固定枚举）：`anaphora_inherit` / `state_only` / `clarification` / `refusal` / `record_reuse` / `other`；要能解释"没有 retrieval_observed"。
2. 若属"追问本应检索却复用状态"，修 `conversations/service.py` 的追问分支；若属"按设计不检索"，则 C12 是**题面/判据口径**问题，需主人决策。
3. 再跑一轮验证（需主人批）。
