# P2-T206 真实 pilot：经理接收记录

- 独立复核：`review-pilot.md`（先生 `b7a17a05-…`）结论——**接收（限授权/账本/回执/额度四面）**，附 5 条返工单；**不接收** T206 report §2「Q01 覆盖同槽 V1→V2」声明。
- 经理决定：**接收 pilot 执行面**（live 运行、账本、回执、额度）；质量结论不作达标（`gate_v0_3` 仍 unapproved），Q01 等观察转 T207 归因。

## 执行事实（复核已独立核对）
- run_id `p2-t206-pilot-20261111-01`；5 cases/6 turns 全执行 0 error；kinds answer 4/conflict 1/not_found 1；branches legacy 4/legacy_with_rag 1/rag 1。
- ledger 1011→1095 行（+84 = 42 reserved + 42 result，全 P2-LIVE；逐笔复算 38 笔 charge 一致）；reserve 0.6893120；settled **0.5713583**（ocr 0.5 + answer_retrieval 0.0713583）；全局请求 547 ≤ GO 566 ≤ 硬顶 1000；pilot ≤2 元满足。
- 真实出站 39（chat 3/embedding 33/ocr 1/rerank 2），RAG POST 35；gate real_sends_allowed=true；citation complete（6 verified）；binding complete（trace 六字段/identity_bound、index_revision 5、dataset_sha a3878212…）。
- GO/预算签署面复核通过：GO 12 字段、非 DRAFT、13 天、plan_sha 02725aa7… 重算一致；预算 40/P2-LIVE 20/39.97+0.03 闭合。

## Q01 更正（不接收原声明）
- T206 准备中的「Q01 覆盖同槽 V1→V2」**作废**：复核表明 V03 与 D01 被导入为**两个独立 active 文档（各 version=1）**，B0 同槽 V1→V2 未被复现；Q01 返回 conflict 属**播种/导入配方问题**，不是版本串值，也不是产品已通过该槽位。要得到版本槽证据需 T207 新计划 + 新 GO 重新播种（计入同 20 元/同请求）。

## 返工单（T207 前/随 T207 处理）
1. 更正 Q01/recipe 声明（本文件）；T207 重新设计导入（历史版→当前版同文档槽）并计入预算/请求。
2. 说明 `run_result` 为 **answer 单侧范围**（6 vs 总计 42 次尝试）。
3. 统一 `summary.settled_failure` / 账本 status=failed / requests.jsonl billed 口径（复核发现 3 笔零 chat 拒答按上界保守留账 0.056064，清单价真实花费约 0.5152943）。
4. 预算元数据两字段已修（`remaining_conservative_cny_at_start` 39.97、`revised_at` 实际签发时刻），build 前后 sha 已记录；limit/stages/history 未变，另存签署版副本。
5. 文档说明 `output_valid=false`（dataclass 默认）与 `paid_attempt` 仅拒答轮存在的语义。

## 成本口径
- 结算口径 0.5713583；保守 reserve 0.6893120；其中 0.056064 为 3 笔零 chat 拒答的全额保守留账（清单价真实约 0.5152943）。复核判定不超 pilot/阶段/项目上限。

## 合规
- 经理按预授权签发 GO/预算；未改 `.env`；未读 H1/H2；产物无凭据；账本纯追加、历史前缀未动。