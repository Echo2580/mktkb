# fixtures/acceptance 模拟语料（T01-C2）

本目录由 `tools/build_demo_corpus.py` 生成，全部内容为**模拟数据**，不代表任何真实企业流程或个人信息。

## 结构

- `normal/`：10 份正常资料（D01～D10），业务版本见 manifest。
- `variants/`：冲突通知、历史/新版本、移除记录、新电话、U06 独立来源、异常样本与混合/失败页样本。
- `boundary/`：单文件边界样本（50/51 页、5000/5001 行、2000 万/超出像素，共 6 个保留文件）。20MB 与 20MB+1 两份体积较大，默认只记录计量与哈希，需要实际文件时用下方“大小边界重建”命令生成。
- `manifest.json`：文件身份、相对路径、SHA-256、业务版本、Locator、场景关联与 `b0_initialization` 初始化配方。
- `questions.json`：64 条题目/场景（40 正常 + 8 无答案 + 6 歧义/冲突 + 10 更新回归），场景引用 B0 配方。
- `font-license/OFL.txt`：静态字体派生所依据的 OFL 1.1 许可副本。

## B0 初始化（业务 V2 的来源）

B0 不是把 D01 直接当作业务 V2 导入，而是在**同一逻辑文件槽**上先建立历史版本：

1. 导入 `variants/V03_物品位置表_历史V1.xlsx`（业务 V1，P01 在 A区3号货架第二层）→ 处理 → 发布。
2. 以新版本方式导入 `normal/D01_物品位置表.xlsx`（业务 V2，P01 在 B区1号货架第二层）→ 处理 → 发布，成为当前有效版本。
3. 其余 9 份正常文件各自首次导入即业务 V1，无历史版本。

完整有序步骤与断言见 `manifest.json` 的 `b0_initialization`（含 `document_slot`、`business_version`、`forbidden`）。
**不得用 V04 建立 B0**（V04 是 D 区新位置，仅用于 U01/U02/U07/U08）；业务版本与应用自动分配的版本号、`revision` 分开，`revision` 由实际运行读取，配方中不预设具体值。

## 大小边界重建（保留实际文件）

需要 20MB 上传边界文件时，用独立入口生成到**全新空目录**（非空目录会被拒绝）：

```powershell
.\.venv\Scripts\python.exe -B tools/build_demo_corpus.py --boundary-only <全新目录>
```

该命令生成并保留 `B01_恰好20MB.pdf`（20,971,520 字节）与 `B02_超过20MB一字节.pdf`（20,971,521 字节），字节数与 SHA-256 与 `manifest.json` 中记录一致；两份文件均为可打开的 PDF（尾部以合法注释填充），pdfplumber 可提取文字、PDFium 可打开。

## 生成命令

```powershell
Set-Location -LiteralPath 'D:\GPT项目\市场部AI知识库'
.\.venv\Scripts\python.exe -B tools/build_demo_corpus.py --output <全新目录>
```

已有非空目录不会被静默覆盖；两次生成应在两个全新目录进行并比对哈希。

## 字体

- 只读复用 `docs/evidence/T01/C1-R1/derived-fonts/` 的静态实例：Regular 400 `F2B1C83E95DA726AA0A10FD5B6A9252A15E75AF9FFB3B25A2930D09860E39669`、Medium 500 `EFF5ACBE28D97768E393285F71A7B9672747ABAAA5E2A99330CDF57FE612555F`，均为 Noto Sans SC VF 固定 wght 派生，保留版权与 OFL。
- 源 VF 为本地 Noto Sans SC 可变字体（版本串含 non-release），未与上游发布包逐字节比较。

## 场景恢复

- 正常 40 题始终在无冲突 B0 上执行。
- C05/C06 需先发布 `variants/V01_临时物料位置通知.pdf` / `V02_店家联系方式变更通知.pdf`。
- U01～U10 每个用例从 B0 独立恢复（独立数据库与文件目录），按 `questions.json` 中 `scenario.actions` 顺序执行。
- `scenario.events`/`assertions` 给出事件先后与断言，供后续测试消费；本步不实现事务、worker 或模型适配器。

## 限制

- 未调用真实 OCR/模型；扫描件与图片的机器识别质量未验证。
- 边界样本只证明计量口径，不构成业务拒绝规则或负载验收。
