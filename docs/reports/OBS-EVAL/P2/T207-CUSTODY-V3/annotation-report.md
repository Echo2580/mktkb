# T207 CUSTODY-V3 实体2/日期2 缺口补证报告

状态：已产出仓外 v0.3 gap addendum，待第二保管角色独立复核；未冻结、未质量放行、未产生运行期四轴证据。
本报告仅为安全聚合与公共 schema；无逐题 ID/题面/答案/目标值/归属/逐题 hash。

## 交付物（仅三类）
- 新密文（仓外）：C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-custody/annotations-gapaddendum-v0_3.fernet（5284 bytes）
- 新密文 SHA256：80a8c4a11aa452cde86dc7887642ea05c374eaaf40b668a0692faa8ac37c9b2f
- 明文规范 SHA256：295ef3daaa35ea22a513ee1cb1b872835890b11211b4ff3639dbcd7c58b52b15（UTF-8 canonical；见下）
- 公共聚合：docs/reports/OBS-EVAL/P2/T207-CUSTODY-V3/annotation-aggregate.json
- 本报告：docs/reports/OBS-EVAL/P2/T207-CUSTODY-V3/annotation-report.md

## 绑定（addendum.bindings，恰9键）
- annotations_v0_2_sha256：3d60c27364244a6ff8df76f66994ee50e5037649ea346c4b538f1fb9175ce4d0
- manifest_sha256：8874985ef8f4aacc5689d5dc4dc60db759c2620492d159171712f7a9b679ce4b
- dataset_version：P2-HOLDOUT-v2；label_version：p2-holdout-v2-2026-11-10
- cases_sha256：a0ad48c9bbab96ac683e325c773dfee2dc247708fea7ddeefb08f567b102c3c3；source_map_sha256：86c86767ce5f4251ff52589cca9d02882aa7f47e23caf7cde654133b8ea821b5
- ingest_plan_sha256：362e3ea10f673021d78c7a647305f04b8557b364a14482ebc2ba370d7752ed19；scenario_contract_sha256：39c7e16103acdac52741a48d895b29ff5675ee97e5691955ccebe5b21a1274ad
- schema_sha256：9fbe4b337510dc87e1205f4e72371d834f4fc0e29edc2cacea34f56307e9c189（v0.2 文档原字节）
- v0.2 标注与 review-v0_2 密文 hash 前后一致；未覆盖旧件。

## 缺口处理计数（安全聚合）
- gap 总数4：实体目标缺口2、日期锚点缺口2；解析4、保留 unknown 0。
- 4 个 gap 轴分布于 3 道题；仅整体替换这 4 轴；120 轴中 116 轴（含全部非 gap 题与非 gap 轴）逐轴核验不变，v0.2 外层 binding 不变。
- basis 分布：case_business_date_baseline=2、frozen_label_target=1、frozen_question_scope=1、public_corpus_structure=0、no_provable_basis_keep_unknown=0。
- 改变字段模式：as_of+reason=2；applicability+criterion+reason+targets=2。source_refs 每项均有冻结题面/标签/公开语料/业务基准日来源。

## addendum 精确 schema（v0.3；04 reader 与独立复核按此实现）
schema_version 固定 "p2-h2-custody-gapaddendum/v0.3"。顶层键恰为 {"schema_version","bindings","gap_summary","gaps"}。
- bindings：恰9键（上列）；除 dataset_version/label_version 为字符串外，其余7键为 64 位小写 hex。
- gap_summary：恰5个整数键 {"gap_total","resolved_count","kept_unknown_count","entity_target_gap_count","date_anchor_gap_count"}。
- gaps：长度 4 的有序数组；顺序 = case_index 升序，同题内 axis 按固定顺序 safety<cross_user<cross_entity<stale_source。每项恰10键：
  - case_index:int(0..29)；case_id:str（须等于冻结加载序同一下标 case_id）；axis∈{"cross_entity","stale_source"}；
  - gap_kind∈{"unresolved_entity_target","unresolved_date_anchor"}（与 axis 固定对应）；resolution∈{"resolved","kept_unknown"}；
  - basis∈{"frozen_label_target","frozen_question_scope","public_corpus_structure","case_business_date_baseline","no_provable_basis_keep_unknown"}；
  - source_refs：非空数组，按 source 固定顺序 frozen_question<frozen_label<public_corpus<case_business_date；元素恰4键 {"source","doc_code","field","locator"}：
    frozen_question→doc_code=null,field="question",locator=null；frozen_label→doc_code=null,field∈{"reference_answer","notes"},locator=null；
    public_corpus→doc_code∈12源代码,field=null,locator={"heading":str} 或 {"page":int≥1}；case_business_date→doc_code=null,field="business_date",locator=null。
  - changed_fields：字符串数组、升序、元素∈轴7字段名；须精确等于 axis_value 相对 v0.2 该轴的差异字段集。
  - disclosures：非空字符串数组、升序；元素∈{"business_date_baseline_not_actual_product_date","historical_intent_date_not_fabricated","request_scoped_collection_no_runtime_record_identity"}。
  - axis_value：完整 7 字段轴对象，字段集恰 {"applicability","criterion","reason","target_refs","targets","as_of","temporal_intent"}，枚举/结构完全沿用 v0.1/v0.2：
    applicability∈{required,not_applicable,unknown}；criterion 按轴固定枚举；reason/temporal_intent 同 v0.1 固定枚举；as_of 为 null 或 ISO 日期；
    target_refs 元素恰 {"collection","index"} 且指向同 case 原集合边界内；targets 元素恰 {"entity_type","entity_key","filters"}（entity_type 非空 str≤256、entity_key str≤256、filters 为 str→str/int/float/bool/null）。
  - kept_unknown 约定（本次0项）：basis 必为 no_provable_basis_keep_unknown、changed_fields=[]、axis_value 必与 v0.2 原轴完全相同；reader 视为 no-op 并保留对应 gap 计数。
- 明文序列化：明文 = UTF-8(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",",":")))，无尾随换行；整体 Fernet 加密落盘。
- 合并/校验规则（04 必须实现）：校验 bindings（重算原输入 hash 且 = annotations_v0_2_sha256）→ 解封并校验 v0.2（30题同序/绑定/枚举/refs/日期）→ 逐 gap 校验 case_index/case_id/axis 唯一、resolution、axis_value 全字段、changed_fields 精确差异且其余字段逐值相同 → 用 axis_value 整体替换该轴 → 确认仅4轴改变（120轴中116轴不变）→ 合并结果仍沿用 v0.2 外层 schema_version/bindings 与30题同序覆盖。

## 语义与边界披露（未验证项）
- 日期：两根 as_of 均取 CaseSpec.business_date=2026-10-28，作为“产品应使用的业务基准日”；不是产品实际使用该日期的证明，不改变 historical intent，也不代表历史事件发生在该日或失效源获准使用。
- 实体：两个目标为冻结题面/原标签/公开语料可核的“请求范围业务记录集合身份”，不是运行期实际记录身份；语料/索引无对应记录，须由 04 走独立验证的严格空集判定；未臆造记录、record_code 或实体实例。
- addendum 只是 v0.2 的 4 轴增量，不单独构成完整30题标注；不产生运行期 checked/violations；owner/实体/日期/全局禁值禁源运行期证据仍未验证。
- 待第二保管角色独立复核无分歧、绑定/覆盖通过后方可冻结；复核前不得作为质量通过或真实运行依据。

## 输入保全与安全
- 22 项输入（封存 manifest/questions/labels、v0.2 标注、review-v0_2、source-map、ingest-plan、v0.1/v0.2 schema、scenario 契约、12 源语料）before/after SHA256 全等；详见聚合 JSON。
- key 仅受控进程内存读取，不打印/复制/落盘；未读 .env；未读 runbook/T207 scoring/真实产品回答/trace/评分/旧助手会话。
- 零模型/产品/网络调用；socket 出站阻断计数0；未派子助手；未 commit/stage；只新建本目录两个公共文件与仓外新密文。

## 过程偏差
- 派单写“其余26题”；实测 4 个 gap 轴分布于 3 道题（其中1道题同时含实体与日期缺口），其余27题未触及；只改 4 个 gap 轴，其余116轴逐轴核验不变，未改任何非gap语义/绑定。
- 首轮构建对实体身份键按“原文连续子串”断言失败（键由题面与标签 token 拼合）；改为逐 token 来源核验后重跑，失败在写盘前、未产生文件。
- 首轮解封显示经控制台代码页乱码；改 base64 内存管道重读，未写明文文件。
- 首轮写后校验脚本日期/实体 gap 下标写反致 IndexError；修正后通过，未改动已交付文件。

## 结论
- 实体2/日期2 缺口均给出结构化解析与固定 basis；解析/保留计数=4/0；basis 见上。待独立复核，完成后停止写入。
