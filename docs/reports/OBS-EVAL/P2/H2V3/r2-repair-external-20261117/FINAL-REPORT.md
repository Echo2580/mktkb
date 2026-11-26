# FINAL-REPORT：R2 修复与真实 H2 验证（2026-11-17，外部开发助手）

任务书：`docs/superpowers/plans/2026-11-17-r2-external-ai-repair-taskbook.md`
交付目录：`docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/`

## 1. 最终结论

**R2 未达标。** 两轮真实运行均为 **质量 4/5**，但**硬失败 0、必要轴 unknown 0** 已达成且可复核。

| 判定 | attempt1 | attempt2（修后最终版本） |
|---|---|---|
| 质量 | 4 pass / 1 fail | **4 pass / 1 fail** |
| 硬失败 | 0 | **0** |
| 20 轴单元 | 16 passed / 4 N-A / 0 unknown / 0 violation | **16 passed / 4 N-A / 0 unknown / 0 violation** |
| 必要轴 unknown | **0** | **0** |
| C29 失败码 | `value_hit`,`source_hit`,`kind_correct`,`refusal_unexpected` | `value_hit`,`source_hit` |
| 失败性质 | contact 安全闸门**整题误拒** | **跨文档覆盖 1/2**（回到修前机制） |
| 结算 | 0.0431940 元 | 0.0433000 元 |

**T207 仍未通过**；不进入 R3、不做全 30 题、不 Git 提交/推送、不声称 release。

## 2. 最小变更（4 文件 / 14 hunk，全部有独立回滚补丁）

| 包 | 文件 | 内容 | 回滚补丁 |
|---|---|---|---|
| 202C | `rag/retrieval.py`、`rag/answer.py`、`rag/facts.py` | RAG 直答路径的跨实体取数联结（9 hunk）：`_store_join_chunks` + 并入店家行 + 逐记录身份渲染 + `_joined_store_row` 门 | `evidence/05-fix/R2-202C-MINE-rollback.patch.txt` |
| 202D | `rag/retrieval.py` | 唯一性守卫（4 hunk）：按派生门店值命中的店家行**恰好 1 条**才联结，固定码 `joined`/`store_row_missing`/`store_row_ambiguous` | `evidence/05-fix/R2-202D-MINE-rollback.patch.txt` |
| 206A | `rag/query.py` | contact 闸门过度拒答修复（1 hunk，+27/−2）：混合角色（others ≥ 2）时从请求角色集合剔除 `phone`/`address` 后继续作答；**只问电话/地址与凭据族仍整题拒答** | `evidence/10-attempt2/R2-206A-MINE-rollback.patch.txt` |

- 评分器 / 分类器 / 冻结合同 / 题集 / 阈值 / 标签 / 旧证据 / case-plan / 预算 / 账本：**一字未改**（哈希逐项复核）。
- 未新增 case 特判；合成数据全部为虚构实体。

## 3. 逐轮状态

| 阶段 | 结果 |
|---|---|
| T-R2-201 零调用重建 | 完成：5/5 重建一致；C29 失败码首次补齐；五档 compat 逐 (case,axis) 一致；评分版本 `flip=false`；C25/C29 unknown 归因 = **历史键形态**（R0 已修） |
| T-R2-202 机制判定 + 修复 | 202A 证明 RAG 路径机制仍复现（R0 只覆盖 legacy）；202B 证明身份同形已一致；202C/202D 修复 |
| T-R2-203 回归 + HTTP | 789 passed / 3 既有失败（0 error）；HTTP 四组见证 21 passed；四条敏感性对照全部成立 |
| T-R2-204 独立预验收 | 两轮：首轮 **D=FAIL**（同店多行互斥值可达）→ 202D 守卫 → 改判 **D=PASS 放行** |
| T-R2-205 attempt1 | 真实运行一次：4/5、硬 0、unknown 0；首偏离定位到 `rag/query.py:1812-1822` 误拒 |
| T-R2-206A + 复验 | 修复落地；独立复验判定"不放行"，阻塞项为 `sources[].locator.cells` 暴露受限列；**主人裁定 A：locator 属来源指针、接受并登记残留** |
| attempt2 | 真实运行一次：4/5、硬 0、unknown 0；C29 回到覆盖 1/2 |

## 4. 累计费用

| 项 | 值 |
|---|---|
| attempt1 | 结算 0.0431940 元 / 账本保守 0.0464051 元 |
| attempt2 | 结算 0.0433000 元 / 账本保守 0.0466764 元 |
| **合计（账本保守口径）** | **0.0930815 元** |
| 项目累计 | **24.8148354 / 40**（余 15.1851646） |
| 阶段 P2-LIVE | **9.7438909 / 20**（余 10.2561091） |
| 账本配对 | **2000 / 2000**（集合差 0/0）；`budget.json` 未改（`79b21700…`） |
| 请求 | planned 37 / 37；attempts_reserved 29 / 31；real_sends 27 / 29 |

## 5. 遗留（按影响排序）

1. **C29 覆盖 1/2（R2 唯一质量失败）**：202C/202D 的联结在真实题面下未触发；触发所需 `field_roles` 与 `store_join` 判定码**不在捕获件内**（`field_role_not_captured`、`retrieval_events_absent`）⇒ 现有证据**不能区分**"条件未满足"与"店家行 missing/ambiguous"。这是**捕获缺失**，不是已证产品缺陷。最小补采见 `evidence/10-attempt2/R2-ATTEMPT2-VERDICT.md §6`。
2. **`sources[].locator.cells` 暴露受限列**：混合形态下引用载荷仍带店家整行的联系人/电话/地址；正文、facts、模型证据、捕获 envelope 均闭合；冻结评分器 `value_forbidden` 只扫正文。**主人 2026-11-17 裁定 A：locator 属来源指针、接受并登记为本残留**（follow-up 编号建议 `R2-FU-LOCATOR-CELLS`）。
3. **contact 闸门"静默丢弃"**：混合形态下用户明确问的电话/地址被无声剔除，正文与 `missing_fields` 无"不提供"说明——属忠实度风险，非本次评分面。
4. **`s2b` 既有失败定级更正**：`test_s2b_intent_semantics` 在 `git archive HEAD` 源码上**绿**，在工作树上红；非 202C/206A 引入，也不是"HEAD 既有"。来源未定位到单文件（+HEAD `conversations/*` 仍红、+HEAD `qa/service.py` 更红、+HEAD `rag/query.py` ImportError）。**任何 release 表述前必须归因**。
5. **两份 run 的 sidecar 事件**：attempt1 根级 `v3-entry-*.json` 属首次被拒尝试（`go_plan_id_mismatch`、零发送），成功运行因 `output_already_exists` 未覆盖该文件，进程退出码 2；权威件为 `seal/<run_id>/run-receipt.json`。attempt2 `EXIT=0`，sidecar 正常。
6. **GO 装槽事实更正**：`run_index≠0` 的 GO 实际读取 `P2-LIVE-GO.v3-r2.pending.json`，固定槽位仅用于 run0。attempt1 首签误装固定槽位（零发送被拒），已恢复固定槽位原字节 `38f3c3f5…`；两次签发的旧件均按 `.archived.json` 独占创建留痕。

## 6. 停止点

R2 到此停止：**不进入 R3/全 30 题、不宣称 T207 通过、不做 Git 提交/推送/合并**。
后续如继续，需要：① 捕获补采（第 5 节第 1 条）；② 对 `R2-FU-LOCATOR-CELLS` 的处置决定；③ `s2b` 归因。
新一轮必须重新生成计划与 GO（同计划不可换 run 复用），并重新做完整 check-only。
