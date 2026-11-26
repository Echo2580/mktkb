# Q1a-1 经理接收（限定范围）

- Date: 2026-11-14
- Package: Q1a-1（safety 轴重评分模块/契约/合成测试）
- Status: **ACCEPTED — PASS_WITHIN_SCOPE**
- 独立验收：`independent-review.md`（SHA256 `0b2d60d2…`）**9/9 PASS**，261 项独立断言 0 失败；aggregate `bac140ad…`。
- 测试：collect 20 / run 20 passed / exit 0；netguard external=0；无 skip/xfail/恒真断言。
- 冻结：C 冻结 12/12；`p2_hard_evidence.py=fba6e606…` 未改；manifest 10/10；暂存空、无 commit；15 tracked modified 均早于本包。
- 零真实调用：network/provider/model/retrieval/embedding/rerank/OCR/judge=0；未读私有 H2/.env；未写账本/GO。

## 管理判定

- **B-01 接受**：独立验收为核对 `c-freeze [funding]` 只对账本/GO 做 SHA256，未解析/未写/未调用；不构成零真实调用或资金件修改违规，仅记录为边界偏差。
- **R-01**：c-freeze funding 行与当前 gitignored 文件不同属既有状态；本包 16:59 后无写入，不计 FAIL。
- **R-02（高）**：Q1a-1 只重评 safety；`cross_user`/`cross_entity`/`stale_source` 为 `recorded_old`。**Q1a-3 不能直接跑**；必须先有 Q1a-1b（其余三轴重评分模块）。
- **R-03/R-04/R-05/R-09**：真实投影未跑、identity 三字段为声明性、getattr 默认可 fail-open、真实旧卡未读——全部作为 Q1a-3 的强制条件：保管侧绑定、适配层显式 required、真实旧卡字节核对。
- **R-06/R-07**：契约精度/不可达码，纳入契约 v0.2；**R-08** 冗余测试可清理，不阻断。

## 范围结论

- 本接收只覆盖 **Q1a-1 合成范围**；不构成 Q1A 整体完成、T207 通过、阈值/基线/发布批准。
- **Q1a-2**（真实 scope/targets 合同）可与 **Q1a-1b**（其余三轴重评分模块）并行；**Q1a-3**（私有重评分 + 11 fail 分诊）在两者之后。
- Q1a-3 必须完成 11/11 分诊、其余三轴真实重算、消费并绑定 Q1a-2 合同；不得把 safety-only 说成整体重评分完成。

## 下一步

1. 派 **Q1a-1b** 开发：cross_user/cross_entity/stale_source 重评分逻辑 + 合成测试 + 独立验收；不读私有 H2。
2. 派 **Q1a-2** 两个保管角色：真实 scope/targets 合同 + 独立复核。
3. 两者接收后派 **Q1a-3**：受控私有重评分 + 11 fail 分诊 + 保管 B 复核。
4. 再按 D1 决策门走 A/B/C。
