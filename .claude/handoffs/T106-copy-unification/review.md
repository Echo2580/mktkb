wb / cn:deepseek-v4.1-flash / reasoning_effort=max

# T106 独立验收 review（D3 文案统一 / ERR-05）

- 对象：`p1/fix-retrieval` @ `a42ee48`（父 `9933a7b`）；`git status --short` 空；未改交付物、未 commit/push/切分支。开发 `report.md` 只作线索，下列 PASS 均引用自跑输出、`git diff/show` 与源码。
- 结论：**FAIL**（1 项阻塞：用户可见文案仍把系统未检索/未识别说成资料缺失；其余 4 项 PASS；必跑项无 NOT-RUN）。
- 环境：`.venv\Scripts\python.exe` 3.12.7；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；零真实模型/embedding/rerank/OCR；未读 `.env`/Holdout。

## 复跑总览

| 范围 | 结果 |
| --- | --- |
| 本包 / unit / observability / integration | 8 / 343 / 255 / **381** passed（耗时 0.03 / 7.22 / 15.50 / 256.32s） |
| 全量 `backend/tests` | **1726 passed / 0 failed / 0 error**（382.99s；跑前 FreePhysicalMemory≈3.43GB） |
| b0 / badcase local+gate | pass29/fail3/skipped8、pass9/fail4；均 exit 3、hard `[]`；对 P0 基线逐例 **0/40、0/13** |
| regression vs `17c0e63` | 基线 pass4/fail3 hard `['security_leak']` → 当前 pass5/fail2 hard `[]`；仅 RG006 fail→pass |
| 前端 | typecheck exit 0；build exit 0（40 modules，367.02kB JS）；`02-chat` **7 passed**；acceptance-02 **5 passed**（expected=5/unexpected=0，含新增 C02） |

## 逐项

### 1. 映射唯一/完整、三要素、T104 保留 — FAIL

机械项通过：`02-probe.py` 自写探针 A–F 全 ok——`REQUIRED_REASONS=33` 全部登记；`REASON_ALIASES` 目标均存在且无别名链；`COPY` 53 条模板全局唯一；33 个 reason 均可渲染，按 copy key 去重后无重复（别名共享为显式登记）；AST 扫描三文件 28 个 reason 字面量全部登记且无一落 `UNCLASSIFIED`；T104 七类 + `MODEL_POST_SEND_AUTH_DENIED` 从父提交逐字重建比对 **8/8 相同**（`copy.py:544-609`；探针 C 段）。

但文案诚实性失败（handoff §1“诚实”、§5“不得编造原因”、§6-1“是否与资料无关”）：

- **`IDENTIFIER_NOT_RETRIEVABLE`（阻塞）** `copy.py:192-200`：同一串既写“资料中未找到标识“{identifier}”对应的记录”，又写“本次未按标识检索，不能据此判断该记录不存在”。调用点 `conversations/service.py:2071-2082`，`service.py:2072-2074` 明确产品检索层没有标识筛选键、内核未接手时失败关闭；即该路径**没有执行检索**，首句是无依据的资料侧结论，且与自身 `material_related=False` 矛盾。探针 H 段用 `parse_question("QF21 放在哪里？", lexicon with QF21)` 实测得到 `intent=None, identifier="QF21", clarification=None, fields=("位置",)`，确认会进入该分支。开发证据 `docs/.../T106/01-copy-mapping.md:73` 明说“保留……以满足验收可接受的缺失措辞”，handoff 无此豁免。探针 G 段 FAIL。
- **同类（应一并修，非阻塞）**：`ANAPHORA_NEW_CONTENT`（`copy.py:338-345`，`rag/answer.py:262-270`）同句既称“资料中未记录这项信息”又称“不是资料中没有答案”；`NO_INTENT`（`copy.py:201-208`，`service.py:2091-2097`）在 `plan.intent is None` 时仍以“资料中未找到与这个问题相符的内容”作唯一原因、无“不是资料中没有答案”（当前 `intent.py` 的 `intent=None` 路径均带澄清/标识，该分支可能已不可达，但仍属交接单要求覆盖的 reason）。探针 G 段共 3 FAIL。

### 2. 行为/结构不变 — PASS

`git diff 9933a7b..a42ee48 -- backend/src/mktkb/conversations/schemas.py` 为空。`schemas.py:96-108` 的 `MessageView` 字段集、`:118-130` 的 `AskResult` 12 字段与父提交逐字相同；`ResultKind` 集合/顺序、`error_code` 语义未改（service.py diff 仅文案来源与 `_model_error_text` 可选 `retryable`）。T101–T105 回归由全量 1726 passed、b0/badcase 逐例 0、regression 仅 RG006（T105 既有）覆盖，无回退。

### 3. 前端修正 — PASS（含 P2）

`npm run typecheck`、`npm run build` 均 exit 0。无候选 clarification（live 与 reload 历史）不再出现“该历史消息未保存候选明细”，统一为“这次回答没有提供可选项……请按上方提示补充……”（`MessageCard.tsx:148-153`）；徽标按 `resultBadgeLabel(kind, candidates.length)`，无候选→“需补充条件”、有候选→“需要确认”（`format.ts:162-187`、`MessageCard.tsx:92`）。`02-chat` 7 passed（21.6s）；acceptance runner（label `t106v`，`--evidence-root` 指向 `backend\.pytest-tmp\T106-verify\acceptance`）`PLAYWRIGHT EXIT 0`、expected=5/unexpected=0，C02 用例独立核为 passed。e2e 仅同步徽标取值（`02-chat.spec.ts:93`、`acceptance-02-kinds.spec.ts:110`）并新增 C02，无删断言/放宽。

P2：`INVALID_QUERY` 徽标统一为“服务调用失败”（`format.ts:167`），正文却是“这是查询条件问题”（`copy.py:174-182`）；历史分支还提示“请按错误码联系管理员处理”（`MessageCard.tsx:254-262`），与“请换个说法后重新提问”不一致。属边缘稳定码，未阻塞 ERR-05 主路径。

### 4. 回归/预算 — PASS

命令与数字见 `04-test-eval-runs.md`。本包/unit/obs/integration/全量各 1 次；全量前内存 3.43GB>2GB。b0 `b0-local-20261108T102648027740Z-6edd2268`、badcase `...6fde474a` 与 `var/eval/runs/p0-{b0,badcase}` 比较 `(status, outcome.kind, 每个 check status)` 全同（0/40、0/13），hard `[]` 无新增。regression 基线 `17c0e63`（`$TEMP\t106v-base` worktree，已 `remove --force`+`prune`）→ 当前仅 RG006 fail→pass；RG001–RG005/RG007 失败集不变；gate 由 `['security_leak']` 收缩为 `[]`，无新增 hard 名。无 skip/xfail/删断言/新依赖。

### 5. 合规/形式 — PASS

`git diff --name-only 9933a7b..a42ee48` 14 文件全在 handoff §4 允许路径；`schemas.py`/`intent.py`/`fixtures/evaluation/*`/`docs/evaluation/gate_v0_1.json`/`var/**` 无 diff；`pyproject`/lock/`package.json` 无 diff。`report.md` 77 行五段；`docs/reports/OBS-EVAL/P1/evidence/T106/` 4 份；`git log --oneline 9933a7b..a42ee48` 仅 `a42ee48` 1 个 commit。P3：`report.md:34` 写“RG001–RG006 状态不变、RG006 PASS”，与 `:51` 及实测“RG006 fail→pass”矛盾，应为 RG001–RG005 不变、RG006 PASS。

## 残余 / NOT-RUN

- 阻塞项：`IDENTIFIER_NOT_RETRIEVABLE` 文案自相矛盾；建议改为不含“资料中未找到”的无检索表述（如“本次未按标识检索，不能判断……”），并补对应单测。NO_INTENT/ANAPHORA 同类文案建议一并修（NO_INTENT 当前可能不可达，ANAPHORA 可达）。
- P2：`INVALID_QUERY` 徽标/正文/历史提示不一致；历史 clarification 有候选但未持久化时只能显示“需补充条件”（中性但丢失“需要确认”）。
- P3：`report.md:34` 的 RG006 表述。
- NOT-RUN：真实模型/embedding/rerank/OCR、Holdout（禁止项）；其余必跑项均实际运行，无 NOT-RUN。

## 证据（本目录 4 份）

`01-verdict.md`、`02-probe.py`（A–H，3 FAIL）、`03-probe-results.md`、`04-test-eval-runs.md`。
