# 主人亲验一页清单 · 原核收候选（2026-11-22）

## 一、实际启动版本与入口

| 项 | 实际值 |
|---|---|
| 版本 | 原核收候选 `codex/p2-e2e @ 93486b6590c6542f34dd70d20a19b792c659f416`（P2「有保留通过」） |
| 启动目录（后端） | `D:\mktkb-clean-93486b6`（该提交的 git worktree 干净检出，detached HEAD） |
| 启动目录（前端） | `D:\GPT项目\市场部AI知识库\frontend`（前端源码与 HEAD 逐字节一致，`git status` 无改动；仅作 UI 外壳，`/api` 反向代理到后端） |
| **实际加载的包路径（自证）** | 后端启动日志首行：`ACCEPTANCE_MODULE=D:\mktkb-clean-93486b6\backend\src\mktkb\__init__.py`（见 §五） |
| 前端访问地址 | **http://127.0.0.1:5173/** |
| 后端 API 地址 | **http://127.0.0.1:8177/api/v1**（健康检查 `/healthz` 返回 `{"status":"ok"}`） |
| 运行模式 | RAG provider = `offline`；OCR 关闭；**未提供任何模型凭据** → 真实模型/OCR/外网调用 **0**，费用 **0** |
| 数据隔离 | 独立数据目录 `D:\mktkb-accept-93486b6\{var,storage}`、独立 SQLite 与独立存储；**未触碰**仓库 `var/`、原业务库、冻结工件、账本与 GO |
| 账号 | 管理员 `admin` / `OwnerAccept-20261122`；员工 `employee` / `EmployeeAccept-20261122` |

重启命令（若进程被关掉）：

```
powershell -NoProfile -File D:\mktkb-accept-93486b6\start-acceptance.ps1
```

## 二、亲验清单（开发自测已跑；主人可按同一顺序复验）

| # | 检查项 | 预期 | 开发自测实测 | 状态 |
|---|---|---|---|---|
| 1 | 登录与权限 | 管理员登录 200；员工上传被拒 403 | 200 / 403 | **PASS** |
| 2 | 上传并发布 | 上传 202 → 处理为 `review_required` → 发布 200、revision 0→1 | 202 / review_required / 200 / rev 1 | **PASS** |
| 3 | 问答与来源详情 | 生成式回答 + `sources[]` + 来源详情（定位/字段） | 生成式回答返回**显式** `service_error`「问答模型尚未配置」；来源详情 `NOT-RUN`（离线模式无来源） | **受限：需主人授权 live 模型** |
| 4 | 缺字段时的徽标/提示 | `not_found` + `missing_fields=["营业时间"]`，不编造 | 实测同值 | **PASS** |
| 5 | 发布新版本后的答案 | 新版本发布 200、revision 1→2，旧版本转 `published`（历史） | 200 / rev 2 / 两版本并存 | **PASS** |
| 6 | 删除后的历史来源访问 | 删除 200、revision 2→3；历史来源访问返回可解释拒绝 | 删除 200；历史来源 `NOT-RUN`（离线模式无来源可访问） | **部分** |
| 7 | 来源与答案一致、按权限显示 | 员工只看到本人会话；管理员看资料 | 员工上传 403；管理员/员工登录各自 200 | **PASS** |

自测证据：[`evidence-owner-acceptance-probe.json`](evidence-owner-acceptance-probe.json)（逐项 HTTP 状态与关键字段），
自测脚本 `D:\mktkb-accept-93486b6\acceptance_probe.py`（同一份可直接复跑）。

## 三、必须知道的三条边界（不影响今日验收，但决定"能不能算发布"）

1. **生成式问答需要模型**：离线模式没有 chat 模型，产品按"服务调用失败，不是资料没有答案"显式拒绝（这是正确行为，
   不是伪造答案）。要做第 3/6 项完整验收，请主人明确授权 live 模式并登记费用（沿用既有预算账本与 GO 流程）。
2. **今天验的是原核收候选，不是修复候选**：FU-1..FU-4 的修复树改动了 `p2_runner.py` / `product_adapter.py`，
   候选流水线摘要因此变化（`28aae43c… → 2aa9177b…`），发布门禁 `candidate.pipeline` 在修复树上按既有规则
   `blocked`。放行需：受影响项独立复验 → 重新冻结（含新 B0 准入）→ 主人确认。**修复候选尚未独立验收，今日不提供。**
3. **前端是候选同源源码的 Vite dev 外壳**：`frontend/` 无改动；`frontend/dist` 是 2026-11-08 的旧构建，**没有使用**。
   若要"构建产物级"前端证据，需另跑 `npm run build`（未在本轮范围内）。

## 四、数据与费用声明

| 项 | 值 |
|---|---|
| 真实模型调用 / OCR / 外网 | 0 / 0 / 0 |
| 新增费用 | 0 元 |
| 原业务数据 / 原 `var/` / 冻结工件 / 账本 / GO | 未读写、未改动（只读核对） |
| 私有 H2 密文 | 未打开、未解密、未复制 |

## 五、版本自证与一个已修正的启动缺陷（独立复核发现）

- **缺陷**：venv 里 `mktkb` 是 editable 安装，指向**主仓库（修复树）** `backend/src`；只 `Set-Location` 到干净检出
  并不会改变 `import` 解析。首版实例因此实际加载的是修复树字节（对 7 项 API 级检查预期无行为差异，但"版本"陈述不实）。
- **修正**：启动器显式设置 `PYTHONPATH=<干净检出>\backend\src`，并在启动日志首行打印实际包路径。
- **自证**：`D:\mktkb-accept-93486b6\backend.log` 首行
  `ACCEPTANCE_MODULE=D:\mktkb-clean-93486b6\backend\src\mktkb\__init__.py`；
  修正后重置数据并**重跑**亲验探针：13 步 **12 OK / 1 FAIL**（唯一 FAIL 仍是"离线模式无来源"的 `source.detail.v1`），
  与新证据 [`evidence-owner-acceptance-probe.json`](evidence-owner-acceptance-probe.json) 一致。
- **结论**：当前实例是原核收候选字节 + 隔离数据 + 零真实调用；`documents=0` 干净起点。
