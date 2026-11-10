# T104 证据 01：修复前状态（ERR-07 产品侧异常分类）

- 分支 `p1/fix-retrieval`；修复前 HEAD `30729bd`（T104 交接单/索引 bookkeeping）；工作树仅本包允许路径。
- 修复前实现（`backend/src/mktkb/conversations/service.py@30729bd`）：
  - `_call_model` 的兜底分支 `except Exception -> ModelUnavailable(f"{type(exc).__name__}")`（旧 `:1437-1438`）：任何未被网关归类的异常都被包装成 provider 不可用。
  - `_answer` 只做 `_service_error(exc.code, _model_error_text(exc.code), exc.retryable, revision)`（旧 `:2113`、`:2248`）：没有“内部/未知”类别，模型路径之外的本地异常直接 500。
  - `_model_error_text`（旧 `:1714-1722`）五条短文案，不含 ERR-07 的“不是资料中没有答案 / 可否重试 / 不重复落库”三要素。
- 修复前 `error_code` 取值集合：`MODEL_NOT_CONFIGURED / MODEL_TIMEOUT / MODEL_UNAVAILABLE / MODEL_BUDGET_REFUSED / MODEL_OUTPUT_INVALID`（+ 网关子类 `MODEL_POST_SEND_AUTH_DENIED`），非 provider 异常无独立码。

## A. 修复前 b0 / badcase local run + gate

命令（仓库根，Windows PowerShell）：

```powershell
$env:PYTHONPATH="backend/src"; $env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli run --suite <suite> --mode local --out %TEMP%\t104-prefix\<suite>
.venv\Scripts\python.exe -B -m mktkb.evaluation.cli gate --run %TEMP%\t104-prefix\<suite>
```

| suite | run_id | status | gate |
| --- | --- | --- | --- |
| b0 | `b0-local-20261105T190107872966Z-359ed37c` | pass 29 / fail 3 / skipped_requires_ocr 8 | exit 3，hard `[]` |
| badcase | `badcase-local-20261105T190118167843Z-c1aad3e1` | pass 9 / fail 4 | exit 3，hard `[]` |

- 修复前失败集与 T103 收口时一致：b0 失败 `{Q25,Q26,Q31}`（本地语料既有 fail），badcase 失败 4 例均为既有状态。
- 逐例快照（`case_id/status/kind/failed check ids`）落 `%TEMP%\t104-prefix\{b0,badcase}-cases-before.json`，用于与本包修复后逐例比较。

## B. 修复前 regression 基线（引用前包）

- T103 证据 03 记录：`pass 3 / fail 4`，hard `['security_leak']`；RG001–RG003 pass，RG004–RG007 fail。
- 本包未改 `fixtures/evaluation/regression.jsonl`（RG005 已是 T104/ERR-07 种子，见证据 04）。
