# T003d 返工 R1 定向复验 review（71756f5）

> 验收者：独立验收助手（无 T003d 开发会话历史）。**结论只来自本会话在主工作树的亲自复跑、独立探针与仓库外变异**；
> 开发报告/返工单只作定位线索，不作 PASS 证据。按 PM 提速策略 A/C：只复核上一轮唯一 FAIL（§3.1）+ 受影响测试 + 全量 1 次，
> §5.1–§5.10 沿用上一轮 `review.md` 的 PASS 结论，不重复劳动。
> 对象：`71756f5`（R1，父 `574e288`；T003d 首交付 `b811f9f` 为其祖先，`git merge-base --is-ancestor` 退出 0）。
> 环境：Windows / PowerShell 5.1；Python 3.12.7、pytest 9.1.1；`MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0`；
> 主工作树 HEAD=`71756f5`，工作树无代码改动（`git diff --name-only HEAD` 仅 PM 的 `.claude/handoffs/_index.md`）；
> 全程串行（未并发跑 pytest）；无 MemoryError / 资源失败。
> R1 证据（3 份，ASCII / UTF-8 无 BOM）：`docs/reports/OBS-EVAL/P0/evidence/verify/T003d/R1-{targeted,probe,full-suite}.txt`。

## 0. 总判定

**PASS**：上一轮 §3.1 的 MEDIUM 已闭环（commit 阶段升级写 `KNOWLEDGE_CHANGED_AT_COMMIT`、契约只对该 reason 退化），
且**未降低原约束强度**（检索阶段/检索后形态仍要求 `retrieve`，未知 reason 回落原表）；受影响测试 113 passed、全量
**1307 passed / 0 failed / 0 error**；提交边界 10/10 路径合规；仓库外 2 个变异全部被回归测试捕获。

| 复核项 | 结论 | 关键证据 |
| --- | --- | --- |
| 1. FAIL 修复闭环 | PASS | `R1-probe.txt` 第 1 条；`test_paths_e2e.py:530`；`service.py:1741,1766`；`contracts.py:161` |
| 2. 不降强度（含 fail-safe） | PASS | `R1-probe.txt` 第 2/3/4 条；`test_contracts.py:266,277,307`；`contracts.py:167-169` |
| 3. 向后兼容（T001/T002/T003a、`rag+no_answer`） | PASS | 定向 113 passed + 全量 1307 passed；`R1-probe.txt` 第 4 条 |
| 4. reason 只写 trace | PASS | `R1-probe.txt` 第 5 条（off/on 归一化 body 相等）；R1 diff 仅 reason 赋值 |
| 5. 定向 + 全量 | PASS | `R1-targeted.txt`（113 passed）、`R1-full-suite.txt`（1307 passed） |
| 6. 提交边界 | PASS | `git show --name-only 71756f5` = 10 个允许路径，禁改路径 0 |
| 7. 测试非空转（仓库外变异） | PASS | `R1-probe.txt` 变异段：m1 1 failed、m2 4 failed；仓库无改动 |

---

## 1. FAIL 修复闭环 — PASS

- **代码（窄修，无业务分支变化）**：`service.py:1741-1752` 只读已创建 Span 名；`:1766-1776` 按是否实际执行
  `retrieve` 写两种稳定 reason；`:2210-2214` 仍在 `commit` Span 结束后调用。`contracts.py:108-113` 定义
  `KNOWLEDGE_CHANGED_AT_COMMIT` 常量，`:161-166` 仅对 legacy 两路 + 该精确 reason 返回 `{intent_parse, commit}`。
- **独立探针复现（并发发布注入：claim→commit 之间 `KnowledgeState.revision +1`）**：
  `OBSERVED commit-upgrade: path=legacy outcome=knowledge_changed reason=KNOWLEDGE_CHANGED_AT_COMMIT
  status=ok spans=['commit','intent_parse'] missing=[]`（`R1-probe.txt`；探针 5 passed）。
  同一用例断言：Span **严格等于** `{intent_parse, commit}`（不伪造 retrieve）、`validate_required_spans == []`、
  问题原文不落 trace。
- **交付回归测试**：`test_paths_e2e.py:530-576` 同口径（真实 HTTP + 真实 `TraceRepository`），定向运行通过。
- 结论：上一轮 §3.1 的现象（`missing=['retrieve']`）在本会话探针中不再出现，修复闭环。

## 2. 不降强度 — PASS

- **检索阶段升级（有 retrieve）**：探针注入 `_retrieve` 抛 `KnowledgeRevisionChanged` →
  `OBSERVED retrieval-stage: reason=KNOWLEDGE_CHANGED ... retrieve ... missing=[]`；
  合成 `TraceRecord(reason='KNOWLEDGE_CHANGED')` + 缺 `retrieve` 的 Span 集 → `['retrieve']`（仍报错）。
- **检索后 commit 升级（有 retrieve）**：探针在正常作答后 bump revision →
  `OBSERVED commit-upgrade-after-retrieve: path=legacy_with_rag_candidates reason=KNOWLEDGE_CHANGED ... retrieve ...
  missing=[]`，未被误降级。
- **fail-safe 回落**：`required_spans(legacy*, knowledge_changed, reason ∈ {None, '', 'KNOWLEDGE_CHANGED',
  'SOMETHING_ELSE', 小写 at_commit})` 全部返回原补充行 `{intent_parse, retrieve, commit}`；
  仅大小写精确的 `KNOWLEDGE_CHANGED_AT_COMMIT` 退化（`contracts.py:161-169` 精确集合匹配）。
- **契约测试**：`test_contracts.py:266`（默认/未知 reason 仍要求 retrieve）、`:277`（AT_COMMIT 退化）、
  `:289`（reason 不跨 path）、`:307`（validate 读 record.reason）均绿；`test_paths_e2e.py:502-527` 检索阶段用例仍绿。

## 3. 向后兼容 — PASS

- 定向三文件 **113 passed**（`R1-targeted.txt`）：包含 T001/T003a 的 `test_contracts.py`、T003c 的 `test_rag_spans.py`、
  T003d 的 `test_paths_e2e.py`；上一轮同一选择器为 106，本次 +7 即 R1 新增用例（计数自洽）。
- `rag+no_answer` 的 §5.9 reason-aware 未被新 reason 影响：探针断言 `RAG+knowledge_changed` 仍 `{parse, commit}`、
  `RAG+no_answer+AT_COMMIT` 仍 `{parse, recall, fuse, commit}`、`RAG+no_answer+DOCUMENT_NOT_FOUND` 仍 `{parse, commit}`。
- 全量 **1307 passed / 0 failed / 0 error**（388.44s）覆盖 T002 trace store、集成与既有契约测试；无 skip 凑数、无 flake。

## 4. reason 只写 trace — PASS

- 探针 `test_r1_behavior_identical_trace_off_on`：同一固定 `client_request_id` + 同一注入，trace off/on 两应用
  状态码均 200、响应键集合相同、归一化 body 相等；off 无 `X-Trace-ID`，on 的 trace `reason=KNOWLEDGE_CHANGED_AT_COMMIT`。
- 响应体无 `reason` 字段（`set(body) == set(AskResult.model_fields)`），响应文本不含 `KNOWLEDGE_CHANGED_AT_COMMIT`；
  `kind=knowledge_changed` 与提示文本由既有 `_commit_result_impl`（`service.py:1521-1527`）决定，R1 未改。
- R1 diff 仅新增 `_executed_span_names` 与 reason 选择表达式，无状态码/分支/入库消息改动（逐行审阅 `git show 71756f5`）。

## 5. 定向 + 全量 — PASS

| 运行 | 命令（均加 `-p no:cacheprovider`、basetemp 在 `backend\.pytest-tmp`） | 结果 |
| --- | --- | --- |
| 定向 | `pytest test_contracts.py test_paths_e2e.py test_rag_spans.py -q` | **113 passed, 1 warning, 11.71s** |
| 全量（仅 1 次） | `pytest backend/tests -q` | **1307 passed, 1 warning, 388.44s** |

- 1307 = T004a 基线 1300 + R1 新增 7（定向 106→113 亦为 +7），无 failed/error；已知 g08 时序 flake 未复现。
- 原始输出见 `R1-targeted.txt` / `R1-full-suite.txt`（仅省略警告块中非 ASCII 的仓库路径行，通过行与进度为原文）。

## 6. 提交边界 — PASS

- `git show --name-only 71756f5` 实测 **10 个路径**，与 PM 允许清单逐一相等（无多余、无缺失）：
  `conversations/service.py`、`observability/contracts.py`、`test_contracts.py`、`test_paths_e2e.py`、
  `docs/evaluation/trace_schema_v0_1.md`、`report.md`、`evidence 10/11/12/13`。
- 未出现 `rag/**`、`main.py`、`config.py`、`store.py`、`tracer.py`、`versioning.py`、其它既有测试、
  `evaluation/**`、`fixtures/**`、`pyproject`、`docs/evidence`、`var`（`git show --name-status` 核对）。
- `b811f9f` 是本 commit 的祖先；本会话未 commit / push / 改 `_index.md` / 改交付物。

## 7. 测试非空转（仓库外变异） — PASS

在 `%TEMP%\t003d-r1\{mut,mut2}`（`git archive 71756f5` 解包副本，仓库外）注入变异，选 3 个相关测试
（e2e commit-upgrade + 2 个新契约测试），干净副本基线 **4 passed**：

| 变异 | 内容 | 结果 |
| --- | --- | --- |
| m1 | `_record_legacy_outcome` 对 knowledge_changed 永远写 `KNOWLEDGE_CHANGED` | **1 failed**（`test_legacy_commit_time_knowledge_changed_after_early_exit`：`'KNOWLEDGE_CHANGED' == 'KNOWLEDGE_CHANGED_AT_COMMIT'`），3 passed |
| m2 | `contracts.required_spans` 删除 AT_COMMIT 分支（永远默认行） | **4 failed**（e2e + 两个参数化契约用例 + validate 用例），其余通过 |

- 仓库工作树在变异前后一致：`git status --porcelain` 条目集合未变（仅 PM 的 `_index.md` 修改与既有未跟踪交接/
  验收证据），无新增/修改代码；临时探针文件已在同一次命令内删除（`Test-Path` 为 False）。变异原文见 `R1-probe.txt` 变异段。

## 8. 未覆盖 / 残余风险 / 建议

1. **未重跑 §5.1–§5.10**：按提速 A 沿用上一轮 `review.md` 的 PASS 结论；本轮只确认与 R1 相关的行为不变。
2. **T006a 门禁未验收**（尚未实现）：其实现须调用 `required_spans(path, outcome, reason=record.reason)`，
   并对 `status=replayed` 跳过 path/outcome 完整性校验（上一轮 §3.3 提示仍有效）。
3. **真实供应商链路未跑**（零真实调用约束，T003c 口径）；commit 阶段异常（上一轮 §3.4 INFO）未新增注入验证。
4. **残余 LOW**：`_executed_span_names` 读 `TraceContext._spans` 私有状态（与既有 `_trace_is_legacy` 读 `_path` 同口径）；
   `tracer.py` 属本包禁改文件，故未加公开 getter。若后续重构 tracer 内部，需同步该函数。
5. **建议**：`clarification` 解析级早退 + commit 升级与 not_found 同代码路径，本探针未单独覆盖；若 T006a 要逐形态
   建用例，可补一条（非阻塞）。R1 可进入人工审核门。
