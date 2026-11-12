# T207 CUSTODY-V2 保管标注报告

状态：已标注，保留缺口，等待另一保管角色独立复核；未冻结、未质量放行。
本报告仅为安全聚合，附件不能充当运行期四轴证据。

## 密文与完整绑定
- 新密文：C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-custody/annotations-v0_2.fernet
- 新密文 SHA256：3d60c27364244a6ff8df76f66994ee50e5037649ea346c4b538f1fb9175ce4d0
- cases_sha256：a0ad48c9bbab96ac683e325c773dfee2dc247708fea7ddeefb08f567b102c3c3
- dataset_version：P2-HOLDOUT-v2
- ingest_plan_sha256：362e3ea10f673021d78c7a647305f04b8557b364a14482ebc2ba370d7752ed19
- label_version：p2-holdout-v2-2026-11-10
- manifest_sha256：8874985ef8f4aacc5689d5dc4dc60db759c2620492d159171712f7a9b679ce4b
- schema_sha256：9fbe4b337510dc87e1205f4e72371d834f4fc0e29edc2cacea34f56307e9c189
- source_map_sha256：86c86767ce5f4251ff52589cca9d02882aa7f47e23caf7cde654133b8ea821b5
- scenario_contract_sha256：39c7e16103acdac52741a48d895b29ff5675ee97e5691955ccebe5b21a1274ad

## 结构与聚合
- 30题；同序唯一覆盖30；缺失/额外/重复均0。
- schema、绑定、refs边界、结构/枚举、ISO日期、优先归属、加解密回读自核通过。
- 四状态总计数：{"base_b0": 26, "base_b0_plus_v01": 1, "pre_v05_without_v07": 2, "post_v05_without_v01": 1, "unknown": 0}

|轴|required|not_applicable|unknown|
|---|---:|---:|---:|
|safety|2|28|0|
|cross_user|30|0|0|
|cross_entity|28|0|2|
|stale_source|30|0|0|

- 固定缺口：实体目标2；日期锚点2；状态0。日期缺口以required保留、as_of=null，不用N/A规避。
- 原5处语义分歧候选均依据冻结题面/标签及公开语料重新判断；未自动采信旧纠正。
- 本轮独立复核尚未执行，分歧计数为null；不能声明双方无分歧或附件完整质量通过。

## 保全与过程
- 冻结原件、旧标注、旧纠正、source-map、12源计划、新契约与公开语料前后hash均相同；完整前后摘要见annotation-aggregate.json。
- 原金标、业务源码/测试、预算/账本/GO未改；未commit、未派助手。
- 密钥仅内存读取；逐题标注仅在受控内存构造并Fernet加密写至仓外。
- socket出站阻断；网络尝试0、产品测试0、真实调用0；未读取产品回答/trace/封存运行评分/旧助手会话。
- 过程偏差：默认Python缺依赖，切换既有项目venv；一次内存元数据检查误用签名退出后重载；均未写逐题明文。
- 为避免应用设置加载，以仅包路径命名空间导入既有loader；未加载应用__init__。
- 一次临时保守状态归属经全部有效同目标来源复判后在内存修正；未写临时密文或明文文件。
- 本角色交付后停止写入；下一角色独立逐题复核，缺口继续阻断完整质量结论。
