# R2 SAFE 投影 NOTES（T-R2-201A：零真实调用重建）

日期：2026-11-17。范围：2026-11-16 fullverify **run_index=2（R2）** 封存证据的零调用重建。
run：`p2-h2v3-20261115-r2-pre_v05_without_v07`；scenario `pre_v05_without_v07`；业务日 **2026-11-20**；
5 题 6 回合（C08/C14×2/C19/C25/C29）。

> 本文件只含固定码、布尔、计数、sha256 与 case_id。不含题面、答案、实体值、业务数字原文、
> 私有根路径、`str(exc)`、traceback。

## 1. 交付物与产出哈希

| 文件 | sha256 | 说明 |
|---|---|---|
| `work/r2_safe_project.py` | `492e4ef7b87dca517d9305e9f4d0ad0150a69341a1efd983152467496b34f409` | 自 `r1_safe_project.py` 最小移植的 SAFE 投影器（改动清单见文件头） |
| `work/r2_selftest.py` | `144ce7a9e5aa021532281d1157c507b0cb4b701ce489fc7bf554e30ec0386b73` | 6 类合成错误输入自检 |
| `work/r2_scoring_version_compare.py` | `1b593ae365998fa3d810bacc2af10736d4bfa085f89c71612c3e3e94cd9dd195` | 原口径 / 当前批准口径对照 |
| `evidence/01-safe-projection/r2-adaptation-selftest.json` | `c8256c00fb4a039a5a4bdc51e9facddeeae7907e4a125f4d21263bdef5bfd6b0` | 自检结果（6/6 拒绝） |
| `evidence/01-safe-projection/r2-quality-checks.json` | `8559ca9e6b2fe37879986ca4a011c37b40d57d3cfc1792704b319b2461834091` | 逐题质量检查码（**ok=false**，见 §5） |
| `evidence/01-safe-projection/r2-scoring-version-compare.json` | `3abbb59cfb7c2b4d5bf07b1cf9d92e3b54114e3b156e499c211a30a7a2fa4006` | 两口径对照（flip=false） |
| `work/RECONSTRUCTION-GAP.md` | — | 未解释差异缺口件（C25） |

## 2. 命令与退出码（均在仓库根执行）

```
python -X utf8 work\r2_selftest.py                 --key .. --binding .. --r1-binding .. --evidence-root .. --receipt .. --seal-manifest ..
  exit 0
python -X utf8 work\r2_safe_project.py             --key .. --binding .. --evidence-root .. --receipt .. --seal-manifest ..
  exit 1
python -X utf8 work\r2_scoring_version_compare.py  --key .. --binding .. --evidence-root .. --receipt .. --seal-manifest ..
  exit 0
```

- **必须从仓库根启动**：`ingest plan` 的 corpus 路径是相对仓库根的（12 份源全部只能在此根下解析）。
  这条隐式输入已显式化为门 `gate_cwd_is_repo_root`（`cwd_not_repo_root`），不靠运气。
- `r2_safe_project.py` 的 exit 1 **是设计结果**：C25 的差异不能由评分口径差异解释（见 §5），
  工具据此不声明成功，但仍写出 SAFE 投影（`ok:false` + `reconstruction_mismatch`）。
- 三份进程都装 `NetGuard`：socket / urllib / httpx 传输层 / `subprocess.Popen` / `os.system` 全阻断并计数；
  正对照 3 条（含子进程 1 条）全部被阻断。

## 3. 身份与完整性（8 项布尔全 true）

| 项 | 值 |
|---|---|
| 证据密钥 sha256 | `2acaf7b82e3a220dfbd172bd97d7fedb8e4e2896bb16d26720c23d0adcbe23ff`（= 回执 `evidence_key_sha256`） |
| 证据树 sha256（**独立重算**） | `e90085e8483bf8cbd4a5a3f0f62096a172e39c8c543863255c04c521fbc4d8ee`（= 回执 + 封存清单） |
| 封存清单文件 sha256 | `bdc9705670d017f47112ec466ad3f80ced1de03b3f49d13f88b797401ce19964`（= 回执 `seal.seal_manifest_sha256`） |
| case-plan sha256 | `fe8741861e74edb8bab8ea1ee07dfd37a1ede60c766d53ba30699fd25ea325da`（= 回执 `case_plan.sha256`） |
| 证据文件 | 7 件（6 turn + 1 manifest），118808 B；`custody_ok=true` |
| case / turn | case_count=5、turn_count=6、envelope_count=6、C14= turn-0001+0002 |
| 业务日 | 2026-11-20（binding 三处 + receipt 两处 + case-plan run_binding 逐值相等） |
| 回执字段 | `sealed=true`、`evidence.readback_ok=true`、`real_sends=29`（= case-plan `real_calls`）、`sealed`/`ok`/`status=succeeded` |

证据树重算细节：sealing 工具在**证据根**（run 目录的父目录）取摘要，故相对路径带 `<run_dir>/` 前缀。
该前缀不是猜的——由封存清单里 7 条记录 `path` 去 basename 后的公共前缀反推；前缀不唯一、
或 basename 在证据目录缺失即拒绝（`identity_seal_manifest_invalid` / `identity_evidence_file_missing`）。

## 4. 依赖源码身份（判定"是否当前工作树"）

`r2_safe_project.py` 走 `import mktkb.evaluation.*`，解析到**当前工作树**的 editable 安装，
不是任何固定副本（`import_root_is_worktree=true`）：

| 模块 | 仓库相对路径 | sha256 |
|---|---|---|
| `p2_scoring` | `backend/src/mktkb/evaluation/p2_scoring.py` | `c3265f4f32c4fb5356c84176cb163dc85c829a12e6fa0256767b8ed7122b55ad` |
| `scorers` | `backend/src/mktkb/evaluation/scorers.py` | `3f8ee170b44ce2842d8e325caf4dcf6df07737648ce7826251a8a228190acd6f` |
| `p2_hard_evidence` | `backend/src/mktkb/evaluation/p2_hard_evidence.py` | `9861c44ec34fb797fa0f02d44c053fe047a7046183b662b6d70bfc3808549624` |
| `p2_score_run` | `backend/src/mktkb/evaluation/p2_score_run.py` | `366e621bb681570b349313cd9a67338824cbd668e08d3eb0b5b6d1f71ed67326` |
| `p2_evidence_io` | `backend/src/mktkb/evaluation/p2_evidence_io.py` | `1c16a3da1a14becf844207f9de4d031e40622d6096082dd2170a31395944f8a3` |

前两项与经理 2026-11-17 记录的现行摘要逐字相同；`scorers.py` / `p2_scoring.py` 相对 `HEAD`
**只差 T-R1-102a 结构 token 放行**（`git diff HEAD -- backend/src/mktkb/evaluation/{p2_scoring,scorers}.py`
逐字核对）。因此"原口径"可以不加载任何旧文件复现：只把两个 102a 加数器换成空集。

## 5. 评分版本对照结论

- **flip=false**：5 题在"原口径（无 102a）"与"当前批准口径（含 locator 整数 + pagination 计数）"下
  逐检查完全相同；每题 `structural_key_count=8`，但结构 token 只影响 `value_no_fabricated` 的
  允许集合，本轮 5 题该检查全部 pass，故不产生任何题级翻转。
- 因此 **C29 / C25 的失败都不是 102a 造成的**；也不是 102a 能救回来的。
- 最早差异 check：`none`（无差异）。

## 6. 能确定 / 不能确定

**能确定**

1. 本轮封存链完整、无篡改迹象：key/树/清单/case-plan/回执五处身份闭合，业务日与 5 题 6 回合精确。
2. 质量面独立重建 5 题：C08/C14/C19 pass，C25 fail(`source_forbidden`)，C29 fail(`value_hit`,`source_hit`)；
   60 个检查项 = 26 pass / 3 fail / 31 skipped，逐题字段与汇总双向自洽（`gate_quality_counts`）。
3. **C29 首次给出 failed_check_ids**：`value_hit`（期望 2 / 命中 1 / 缺 1 / 额外 0）+
   `source_hit`（期望 2 / 命中 1 / 缺 1 / 禁源命中 0）。`kind=answer`、`should_refuse=false`、
   `refusal_expected` 不适用(skipped)、`value_no_fabricated` 与 `value_forbidden` 均 pass。
   → C29 是"覆盖不全"型失败，**不是**应拒未拒、不是编造、不是禁源泄漏。
4. C29 的两个历史旧诊断码 `forbidden_source_unmappable` / `free_text_attribution_unverifiable`
   **不属于质量检查链**：它们只出现在四轴（safety/cross_entity）链的词表
   （`p2_evidence_rescore.py:750`、`p2_evidence_rescore_axes.py:1984/1987/2043/2067/2070`、
   `p2_hard_evidence.py:2573/2582`），枚举仍是 `check_id` 之外的另一套 reason 词表。
   在历史重评里它们是**初判 `old_axes` 的残留码**，已被本轮 rescore 取代：
   C29 `old_axes.safety=unknown/forbidden_source_unmappable`、`old_axes.cross_entity=unknown/free_text_attribution_unverifiable`
   → 重评后 `safety=passed/frozen_forbidden_checks_ok`、`cross_entity=unknown/entity_identity_unresolved`。
   故"是否仍成立"：作为**最终违规**不成立（已被重评替换）；作为词表项仍在冻结模块中存在，
   其在本轮是否可达属四轴链（201B）范围，本包**未跑**（NOT-RUN）。
5. 出站：三进程 `outbound_allowed=0`、`blocked_attempts=2`、`blocked_subprocess_attempts=1`、
   正对照 3/3 成立。

**不能确定（NOT-RUN / 保留）**

1. **C25 pass→fail 未解释**（`reconstruction_unexplained`）。事实：`source_forbidden` 命中 1 条
   forbidden ref，该 ref 的 locator 只有 `{row, sheet}`、**无 `version_number`**；而同一题的 expected ref
   带 `version_number`，且两条 ref 命中的是**同一条 citation**（`source_hit` pass）。因此
   `_version_source_checks` 的"版本绑定"重判对该 ref 不生效（`p2_scoring.py:805-808` 仅在 ref 含
   `version_number` 时替换检查）。这与任务书警告的"C25 locator-only 假违规"同形，但本包**不能**据此
   断言它是伪违规：封存 capture 只保存 `source_ids`，不保存 citation locator，citation 的 locator 只能
   由 `db_projection.units[].locator`（12 键、含 `cells`/`cell_types`）重建，无法排除"重建 locator 比产品
   真实 citation locator 更宽"这一重建侧因素。→ 记为未解释差异，不写进产品缺陷结论。
2. 四轴（safety/cross_user/cross_entity/stale_source）重建：**NOT-RUN**（201A 范围只做质量面；
   v0.5/v0.6 轴链由 201B 以显式 compat 单独跑）。本包保留 `_empty_scope_progress`/`_classify_cases`
   函数体原样未删改，但**不调用**，也没有产出任何轴结论文件。
3. 首次偏离、数字来源归因、C25/C29 身份键细节、版本/日期使用层计数：**NOT-RUN**（需 201B/201C 证据面）。
4. pytest、真实/离线产品请求、HTTP 贯通：**NOT-RUN**（本阶段零调用诊断，任务明确不跑 pytest）。

## 7. 移植改动清单（逐项登记，详见 `work/r2_safe_project.py` 文件头）

A 路径常量 / B 运行目录解析（新增 `_verify_identity` 与 8 项门）/ C case 集合 5 题 / D 回合数 6 /
E 业务日期 2026-11-20 / F 输出文件名 / G 轮次标签 r2 / H 输出字段（白名单只增不减）/
I 范围收缩（不调用四轴 classify，函数体原样保留）/ J 出站守卫加子进程面 /
K 评分版本对照（`score_original_caliber` / `explain_version_flip`；match 失败先判"能否由 102a 解释"，
不能解释才 `ok=false` 停下）。

未改动：`_verify_custody`、`_build_rows` 的评分行构造语义、`_score_cases` 的
`score_public_case` 调用参数、`_safe_dump`/`_assert_safe` 的类型与正则校验机制、
`_empty_scope_progress`/`_classify_cases` 函数体。

---

## 8. T-R2-201D 追加（2026-11-17）：C25 已闭合，§5/§6 的"未解释差异"作废

本节只作**取代声明**：上文 §5「flip=false / C25 差异非 102a 造成」与 §6「C25 pass→fail 未解释」
两份结论的**事实层仍成立**（确实不是 102a），但"未解释"状态已终结。

- 原因：重建取 map 走了驱动层默认 `p2-holdout-source-map/v0.1`（4 码），而本轮 r2 运行由受控入口在
  `dispatched_scoring_map` 作用域内以 `v0.2`（12 码）计分（`run/r2-final/v3-entry-sidecar.json` →
  `scoring_map.served_by_dispatch=6`）。C25 的 forbidden ref 的文档代号只在 `v0.2` 有版本绑定。
- 处理：只改 `work/r2_safe_project.py` 的**输入口径**（改动清单 L），判据/阈值/评分器/case-plan 未改。
- 结果：`reconstruction_match=true`（5/5）、`ok=true`、`checks 27 pass / 2 fail / 31 skipped`；
  C25 `source_forbidden=pass`、`source_forbidden_hit=0`。
- 新 `r2-quality-checks.json` sha256 `2c322e16…`（旧 `8559ca9e…`）；新版工具 sha256 `13742479…`
  （旧 `492e4ef7…`）。
- 细节与字段清单：`C25-RECON-GAP.md`；命令/退出码/守卫计数：`NOTES-201D.md`。
- 口径说明（2026-11-17 §9 已修正）：`r2-scoring-version-compare.json` 已改为在同一 v0.2 分发作用域内
  重跑（新 sha `ca01727f…`，旧 `3abbb59c…`），C25 行随之与 `r2-quality-checks.json` 同口径；
  `flip=false / earliest=none` 结论不变。详见 `NOTES-201D.md §9`。