# C1-P6 逐源生命周期日期 —— 可行性核查（公开件）

- 角色：**普通开发**（非验收、非经理、非保管）。
- 基线：分支 `codex/p2-e2e`，HEAD `97b0066726e5b8d6f94cbc0b63a890084550c106`，暂存区 0 项、0 commit。
- 工作区：`D:\GPT项目\市场部AI知识库`。
- 本轮唯一问题：**12 个源各自的发布/生效/失效日期，是否存在可复算的公开来源？**
- **结论：`NOT-RUN`（情形 B —— 不能复算）。**
- 硬边界：零真实调用、零出站；未读 runbook / 题面 / 标签 / 私有密文 / key / 证据 / `.env`；未 stage/commit/push；未新建 worktree/切分支；除本文件外**未新增、未修改任何文件**。

> 本文件不含题号、题面、答案、目标值、filter 值、记录键或任何从产品行为反推的日期。全部日期陈述均标注公开件定位。

---

## 0. 一句话

12 个源**没有任何一个**带有可复算的发布/生效/失效日期：全部 12 份文件只携带**同一个常量** `2026-10-27`（"业务更新"页眉），该常量与 `manifest.json` 的 `built_at` 逐字相同、对历史版本与新版本一视同仁，因此**既不是逐源日期，也不能充当区间任一端**。生命周期语义关键词在 12 源中命中 **0** 次。

---

## 1. 被核查的 12 个源（先钉住"是哪 12 个"）

12 源 = `T207-ingest-plan-H2.json` 的 `sources` 数组（0..11），四个 scenario 的 `source_indices` 取并集恰为 0..11（12 个）：

| scenario | source_indices | 数量 |
|---|---|---:|
| `base_b0` | 0,1,4,6,7,8,9 | 7 |
| `base_b0_plus_v01` | 0,1,4,6,7,8,9,10 | 8 |
| `pre_v05_without_v07` | 0,1,2,4,5,6,7,8,9,10 | 10 |
| `post_v05_without_v01` | 0,1,2,3,4,5,6,7,8,9,11 | 11 |
| **并集** | **0..11** | **12** |

场景名与索引的对应自洽：`+v01` 恰加 index 10，`pre_v05` 恰排除 index 3（V05），`without_v07` 恰排除 index 11（V07）。来源：`docs/evaluation/p2-h2-scenarios-v0_2.json`（sha `39c7e161…`）、`T207-ingest-plan-H2.json`（sha `362e3ea1…`，与任务给定一致）。

**字节同一性已核验**：12 份文件的实测 SHA-256 与 `fixtures/acceptance/manifest.json` 记录的 `sha256` **12/12 全等**，故下述扫描针对的正是清单所指的语料字节。

---

## 2. 逐源可见日期实测（决定性证据）

抽取方式：xlsx 用 `openpyxl` 遍历**全部工作表（含 hidden）**逐单元格；docx 遍历正文段落、全部表格、页眉页脚；pdf 逐页 `pdfplumber` 提取文本。均为本地文件解析，无 OCR、无网络。

| # | 源（ingest plan 顺序） | 文件 | 可见日期 | **定位** | 原文 |
|---:|---|---|---|---|---|
| 0 | V03 物品位置表 历史V1 | `variants/V03_物品位置表_历史V1.xlsx` | 2026-10-27 | `物品位置!A3` | `业务更新：2026-10-27` |
| 1 | D01 物品位置表 | `normal/D01_物品位置表.xlsx` | 2026-10-27 | `物品位置!A3` | `业务更新：2026-10-27` |
| 2 | V04 物品位置表 新版V3 | `variants/V04_物品位置表_新版V3.xlsx` | 2026-10-27 | `物品位置!A3` | `业务更新：2026-10-27` |
| 3 | V05 新版V3 移除P01 | `variants/V05_物品位置表_新版V3_移除P01.xlsx` | 2026-10-27 | `物品位置!A3` | `业务更新：2026-10-27` |
| 4 | D02 合作店家信息 | `normal/D02_合作店家信息.xlsx` | 2026-10-27 | `店家信息!A2` | `业务更新：2026-10-27` |
| 5 | V06 合作店家信息 新电话 | `variants/V06_合作店家信息_新电话.xlsx` | 2026-10-27 | `店家信息!A2` | `业务更新：2026-10-27` |
| 6 | D03 市场部工作指南 | `normal/D03_市场部工作指南.docx` | 2026-10-27 | `body.p1` | `模拟数据｜业务更新 2026-10-27｜仅用于入职考核演示` |
| 7 | D04 活动策划流程 | `normal/D04_活动策划流程.docx` | 2026-10-27 | `body.p1` | 同上 |
| 8 | D05 物料领用规范 | `normal/D05_物料领用规范.pdf` | 2026-10-27 | `page1` 第 2 行 | 同上 |
| 9 | D06 店家资料维护说明 | `normal/D06_店家资料维护说明.pdf` | 2026-10-27 | `page1` 第 2 行 | 同上 |
| 10 | V01 临时物料位置通知 | `variants/V01_临时物料位置通知.pdf` | 2026-10-27 | `page1` 第 2 行 | 同上 |
| 11 | V07 物料位置独立通知 | `variants/V07_物料位置独立通知.pdf` | 2026-10-27 | `page1` 第 2 行 | 同上 |

**汇总：12 源中出现的全部不同日期值 = `['2026-10-27']`（仅 1 个）。**

生命周期语义关键词（`生效|失效|有效期|起算|截止|发布日|废止|作废|停用|启用|开始日期|结束日期|业务日期|数据截止|生效日`）在 12 源中命中 **0 次**（`有生命周期词的源：{}`）。

补充：xlsx 中还覆盖了 `备用物料表`（visible）与 `旧草稿`（**hidden**）等工作表，二者均无任何日期。

---

## 3. 为什么这个常量**不能**当区间端点（三条独立理由）

1. **不可区分（致命）**：同一常量同时出现在 **V03（业务 V1，历史版）**、**D01（业务 V2）**、**V04（V3）**、**V05（V3 移除 P01）**——即同一 `doc-positions` 逻辑槽的全部历史版与新版。若把 `2026-10-27` 当 `effective_from`，则 12 源**同时生效**，"某源被后生效版本取代"在结构上永不可能成立。这不会让 `stale_source` 变可判，只会把它从 fail-closed 换成 **fail-open（全 not-stale 假阳性）**，比现状更坏。
2. **语义不符**：值为**"业务更新"**（数据刷新戳），且与 `fixtures/acceptance/manifest.json:3` 的 `"built_at": "2026-10-27"` **逐字相同**。它是**语料构建基线**被写进每份文件页眉，不是该源的发布或生效日期。
3. **无右端**：12 源均无 `effective_to` / 失效 / 废止标注（生命周期词 0 命中）。`stale_source` 要判"被取代"，必须要有区间右端或"后继源严格更晚生效"的偏序；两者都不存在。

**构建/容器元数据同样不可用**（实测，仅作已排除项列出）：xlsx/docx core props `created`/`modified` = `2026-10-01 09:00:00`（构建期）；PDF `CreationDate`/`ModDate` = `D:20000101000000+00'00'`（ReportLab 默认值）；OOMXL zip member datetime = `1980-01-01`（ZIP epoch）。四者**互相矛盾**且均为构建产物，无生命周期语义。

---

## 4. 精确缺项（缺什么、在哪没有、只能谁给）

### 4.1 缺的是什么类信息

**源侧时间有效期**：每个源的 `published_at`（发布时刻）、`effective_from`、`effective_to`——即"该源在何时间区间内是当前有效版本"。
注意**不缺** `as_of`：`as_of` 是运行期观测值（P5 已确认 36/36 回合可由 `plan_observed.as_of` 确定性重建）。缺的是**被比较的另一侧**——源侧区间。没有它，`_check_stale_source` 无从比较。

### 4.2 逐份公开件确认"没有"

| 公开件 | SHA-256（本轮实测） | 实况 |
|---|---|---|
| `fixtures/acceptance/manifest.json` | `6889915267c5127312f1ee9308362ce0198277b1a916a2e6413dd48b5d2755b6` | 仅 `built_at`（L3）与 `op`/`business_version`/`step` 顺序（L29–217）。无任何逐源日期字段。`assertions`（L218–223）只断言"发布后位置为何"，无日期。 |
| `fixtures/acceptance/README.md` | `534d00fa0dae2a6ba0963811441504837f912b33db626091c950bac2cdd5cbb7` | 发布只以**有序步骤**描述（L18–19：导入→处理→发布）；并明确"`revision` 由实际运行读取，配方中不预设具体值"。无日期。 |
| `docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json` | `362e3ea10f673021d78c7a647305f04b8557b364a14482ebc2ba370d7752ed19` | 12 源仅 `path` / `document_ref`。**零日期**。 |
| `docs/evaluation/p2-holdout-v2.source-map.json` | `86c86767ce5f4251ff52589cca9d02882aa7f47e23caf7cde654133b8ea821b5` | 仅 `base_doc_code` + `version_number`（L3–8）。**零日期**；且 L12 明示 `Mapping is historical identity, not an active-version assertion`。 |
| `docs/evaluation/p2-h2-scenarios-v0_2.json` | `39c7e16103acdac52741a48d895b29ff5675ee97e5691955ccebe5b21a1274ad` | 仅 `source_indices` / `ingest_batches`。**零日期**。 |
| 12 份语料可见文本 | 见 §1（12/12 与 manifest 相等） | 唯一日期 = 常量 `2026-10-27`；生命周期词 0。 |

### 4.3 只能由谁提供

1. **保管 A / 保管 B**（唯一可读 `T207-runbook.md` 的角色）：可转述 §8 的 custodian assumptions。**但要注意**：`p2-holdout-v2.source-map.json:12` 对 §8 的转述只涉及**版本号**（"V04 published as v3；V05 subsequently published as v4；V06 replaces D02 as v2"），**未见日期**。故即使读到 runbook，很可能仍然没有日期。我按边界**不读 runbook**，因此只能引述该指认、**无法确认 §8 是否含日期**——这一点必须由保管角色回答。
2. **主人裁定**（若公开件与 runbook 都不含逐源日期，则只剩两条路，且都必须由主人定）：
   - **(a) 改口径**：授权合同**新版本**，把 `stale_source` 的时间性改为**非日期口径**（例如"版本序取代 + `as_of` 版本比较"），并同时定义"空集 / 未走到分支"的观测语义。这属于新契约 + 新 GO，不是本轮能签的。
   - **(b) 下发生命周期表**：由主人/保管下发一份权威的逐源 `published_at`/`effective_from`/`effective_to` 作为**新冻结件**。注意这是**标注决定（labeling decision）**，不是"由公开件投影"；开发角色不得代填，也不得从题干语义或产品行为反推。

---

## 5. 明确拒绝的替代口径（按任务书要求）

| 替代 | 为什么拒绝 |
|---|---|
| 用 scenario 的 active-version 断言代替"日期" | 版本生效 ≠ 有日期证据。`source-map.json:12` 自己就声明该映射"**不是** active-version assertion"。且顺序/版本号无法产生可与 `as_of` 比较的日期。 |
| 用 addendum 的 `business_date` 冒充逐源生命周期 | `business_date` 是单值业务日期，既不能区分 12 源、也无区间右端；把单值当日程区间会直接制造"看似可判"的假证据（与 v2 §8.6 反对给 stale 新造 `targets` 同一类错误）。 |
| 用 `built_at` / core props / PDF CreationDate / zip epoch | 见 §3 末尾：互相矛盾、均为构建产物、无语义。 |
| 用"上传顺序"（ingest plan 序 / `b0_initialization.steps` 序） | 顺序只能给出**全序**，给不出日期；且 `source-map.json:11` 已说明版本身份"follows upload order, **including unpublished uploads**"——顺序里混有未发布上传，不能当发布时刻。 |

---

## 6. 覆盖统计（12 源）

| 口径 | 计数 |
|---|---:|
| 能定出**完整窗口**（`published_at` + `effective_from` + `effective_to` 全有） | **0 / 12** |
| 只能定出**一端**（有 `effective_from` 或 `effective_to` 之一） | **0 / 12** |
| **无任何生命周期端点来源** | **12 / 12** |
| 附注：有一个 corpus-wide 常量日期 | 12 / 12（值为 `2026-10-27`，语义为"业务更新"、与 `built_at` 相同、版本无关 → **不构成任何一端**） |

---

## 7. 对本轮上游结论的影响

- `stale_source` 在公开件范围内**没有非空 pass 通道**：12 条 matched-record 轴仍会被 P4 适配器的固定码 `stale_lifecycle_evidence_missing` 无条件封死（该固定码见 P5 报告 §4；本轮未读适配器源码，仅引述）。
- **P5「C1-2 不值得签 GO」的结论不因本轮改变**，反而被加强：缺口不在"采集没补"，而在"**公开件里根本没有这个数据**"。补 v0.3 采集字段也解决不了——除非主人下发生命周期表（§4.3 之 b）或改口径（§4.3 之 a）。
- 因此 **C1-2 不应基于"补采集"启动**；若仍要推进 stale 轴，入口是 §4.3 的两条裁定路径。

### 7.1 一条路由提示（未读，供经理分派）

工作区里存在前序轮次产物 `docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/product-date-recon.md`（untracked，标题含 "product-date-recon"）。它**不在本轮允许读取的 5 份公开件内**，故我**没有读它**，也不对其内容作任何断言。仅提示：若主人/经理怀疑曾有过一次"产品日期复算"，该文件是应当被优先核对的既有记录——它可能证实或推翻本报告 §2 的"无逐源日期"结论。本报告的结论**仅**基于 §4.2 所列 5 份公开件 + 12 份语料可见文本。

---

## 8. 零调用与保全

### 8.1 零真实调用

- 未调用产品 / 模型 / embedding / rerank / OCR / 裁判 / 检索 / 鉴权 / 余额；未启动任何服务；未创建 GO。
- **零出站**：本轮执行的只有 `.venv/Scripts/python.exe -B` 的**本地文件解析**（`openpyxl` / `python-docx` / `pdfplumber` / `hashlib` / `json` / `zipfile`），脚本内无 `socket` / `http` / `requests` / `httpx` 代码路径。
- **如实说明**：本轮**未运行** netguard 正对照。理由是情形 B 不新增 `evidence/`、且本轮未创建任何计算进程（仅本地解析）。若复核方要求形式化的 4/4 拦截回执，需另派（沿用 P4/P5 的 `evidence/netguard/` 逻辑）。
- 未读 `T207-runbook.md`、真实 H2 题面/标签/答案/目标值、私有密文、key、证据、`.env`、保管会话。另：`fixtures/acceptance/questions.json`（fixture 题库）**主动跳过**——它属题目材料且与生命周期无关。

### 8.2 保全（本轮终态）

| 项 | 结果 |
|---|---|
| HEAD | `97b0066726e5b8d6f94cbc0b63a890084550c106`（未变） |
| 分支 | `codex/p2-e2e`（未切、未建 worktree） |
| 暂存区 | **0 项** |
| 15 个 tracked modified | **15/15 哈希不变**（逐文件 SHA-256 前后比对） |
| untracked（porcelain 条目） | **214 → 214（不变）**。原因见下方注①：整棵 `Q1A-EVAL-REPAIR/` 在基线时已被 git 折叠为**一条** `??` 条目，新增文件落在该目录内，故条目数不变 |
| 新增文件 | 仅本文件 1 个；`git status --porcelain -- <本文件>` = `??`，`git check-ignore` 退出码 1（**未被忽略**） |
| 全仓近期写入扫描 | 除本文件外，工作区近 75 分钟内无本会话产生的其他文件（其余均为 p3/p4/p5 等前序轮次既有产物，时间戳早于本会话首个工具调用） |
| commit / push | 0 |
| C 冻结 12 / 合同 v1·v2 / 旧卡·账本·GO / Q1a-1·1b / P3·P4 模块与契约 / 30 题·标签·阈值 | **未触碰**（本轮只读） |

注①：基线 untracked 快照里已有 `?? docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/`（折叠条目，前后逐字相同）。`c1-1/p6/` 在基线时**不存在**（`Test-Path` = False）。因此本轮对 untracked 集合的**唯一**影响是在这条已折叠目录内加了 1 个文件；逐条 `porcelain` 条目前后完全一致（`Compare-Object` 空）。

---

## 9. 复核方法（逐条可重算）

六个携带版本的 xlsx 已足以独立证伪"逐源日期存在"：它们的日期字段值完全同一。

```python
# 保存为任意外部路径（例如 %TEMP%\check.py），不落入仓库
import json
from pathlib import Path
R = Path(r"D:\GPT项目\市场部AI知识库")
plan = json.loads((R / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json").read_text("utf-8"))
import openpyxl, docx, pdfplumber

def text_of(p):
    n = p.name.lower()
    if n.endswith(".xlsx"):
        wb = openpyxl.load_workbook(p, data_only=True)
        return "\n".join(
            f"{ws.title}!{c.coordinate}={c.value}"
            for ws in wb.worksheets for row in ws.iter_rows()
            for c in row if c.value is not None
        )
    if n.endswith(".docx"):
        d = docx.Document(p)
        return "\n".join([q.text for q in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])
    with pdfplumber.open(p) as pdf:
        return "\n".join(pg.extract_text() or "" for pg in pdf.pages)

for i, s in enumerate(plan["sources"]):
    t = text_of(R / s["path"])
    dates = sorted({w for w in t.replace("：", " ").replace("｜", " ").split()
                    if w.startswith("2026-") or w.startswith("20") and "-" in w})
    life = [k for k in ("生效", "失效", "有效期", "截止", "发布日", "废止", "作废", "停用") if k in t]
    print(i, s["path"].split("/")[-1], "dates=", dates, "lifecycle=", life)
```

预期输出：`dates=['2026-10-27']`（12 行全部相同）、`lifecycle=[]`（12 行全空）。

再核对 §4.2 的五个 SHA-256（`Get-FileHash -Algorithm SHA256`）即可确认所审字节一致。

---

## 10. 结论

**`NOT-RUN`**。

逐源发布/生效/失效日期在允许的公开件范围内**不存在**，且不是"再挖一层就能找到"的缺口：12 份语料只带一个与 `built_at` 同值的构建期常量，元数据侧（manifest / README / ingest plan / source-map / scenarios）**一致地只记录顺序与版本号、不记录日期**。要继续 `stale_source` 轴，必须先由**主人**在 §4.3 的 (a) 改口径 与 (b) 下发生命周期表 之间作裁定；在此之前，任何"逐源生命周期投影"模块都会是在编造日期，故本轮**不产出** `p2_source_lifecycle.py`、测试与 `evidence/`。
