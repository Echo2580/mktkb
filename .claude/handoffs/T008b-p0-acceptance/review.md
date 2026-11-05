# T008b 独立验收（对象 `2f7b174`）

- 日期：2026-11-05；分支 `p0/obs-eval`；交付 commit `2f7b174`（父 `5152298`，纯簿记）。
- 当前 HEAD 为 `a9b474a`（仅 T008b verify prompt + index 簿记），不属于本包交付；工作树干净。
- **总判定：PASS**。§5.1–§5.6 全 PASS；无 MEDIUM/HIGH；LOW 5 项非阻断。
- 环境：Windows PowerShell；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；`.\.venv\Scripts\python.exe -B`；
  basetemp 全在 `%TEMP%`；串行执行；零真实模型/OCR/embedding/rerank 调用；未读 `.env`。

## 1. §5 逐条判定

| 条目 | 判定 | 命令 / 证据 |
| --- | --- | --- |
| §5.1 七条齐备且非空转 | **PASS** | 7 个函数 `test_p0_acceptance.py:181,213,259,299,379,497,524`；`pytest backend/tests/evaluation/test_p0_acceptance.py -q` → **7 passed**（7.19s，exit 0）。M1→#1/#2 红、M2→#6 红（见 §2）。 |
| §5.2 golden 可信 | **PASS** | `golden/chat_response.json:2-26` 记录 `captured_from_commit=5152298`、采集命令、6 项归一化清单；测试只读（`test_p0_acceptance.py:113-114,183`），并在 `:186-188` 断言 `_meta` 与 `NORMALISED_FIELDS`/`ASSERTED_NOT_RECORDED` 逐字一致；`:203-205` 同应用二次提问仍相等。sha256 `b86484dc…8e52`。 |
| §5.3 p0-report 完整 | **PASS** | `p0-report.md:10-16` 逐字免责句；`:18-72` 七条命令/结果；`:127-139` NOT-RUN 边界（live→4、真实 baseline、真实 OCR/embedding/rerank/模型、P1/P2）；`:141-146` 放行看 `release_allowed/blocked`；`:148-159` 证据锚（4 份 + 3 个交付物 sha256 全部实测一致）。 |
| §5.4 口径一致 | **PASS** | 独立重跑 b0：40 题 / scored 32 / OCR 8 / pass 29 fail 3（Q25/Q26/Q31）；badcase：13 / 13 / pass 9 fail 4（N05/N06/N09/N11）；badcase 无 gold = N10/N12/N13（检索分母 10/13）；`index_revision` 6/4、`pipeline_version` 735da1397044、dataset_sha256 均与 `p0-report.md:113-125` 一致。 |
| §5.5 硬约束 | **PASS** | 提交仅 9 个允许文件（`git show --name-status 2f7b174`）；conftest **14 行新增 / 0 删除**（`git diff --numstat`）；无业务/观测/评测实现、无依赖、无 `.env`、无 `--allow-holdout-details`；7 条测试全绿；既有 integration 包含在 1593 全量内全绿。 |
| §5.6 测试与回归 | **PASS** | 本文件 **7 passed**（7.19s）；`backend/tests/evaluation` **320 passed**（18.67s）；全量 `backend/tests` **1593 passed / 0 failed / 0 error**（399.10s / 6:39）；已知 flake 未命中。三次运行后 `git status --porcelain` 均为空。 |

## 2. 变异抽查（仓库外，已验证可失败）

- 隔离：`git worktree add --detach %TEMP%\t008b-wt-<id> 2f7b174`；主仓库 tracked 文件未改。
- **M1**（去 `X-Trace-ID`，`backend/src/mktkb/main.py:147`）：`-k "01 or 02"` → **2 failed**（#1/#2，exit 1；#2 KeyError `X-Trace-ID`）。还原后 sha256 `a0473f7c…7800` = 原值。
- **M2**（让 gate 不上报 `forbidden_source_citation`，`backend/src/mktkb/evaluation/gate.py:1229` 的 `if verdict == "matched":` 改 `False`）：`-k 06` → **1 failed**（exit 3≠1；hard_failures=[]），证明 #6 非空转。还原后 sha256 `c8f1c9d4…1ff5` = 原值。
- 两次还原后 worktree `git status` 为空；删除 worktree 后主仓库 `git status` 为空。
- 开发证据 01 §C/§D 记录的两个原文件 sha256 与本次实测一致，独立复核成立。

## 3. p0-report 与实际一致性

- CLI 独立冒烟：`run --suite b0 --mode local` exit 0；默认 `gate` **exit 3**（`quality=unknown`、`config_status=unapproved`、`hard_failures=[]`、`scored=32/32`）；`diff`/`export`/`baseline approve` 默认均 **exit 3**；`baseline list` 0 条；`--mode live` **exit 2**；`--allow-holdout-details` **exit 2**。与 `p0-report.md:74-93` 一致。
- #5 测试内审批配置独立产物：baseline `c0ce2856938f`；`diff.json` `release_allowed=True`、`blocked=None`、`empty=True`、30 个 metric delta、**16 855 B**；`report.md` **7 888 B**；`report.html` **13 451 B**（与 `p0-report.md:60-61` 字节数逐字一致）。该配置明确不是 T009 审批。
- p0-report 未出现“质量通过”；`live→4` 明确写为 NOT-RUN/GAP；真实 baseline 与阈值审批明确待 T009；默认门禁口径为 exit 3/`thresholds_unapproved`。符合 T008a 约束。
- 一处文档不一致：开发 `report.md:15` 写 p0-report “104 行”，实际 **171 行**（LOW-1，不影响报告内容）。

## 4. 提交边界

- `git show --name-status 2f7b174`：**9 文件**，全部在 handoff §2 允许路径；8 个 A + `conftest.py` 1 个 M。
- `git diff --numstat 5152298 2f7b174`：全部为新增；conftest `14/0`（只追加，无删除）；无 `backend/src`、`tools`、`docs/evaluation`、`docs/evidence`、`var`、依赖文件改动；无 `_index.md` 或其他包产物。
- parent `5152298` 仅 7 个 docs/簿记文件；验收后工作树无本包以外变更；未 commit/push。

## 5. 问题分级

| 级别 | 问题 | 影响 |
| --- | --- | --- |
| **LOW-1** | 开发 report 写 p0-report 104 行，实际 171 行 | 文档计数笔误；报告本身完整 |
| **LOW-2** | golden “两次独立采集字节相同”仅开发证据 01 §E 转录；采集脚本在 `%TEMP%`，未入库，无法独立重放 | 按提示词记 LOW，不判 FAIL；测试内二次提问稳定 + golden 哈希锚定 |
| **LOW-3** | #1 仅断言 `_meta.captured_from_commit`/`capture_command` 非空，未断言 commit==5152298 | golden 来源是文档级绑定；不影响归一化比对 |
| **LOW-4** | #7 业务问答阶段已还原 socket guard（报告已说明）；socket=0 仅覆盖评测全流程 | 业务阶段仍有 provider/Settings/.env/模型调用守卫；无证据表明真实调用 |
| **LOW-5** | p0-report 的 CLI 精确产物 SHA 来自证据 02；本次未按同一 run_id 重放 | 已独立复现机制、字节数与默认退出码；哈希不可跨 run 复现属正常 |

无 MEDIUM/HIGH；以上均非阻断。

## 6. 未覆盖

- 仅对 2/7 条做了仓库外变异（#1/#2、#6）；#3/#4/#5/#7 为静态审阅 + 实际全绿，未做定向破坏。
- golden 采集脚本未入库，无法独立重放“两次采集”；#1 的重跑稳定性是替代证据。
- p0-report §2 的精确 CLI 产物哈希未按原 run 重放（run_id/时间必然不同）；默认退出码、字节数、机制已复核。
- 未跑 live、真实 OCR/embedding/rerank/模型、P1/P2 质量；未审查 HTML 渲染效果（报告已列 NOT-RUN）。
- 仅验收本包；T001–T008a 的结论按任务前提接受，未重新验收。
- 验收证据：`docs/reports/OBS-EVAL/P0/evidence/verify/T008b/01-pytest-runs.txt`、`02-mutation-cli.txt`、`03-report-consistency.txt`（UTF-8 无 BOM，ASCII 文件名，共 3 份）。

## 7. 对 T009 的输入

- **p0-report 可引用性**：可作为 P0 机制与“当前不放行”结论的引用源；引用 `p0-report.md` §0/§1/§4/§5/§6，并同时引用其锚定的交付物/证据 sha256。**不可**把测试内审批配置当真实 baseline，也不可把 `release_allowed=True` 当作当前放行结论；当前默认状态仍是 exit 3、无 baseline、P0 不放行。
- **NOT-RUN 清单**：`mode=live`→exit 4 端到端（仅单测）；真实 baseline + 阈值审批（T009 人工门）；真实 OCR/embedding/rerank/模型；P1/P2 真实回答质量；HTML 渲染；`cross_entity`/`stale_bypass` 无 case 类（`not_applicable`）；#7 业务阶段 socket guard 未保持。
- **T009 anchors 应包含的字段**：提交 sha（`2f7b174` 及其 parent `5152298`）；`dataset_version`（b0 `b0:b0-2026-11-04:bd4f0f7ccc6e`、badcase `badcase:badcase-2026-11-04:e5f0662af3f2`）与 `dataset_sha256`；`index_revision` 6/4；`pipeline_version` `735da1397044`；`gate_version` `mktkb.gate.v0.1`；`run_id`、`baseline_id`、`gate_result_sha256`、`approval.json` 的 sha256；b0 40/32/8（pass 29/fail 3：Q25/Q26/Q31）与 badcase 13/13/0（pass 9/fail 4：N05/N06/N09/N11；检索分母 10/13，无 gold N10/N12/N13）；gate/baseline/diff/export 的**命令 + exit code**；`p0-report.md`、`test_p0_acceptance.py`、`golden/chat_response.json`、`conftest.py` 与验收证据的 sha256；以及“默认 gate=3/thresholds_unapproved、真实放行看 release_allowed/blocked”的原文锚。T009 必须用真实审批替换测试内配置，不得把 `%TEMP%` 演示件写入仓库。
