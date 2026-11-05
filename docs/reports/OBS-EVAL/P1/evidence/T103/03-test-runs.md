# T103 证据 03：测试与 local run/gate 结果

环境：Windows，仓库根 `D:\GPT项目\市场部AI知识库`，Python `.venv\Scripts\python.exe`（3.12.7）。
除特别注明外均带 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；零真实模型/embedding/rerank/OCR 调用。

| # | 范围 | 命令（cwd=`backend`） | 结果 |
| --- | --- | --- | --- |
| 1 | 本包 | `..\.venv\Scripts\python.exe -B -m pytest tests/unit/test_p1_t103_record_fallback.py tests/integration/test_p1_t103_record_fallback_http.py -q` | **6 passed**，3.31s |
| 2 | `tests/unit` | `..\.venv\Scripts\python.exe -B -m pytest tests/unit -q` | **306 passed**，7.36s，0 failed/0 error |
| 3 | `tests/integration` | `..\.venv\Scripts\python.exe -B -m pytest tests/integration -q` | **353 passed**，281.12s，0 failed/0 error（无 flake） |
| 4 | `tests/observability` | `..\.venv\Scripts\python.exe -B -m pytest tests/observability -q` | **255 passed**，49.98s；trace path/outcome/必需 span 未破坏 |
| 5 | 全量 | `..\.venv\Scripts\python.exe -B -m pytest tests -q` | **1640 passed**，403.66s，0 failed/0 error |

- 全量前 `FreePhysicalMemory=2.61 GB`（≥2GB 门槛）；运行期间未 OOM。
- 未使用 `skip`/`xfail`/删断言/放宽；新增测试无真实 provider 构造，未读 `.env`/Holdout。
- `tests/integration/test_chat.py::test_g08_short_budget_cancels_inflight_model_call` 本轮未失败，无需隔离复跑。

## 前端

| 命令（cwd=`frontend`） | 结果 |
| --- | --- |
| `npm run typecheck` | exit 0（`tsc --noEmit`） |
| `npm run build` | exit 0；typecheck + `vite build`，40 modules，276ms |

## b0 / badcase / regression local 前后对照（命令见证据 01）

| suite | 修复前 run_id | 修复后 run_id | 修复前 status | 修复后 status | 修复后 gate | 逐例差异 |
| --- | --- | --- | --- | --- | --- | --- |
| b0 | `...175315514116Z-dd93c223` | `...180223246377Z-47c89d6a` | pass 29 / fail 3 / skipped 8 | **pass 29 / fail 3 / skipped 8** | exit 3，hard `[]` | **0**（Q25/Q26/Q31 与 Q34/Q35/Q37/Q38 状态逐例一致） |
| badcase | `...175320230801Z-2ea88b3d` | `...180228639740Z-38c547e5` | pass 9 / fail 4 | **pass 9 / fail 4** | exit 3，hard `[]` | **0** |
| regression | `...175344426127Z-52857f27` | `...180135073913Z-056b76aa` | pass 3 / fail 4 | **pass 4 / fail 3** | exit 1，hard `['security_leak']` | RG004 fail→pass；RG001–RG003/RG005–RG007 不变 |

- b0/badcase 逐例比较口径：`(status, outcome.kind, failed check ids)`；两套件 `case_diffs=0`，hard failures 无新增。
- regression 关键 checks：RG004 `kind_correct`/`refusal_expected` 转 pass，`forbidden_values` 仍检查「该历史消息未保存候选明细」；RG005–RG007 失败 check 集合与修复前逐条相同；gate 未新增 hard failure 名称（仍只有 RG006 `security_leak`）。
- b0 的 Q25/Q26 本地 fail 是 enterprise 语料无 D03/D05 的既有 value/source fail，不是本包回落的记录路目标行为；Q31 既有 local fail 未动；Q34/Q35/Q37/Q38 在 b0 仍 `skipped_requires_ocr`（本地 OCR 不可用），其非 OCR 检索分支由证据 02 的产品离线探针（var 库已有 D07–D09 文本）验证。
