# P2-T202 独立验收 review（H2 封存 + 数据协议）

- 结论：**PASS（可交经理人工审核门）**；6 项验收项全部 PASS，未发现需返工的标准违例。
  本结论**不代表 P2 整体通过**（T203–T209 未验收）。
- 角色：独立验收助手（冷上下文，非开发者/非命题者/非经理）；证伪优先，完成后停止。
- 现场：分支 `codex/p2-e2e`、HEAD `3afe8c3`；T202 交付未提交（不 commit/push）。

## 0. 现场复核（独立）

- `git diff --stat`：仅 `.claude/handoffs/_index.md`（+6 行，PM 协调文件）；`git diff --cached` 空；无新 commit。
- T202 交付全部未跟踪：`p2_dataset.py`(41467 B)、`test_p2_dataset.py`(45222 B)、
  `docs/evaluation/p2-dataset-v0_1.md`(15024 B)、`docs/reports/OBS-EVAL/P2/T202/**`。
- `dataset.py` 未改：工作区 blob `db7631547e99…` == `HEAD:backend/src/mktkb/evaluation/dataset.py`；
  `git diff -- dataset.py` 为空；文件 sha256 `945d150db9023b19…`。
- 封存：`D:\mktkb-p2-holdout\v2` 仅 5 个文件（`questions.jsonl.fernet`/`labels.jsonl.fernet`/
  `manifest.json`/`audit.md`/`custodian-report.md`），无明文与临时脚本；key 在 `D:\mktkb-p2-holdout\keys\v2.key`（44 B，不入库）。

## 1. 接口与契约 — PASS

- 签名与冻结契约一致：`load_p2_dataset(manifest_path, *, visibility)`；缺少 visibility → `TypeError`，
  `"Public"/None/""` → `P2DatasetError(visibility_invalid)`，无默认值。
- **public 绝不打开封存 root**（自写 `sys.addaudithook` 探针，非仅跑开发测试）：env 指向真实 root 时
  仅 1 次 open（仓库 manifest），root 内 0 次；直接传 root 内 manifest → `visibility_root_violation` 且 0 次 open；
  返回 `cases=()`、`labels={}`。
- **holdout 必须注入 env**：无 env → `holdout_env_missing` 且 0 次 open；正常路径只 open
  manifest + key + 两个密文（3 次在 root 内、1 次 key），无越界读取。
- fail-closed 矩阵（自建合成封存，工作区外临时目录，Fernet 现生成）：31 个场景全部命中预期稳定原因码
  （缺 env/key/文件、坏 key、错 key、密文/明文 sha 不符、data 题数/分层/turn_stats 不符、重复 id、
  questions 含答案字段、行内多/缺字段、labels 缺/多 case、多轮缺轮/单轮多轮、locator 非法、UUID 不透明 id、
  manifest 未知/缺失字段与冻结值），异常文本不含哨兵题干/答案标记（0 命中）。
  （首轮 4 个用例为我方探针构造错误，修正后全部按预期拒绝；不涉及产品缺陷。）
- 46 个原因码与 `docs/evaluation/p2-dataset-v0_1.md` 逐条对齐（独立 AST 提取比对，缺失 0）。

## 2. 测试 — PASS

- 指定命令（复跑）：
  `.\\.venv\\Scripts\\python.exe -B -m pytest backend/tests/evaluation/test_p2_dataset.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t202-verify`
  → **64 passed, 1 warning in 0.82 s**；无 skip/xfail（源码扫描 0）。
- 额外对照（因 dataset.py 未改，非必需）：`test_dataset.py` → **21 passed**，P1 holdout 行为未受影响。
- 不只看开发测试：第 1/3/4/5 项均为本助手自写探针/独立解密结论。
- 临时 basetemp（我创建的两个）已删除，工作区无新增残留。

## 3. 封存完整性（不读内容逐题）— PASS

- 仓库副本 `docs/evaluation/p2-holdout-v2.manifest.json` 与封存 manifest **逐字节相同**
  （sha256 `8874985ef8f4aacc…ce4b`，1037 B，15 字段严格、冻结值全对）。
- 密文 sha256 == manifest；一次性内存解密（脚本与明文不落盘、用后删除）：
  **30/30 行**、分层 **10/5/5/5/5**、明文 sha256 双向一致、questions 严格 13 键 / labels 11 键
  （全 30 行带可选 `label_version`）、questions 答案字段 0、id 唯一且 questions↔labels 集合相等、
  `label_version` 唯一 `p2-holdout-v2-2026-11-10`、`requires_ocr` 全 false、
  turn_stats `36 / max 3 / {1:25,2:4,3:1}` 与数据实算一致、locator/来源引用 0 违规、`validate_case` 30/30。
- 加载器 holdout 结果与独立解析一致：30 cases、0 `metadata_mismatch`、turns/answers 逐条相同。

## 4. 泄漏与审计 — PASS（1 条需知情的观察）

- 仓库扫描（backend/src、backend/tests、docs/evaluation、docs/reports、.claude/handoffs + 仓库根文件 +
  docs/*.md）：**1200 个文本文件 / 16.9 M 字符**；72 个题干 16 字符窗口 + 88 个答案窗口 + 55 条整条全文：
  **题干命中 0 个文件**，key 字符串（全串与前 22 字符）命中 0。
- 观察（非阻断）：有 6 个**先于封存**的文件含与 H2 答案相同的短事实串
  （`.claude/handoffs/_scratch/**/cases.jsonl` 3 个，mtime 2026-11-09/11-10 上午；`test_notice_facts.py`、
  `test_parsers.py`、`墨刀…提示词.md` 均为 `366046d`(2026-11-04) 已跟踪文件）。它们是公开 B0/测试夹具，
  非 H2 泄漏；含义是“答案短串”不能当作冷题证据。
- 与公开 B0 的重合度：题干字符 4-gram Jaccard 最大 **0.467**（>0.6 的 0 条）、答案与 B0 答案逐字相同 **0 条** → 无抄题迹象。
- 封存侧文档扫描：`audit.md`/`custodian-report.md` 对 H2 题干/答案片段命中 **0**；custodian-report 含 30 个 case_id、
  4 个 sha 与分层计数（仅元数据，本地保留，不入库）。
- `audit.md` 已写 H1 暴露事实：H1=P1-PRE-1 30 题、历史聚合 **7/30**、**2026-11-09 误打印题干事件**、
  “不得再称未见冷题”、H1/H2 不可用分数差宣称质量提升、可见性边界表与读取人员仅两类。
- 开发未访问封存 root：开发自述 + 证据 `verify.json` 声明 + 仓库无明文/key + 代码/测试不引用真实路径
  （仅测试 docstring 出现路径字样）+ 封存文件 mtime 仍为 2026-11-10T11:08Z。**属“无反证”级别**，无 OS 审计日志可证。

## 5. 语义抽检（6 题，每层≥1）— PASS

| case_id | 层 | 判定 | 依据（不含题干/答案） |
|---|---|---|---|
| h2-par-06 | paraphrase | PASS | 3/3 评分值均在所引政策文档且上下文重合 |
| h2-mt-01 | multi_turn | PASS | 3 轮；2 个评分值分别落在对话所指两行（店+物品匹配） |
| h2-neg-02 | negative | PASS | 应拒答成立：所问店存在，但该“店+物品”行在表中不存在 |
| h2-stale-03 | stale_conflict | PASS | 冲突 gold=现行表行+第二有效来源；禁用值只在被取代版本 |
| h2-sec-01 | cross_doc_security | PASS | 两值来自两文档；禁用值属另一门店（跨实体诱饵） |
| h2-stale-05 | stale_conflict | PASS | gold 只在独立通知；禁用来源为已删除/移行文档 |

- 仅记 case_id + 判定；未记录题干/答案。**未覆盖**：其余 24 题语义、H2 与 H1 的独立性（H1 原件不在本验收范围）。

## 6. 范围 — PASS

- 开发只新增允许的 4 类文件；`dataset.py`、`pyproject.toml`、其它源码/测试 0 改动；无 schema/业务 API/生产依赖变化。
- 无真实模型/OCR 调用（本助手亦未做）；未读 `.env`/H1 原件；未跑全仓测试；未 commit/push。

## 7. 非阻断观察（供后续任务）

1. `public` 在 **未设 env** 时可读封存 root 内的 manifest（仅元数据，不返回题目）——开发已在报告 §7.6 披露；
   建议 T203 调用方固定传仓库副本路径。
2. 加载器不校验行内 `business_date` 与 manifest 相等（H2 实际全为 2026-10-28）；契约未要求，记录备查。
3. `cryptography` 未写入 `pyproject.toml`（缺失时 `crypto_unavailable` fail closed）；可移植性需 T206 关注。
4. 未检查 symlink/TOCTOU（root/key 由操作者注入，内容安全由 sha256 保证）；开发已披露。
5. 若 `MKTKB_P2_HOLDOUT_ROOT` 被设成仓库父目录，public 会因“路径在 root 内”拒绝合法仓库 manifest（过度拒绝，方向安全）。

## 8. 复现命令（关键）

```bash
.\\.venv\\Scripts\\python.exe -B -m pytest backend/tests/evaluation/test_p2_dataset.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t202-verify   # 64 passed
.\\.venv\\Scripts\\python.exe -B -m pytest backend/tests/evaluation/test_dataset.py -q -p no:cacheprovider --basetemp backend/.pytest-tmp/p2-t202-verify-legacy  # 21 passed
git diff --stat ; git diff --cached --stat ; git hash-object backend/src/mktkb/evaluation/dataset.py ; git rev-parse HEAD:backend/src/mktkb/evaluation/dataset.py
```

## 9. 证据入口（4 个）

1. `evidence/verify/structure.json`——manifest/密文/明文 sha、30/30、分层、turn_stats、字段集、loader 对照、dataset.py blob。
2. `evidence/verify/access.json`——audit hook 实测 open 次数、public/holdout 边界、visibility 严格性。
3. `evidence/verify/failclosed.json`——31 个 fail-closed 场景矩阵与“异常不含题干/答案”结论。
4. `evidence/verify/leak-semantic.json`——1200 文件泄漏扫描、B0 相似度、封存文档扫描、6 题语义抽检。

## 10. 边界声明

- 只写 `docs/reports/OBS-EVAL/P2/T202/review.md` 与 `evidence/verify/`；未改源码/测试/开发报告/manifest/封存数据；未 commit/push。
- 解密封存仅在内存完成，探针脚本位于工作区外并能删尽；未把任何题干/答案写入本文件或证据。
