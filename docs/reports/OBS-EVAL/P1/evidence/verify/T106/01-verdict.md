# T106 独立验收 01：判定

- 模型：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`
- 对象：`p1/fix-retrieval` @ `a42ee48`（父 `9933a7b`）；`git status --short` 空；未改交付物、未 commit/push/切分支。
- 结论：**FAIL**（1 项阻塞：用户可见文案仍把系统侧失败说成资料缺失；其余 4 项 PASS；必跑项无 NOT-RUN）。

| # | 验收项 | 判定 | 关键证据 |
| --- | --- | --- | --- |
| 1 | 映射唯一/完整、三要素、T104 逐字保留 | **FAIL** | 映射机械检查 33/33 通过（`02-probe.py` A/B/C）；`IDENTIFIER_NOT_RETRIEVABLE`/`NO_INTENT`/`ANAPHORA_NEW_CONTENT` 文案自相矛盾（见下） |
| 2 | 行为/结构不变 | PASS | `git diff 9933a7b..a42ee48 -- backend/src/mktkb/conversations/schemas.py` 空；`schemas.py:96-130`；全量 1726 passed |
| 3 | 前端修正 | PASS | typecheck/build exit 0；`02-chat` 7 passed；`acceptance-02` 5 passed（含 C02） |
| 4 | 回归/预算 | PASS | unit 343 / obs 255 / int 381 / full 1726；b0/badcase 逐例 0；regression 仅 RG006 |
| 5 | 合规/形式 | PASS | 14 文件全在允许路径；report 77 行五段；证据 4 份；1 commit |

## 阻塞项（item 1）

`backend/src/mktkb/copy.py:192-200`（`IDENTIFIER_NOT_RETRIEVABLE`）同时写：

> “资料中未找到标识“{identifier}”对应的记录……本次未按标识检索，不能据此判断该记录不存在”

该 reason 的调用点是 `conversations/service.py:2071-2082`：只按标识、无门店/物品时，产品检索层**没有执行标识检索**（同文件 `:2072-2074` 注释明确“失败关闭”）。因此“资料中未找到……记录”是系统未执行检索时编造的资料侧结论；同一句又承认“未按标识检索”，自相矛盾。探针 H 段用 `parse_question("QF21 放在哪里？", lexicon with QF21)` 实测得到 `intent=None, identifier="QF21", clarification=None, fields=("位置",)`，确认会进入该分支。违反 handoff §1“唯一、诚实、可自救”、§5“文案不得编造原因”、§6-1“是否与资料无关”。开发证据 `docs/reports/OBS-EVAL/P1/evidence/T106/01-copy-mapping.md:73` 甚至写明“保留……以满足验收可接受的缺失措辞”——handoff 无此要求。

同类（非阻塞或需一并修）：

- `copy.py:338-345`（`ANAPHORA_NEW_CONTENT`，调用点 `rag/answer.py:262-270`）：同一句既称“资料中未记录这项信息”又称“不是资料中没有答案”，语义互斥；原因为新内容未进入记录检索，不应断言资料未记录。
- `copy.py:201-208`（`NO_INTENT`，调用点 `service.py:2091-2097`）：`plan.intent is None` 时尚未检索，文案仍以“资料中未找到与这个问题相符的内容”作唯一原因，且无“不是资料中没有答案”；系统侧识别失败被表述成资料缺失。当前 `intent.py` 的 `intent=None` 返回均带澄清/标识，该服务分支可能已不可达，但仍属交接单要求覆盖的 reason。

## 其他发现（不改变 PASS）

- `INVALID_QUERY`：`format.ts:167` 徽标统一为“服务调用失败”，但 `copy.py:174-182` 正文说“这是查询条件问题”；前端历史分支还提示“请按错误码联系管理员处理”。徽标/正文对同一错误不一致（P2）；`ERROR_CODE` 属 `service_error` kind，前端无 reason 字段，改为按码特判需额外映射。
- 历史 clarification 有候选但未持久化时，徽标显示“需补充条件”而非“需要确认”（`format.ts:179-187`）；属中性可自救，但无法区分“曾有候选”。P3，与 handoff §8 的“前端不得猜原因”一致。
- `report.md:34` 写“RG001–RG006 状态不变、RG006 PASS”，与 `report.md:51` 及实测“RG006 fail→pass”矛盾；应为 RG001–RG005 不变、RG006 PASS。P3 文档表述。

## NOT-RUN

- 真实模型/embedding/rerank/OCR、Holdout：NOT-RUN（禁止项；全部受控/offline）。
- 无其他 NOT-RUN；前端 e2e 与 acceptance 均实际运行。

## 证据

- `02-probe.py`：自写独立探针（A–G，含 3 条诚实性 FAIL）。
- `03-probe-results.md`：探针输出与逐项解读。
- `04-test-eval-runs.md`：pytest、b0/badcase、regression、前端命令与数字。
