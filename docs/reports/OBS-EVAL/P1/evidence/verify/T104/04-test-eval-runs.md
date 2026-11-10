# T104 独立验收证据：测试复跑、评测对照与范围

环境：Windows；`.venv\Scripts\python.exe` 3.12.7；cwd=项目根；每条 pytest 前 `MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；命令含 `-B -p no:cacheprovider --basetemp backend\.pytest-tmp\<label>`；零真实模型/embedding/rerank/OCR。

## A. pytest 复跑

| 范围 | 结果 |
| --- | --- |
| `backend/tests/unit/test_p1_t104_error_classification.py` + `backend/tests/integration/test_p1_t104_error_classification_http.py` | **38 passed**（6.19s） |
| `backend/tests/unit` | **335 passed**（6.78s） |
| `backend/tests/observability` | **255 passed**（17.63s） |
| `backend/tests/integration` | **361 passed / 1 failed**（270.13s） |
| 全量 `backend/tests` | **1678 passed / 0 failed / 0 error**（403.90s） |

- `tests/integration` 唯一失败：`test_chat.py::test_g08_short_budget_cancels_inflight_model_call`，断言 `len(facts["calls"]) == 1` 实得 0（1.2s 总预算下的时序 flake；失败与通过两次断言点均为 `elapsed < 1.0 / MODEL_TIMEOUT` 时序，不涉及 error_code 分类）。按 §11A 隔离复跑 1 次：**1 passed（1.42s）**；随后全量复跑同用例通过。
- 全量 1678 与 report 一致；本包 38、unit 335、observability 255、integration 361/1 均与 report 逐项一致。

## B. b0 / badcase local run + gate（本机复跑）

命令：

```powershell
$env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"; $env:PYTHONPATH="backend/src"
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite <b0|badcase> --mode local --out "$env:TEMP\t104-verify\<suite>"
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run "$env:TEMP\t104-verify\<suite>"
```

| suite | 本次 run_id | status | gate | 对 P0 基线逐例 diff |
| --- | --- | --- | --- | --- |
| b0 | `b0-local-20261105T195011354683Z-3631a178` | pass 29 / fail 3 / skipped 8 | exit 3；hard `[]`；scored 32/32 | 对 `var/eval/runs/p0-b0`：`case_diffs=0`，`ids_equal=True` |
| badcase | `badcase-local-20261105T195021438537Z-c3956baa` | pass 9 / fail 4 | exit 3；hard `[]`；scored 13/13 | 对 `var/eval/runs/p0-badcase`：`case_diffs=0`，`ids_equal=True` |

逐例比较口径：`(case_id, status, outcome.kind, outcome.reason, failed check ids, path)`。基线失败集亦一致：b0 `{Q25,Q26,Q31}`，badcase `{N05,N06,N09,N11}`。

## C. 开发前后对照产物交叉核对（只作交叉核对，不作 PASS 证据）

`%TEMP%\t104-prefix` 与 `%TEMP%\t104-post` 仍存在；直接读其 `run_manifest.json` / `cases.jsonl` / `gate.json`：

- run_id 与 report/evidence 01 一致：b0 `...359ed37c` → `...ede10da1`；badcase `...c1aad3e1` → `...018e3089`。
- 原始 `cases.jsonl` 逐例比较：b0 `case_diffs=0`、badcase `case_diffs=0`；前后 gate 均 exit 3、`hard=[]`。
- regression（未改文件）：`%TEMP%\t104-post\regression` 为 pass 4 / fail 3、gate exit 1、hard `['security_leak']`；RG005 `kind=answer`，失败 checks `kind_correct,refusal_expected`，与 report §3/§4 一致；`git diff e7ee804^ e7ee804 -- fixtures/evaluation/regression.jsonl` 为空。

## D. 范围、静态检查与非阻塞残余

- `git show --stat e7ee804`：9 文件 = report.md、`service.py`、2 个新测试、`test_conversations.py`、4 份证据；均在 handoff §4 允许路径；`git diff e7ee804^ e7ee804 -- backend/src` 仅 `conversations/service.py`。
- `git diff` 对 `backend/src/mktkb/providers/`、`conversations/schemas.py`、`frontend/`、`fixtures/evaluation/regression.jsonl`、`docs/evaluation/gate_v0_1.json`、b0/badcase 数据均为空；`git status --short` 空。
- `git show e7ee804` 无 `pytest.mark.skip/xfail/skipif` 新增；新测试只使用 `EvidenceEchoGateway`/自造 fake；评测 `runner.py:314-318` 强制 `provider_mode="offline"`。
- 非阻塞残余（详见 01 §非阻塞残余）：
  1. `budgeted.py:283/:293` 的本地输入/单请求上限仍抛 `ModelUnavailable`；`deepseek.py:146-147` 把任意非 200（含 401/403）映射为 `ModelUnavailable` 且 retryable=True。网关按 handoff 只读，T104 未改；部分配置/鉴权原因仍会显示 provider 不可用。
  2. 内部兜底仅覆盖两处模型调用/校验窗口；`_answer` 更早的意图/取证/排序异常仍为 HTTP 500，不归 `QA_INTERNAL_ERROR`。
  3. `frontend/src/features/chat/MessageCard.tsx:64` 历史消息重试徽标仍按 `error_code !== 'MODEL_OUTPUT_INVALID'` 推导；新增 `QA_INTERNAL_ERROR` 历史消息会显示重试按钮（实时响应用 `live.retryable` 正确）。report §4 已披露，留 T106。
  4. `MODEL_BUDGET_REFUSED` 文案同时含“本次未发送请求”与统一句“这是服务调用失败”；按产品级“问答服务调用失败”解读成立，重试建议明确“重试不会自行恢复”，不构成可重试性误导。
  5. report §3 写“sha 见交付回复”而未内嵌 SHA；commit 本身可核为 `e7ee804deea5ab6b300690d6212e6bf5c4a8c0d5`。
  6. 未注册码 + `retryable=False`（`_VendorSpecific`/基类 `MODEL_ERROR`）走 `_MODEL_ERROR_FALLBACK`，文案固定“可稍后重新提问”，与 `retryable=False` 不自洽（`service.py:1786`、`:1789-1794`）；当前生产无该码路径，P2，见 `03-probe-results.md` §E。
