# T207 A 路径独立收口复核

主人，**限定接收 T207 的如实报告收口，收口范围阻断 0；不认定质量达标、发布通过或 P2 全部完成。** H2 保持 aborted / 未达标，H2DIAG 保持拒收并已回退。经理可据此更新接收状态，按已授权范围本地提交后暂停；不进入 T208/T209/T900。

- 日期：2026-11-11；独立复核上下文为新的内置子代理，未沿用开发或经理的验收结论。
- 实际基线：`codex/p2-e2e`，`93a89ec92682260c186256a98521becb49f413c8`。本次 HEAD 未变、未 commit。
- 只写本报告及 `evidence/closeout-verify/`。未改源码、测试、契约、已有评分产物、账本、预算和 GO；未执行产品、ASGI、TestClient、E2E、真实模型/OCR 或浏览器操作。
- 主要实跑证据：自行编写的 `evidence/closeout-verify/independent_closeout_audit.py`，**退出码 0，223 条断言通过，网络尝试 0**。完整断言、输入 SHA256、运行身份和结果见 `audit-results.json`，控制台结果见 `audit-run.txt`。

## 1. 逐项结论

| 复核项 | 判定 | 独立核对结果 |
|---|---|---|
| 公开矩阵固定选例、无重复及失败保留 | PASS | 原公开 R1/R4/R2 全量分别离线重评分 52/3/2 例，完整逐题评分含 checks 与原 `R1-fixed/R4/R2-fixed` 逐值一致。固定取 R1 的 B0 40、N01–N07、C01–C04，R4 的 N08/C05/C06，R2 的 U01；55 个唯一公开 case，未逐题择优。Q25 `value_hit`、Q33 `source_hit` 失败均保留。 |
| 公开观测统计 | PASS（组合观测） | 独立按 ID 集合计算 B0 38/40、N 8/8、C 6/6；按评分属性计算 exact 24/24、OCR 7/8。exact/OCR 是 B0 子集，不新增分母。 |
| 原真实运行来源及身份 | PASS（产物溯源） | 核对公开 run 的 manifest、summary、原行、case 文件、存档分数。三者均显式 live、binding complete、trace identity bound、dataset 文件 hash 相符、实测 network available、mock_intercepted=0；run_id/config_hash/index_revision/real_calls 与所选矩阵行、存档一致。见下表。未将逐行 real_calls=0 当作无调用，未对 run 级出站按选中行重复求和。 |
| U 证据 | PASS（既有证据口径） | U01 为 R2 真实 smoke；U02–U10 为既有本地控制，合计 R1+L9 的 10/10。已有控制文件 exit_code=0，生成时间 `2026-11-11T07:17:40+00:00`，所引测试函数在当前源文件存在。真实 update_delete 行覆盖仍为 1/10、缺 9。未将旧控制称为本轮重新通过，未再次启动已知挂起的 U/ASGI 复跑。 |
| H2 原聚合与中止语义 | PASS（如实记录）；质量未通过 | 仓内 run 目录恰为三份聚合；独立核对 30 总数、评分完成 21=11 pass+10 fail、9 error/未完成，已开始 22、其中 1 出错、完全未开始 8；各分层求和一致。stop_code 为 product_service_error，错误 MODEL_OUTPUT_INVALID；release_ready/threshold_met/thresholds_approved 均 false。 |
| H2 安全边界与映射缺口 | PASS（报告边界）；安全未认证 | 原卡 hard_failures=0 仅为输出字段，cross_doc_security 五题全部未完成，V04/V06 未映射 block 保留，不能认证四类真实硬失败全零。未补旧运行诊断、未读真实题干/答案/逐题 trace。三聚合未含本次明确扫描的 case_id/question/reference_answer/expected_values/product_text/answer_text/turns_detail 明细键。此检查不等同对整个历史仓库作全面防泄漏认证。 |
| H2 原元数据保全 | PASS（字节完整性） | 仓外 gate/run_manifest/summary 三文件只计算 hash 与大小，不解析内容；分别 65,509 / 74,341 / 128,089 bytes，与 audit 记录全部一致。仓内三安全聚合的 hash 和大小亦一致。只确认备份完整性，不将旧 audit 的字段计数冒称为本次重新读取证明。 |
| 费用、预算和固定文件 | PASS（共享账本保守口径） | 调用拥有该会计规则的只读 read_ledger_snapshot 独立重算，与收口 verification 完全一致：774 reservation / 774 result，P2 6.784628、项目 21.8555725 元。固定三文件前后 hash 相同。本轮新增真实调用/预留 0。未核对供应商实账。 |
| H2DIAG 拒收后回退 | PASS（回退） | 已读独立拒收报告，不将其正常数值探针或同步测试等同包验收通过。三源码/测试及两契约分别 hash 等于 rollback-proof，且逐字节等于 HEAD 内容；全部源码/测试 diff 为空，runbook 无诊断承诺。拒收 patch 留作证据，不是有效代码。 |
| 报告授权和停止边界 | PASS | 最终报告与 PM §14 保留未达标、未完成复跑、未做全仓验证等限制；本轮不付费、不 push/合并/部署、不进入下一任务。报告开头/§5 当时处于“独立复核后更新”状态，允许经理仅据本结论补状态/提交标记，不改核心观测。 |

公开来源身份（实测调用数为原完整 run 的出站数）：

| 来源 | 选中/原重评分例数 | index_revision | config_hash | real_calls |
|---|---:|---:|---|---:|
| R1-fixed / p2-t207-r1-20261111-01 | 51/52 | 11 | `8bf2a7b738dbccc468f9f95418e575d45d65803bb35289a7594cc2f2ef38496b` | 117 |
| R4 / p2-t207-r4-20261111-01 | 3/3 | 5 | `8de2f3b01cd4ae3fac3e63c5754ffd4e65a0c567297b9a6790a62c2fe433cd94` | 10 |
| R2-fixed / p2-t207-r2-20261111-01 | 1/2 | 3 | `1370e34b4178c2cd162acb4260a101b96eca4cb7c1bb24a3722dea633b510c35` | 9 |

三个运行的 pipeline_version 标签均为 `d3ca88d2c515`，但不能据此消除不同实际执行时点、产品改动、索引和配置的差异。本结论是本地产物一致性和身份绑定复核，没有重新向供应商验证历史调用或完成同版本 baseline。

## 2. 会计核对

`run_result.attempts_*` 为全操作尝试，逐运行断言 `sum(attempts_by_operation)=attempts_reserved`；`by_operation/settled_cny` 为 answer 单侧，二者不可互换。

| 运行 | 全操作 reservation | chat 发送 | 全操作保守占用（元） | answer 单侧 settled（元） |
|---|---:|---:|---:|---:|
| R1 | 129 | 40 | 5.9473320 | 0.28944 |
| R2 | 10 | 1 | 0.0207119 | 0.020004 |
| R3 | 5 | 1 | 0.0015582 | 0.00116 |
| R4 | 13 | 0 | 0.0574594 | 0.056064 |
| H2 aborted | 70 | 21 | 0.1862082 | 0.1825 |
| T207 合计 | 227 | 63 | 6.2132697 | 不与全操作口径混算 |

与先前 P2 保守占用 0.5713583 相加为 6.784628。费用中心 answer_retrieval=0.634628、ocr=6.15；余额和容量结论只是当前冻结快照，GO 文件仍存在不表示暂停解除。

固定三文件 SHA256（本次审计前后相同）：

- 账本：`1648405845fd5e19b593e610b92f8505fdfd78a9e57079648dc14673576785d7`
- 预算：`79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e`
- GO：`3ed427f42ac2eeedff489505b94f730eadba1dc38f1b9adecf94d25750b02a7c`

## 3. 实际命令与证据固定

| 本次实际命令/操作 | 退出码与结果 |
|---|---|
| `.venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/closeout-verify/independent_closeout_audit.py`，cwd 为仓库根 | **0；223 条断言通过**。stdout 落 `audit-run.txt`，结构化证据落 `audit-results.json`。设置 MKTKB_NO_DOTENV=1、TEMP/TMP 到指定 visualizations/t207-closeout-review-temp；connect/connect_ex/create_connection 均拒绝，实际尝试 0。 |
| `git diff --exit-code -- backend/src backend/tests frontend/src frontend/tests docs/evaluation/p2-dataset-v0_1.md docs/evaluation/p2-live-binding-v0_1.md` | **0；无输出、无差异**。另对五回退文件逐项执行 `git show <完整HEAD>:<path>` 与工作区 bytes 的 SHA256 比较，全部一致。 |
| `git rev-parse HEAD`、`git branch --show-current` | **0；与审计基线及分支一致**，审计后 HEAD 相同。 |
| 被审文件 SHA256 快照生成 | **0**；`review-source-hashes.json` 固定最终报告、PM §14 所在文件、runbook、生成器、组合矩阵、verification、H2 audit、审计脚本/结果/日志及拒收/回退证明。其时间点在经理最终状态更新之前。 |
| `git diff --check -- docs/reports/OBS-EVAL/P2/T207/evidence/closeout-verify` | **0**。新增未跟踪文本另作 UTF-8/末尾换行检查，见 `final-artifact-check.json`。 |

关键交付 SHA256：矩阵 `b020ddef71a349432c193877017a9593046f89ed352312dfdb540084f4a1a485`；verification `4a1b1ad9e46f52f861802e381f92e0d5ea4beff66db6487b8c4ce182dac43355`；H2 artifact audit `86d588ba55a81c34123bfaf6e865485ab1012b84e1bc2c1a2d3202e1a84b6aec`；被审最终报告 `55563810556609999a901f3e1c6f3bc652a495e09654e98059b13ca15cfeaf13`。允许后续状态更新的前后版本可据快照比对，其他核心数据不应随接收结论更改。

本次没有重新执行经理的 16 passed/5 deselected 同步子集，也没有重跑此前 H2DIAG 的 21 passed/6 deselected；这两者只作为各自报告中的执行记录，不记为本次通过的测试数。本次独立完成的是公开产物离线重评分和223条同步证据断言。

## 4. 必须保留的剩余问题

1. H2 11/30、10 fail、9 error/未完成，版本来源映射缺口、模型输出异常、未完成安全层与 hard_failures 分类证明均未闭环；不签质量或安全通过。`11+9=20<24` 仅是现行评分的算术上限，映射缺口使其不能成为修复后能力预测。
2. Q25/Q33 仍失败；N/C any-of 文案未自动评分，R4 禁用版本来源映射和语料覆盖存在已披露盲区。组合 N/C pass 不等同所有文案/版本判据全部通过。
3. U 控制的旧记录仅能证明其记录时点结果；本轮复跑未完成。完整回归/E2E/真实模型修复验证与同版本 baseline 均未做，不能用本次产物审计替代。
4. H2DIAG 安全反例导致拒收；本轮仅回退，不构成已修复。仓外原元数据按原授权保存、不提交；本次未扩大到读取其题号或扫描全部历史仓库。
5. T208/T209/T900 未执行；本次是 T207 报告如实收口的独立复核。经理完成授权的本地提交及交接后应暂停，不因本报告自动恢复付费或后续任务。
