# T207 CUSTODY-V3 gap addendum 独立复核（第二保管角色）

状态：PASS — structure PASS / semantic_consistency PASS / 无强解 / 无分歧；建议经理验收后冻结 v0.3 gap addendum。本复核不是质量放行，也不产生运行期四轴证据。

## 交付物（仅三类；无逐题内容）
- 复核结论密文（仓外同 custody 目录）：`C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-custody/review-gapaddendum-v0_3.fernet`
  - 5284 bytes；ciphertext sha256 `5062211f39172a17fb729284b12e5020f5d6164d1b3c11a4c053e76ef1e48266`；明文 canonical sha256 `295ef3daaa35ea22a513ee1cb1b872835890b11211b4ff3639dbcd7c58b52b15`
  - 与标注方 addendum 明文逐字节一致（独立复判无分歧 → 一致复核记录；若有分歧本应另写同 schema 纠正候选，不覆盖原件）。
- 公共聚合：`docs/reports/OBS-EVAL/P2/T207-CUSTODY-V3/review-aggregate.json`
- 本报告：`docs/reports/OBS-EVAL/P2/T207-CUSTODY-V3/review.md`

## 环境与安全
- 工作区 `D:/GPT项目/市场部AI知识库`；项目 `.venv` Python 3.12.7；`MKTKB_NO_DOTENV=1`、`MKTKB_P2_HOLDOUT_ROOT=D:/mktkb-p2-holdout/v2`、`MKTKB_P2_HOLDOUT_KEY_FILE=D:/mktkb-p2-holdout/keys/v2.key` 受控注入；用既有受控 loader 解封；key 只在进程内存，不打印/复制/落盘；不读 `.env`/runbook/scoring/真实回答/trace/评分/旧助手会话。
- 未派子助手；未 commit/stage；socket connect/connect_ex/create_connection 阻断计数 0；模型调用 0、产品测试 0、真实调用 0。

## 独立检查与结论（PASS/FAIL/未验证）
1. addendum 密文完整性：PASS — 5284 bytes，ciphertext sha256 `80a8c4a11aa452cde86dc7887642ea05c374eaaf40b668a0692faa8ac37c9b2f` 与派单/标注报告一致；Fernet 解封；明文规范序列化 sha256 `295ef3daaa35ea22a513ee1cb1b872835890b11211b4ff3639dbcd7c58b52b15`，无尾随换行。
2. 精确 schema/字段/枚举/类型/序列化：PASS — 顶层恰 {schema_version,bindings,gap_summary,gaps}；bindings 恰 9 键；gap_summary 恰 5 整数键；gaps 长度 4，按 case_index 升序且同题内跨实体先于日期；每项恰 10 字段；source_refs 顺序/来源约束、changed_fields 精确差异、disclosures 枚举、axis_value 七字段与 target_refs 边界全部符合 annotation-report 定义。
3. bindings 逐项重算：PASS — 9/9 与真实原输入相等（annotations_v0_2 `3d60...`、manifest `8874...`、cases `a0ad...`、source_map `86c8...`、ingest_plan `362e...`、schema `9fbe...`、scenario `39c7...`；dataset/label 版本与封存 manifest 一致）。
4. v0.2 附件解封与校验：PASS — 30 题与原冻结加载同序；外层 3 键、8 bindings 重算一致；120 轴字段/枚举/refs 边界/日期合法；场景计数 base_b0 26、base_b0_plus_v01 1、pre_v05_without_v07 2、post_v05_without_v01 1、unknown 0，与 V2 验收记录一致。
5. 4 个 gap 轴独立重判：PASS — 复核 4、一致 4、纠正 0、保留 unknown 0。
   - 实体 2：目标身份可由冻结题面/原标签 token 与公开语料核对（请求范围业务记录集合身份；无 record_code、无运行期记录身份、无实体实例臆造）；basis 为 frozen_label_target 1 / frozen_question_scope 1，与证据来源相符。
   - 日期 2：as_of = CaseSpec.business_date 业务基准 2026-10-28（basis case_business_date_baseline、reason business_date_default），披露明确“非产品实际使用该日期的证明、未虚构历史意图日期”，未改变 historical 语义。
   - 无强解：v0.2 中恰为 2 个 cross_entity unknown + 2 个 stale_source insufficient_annotation，与 addendum 4 轴一一对应；无其他未解轴被改，kept_unknown 计数 0。
6. 其余 116 轴不变：PASS — 合并模拟仅 4 轴改变、116 轴逐值不变；30 题/四状态/场景归属不变；外层 schema/bindings 保留；合并记录 canonical sha256 `e9704b3a9668968e07deeb5877da411afe0170e1b260eccf57d5e89c896872f4`。
7. 旧密文保全：PASS — annotations-v0_2 `3d60...`、review-v0_2 `9639...`、addendum `80a8...` 三者均未覆盖。
8. 输入前后 hash：PASS — 23 项 before=after（含 12 源语料、封存 manifest/questions/labels、两版 schema、scenario、source-map、ingest-plan、annotations/review/addendum 密文）。
9. 未验证（边界）：04 侧 addendum reader/merge 实现；运行期 context/source/date/entity 快照与产品实际 as_of 实采；真实运行四轴 checked/violations；v0.2 其余 116 轴的语义重判（本次仅核验逐值未变）。

## 安全聚合
- 结构 PASS、语义一致性 PASS、质量就绪 BLOCKED、verdict PASS、建议冻结 true。
- gap 复核计数：一致 4 / 纠正 0 / 保留 unknown 0；basis 分布：case_business_date_baseline 2、frozen_label_target 1、frozen_question_scope 1、public_corpus_structure 0、no_provable_basis_keep_unknown 0。
- 合并后：cross_entity required 30、unknown 0；固定 gap 计数 unresolved_entity_target 0、unresolved_date_anchor 0、unresolved_scenario 0。
- 安全计数：network=0（connect/connect_ex/create_connection 均 0）、product=0、real=0、model=0、subagent=0、commit=0；新明文文件 0；新数据库 0。
- 过程偏差：首轮脚本两处校验逻辑笔误（v0.2 bindings 键数、实体键连续子串假设）与一次缺失导入启动退出；均在写盘前修正，未改任何文件、未写明文。

## 结论与剩余 unknown
- 建议：addendum 可在经理验收后冻结；冻结仅确认 4 gap 补证与绑定/覆盖/无强解，不等于质量通过或运行期四轴通过。
- 剩余 unknown：实体目标为请求范围集合身份（非运行期实际记录身份，04 仍需严格空集判定）；日期锚点为业务基准日（非产品实际使用证明，04 仍需实采 as_of）；运行期四轴证据未产生。
