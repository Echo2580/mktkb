# T207 导入配方：B0 语料 + Q01 版本槽（可机读副本见 `T207-import-recipe.json`）

- 角色：T207 准备助手。真实调用 **0**（本文件与 JSON 都是离线清点与配方，没有上传/OCR/发布）。
- 范围：**公开矩阵（B0/N/C/U）用 fixtures 版**（`fixtures/acceptance/{normal,variants}`）；H2 用声明过的 corpus 子集，
  两套永不混灌（编号同号不同义，见 §5）。
- 目标：让 `doc-positions` 这一个**逻辑文档**真正含「历史版 → 当前版 → 未生效版」三版，
  修掉 T206 的事实失败——V03 与 D01 被导入成两个独立 active 文档（各 version=1），Q01 因此返回 conflict。

## 1 T206 失败事实与产品实际可用的路径

| 事实 | 证据 | 结论 |
|---|---|---|
| V03、D01 各成一份 active 文档、各 version=1 | `T206/PILOT/{run_manifest.json,cases.jsonl}`；T206 report §更正 1；verifier `b7a17a05` | 「同槽多版本」没被复现 |
| 根因在 CLI，不在产品 | `backend/src/mktkb/evaluation/cli.py:598-603` 只造 `IngestSource(path=…)`（`document_id=None`、`publish=True`）；`cli.py:874-909` 的 `--ingest` 只收路径 | 驱动层没有「作为既有资料的新版本」与「不发布」两个入口 |
| 产品本身支持多版本与不发布 | `documents/service.py:656-833`（`stage_upload(document_id=…, expected_active_version_id=…)`，`number = latest+1`）；`documents/models.py:87-120`（`DocumentVersion.state` / `active_version_id`）；`product_adapter.py:300-333`（`IngestSource.document_id` / `expected_active_version_id` / `publish`） | 只需补驱动，不改业务 |

产品里「未生效」的可达定义（`documents/models.py:31-44`）：**已处理成功但未发布**（`state=review_required`），
`active_version_id` 仍指向上一版。产品没有「生效日期」字段，因此 `U01`（`upload_version V04` + `process`，不发布）
就是本产品能给出的「未生效版」。**注意**：`fixtures/acceptance/manifest.json` 的 `b0_initialization.forbidden`
禁止「用 V04 建立 B0」——本配方只用 V04 做**未生效的第三版**，B0 的当前有效内容仍是 D01（V2），不违禁。

## 2 调用顺序（42 步，逐字对应 JSON `steps[]`；id 全用占位）

| # | op | 文件 | 目标状态断言（占位 `{D}` = 第一次上传返回的 document_id） |
|---|---|---|---|
| 1 | upload_document（**上传名改写成** `D01_物品位置表.xlsx`） | V03 | 202；新文档名 `D01_物品位置表.xlsx`；`version.number=1`、`state=queued`；documents +1 |
| 2 | process | V03 | job=`succeeded`；`v1.state=review_required` |
| 3 | publish（`expected_active_version_id=null`，`expected_revision=R0`） | V03 | 200；`active_version.number=1`；revision +1 |
| 4 | upload_new_version（`document_id={D}`，`expected_active_version_id={v1}`） | D01 | 202；**同一** `{D}`；`version.number=2`；documents 不变 |
| 5 | process | D01 | job=`succeeded`；`v2.state=review_required` |
| 6 | publish（`expected_active_version_id={v1}`） | D01 | 200；`active_version.number=2`；`v1.state=superseded`；revision +1 |
| 7 | upload_new_version（`document_id={D}`，`expected_active_version_id={v2}`） | V04 | 202；`version.number=3` |
| 8 | process | V04 | job=`succeeded`；`v3.state=review_required` |
| 9 | **skip_publish** | V04 | `active_version.number=2`、`state=published`；`latest_version_number=3`；**revision 不变** |
| 10–36 | D02…D10（9 份，各 upload_document → process → publish） | D02…D10 | 各 `version.number=1`；publish 200；D07/D08/D09 `ocr_mode=text`（8/2/1 页），D10 `ocr_mode=table`（1 页） |
| 37–39 | V01（upload_document → process → publish） | V01 | **只在 R2（C05 复核）导入**；B0 主运行不导入，否则 Q01 变 conflict |
| 40–42 | V02（upload_document → process → publish） | V02 | **只在 R3（C06 复核）导入** |

- 上传名改写（第 1 步）是必要的：产品**没有改名 API**（`documents/routes.py` 只有 upload/version/publish/cancel/delete/preview/file），
  文档名取自首次上传的 filename（`documents/service.py:766-773`）；而评分要把「产品文档名 → 数据集 doc_code」显式映射
  （`p2_scoring.py:427-436,459-465`）。若坚持用 V03 原名，就**必须**在 `document_codes` 里显式写
  `{'V03_物品位置表_历史V1.xlsx': 'D01'}`——同样合法，但产品界面会一直显示历史版文件名，故不推荐。
- `allow_same_name` **不得**用来做版本：它建的是第二份独立文档（`name_key=NULL`，`documents/service.py:766-773`），
  正是 T206 的失败形态。

## 3 灌库后必须成立的断言（`assertions_after_ingest`）

1. `documents` 计数 = 12（B0 运行：1 个 doc-positions 槽 + D02…D10 九份；V01/V02 不在 B0 运行里）。
2. doc-positions 槽：`latest_version_number=3`、`active_version_number=2`、三版 sha256 恰为 {V03, D01, V04}。
3. 第 3 版 `state=review_required` 且 `active_version_id` 不是它；第 1 版 `superseded`。
4. `knowledge_state.revision` 只随发布递增：B0 运行 10 次发布 = +10（V04 的处理不入 revision）。
5. Q01 回答 = `B区1号货架第二层`；来源 `unit_key=sheet:物品位置:row:8`、`status=active`、`version_number=2`。
6. Q01 的来源**不得**是 V03 的 `A区3号货架第二层`，也**不得**是 V04 的 D 区位置（未生效版不得进入引用）。

## 4 失败判定（任一命中即停，不重试、不补跑）

| 现象 | 判定 |
|---|---|
| 第 4 步返回 409 `SAME_NAME_REQUIRES_ACTION`，或 documents 计数 +1 | 版本槽没复现（T206 同形失败），停 |
| 第 9 步后 `active_version_number=3` 或 revision 变了 | 未生效版被当生效，停 |
| 第 2/5/8 步 job 非 `succeeded` | 数据面失败，停 |
| 12 页 OCR 的 `mode` 与计划项模型不符 | `ocr_mode_plan_mismatch`（`p2_live.py:898-937`），**发送前**停 |
| 上传 409 `DUPLICATE_CONTENT` | V03/D01/V04 字节碰撞（不应发生：三者 sha 互异），停 |
| Q01 来源命中未生效版 | 版本隔离失败（硬失败口径），停并记 gate 行 |

## 5 与 corpus 版 V01–V08 的关系

| fixture（B0，本矩阵用） | corpus（H2 用，若声明） | 说明 |
|---|---|---|
| V03 `物品位置表_历史V1.xlsx` | V01 `终端物料位置表_历史V1.xlsx` | 同角色：B0 历史版槽 |
| V04 `物品位置表_新版V3.xlsx` | V02 `终端物料位置表_新版V3.xlsx` | 同角色：新版 / 未生效候选 |
| V05 `新版V3_移除P01.xlsx` | V07 `物品位置表_移除QF21马克杯.xlsx` | 同角色：删行 |
| V06 `合作店家信息_新电话.xlsx` | V08 `门店联系人变更通知.pdf` | 同角色：联系人变更 |
| V01 `临时物料位置通知.pdf` | —（corpus V03 是已失效价目表，不同义） | 位置冲突的「另一有效来源」只在 fixture 侧 |
| V02 `店家联系方式变更通知.pdf` | —（corpus V04/V05 是同名不同字节对照） | 电话冲突只在 fixture 侧 |
| — | corpus V04/V05 同名不同字节、V06 同字节副本 | fixture 侧无对应；B0 的同名/重复语义由 A0x 异常样本承担 |

两套**字节不同、编号同号不同义**：混灌会让 `document_versions.sha256` 唯一约束与 `document.name` 同名校验互相干扰，
也让 `document_codes` 映射出现一对多。规则：公开矩阵只灌 fixtures；H2 只灌它自己声明的 corpus 子集。

## 6 离线测算：chunk / embedding 批（`evidence/estimate.py` 可复跑）

| 资料 | 单元 | chunk | 唯一文本 | 批（batch=5） |
|---|---|---|---|---|
| D01 `物品位置表` | 9 | 9 | 9 | 2 |
| V03（历史 V1） | 9 | 9 | 9 | 2 |
| V04（新版 V3） | 9 | 9 | 9 | 2 |
| D02 `合作店家信息` | 4 | 4 | 4 | 1 |
| D03 `市场部工作指南` | 8 | 2 | 2 | 1 |
| D04 `活动策划流程` | 7 | 2 | 2 | 1 |
| D05 `物料领用规范` | 8 | 2 | 2 | 1 |
| D06 `店家资料维护说明` | 6 | 1 | 1 | 1 |
| V01 / V02（冲突通知） | 5 / 5 | 1 / 1 | 1 / 1 | 1 / 1 |
| **非 OCR 小计（B0 运行 8 份）** | 60 | 38 | 38 | **11** |

OCR 侧（D07 8 页 / D08 2 页 / D09 1 图 / D10 1 图 = **12 页**）的 chunk 数只由「OCR 文本长度」决定，
本产品没有每页字数上限（`parsers/types.py:25-36` 只有像素/页数/tile 上限），所以按**每页字数上限**给三档：

| 口径 | D07 | D08 | D09 | D10 | 合计批 |
|---|---|---|---|---|---|
| 转录锚定（`tests/acceptance/support/ocr_transcripts.py`，640/125/56/138 字） | 1 | 1 | 1 | 1 | **4** |
| 每页 ≤1,800 字 | 5 | 2 | 1 | 1 | **9** |
| 每页 ≤2,700 字（**计划取此档**） | 7 | 2 | 1 | 1 | **11** |

- 计划 `index_embedding.requests = 22 = 11（非 OCR）+ 11（OCR 上限）`；实际若小于上限，未用的请求不会被花掉（`AttemptBudget` 只在使用时扣）。
- 上限不成立（某页 OCR 文本 > 2,700 字）时：第 3 批 embedding 在**发送前**被 `attempt_quota_exhausted` 拒（fail-closed，不超支），
  重跑要新计划 + 新 GO。
- OCR 计费与批数无关：`11×0.5 + 1×0.15 = 5.65 元`（D10 实测判 table，T204 §7）。
