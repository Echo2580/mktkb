# P2 数据集契约 v0.1（T202 冻结：H2 受限加载）

> 状态：**T202 开发交付，待独立验收**。本文件冻结 `load_p2_dataset(manifest_path, *, visibility)`
> 的可见性语义、manifest schema、封存布局、解封顺序与稳定原因码；T203/T205/T206 不另定义
> 同名概念。T202 只做加载器与合成夹具测试：**零真实调用**，不接触真实 H2/密钥，不修改
> P1 holdout 原件与 `dataset.py` 行为。

## 1. 不变量

1. **可见性必须显式**：`visibility` 只接受 `"public"` / `"holdout"`，没有默认值；传错/传空
   一律拒绝（`visibility_invalid`），不做“猜一个”。
2. **public 绝不打开封存 root**：只读 manifest（repo 内元数据，只含版本/计数/hash）。若
   manifest 路径落在 `MKTKB_P2_HOLDOUT_ROOT` 内，直接拒绝（`visibility_root_violation`），
   一个字节都不读。public 返回对象不含题目/答案（`cases` 空、`labels` 空）。
3. **holdout 必须由运行环境注入 root 与 key**：`MKTKB_P2_HOLDOUT_ROOT` +
   `MKTKB_P2_HOLDOUT_KEY_FILE`；manifest 必须位于 root 内；key 不在仓库。
4. **解封前后各验一次摘要**：先校验密文 sha256，再 Fernet 解封，再校验明文 sha256；
   两者都只认 manifest 里的冻结值。
5. **明文只在内存**：解密后的 JSONL 在内存里逐行校验，不写临时文件、不打印；返回对象的
   `repr` 不带 `cases`/`labels`。
6. **错误 fail closed 且不泄题**：所有失败抛 `P2DatasetError`（`.reason` 为稳定原因码），
   `detail` 只含字段名/行号/计数/摘要，不含题干或答案正文；不返回半成品、不降级为空数据。
7. **题数与分层冻结**：H2 = 30 题、10/5/5/5/5；manifest 与数据都必须等于冻结值，
   “少两题但 manifest 自洽”同样拒绝。

## 2. 接口

`load_p2_dataset(manifest_path: Path | str, *, visibility: str) -> P2Dataset`

| 可见性 | 读取 | 返回 | 允许调用者 |
|---|---|---|---|
| `public` | 只读传入的 manifest 文件 | `P2Dataset(visibility="public", manifest=...)`；`cases` 为空、`labels` 为空 | 开发/验收/经理/报告 |
| `holdout` | manifest + key 文件 + root 下两个密文 | `P2Dataset(visibility="holdout", manifest, cases, labels, metadata_mismatch_count)` | 受控评测进程（T203/T205/T206 runner） |

返回对象：

| 字段 | 说明 |
|---|---|
| `visibility` | `"public"` / `"holdout"` |
| `manifest` | `P2Manifest`：严格校验后的元数据 + `manifest_sha256`（manifest 文件字节摘要，供 T203 写入 run_manifest） |
| `cases` | `tuple[CaseSpec, ...]`（holdout 专用；已按 `load_holdout_dataset` 同口径合并并过 `validate_case`） |
| `labels` | `Mapping[str, Mapping[str, Any]]`（holdout 专用；`case_id -> labels 行`，只读映射） |
| `metadata_mismatch_count` | questions 与 labels 在 `expected_kind`/`should_refuse` 上不一致的条数（labels 为权威，只计数不中断，供验收发现数据问题） |
| `label_for(case_id)` | holdout 取某题 labels；public 调用直接 `dataset_inconsistent` |

`CaseSpec` 的 `suite`/`split` 仍为 `"holdout"`（沿用 dataset.py 的 holdout 行契约）；
P2 数据集身份由 `manifest.dataset_version` / `manifest.label_version` / `manifest_sha256`
表达。**T203 不得只凭 `suite` 区分 H1/H2**：H1 与 H2 的 `suite` 都是 `"holdout"`。

## 3. manifest（`p2-holdout-manifest/v0.1`，严格 15 字段）

| 字段 | 校验 |
|---|---|
| `schema_version` | 必须 `p2-holdout-manifest/v0.1` |
| `dataset_version` | token（字母数字与 `_.:/-`，≤64），如 `P2-HOLDOUT-v2`；manifest 为权威，T203 绑定进 run 身份 |
| `suite` | 必须 `p2-holdout`（**不是**行内 `"holdout"`） |
| `label_version` | token，如 `p2-holdout-v2-2026-11-10`；questions/labels 行内出现时必须与之逐值一致 |
| `case_count` | 整数（拒绝 bool/浮点/字符串），且必须等于 **30** |
| `strata` | 恰好 5 个冻结分层，各为正整数，且必须等于 10/5/5/5/5，合计等于 `case_count` |
| `business_date` | `YYYY-MM-DD` 且为合法日期 |
| `created_utc` | ISO8601 且带 UTC（`Z` 或 `+00:00`） |
| `author` | 非空文本，≤64，不得含换行 |
| `encryption` | 恰好 `kind` / `key_id`：`kind` 必须 `fernet`，`key_id` 为 token |
| `questions_plaintext_sha256` / `labels_plaintext_sha256` / `questions_ciphertext_sha256` / `labels_ciphertext_sha256` | 64 位小写十六进制（见 §5 校验次序） |
| `turn_stats` | 恰好 `total_turns` / `max_turns_per_case` / `turn_histogram`，且内部自洽（见下） |

未知字段、缺失字段、类型不符一律拒绝。manifest 为 repo-safe：只有版本/计数/hash/分层，
写入仓库不构成题干泄漏。

### 3.1 turn_stats 口径（冻结）

单条 case 的声明轮数 = `len(turns)`（`turns` 非空时；`turns` 即完整轮序列），否则 1。
因此：

- `turn_histogram` 的键是 `"1"`..`"N"` 的规范十进制（无前导零），值为条数（≥1）；
- `sum(turn_histogram.values()) == case_count`；
- `max_turns_per_case == max(bucket)`；
- `total_turns == Σ bucket × count`。

holdout 还会用解密后的 questions 复算这三个值，必须与 manifest 逐值相等
（`holdout_turn_stats_mismatch`）。**保管方按同一公式填写**；若实际 manifest 用了别的
口径（例如把首轮另算成 1+len(turns)），T206 准入前必须先对齐，否则会被 fail closed 拒绝。

## 4. 封存布局与环境

    <root>/manifest.json              # 本文档 §3 的元数据（与仓库内公开副本应逐字节一致）
    <root>/questions.jsonl.fernet     # questions 明文 JSONL 的 Fernet 密文
    <root>/labels.jsonl.fernet        # labels 明文 JSONL 的 Fernet 密文
    <key file>                        # Fernet key（44 位 url-safe base64，可带行尾换行）

| 环境变量 | 含义 | 缺省/空 |
|---|---|---|
| `MKTKB_P2_HOLDOUT_ROOT` | 封存 root 目录 | `holdout_env_missing` |
| `MKTKB_P2_HOLDOUT_KEY_FILE` | key 文件路径（可在 root 外） | `holdout_env_missing` |

限制：manifest ≤ 256 KiB、每个密文 ≤ 8 MiB、key 文件 ≤ 4096 字节；超限即拒绝，不“先读进来
再说”。key 内容不打印、不进错误文本。

## 5. 解封与校验次序（任一不符即停）

1. `visibility` 合法（`visibility_invalid`）；
2. holdout：两个环境变量非空（`holdout_env_missing`）；
3. root 必须是已存在目录（`holdout_root_invalid`）；
4. manifest 必须位于 root 内（`holdout_manifest_outside_root`）；
5. 读 manifest 并严格解析（§3 的原因码）；
6. 读 key：存在（`holdout_key_file_missing`）→ 可读/UTF-8（`holdout_key_unreadable`）→
   44 位 base64 且 Fernet 可接受（`holdout_key_invalid`）；
7. 读两个密文：存在（`holdout_ciphertext_missing`）→ 非空可读
   （`holdout_ciphertext_unreadable`）→ 不超限（`holdout_ciphertext_too_large`）；
8. 密文 sha256 == manifest（`holdout_ciphertext_sha256_mismatch`）；
9. Fernet 解封（`holdout_decrypt_failed`；缺依赖 `crypto_unavailable`）；
10. 明文 sha256 == manifest（`holdout_plaintext_sha256_mismatch`）；
11. 明文 JSONL 结构：UTF-8、无 BOM、逐行 JSON 对象（`holdout_questions_invalid` /
    `holdout_labels_invalid`）；
12. questions 逐行：答案字段白名单（`holdout_answer_field_leak`）→ `label_version`
    （`holdout_label_version_mismatch`）→ dataset.py holdout 13 键校验
    （`holdout_questions_invalid`：suite/split/turns/expected_kind/business_date…）→
    `case_id` 唯一（`holdout_duplicate_case_id`）；
13. 题数（`holdout_case_count_mismatch`）→ 分层（`holdout_strata_mismatch`）；
14. 轮数结构（`holdout_turns_invalid`：multi_turn 必须 `turns>=2`；非 multi_turn 不得声明
    多轮且 `question` 非空）→ turn_stats 复算（`holdout_turn_stats_mismatch`）；
15. labels 逐行：`label_version` → dataset.py holdout 11 键校验（`holdout_labels_invalid`）→
    `case_id` 唯一（`holdout_duplicate_case_id`）→ 数量（`holdout_case_count_mismatch`）；
16. questions 与 labels 的 `case_id` 集合必须相等（`holdout_case_id_set_mismatch`，只报计数，
    不打印 id 列表）；
17. 合并 `CaseSpec` 并逐条 `validate_case`（`holdout_case_invalid`：locator 结构、不透明 id、
    `should_refuse` 必须有原因等在整个 case 上复核）。

## 6. 稳定原因码（`P2DatasetError.reason`）

异常族码 `P2DatasetError.code = "P2_DATASET_INVALID"`；下表是全部 `reason`。文案只含字段名/
行号/计数/摘要。

### 6.1 可见性与 manifest

| 码 | 触发 |
|---|---|
| `visibility_invalid` | `visibility` 缺失以外的非法值（含 `None`/bool/大小写不符） |
| `manifest_missing` | manifest 不存在 |
| `manifest_unreadable` | manifest 不可读（权限/是目录等） |
| `manifest_too_large` | 超过 256 KiB |
| `manifest_not_utf8` | 不是 UTF-8 |
| `manifest_json_invalid` | 非 JSON / 顶层非对象 / 带 BOM |
| `manifest_field_missing` | 缺字段 |
| `manifest_field_unknown` | 多字段 |
| `manifest_schema_version_invalid` | schema 版本不符 |
| `manifest_dataset_version_invalid` | `dataset_version` 非 token |
| `manifest_suite_invalid` | `suite` 不是 `p2-holdout` |
| `manifest_label_version_invalid` | `label_version` 非 token |
| `manifest_case_count_invalid` | `case_count` 类型错或 != 30 |
| `manifest_strata_invalid` | 分层键/值/合计/冻结值不符 |
| `manifest_business_date_invalid` | 日期格式或合法性不符 |
| `manifest_created_utc_invalid` | 非 ISO8601 或非 UTC |
| `manifest_author_invalid` | `author` 为空/过长/含换行/非字符串 |
| `manifest_encryption_invalid` | `encryption` 块字段/kind/key_id 不符 |
| `manifest_sha256_invalid` | 四个 sha256 不是 64 位小写十六进制 |
| `manifest_turn_stats_invalid` | `turn_stats` 字段/类型/内部自洽不符 |
| `visibility_root_violation` | public 传入封存 root 内的 manifest |

### 6.2 holdout 环境/路径/key/密文

| 码 | 触发 |
|---|---|
| `holdout_env_missing` | `MKTKB_P2_HOLDOUT_ROOT` 或 `MKTKB_P2_HOLDOUT_KEY_FILE` 缺失/空白 |
| `holdout_root_invalid` | root 不存在或不是目录 |
| `holdout_manifest_outside_root` | manifest 不在 root 内（防止拿公开副本冒充封存 manifest） |
| `holdout_key_file_missing` | key 文件不存在 |
| `holdout_key_unreadable` | key 文件不可读/非 UTF-8 |
| `holdout_key_invalid` | key 不是合法 Fernet key |
| `holdout_ciphertext_missing` | 密文文件不存在 |
| `holdout_ciphertext_unreadable` | 密文为空或不可读 |
| `holdout_ciphertext_too_large` | 密文超过 8 MiB |
| `crypto_unavailable` | 缺 `cryptography.fernet`（评测依赖；不退回明文/自制加密） |
| `holdout_decrypt_failed` | 给定 key 无法解封（错 key/坏密文） |
| `holdout_ciphertext_sha256_mismatch` | 密文摘要与 manifest 不符 |
| `holdout_plaintext_sha256_mismatch` | 解封后的明文摘要与 manifest 不符 |

### 6.3 数据契约与返回对象

| 码 | 触发 |
|---|---|
| `holdout_questions_invalid` | questions 行未通过 dataset.py holdout 字段校验（含非法 turns 文本） |
| `holdout_labels_invalid` | labels 行未通过 dataset.py holdout 字段校验 |
| `holdout_answer_field_leak` | questions 行出现答案字段（6 个白名单字段之一） |
| `holdout_case_count_mismatch` | questions 或 labels 行数 != manifest `case_count` |
| `holdout_strata_mismatch` | 实际分层计数 != manifest `strata` |
| `holdout_label_version_mismatch` | 行内 `label_version` != manifest `label_version` |
| `holdout_duplicate_case_id` | questions 或 labels 内 `case_id` 重复 |
| `holdout_case_id_set_mismatch` | questions 与 labels 的 `case_id` 集合不相等（只报计数） |
| `holdout_turns_invalid` | multi_turn 缺轮 / 非 multi_turn 声明多轮 / 单轮题空 question |
| `holdout_turn_stats_mismatch` | 复算轮数统计 != manifest `turn_stats` |
| `holdout_case_invalid` | 合并后的 `CaseSpec` 未通过 `validate_case`（locator 结构、不透明 id、拒答原因等） |
| `dataset_inconsistent` | 返回对象自身不自洽（public 带行、数量对不上、public 调 `label_for`） |

## 7. 后续任务调用约定

- **T203**：runner 只接受 `visibility="holdout"` 的 `P2Dataset`；把 `manifest_sha256`、
  `dataset_version`、`label_version`、`turn_stats` 写进 run_manifest；按 `turn_stats` 计算
  `answer` 请求数（1 题 ≠ 1 请求）；trace/产物里不得出现 `question`/`reference_answer` 原文
  （H2 仅聚合）。测试时用合成封存，禁止指向真实 root。
- **T205**：评分用 `dataset.cases` + `dataset.labels`；`metadata_mismatch_count` 只作数据质量
  信号，不改变真值；`holdout_case_invalid` 属于数据错误，不能当“答错”计分。
- **T206**：正式准入前核 `manifest_sha256` 与审批的公开副本一致、`turn_stats` 与请求计划一致；
  key 只在该进程环境注入，跑后审计输出目录无明文残留。
- **T209**：归档只存 `manifest`（元数据）与聚合结果，不存 `cases`/`labels`。

## 8. 与 dataset.py / H1 的关系

- 本包**未修改** `dataset.py`：P1 holdout 的常量、sha256、校验与报告行为全部不变；T202 只
  `import` 其 `CaseSpec` / `validate_case` / `HoldoutPolicy` / `_question_row` / `_label_row`
  （逐行校验复用私有函数，是为了让 H2 与 H1 用同一套字段规则，而不是复制一份会漂移的 schema）。
  若 dataset.py 后续收紧规则，H2 加载器自动跟随；测试用合成夹具锁定行为。
- H1 原件（`docs/evidence/LOCAL-R1-20261101/P1-HOLDOUT/`）只读、不读、不改；H1 曾有题干
  暴露事件，不能再说“未见冷题”。H2 与 H1 题集不同，分数不可直接对比。

## 9. 明确未做 / 限制

- **不实现加密封存工具**（key 生成/加密/写 manifest 属数据保管角色）；本包只做解封与校验。
- **不改依赖清单**：`cryptography`（本机 .venv 已有 50.0.2）未写入 `pyproject.toml`；缺依赖时
  `crypto_unavailable` fail closed。T206 若要可移植，建议在评测依赖锁里声明版本。
- **不检查 symlink**：root/key 由操作者注入，内容安全由 sha256 保证；部署侧（T206）自行核路径。
- **public 读一个环境变量做越界判断**（只读变量，不打开文件）；未配置 root 时不做额外拒绝，
  因此 public 无法识别“未注入 env 的封存 manifest 路径”——但该路径下 public 只读 manifest 本身
  （repo-safe 元数据），不打开密文/key/root 内其它文件，也不会返回题目或答案。
- 只跑本包测试；未跑全仓、未联网、未装依赖、未读 .env / H1 / 真实 H2、未访问
  `D:/mktkb-p2-holdout`、未 commit/push。

## 10. T207-FIX-H2SCORE：runner 内的 H2 聚合产物（additive）

H2 run 过去只写计数型 ``holdout_aggregate.json``（planned/executed/kinds/branches/strata），
质量聚合（pass≥24/30、``hard_failures=0``）只能靠 ``p2-score --visibility holdout`` 读工作区外的
封存逐题行/判定表 —— 而这两类输入没有生产者。本包在 runner 的受限进程内用**已解封在内存里的**
``dataset.cases`` + 本次 run 的逐题/逐轮产品结果直接算出 H2 聚合，写 ``holdout_scorecard.json``：

- **只写聚合**：字段与 ``p2-score --visibility holdout`` 的产物同 schema
  （``mktkb.p2.scoring.v0.1``）——``total/executed/errors/passed/failed/min_pass/threshold_met/
  hard_failures/hard_failures_by_kind/by_stratum/thresholds_approved/blocks/release_ready/
  execution_mode/real_calls/run_id/config_hash``；无 ``case_id``/题干/答案/逐题行，``detail_export=false``。
- **逐题判定只在内存**：复用 ``p2_score_run.holdout_case_scores_from_rows`` 的逐题评分口径 +
  ``aggregate_holdout_bundle`` 的聚合口径；单题评分异常 → 该题记 ``error`` 并出
  ``holdout_case_unscorable`` block（severity=unknown），**不猜 pass**。
- **B1：打分必须看到回答正文（行不落盘）**：打分侧只从 ``product.text`` 取回答，所以 ``_execute``
  在 holdout 路径把每题的完整观测（``turns[*].product`` 含 ``text``/``sources``/``evidence``，与公开
  run 的 ``cases.jsonl`` 行同形）另存进 ``P2RunLedger.scoring_cases``，跑完由它喂逐题判定；落盘的
  ``ledger.cases`` 仍按 ``include_text=False`` 收窄，H2 产物里没有逐题行/题干/回答。单变量测试：
  同一条产品观测带 ``text`` → ``pass``、去掉 ``text`` → ``fail``；30 题合成封存实跑 23 条正确回答 →
  ``passed=23``（去掉正文的对照臂 → ``passed=0``）。
- **B2：结构类来源问题不计 pass，硬失败判定权在封存方**：逐题行里出现 ``source_not_active``
  （引用旧/失效版本）/``source_forbidden_document``/``source_outside_run``/``citation_not_unit_level``
  时，该题状态由 ``pass`` 降为 ``error``（不计 pass，也不冒充 fail），并出
  ``holdout_hard_failure_unclassified``（unknown，evidence 带 ``codes``/``counted_as``/
  ``hard_failures_owner="sealed-labels"``）。``hard_failures`` 在本卡因此**恒 0**，含义是
  "驱动层不代分类"，**不是**"无硬失败"；硬失败类别与计数以封存判定表（``p2-score --verdicts``）为准。
- **文档代号映射（确定、可审）**：从本次 ingest plan 的语料文件名建「产品文档名 -> doc_code」：
  规范名 = ``document_ref``（同槽新版本）> ``name``（上传名）> 文件名；代号只取规范前缀
  ``[A-Z]NN``（如 ``D01_``/``V03_``）；规范名与去扩展名、文件名与去扩展名这些候选名按 set 去重后
  登记（同名时只登记一次，通常 2–4 个键；与 ``p2_scoring._lookup_document_code`` 的原样/去扩展名/文件名三级查找对齐）；同一名字映射到
  两个代号 → ``holdout_document_code_ambiguous``；无 ingest plan 或文件名无前缀 →
  ``holdout_document_code_unmapped``；``dataset.cases`` 里 ``expected_sources``/``relevant_units``
  的 doc_code 全集必须都能映射，否则出 ``holdout_document_code_unmapped`` block
  （evidence 只有 ``{"missing_count": N, "mapped": N}``，不导出来源输入字符串）。
- **阈值未批但观测值可读**：``thresholds_approved`` 只在 gate 配置显式 ``status="approved"`` 时为真；
  gate_v0_3 现值 unapproved → 出 ``holdout_threshold_unapproved``（unknown）、``release_ready=false``，
  但 ``passed/failed/errors/by_stratum`` 照常写出（未执行/error 一律不计 pass）。
- **执行身份**：``execution_mode`` 只在 ``manifest.execution="live"`` 时标 ``live``，否则 ``local_mock``；
  ``real_calls`` 取本轮的**实测出站尝试数**（与 ``p2-score`` 同口径：``summary.network.outbound_attempts``
  的分母；不是"有出网的请求行数"；实测不可用时记 0 并保留 ``network.available=false``）；
  ``run_id``/``config_hash``
  来自本次 run 的绑定摘要（绑定未完成时 ``config_hash=null``，不编造）。
- **写盘隔离与泄漏审计**：产物只落 run_dir（工作区外）；写盘前用**本次解封在内存里的题面**逐题扫
  聚合 JSON 文本：case_id、``case.question``、**每个回合的 ``turns[*].question``/``text``**、
  ``reference_answer``（needle ≥2 字；1 字题面在产物里没有判别力，见 ``_HOLDOUT_LEAK_MIN_NEEDLE``），
  并拒收明细字段名；命中 → ``holdout_scorecard_leak``，退化成"全部记 error + 稳定 block"的聚合
  （产物仍写出、绝不写明细）。兜底卡**不再经过聚合器**（泄漏可能就来自聚合器自己的输入）：若兜底卡
  自己又被同一条 needle 命中，则去掉全部说明文本再写一次。
- **与 ``p2-score`` 的关系**：``p2-score --visibility holdout`` 保留为**可选独立复核**（需工作区外的
  封存逐题行或判定表）；H2 run 的质量读数不再依赖它。两者逐题口径相同（含 B2），但
  ``thresholds_approved`` 来源不同：runner 读 gate 配置 ``status``，``p2-score`` 当前硬编码 ``false``
  ——gate 转 approved 后两张卡会不一致，放行判断一律取**更保守**者（任一为 false 即不放行），
  见 ``p2-live-binding-v0_1.md`` §10.9。
- **测试**：合成封存设施（30 题 / 10-5-5-5-5 / 36 回合）见
  ``backend/tests/evaluation/test_p2_holdout_scorecard.py``，与 T202 同口径现生成 Fernet key 与
  合成题干/答案；不读真实 H2、不取真实 key。

## 11. T207-FIX-H2MAP：H2 版本来源身份（additive）

`p2-holdout-v2.source-map.json` 绑定 V03→D01/v1、V04→D01/v3、V05→D01/v4、V06→D02/v2；依据 acceptance 的 B0 初始化及 `T207-ingest-plan-H2.json` 上传顺序，企业语料 manifest 的同名 V 代号属于另一套语料，不混用。
H2 rows 评分仅在内存复制 expected/relevant/forbidden 引用：版本代号改写为基槽，locator 合并 `version_number`；不改封存文件或金标。普通基槽引用仍不约束版本。
仅 H2 显式打开 `include_source_version`：从产品 source 的正整数 `version_number` 取版本，locator/source_index 自报版本不能补足产品缺版本；二者冲突以 `source_version_conflict` 拒绝。版本、原 locator 和 unit_key 必须在同一条 citation 上同时成立，unit_key 不得绕过版本检查；错版/缺版的 source_hit 不命中，版本禁用引用同样受约束。
映射文件缺失、坏 schema、重复键/重复身份、期望 locator 版本冲突或 expected/relevant 基槽未覆盖均以 `holdout_document_code_unmapped` 阻断；runner 还核对实际上传顺序和引用版本文件是否已导入，失败时全部记 error。禁止来源无须已导入；全局映射中未引用的版本也无须导入。
映射只证明历史身份，不证明 active：原完整 H2 配方中 V05 发布为 v4 后 V04/v3 已失效；经理受控聚合发现的正向 inactive 来源契约阻断由后续独立分场景包解决，本包不修改状态/题集/阈值。公开 P2 默认参数、P1、停止/重试/隔离语义不变。

## 12. T207-SAFE-DIAG：受控内存聚合

H2 runner 的 `holdout_scorecard.json.diagnostics` 使用 `p2-safe-diagnostics/v1`；公开 run 不输出本子树。固定键表及严格校验在 `p2_diagnostics.py`：`counts`、`kind_matrix`、`failed_checks`、`refusal_confusion`、`errors`、`model_failure_reasons`、`source`、`by_stratum`、`classification_status`、`classification_owner`、`hard_failure_evidence`、`structural_evidence`。生成与写盘均校验完整树，每层 exact keys；只允许固定状态字符串和非负整数，bool/float 不算整数，诊断内不接受数组。未知 kind/check/error/reason 只进入固定 unknown 键，不输出外部字符串。

`planned=scored+errors+not_executed`；scored 为完成正常评分的 pass/fail，旧 scorecard.errors 仍包含未开始。末轮矩阵使用 `kind_answer` 等固定键，矩阵总数=`observed+unknown_kind`；实际 kind 在已登记正常结局/拒答枚举内才进入 observed，未知实际 kind 单列 unknown_kind。任何中间轮错误、未完成回合或未开始均不进入矩阵。五个分层与总计逐项守恒。source 仅 matched/unmatched/mapping_blocked；source_hit skipped 不混入 matched，普通来源失败不被猜为硬失败。

结构性评分 error 同样不进入正常矩阵。`refusal_confusion` 只用 should_refuse 和实际 no_answer/not_found/refusal 集合计算 tp/fp/tn/fn，与 expected_kind 独立；另列 errors/not_executed/unknown，七项之和等于 planned，前三类异常不并入TN。precision=tp/(tp+fp)，recall=tp/(tp+fn)，false-refusal=fp/(fp+tn)；分母为0时保持未定义/null，不填0冒充已测。

四类 safety/cross_user/cross_entity/stale_source 当前均 `checked=0, unknown=planned, violations=0`，`classification_status=unverified`、owner=sealed_reviewer，另保留固定结构性违规计数。`hard_failures=0` 不是已验证安全；runner 始终新增 `holdout_hard_failure_unverified` 阻断且 release_ready=false。

后续受控分类接口必须由封存复核方在内存按“case × 四类维度”提交 checked/result 与证据归属，绑定 dataset/manifest、run/config、场景和来源有效状态；仅有硬失败标签 None 或普通 source_hit fail 不足以证明已检查。证据引用与逐题判定留在受控区，只能导出本严格聚合 schema 批准后的计数；本包尚未实现或接受该分类接口，也不把结构性计数代替四维覆盖。
