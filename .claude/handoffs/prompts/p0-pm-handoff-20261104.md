# P0 项目经理交接提示词（2026-11-04 22:20）

> **用法**：把本文件**全文**粘贴给新窗口；该窗口以「项目经理（PM）」身份接手本项目的 P0 阶段。
> 本文件自足，新窗口不需要读旧聊天记录。
> 文件路径：`.claude/handoffs/prompts/p0-pm-handoff-20261104.md`

## 0. 第一动作（不要跳）

1. 调用 `skill` 工具加载 **`project-manager`** 技能，严格按其中的门禁（G0–G6）、目录拓扑、串行规则执行。
2. 只读核对现场（**此步禁止修改任何文件**）：

```powershell
cd D:\GPT项目\市场部AI知识库
git log --oneline -6
git status --short
git tag --list
```

3. 按顺序读（先 1–2，再 3–4 的关键章节，最后 5–6）：
   1. `.claude/handoffs/_index.md`
   2. `.claude/handoffs/2026-11-04-p0-task-breakdown.md`
   3. `docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md`（§1/§3/§6/§7/§8/§11 必读）
   4. `docs/superpowers/plans/2026-11-04-mktkb-observability-evaluation-p0.md`（全局约束、Task 1–7、验收映射）
   5. `README.md`、`本地交付说明-20261104.md`、`错误记录-20261104.md`、`docs/项目进度.md`（顶部状态 + §68）
   6. `docs/evidence/LOCAL-R1-20261101/TEST-20261104/PM-HANDOFF-20261104.md`（上一任 PM 的现场交接，本地文件、不入库）
4. 先向主人回复一段 ≤10 行的「现场核对 + 理解 + 待确认参数」，**等答复后再派单；不要先开工**。

## 1. 项目是什么

市场部 AI 知识库（MKTKB）：本地 RAG 知识库（FastAPI + React 19 + SQLite FTS5 + DeepSeek / DashScope / 腾讯 OCR）。管理员上传 xlsx/docx/PDF/扫描件 → 解析、建索引、按版本发布；员工自然语言提问 → 得到带来源引用的答案。

- GitHub：https://github.com/Echo2580/mktkb（Public；未声明 License；无英文版）
- 运行环境：Windows 本地，Python 3.12.7 `.venv`，Node.js ≥22.12
- 非云端、非部署状态；所有真实调用受本地预算账本约束

## 2. 当前状态（交接时 2026-11-04 22:20）

- **v0.1 本地交付版已冻结**：`main` @ `85dfbe0`，tag `v0.1-local-20261104` → `366046d`。
- **主人决定（2026-11-04）**：本版**不修缺陷、不部署**，先做「自动化评测与可观测性」P0；P0 完成后再修缺陷。
- 40Q 真实矩阵（20:35）：**31/40**；Q01–Q24 精确题 **24/24**；Q25–Q40 语义/扫描件 **7/16**。账本 **15.050980 / 20 元**，余 **4.949020 元**，0 未结算。
- 自动化测试：**948 passed / 0 failed**（2026-11-04 17:31）。
- 已知缺陷（本轮不修）：D4（流程/规范类被路由成记录枚举后死路，P1）、D1（预发送异常误包装为 MODEL_UNAVAILABLE，P1）、D5（未识别门店沿用上一轮，P2）、D6（字段错配/含糊直吐记录，P2）、D3（澄清文案误导，P2）。详见 `错误记录-20261104.md`。
- 仓库**不含** `docs/evidence/`（约 5.8GB，仅本地保留）；P0 验收证据入库路径已改为 `docs/reports/OBS-EVAL/P0/`（plan 与 spec 已同步）。
- **上一任 PM 窗口已完成、不要重做**：
  1. 清理约 15.6GB 旧交接/测试中间数据（归档区 `D:\GPT项目\_归档_MKTKB_20261104_清理\`，含逐文件清单）；
  2. `git init` + 首次提交 + 推送 GitHub；
  3. 把 40Q 结果补写进 `docs/项目进度.md`（§68）与 `错误记录-20261104.md`；
  4. 修正 plan/spec 两处过期约束（“无 .git / anchors.json” → “git commit 为版本锚”；证据路径 → `docs/reports`）；
  5. README 重写（结构/徽章/Mermaid 架构/路线图）+ 4 张真实界面截图（`docs/assets/`）；
  6. 写好 P0 任务拆解 **T001–T009** 与 `.claude/handoffs/_index.md`（全部 `G0 待审`）。
- **未做**：P0 任何代码；未建 `docs/reports/`；未建 `p0/obs-eval` 分支；未派任何开发/验收窗口。主人明确要求「先拆任务单，暂不开工」。

## 3. 本阶段唯一目标：P0

按 task-breakdown 完成 **T001–T009（9 包）**：

| 包 | 内容 | 依赖 |
|---|---|---|
| T001 | Trace 数据契约与版本绑定 | — |
| T002 | SQLite Trace 仓储 | T001 |
| T003 | 最小侵入埋点 + 中间件 + `X-Trace-ID`（最高风险，动 8 个生产文件） | T002 |
| T004 | 评测数据集 + gold 解析 + scorer | T001 |
| T005 | Replay / Local Runner（零真实调用） | T004 |
| T006 | 双层发布门禁与退出码 | T005 |
| T007 | Baseline / Diff / 报告 | T006 |
| T008 | CLI + P0 七条验收 | T007 |
| T009 | 独立验收与 P0 收口 | 全部 |

**P0 七条验收**：① 现有业务行为不变；② 每次执行尝试可用 `trace_id` 关联完整阶段；③ B0 40 与 Bad Case 13 可独立回归；④ 结果绑定 dataset / index / pipeline 版本；⑤ 可生成 baseline / diff / JSON 报告；⑥ 硬门禁失败返回非零退出码；⑦ 零真实模型调用。

**本阶段不做**：修 D4/D1/D5/D6/D3、部署、Ragas/Langfuse/看板/告警、Holdout 30、live 端到端评测（属 P1/P2/P3）。P0 完成后交主人验收（G5）；**主人未明确说继续前，不得进入修复阶段**。

## 4. 硬约束（每包都适用）

**PM 侧**
- 只写 `.claude/handoffs/**`；不写产品源码/测试/文档正文/数据文件；不替开发实现；不替验收判 PASS。
- 串行闸门：同一时刻「人工待审」≤1 项；有未决策待审项时不得派新任务；返工 ≤3 轮，超限停下升级主人。
- 派单前写全任务单：目标 / 边界（允许改·禁止改）/ 输入 / 依赖 / 可判定验收标准 / 验证命令 / 报告格式；提示词必须**落文件**。
- 验收助手必须**全新上下文**，不能看开发对话；PASS 必须由其独立复跑的证据支撑；`NOT-RUN` 不得写成通过。
- 只有实际执行过的检查才能写成「已验证」。

**产品 / 仓库侧**
- P0 铁律：零真实模型 / OCR / embedding / rerank 调用、不读 `.env`、不改现有 API 请求参数与响应 Body、不改业务库与 `rag-index.sqlite3` schema、不新增生产依赖、不接 Ragas/Langfuse/OTel/Prometheus。
- 只读区：`docs/evidence/`、`var/`、`.env`、账本 / `budget.json` / GO、`fixtures/`、`corpus/`、归档区；不清理、不重置、不改上限。
- 证据：验收证据入库 `docs/reports/OBS-EVAL/P0/`；运行产物 `var/eval/`、`var/observability/` 不入库，只记路径与 sha256；版本锚用 **git commit**（plan 已改）。
- 分支：开发交付在 `p0/obs-eval` 分支逐包 commit（`p0/T00x ...`）；协调文档可提交 `main`；T009 通过并经主人验收后再合并 `main`。
- 测试命令：`.\.venv\Scripts\python.exe -B -m pytest ...`，并设置 `$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"`。
- 不停止 / 重启外部服务（AstrBot 等）；不杀主人已在运行的本机服务（前端 5673 / 后端 8077 可能正在跑）。
- 凭据只在运行时从 `.env` 读取，不打印、不写进报告或命令行；任何真实调用必须先经主人授权并记账（P0 应为 0 次）。

## 5. 派单建议（主人尚未最终确认，先问）

- 执行方式：建议 **1 个开发助手（顺序 T001→T008）+ 1 个独立验收助手（V1–V5 分别证伪）**。若新窗口所在 harness 支持 teammate，用 `spawn_teammate` / `team_task_*`；否则走人肉中继（`prompts/T00x-*.md` 由主人复制到开发/验收窗口）。
- 每包一个提交；T003 风险最高，必须要求「golden 固定响应 + 既有 integration 测试全绿」。
- 需要主人确认的 3 个参数：① 是否按 1 开发 + 1 验收；② 是否走 PR（建议 `p0/obs-eval` → `main` 开 1 个 PR 逐包 review）；③ 是否接受现有 9 包粒度（T003/T004/T005 工作量最大）。
- 若主人回复「**按默认派单**」，即按上述默认执行，不用再问。

## 6. 环境与工具坑（已踩过）

- 本 harness 的 `pwsh` 实为 **Windows PowerShell 5.1**：写 `.ps1` 且含中文时文件必须带 BOM，或改用纯 ASCII 脚本；中文路径命令用 `-LiteralPath`。
- `git` 身份已配置（Echo2580 / zhaot2580@gmail.com）；`gh` 已登录且有 repo 权限。
- Python：`.venv\Scripts\python.exe`（3.12.7）；Node v24；前端 Vite 8。
- 前端 5673 / 后端 8077 可能由主人服务占用，不要随意启停。
- `docs/evidence/` 是大目录（~5.8GB）：不要全树递归扫描，明确用途再读具体文件。
- 项目语料与真实调用说明见 `README.md`「数据与合规说明」；`var/` 是主人本地业务数据，不要动。

## 7. 你的第一批产出（只读，不改项目文件）

向主人回复（≤10 行）：

```text
现场核对：HEAD=<sha>，工作区<干净/有改动>，tag=<...>，任务单/索引<存在>
P0 理解：<一句话目标 + 七条验收>
待确认：1) <派单方式> 2) <PR> 3) <包粒度>
```

主人确认后，再创建 T001 任务单（`.claude/handoffs/T001-.../handoff.md`）与派单提示词（`.claude/handoffs/prompts/T001-dev.md` 等），按 G1 进入 T001。

## 8. 备注

- 本窗口（前任 PM）已完成收尾、P0 未开工。为避免两个 PM 同时写 `.claude/handoffs`，请主人**先关闭前任窗口**，再让新窗口接手。
- 技能：`project-manager` 必加载；可配合 `writing-plans`、`subagent-driven-development`、`verification-before-completion`。
- 用户偏好：中文；先给结果、只展开必要细节；称呼「主人」；不写许可证、不做英文版（已定）；不打印凭据。
