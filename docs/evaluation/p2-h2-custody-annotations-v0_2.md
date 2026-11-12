# H2 四状态四维保管附件 v0.2

主人已于2026-11-12明确批准恢复T207与scenario-expansion-decision.md的四状态替换。v0.1原schema、原标注及拒收纠正密文不覆盖。仅两个隔离保管角色读取冻结H2题面/标签；不读真实运行回答/trace/封存评分，经理、开发、普通验收只安全聚合。

## 与v0.1的兼容关系

沿用 `docs/evaluation/p2-h2-custody-annotations-v0_1.md` 的每轴全部字段、精确结构、固定criterion/reason枚举、target_refs边界与实体/日期未知规则。仅外层schema_version改为`p2-h2-custody/v0.2`，bindings增加`scenario_contract_sha256`（本次公共JSON原始字节SHA256），scenario_id改为下述四枚举或`unknown`。其他绑定仍为原manifest/dataset_version/label_version/cases/source_map/ingest_plan/schema_sha256；schema_sha256绑定本v0.2文档原始字节。外层仅`schema_version,bindings,cases`；cases仍原冻结同序30题且逐题仅`case_id,scenario_id,axes`，axes仅四轴对象。若v0.1原密文实际键名与该显式定义不同，v0.2按本定义统一而不改旧件。

## 四状态固定契约

公共契约唯一来源 `docs/evaluation/p2-h2-scenarios-v0_2.json`。source_indices是原12源ingest-plan的0基下标子序列，保留原path/name/document_ref和顺序。批数仅公开Mock预检，不等于新正式计划。

|scenario_id|来源|D01/D02 active版本|B|
|---|---|---|---:|
|base_b0|V03,D01,D02,D03,D04,D05,D06|2/1|8|
|base_b0_plus_v01|base_b0后独立V01|2/1|9|
|pre_v05_without_v07|原12源去V05,V07|3/2|11|
|post_v05_without_v01|原12源去V01|4/2|13|

每题按冻结语义、全部有效同目标来源及独立冲突唯一归属。多个状态都满足时按JSON assignment_priority取首个；不得仅看expected source存在，不得按产品回答或分数择优。不存在可证状态则unknown并阻断。先保管标注、另一保管角色独立核对，双方无分歧且绑定/覆盖通过后才冻结。

## 四轴与残余缺口

四轴仍为safety/cross_user/cross_entity/stale_source。cross_user与stale_source全部required。安全良性N/A不得取消全局禁值禁源检查。实体缺实际记录/集合身份不能改N/A/shared_background来规避。无资料拒答不等于无实体要求，正文通用规则不能代替所求事实。

原复核的2处实体和2处日期缺口应只依冻结题面/原标签/公开语料重新明确；可用已有CaseSpec.business_date作为产品应使用的基准，但不能把历史意图缺明确日期臆造为该日期，也不能声称产品实际上用了它。无法明确继续unknown/固定gap计数，不降低标准。多轮按完整冻结历史语义判断，不能创造未授权as_of。

## 文件与可见性

新密文仅 `C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-custody/annotations-v0_2.fernet`；独立复核通过则另存`review-v0_2.fernet`，不得覆盖旧件。Fernet key仍只在受控内存从原key-file读取，不输出/复制；不得保存逐题明文脚本、日志、JSON、临时文件或新数据库。

公共报告只整体hash、bindings、case_count/唯一覆盖、scenario总计数、各轴required/N/A/unknown、固定gap/disagreement计数、输入前后hash和过程偏差。无逐题ID/hash/目标/归属/题干/答案/交叉表。语义附件不产生运行期checked/violations；有unknown不得称完整质量通过。
