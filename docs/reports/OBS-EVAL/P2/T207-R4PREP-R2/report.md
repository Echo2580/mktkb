# P2-T207-R4PREP-R2 文档收口报告（零真实调用）

- 角色：R2 文档收口助手（全新上下文）。**零真实调用**、零网络、**零 commit**；未读 `.env`/H1/H2；
  只写 T207 三份文档与本目录；plan/case/ingest/GO JSON、源码/测试/fixtures/账本/预算/固定路径 GO 均未动。
- 现场 HEAD `05f785e`（执行阶段文档/产物提交，无代码改动）；代码基线仍 `1dca413`。

## 1 逐项改动（行号为改后行号）

| 项 | 位置 | 改动与依据 |
|---|---|---|
| **F-7** | `PM/T207-runbook.md:29, 31-35, 43, 46-49, 155` | §1.1 删掉写死的账本期望值，改为「**先跑、把 sha 与字节/行数记进本次 run 记录**，账本不预设断言值」+ 参考快照（**R1–R3 后 / R4 前**：`05b54d06…`、1,354,211 B / 1383 行 / 691 reserved / 691 result，注明 run 后必变、执行前重算）；预算 `79b21700…` 保留为**可断言不变量**；§1.4 明确唯一判据是「同一次执行内预检前后逐值相同」；§4 停止规则 1（:155）同步改为「预算 sha 变 / 同一执行内 §1.1 前后不一致」，避免与 §1.1 自相矛盾；原「预期读数 254/653/8.127376」标为 T207-FIX-A 历史数并补 R4 读数（18 请求 / `max_requests=760` / worst `0.144960` / 窗口 69）。依据：R4PREP-R1 review §4「F-7」+ 账本实测 |
| **F-8** | `runbook:144-150` | 保留 `summary.json` 的 `providers.live.request_ceiling.effective_max_request_cny`=0.04096 半句（另有 `authorization_max_request_cny`=0.5、`provider_single_request_cny.embedding`）；删除「`index_status.degraded` 为空」，改指 `run_manifest.ingest` 逐 source 的 `upload_status/job_state/publish_status` + 失败码。依据：`p2_runner.py:2291-2296` 只抄 5 键（documents/units/chunks/engine_version/provider_mode）；`degraded` 属 `QaIndexStatus`（`qa/service.py:272-284`）进程内字段，产物里 grep 无该词 |
| **F-9** | `runbook:374`、`report.md:167`、`cost:251-252` | `product_adapter.py:2137→2156`（`text=str(payload.get("text"))`），`ask_turn` 2003→**2020**；`scorers.py:632`（`text = outcome.text`）复核**未变**；历史段保留 `489aadd` 行号并标明现值 |
| **F-10** | `cost:226-227, 231-232` | §8.3 判定列余量统一为 **R4 后**基准：阶段 **13.3140796**（20.00−6.6859204）、项目 **18.2431351**（40.00−21.7568649），与请求列 891（1600−709）同基准；附换算一行 |
| **F-11** | `report.md:216` | 「§9.0 更正」→「§9 首部（HEAD 更正）」（全文无 §9.0 标题） |
| **F-12** | `report.md:227-228` | 新增归因：`PM/T207-PM-decisions-01.md` 的 §11/§12 是**经理侧追加**，非 R4PREP/R2 交付面（原文在 `T207-R4PREP-R1/report.md` §3，不在本包可改面） |
| **F-13** | `runbook:69, 369` | §3 下补 **`### 3.1 公开三 run（R3 → R2 → R1）`**（与 §3.2 同级）；「例外的判据见**下条**」→「见 **§9 下文**『重签口径』（不是相邻下一条 bullet）」 |

## 2 现场观察（只读，如实）

- 账本在被改前已出现 `run_id=p2-t207-r4-20261111-01` 的 13 条 reservation（06:41:36–06:41:41Z，`chat` 3 条 `failed`），
  仓库已有 `p2-t207-r4-20261111-01/` 与 `scoring/R4/` 产物 ⇒ **R4 已进入真实执行**，任何写死的「当前基线」都会立刻过期；
  本包因此把 §1.1 改成「记录当次实测」，只把 R1–R3 后读数留作**带标签的参考快照**。
- 预算 `79b21700…`、固定路径 GO `3ed427f4…`（H2）内容未变。

## 3 限制

- 零真实调用：未跑 `p2-run`/`p2-score`/任何 python 探针，行号与字段名均由**读代码 + 读既有产物**得到，未重放执行。
- 未改 `T207-R4PREP-R1/report.md`（F-12 原文所在处不在允许面），归因落在 `T207/report.md` §9.5。
