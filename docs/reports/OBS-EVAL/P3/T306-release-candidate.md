# T306 发布候选材料（P3 知识运营）

> 结论：候选具备提请发布条件，**待项目经理独立验收 + 主人 P3 发布决定**；本窗口不提交、不部署、不跑真实环境。
> 基线：HEAD `0d6ba61`；候选形态：该 HEAD + 工作区未提交 P3 改动（共 84 项 git 状态条目，其中含非 P3 在途改动，见 §1.4）。

## 1. 候选版本描述

### 1.1 后端（新增只读运营 API）

| 文件/目录 | 状态 | 说明 |
| --- | --- | --- |
| `backend/src/mktkb/operations/` | 新增 | 总览/问答/资产/评测只读路由、查询、口径与 schema |
| `backend/src/mktkb/main.py` | 修改（+2 行） | 挂载 operations 路由 |
| `backend/tests/operations/` | 新增 | 69 条后端运营测试与种子 helpers |

### 1.2 前端（运营三页 + 图表依赖）

| 文件/目录 | 状态 | 说明 |
| --- | --- | --- |
| `frontend/src/features/operations/` | 新增 | 总览、问答诊断、知识资产、评测、抽屉与筛选/映射 |
| `frontend/src/api/client.ts` | 修改（+52 行） | 运营 API 客户端 |
| `frontend/src/api/schema.d.ts` | 修改 | 由 OpenAPI 重新生成 |
| `frontend/src/app/App.tsx` | 修改（+6 行） | 三条运营路由 |
| `frontend/src/app/AppShell.tsx` | 修改（+17/-） | 「知识运营」导航与管理员门禁 |
| `frontend/package.json` / `package-lock.json` | 修改 | 新增 `echarts@6.1.0`（T303 图表，T306 未再动） |

### 1.3 测试基础设施与证据

| 文件/目录 | 状态 | 说明 |
| --- | --- | --- |
| `frontend/e2e/operations-seed.py`、`operations-overview.spec.ts` | 新增（T303） | 26 条总览用例 |
| `frontend/e2e/operations-qa-seed.py`、`operations-qa.spec.ts` | 新增（T304） | 19+1 条问答诊断用例 |
| `frontend/e2e/operations-assets-seed.py`、`operations-assets-page.spec.ts` | 新增（T305） | 20 条资产页用例 |
| `frontend/e2e/operations-integration-seed.py`、`operations-integration.spec.ts` | 新增（T306） | I1-I8 双 project |
| `frontend/playwright.operations.config.ts`、`playwright.operations-qa.config.ts`、`playwright.operations-assets.config.ts` | 新增（T303-T305），T306 按裁决整改 | 端口 8288/5299、8289/5300/8292/5302、8290/5301 |
| `frontend/playwright.operations-integration.config.ts` | 新增（T306） | 8291/5303 + 8293/5304 |
| `docs/reports/OBS-EVAL/P3/` | 新增 | T301-T306 证据、验收、交付与发布材料 |
| `docs/superpowers/plans/2026-11-21-mktkb-p3-operations-taskbook.md` | 新增 | P3 任务书 |
| `docs/superpowers/specs/2026-11-21-knowledge-operations-data-center-design.md` | 新增 | 设计说明 |
| `原型设计/P3原型/` | 新增 | 产品原型 |

### 1.4 非 P3 在途改动（保留，不纳入本候选提交）

`.claude/handoffs/_index.md`、`docs/reports/OBS-EVAL/P2/**` 的 P2 后续证据、`.tmp-r2-obs-baseline/`、`.tmp-t3review-isolated/`、`backend/requirements-ragas-eval.lock` 等。它们属于 P2 在途工作，提交拆分时排除。

### 1.5 建议提交拆分（供主人批准后执行；本窗口不提交）

```text
1) feat(operations): backend read-only operations API
   backend/src/mktkb/operations/
   backend/src/mktkb/main.py
   backend/tests/operations/

2) feat(operations-ui): operations overview / Q&A diagnosis / assets pages
   frontend/src/features/operations/
   frontend/src/api/client.ts
   frontend/src/api/schema.d.ts
   frontend/src/app/App.tsx
   frontend/src/app/AppShell.tsx
   frontend/package.json
   frontend/package-lock.json

3) test(operations-e2e): T303-T306 acceptance suites & Playwright configs
   frontend/e2e/operations-*.py
   frontend/e2e/operations-*.spec.ts
   frontend/playwright.operations*.config.ts

4) docs(p3): taskbook, design, evidence, delivery, release candidate, prototype
   docs/superpowers/plans/2026-11-21-mktkb-p3-operations-taskbook.md
   docs/superpowers/specs/2026-11-21-knowledge-operations-data-center-design.md
   docs/reports/OBS-EVAL/P3/
   原型设计/P3原型/
```

提交前建议逐组 `git status` 复核，确保 `.env`、`var/`、隔离库与临时目录不入库。

## 2. 变更说明（T301-T305 汇总）

| 任务 | 内容 | 验收记录 |
| --- | --- | --- |
| T301 | 基线与数据核对、独立复算口径、Span 映射、D5 冲突引用缺口上报 | `docs/reports/OBS-EVAL/P3/T301-data-audit.md`、`T301-isolated/T301-recomputation.md` |
| T302 | 只读运营查询与接口契约（18 项）、种子与后端测试 | `docs/reports/OBS-EVAL/P3/T302-evidence/T302-delivery.md` |
| T303 | 运营总览页（P1-P13）、26 条 Playwright | `docs/reports/OBS-EVAL/P3/T303-acceptance.md` |
| T304 | 问答诊断页（Q1-Q10）、19+1 条 Playwright、双栈 | `docs/reports/OBS-EVAL/P3/T304-acceptance.md` |
| T305 | 知识资产页（A1-A10）、20 条 Playwright、抽屉与失败导入 | `docs/reports/OBS-EVAL/P3/T305-acceptance.md` |
| T306 | 配置整改、全套回归、I1-I8 集成、两套复算、性能、启动/回退、候选材料 | 本文件与 `T306-delivery.md` |

三条页面：`/operations`（总览）、`/operations/requests`（问答诊断+评测页签）、`/operations/documents`（知识资产）。均为管理员只读；员工 403/门禁。

## 3. 启动与回退方式

### 3.1 启动

- 日常：双击 `一键启动.cmd` → 先 `--owner-live`；亲验 GO 失效时自动回退 `--offline`（不调真实模型、不伪造答案）。
- 仅真实：`启动-真实问答.cmd`（`--owner-live`）。
- 仅离线：`.venv\Scripts\python.exe -B tools\start_local.py --offline`。
- 安全隔离：先设 `MKTKB_DATA_DIR=<隔离目录>`，再运行；否则使用 `.env` 推导的 `var\`。
- 本任务实测：`--offline` + 隔离目录，8077/5673 起服成功、登录页可达、退出码 0、`var\` 零变化（`T306-delivery.md` §6.2）。

### 3.2 回退

- P2 参照：候选 `7556efd`、发布记录 `cb74457`。
- 已提交后回退：对 P3 各提交 `git revert <sha>`。
- 未提交时回退：经主人批准，丢弃 §1.1-1.3 工作区 P3 改动；保留 §1.4 非 P3 在途改动。
- 回退动作本窗口一律未执行。

## 4. 测试证据总表

| 层级 | 结果 | 证据 |
| --- | --- | --- |
| 开发自测 | **PASS** | 后端 operations 69/0/0、P2 最小回归 450/0/0、build 0、T303 26/0、T304 19/0/1skip、T305 20/0、T306 16/0；日志 `T306-evidence/logs/` |
| 独立验收 | **NOT-RUN**（待项目经理） | T301-T305 验收记录均为 PASS；T306 由项目经理按完成条件复核 |
| 真实环境验证 | **NOT-RUN**（须主人授权） | 未跑 `--owner-live`，未调真实模型/OCR/Ragas |

补充实查：

- 员工门禁：三页文案 + 六接口 403（I4 双 project）。
- 旧版引用只给元信息：superseded 仅名称/版本/时间，无 locator（T304 Q4 / I1）。
- 参数串联：T305 资产抽屉「查看关联问答」→ T304 requests 按 `document_id` 过滤 + 横幅（I3 双 project）。
- 指标复算：T301 13/8-1-1-1-1-1/10-13；集成 overview==明细（6/2/8/0）。
- 性能：两库三窗口五采样，中位 < 0.05 ms；查询计划无全表扫描；未建索引。
- Trace 关闭/未记录：关闭栈阶段区「Trace 已关闭」；主栈「本次未记录执行过程」。

## 5. 受控替身范围、环境与剩余限制

### 5.1 受控替身

- 所有 E2E 与后端运营测试使用隔离 SQLite + 受控种子；无真实模型、OCR、Ragas 调用。
- Trace 由受控 `TraceRecord` 写入；冲突/失败导入/评测 run 均为构造样本，界面标注受控/Mock 语境。
- 启动试跑使用 `--offline`：模型三键清空、OCR 禁用、provider 离线。

### 5.2 测过的环境

- Windows 11 + PowerShell 7；Python 3.12 仓库根 `.venv`；Node/Vite 现有依赖；Chromium desktop 1440×900 + mobile 390×844。
- 端口：8288/5299、8289/5300/8292/5302、8290/5301、8291/5303/8293/5304、8077/5673（试跑后全部释放）。
- 数据目录：`docs/reports/OBS-EVAL/P3/<T30x>-evidence/isolated-var`、`T306-evidence/isolated-var-launcher`；`var\` 未写。

### 5.3 剩余限制与待验证

1. I6「空窗口 assets 空态」与 T305 当前库存口径存在张力：空窗口仍列 4 份资料、引用 0；空态由无匹配筛选触发。待主人裁决是否改资产列表口径（见 §6 A）。
2. T301 D5：冲突消息持久引用 2 行 vs 口径 0，仍存在；属既有产品行为。
3. 性能只覆盖小样本与 SQL 等价形状，不含应用层聚合/HTTP 开销；真实规模待验证。
4. `--owner-live`、真实模型/OCR、真实部署、跨 OS/浏览器均 NOT-RUN。
5. 评测仅在受控 run 上验证列表/抽屉/holdout 扣留；真实评测执行链路未跑。
6. 启动器无 `--data-dir` 参数，安全隔离依赖 `MKTKB_DATA_DIR`；双击默认写 `var\`。
7. `perf_probe.py` 原引用缺失，本次为新建等价探针（见 §6 B）。

## 6. 上报事项与 T302 补充单建议

- **A 口径裁决**：资产列表“当前库存”与 I6“空窗口空态”冲突，建议维持 T305 口径并接受本次测法，或另立任务改口径。
- **B 文档缺口**：dispatch 引用的 T302 `perf_probe.py` 不存在，已新建 T306 版并标注。
- **C 既有 D5**：冲突持久引用 2 行，继续待决，本任务未改。
- **D 启动器**：建议增加显式 `--data-dir` 或在 `.cmd` 固定 `MKTKB_DATA_DIR`，避免双击写 `var\`。
- **T302 补充单建议**：暂不立单。触发阈值：单窗口完成量接近 400 行（20 页 × 20）或需要 30 天逐条对账；资料数超过约 200 份或需要按最新版本排序/精确筛选。届时再评估游标上限、`page_size`/导出与 `latest_version`、服务端名称搜索。

## 7. 发布条件对照（任务书 §4 四条）

1. **三个页面与查询可用、三场景过独立验收**：开发自测三条链路（I1/I2/I3）双 project PASS；T303/T304/T305 验收 PASS；独立验收待项目经理复核 → 材料齐备，状态“待独立验收”。
2. **汇总数字可从明细复算、异常有状态**：T301 逐项一致；集成 overview==明细（今日 6/6、7 天 8/8、空 0/0）；无 Trace/未记录/关闭/未知字段均有明确状态 → PASS（开发自测）。
3. **员工无法访问管理员数据、无 P2 回归**：六接口 403 + 三页门禁双 project PASS；P2 最小回归 450/0；历史引用/原件/P2 问答流程无回归 → PASS（开发自测）。
4. **候选、环境、替身、待验证、回退已记录**：本文件 §1/§5/§3 + `T306-delivery.md` → PASS。

发布决定权归主人；本窗口不提交、不部署。
