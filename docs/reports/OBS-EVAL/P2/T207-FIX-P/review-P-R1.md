# P2-T207-FIX-P-R1 独立验收复核（全新上下文，只读复核 + 自建探针）

- 角色：独立验收助手（未参与开发对话）。交付只写本目录：`review-P-R1.md` + `evidence/verify-r1/{probe_r1.py,01-scope-and-baseline.txt,02-pytest-rerun.txt,03-old-vs-new-and-boundary.txt}`。
- 现场：分支 `codex/p2-e2e`；HEAD=`ffc9fe5`（T207-FIX-P 开发提交），P-R1 全程**无新 commit**（`git reflog` 顶端仍是 ffc9fe5）。
- 工作树同时含并行包改动（`backend/src/mktkb/evaluation/**`=FIX-A、`p2_runner.py` 等=FIX-B-R1），按任务书**未验证、未改动**；本包范围只涉 3 个路径。
- 未读 `.env`/H1/H2；零真实调用（本复核全部是 git / 文件哈希 / `_validate_answer` 单元调用）；未 commit、未 push。

## 0. 结论

**接收（阻断 0）**。4 条新增边界用例方向正确、在旧口径下确实无法通过；报告数字与实测逐项一致；唯一越界项是 report 从 100 行涨到 116 行（FIX-P 包的 ≤100 约定，非 P-R1 约定），已注明、可接受。瑕疵 3 处（措辞/出处口径）+ 1 条既存口子（非本包），均不阻断。

## 1. 逐条判定

| # | 任务书条目 | 判定 | 独立证据 |
|---|---|---|---|
| 1 | 范围：只改 3 路径；`backend/src/**` 零改动；无 skip/xfail；无 commit | **PASS** | §2 |
| 2 | 复跑本包单测 8 passed / exit 0 | **PASS** | §3（独立跑两次，均 8 passed / 0.02s） |
| 3 | 用例真正钉住边界（含证明 (a)/(d) 旧口径不成立） | **PASS**（3 处措辞瑕疵 + 1 条既存口子（非本包），见 §7） | §4 |
| 4 | 报告数字/行数/限制与实测一致；116 行超 ≤100 的性质 | **PASS（含可接受的越界）** | §5 |
| 5 | 合规：零真实调用、未读 .env/H1/H2、未 commit | **PASS**（过程不可审计，产物层面为证） | §6 |

## 2. 范围核对（条目 1）

- 本包 3 路径（`git diff --numstat HEAD`）：`test_p2_t207_fix_p.py` +108/−2、`report.md` +17/−1、`?? evidence/05-p-r1-pytest.txt`。
  - 测试文件删的 2 行是模块 docstring（"只固定三条…"改为四条列表 + 第 3 条描述改写），**既有 4 条用例的主体与断言零改动**（diff 只在文件头追加）。
  - 报告删的 1 行是 §3 表"82 行"那一格（改 89 并补 P-R1 后 195）。
- `backend/src/**`：`git status --porcelain -- backend/src/mktkb/conversations` 为空；`backend/src` 下唯一改动全部在 `evaluation/`（并行包）。`service.py` 工作树 sha16=`e9272b62492bafaf`（2408 行）== HEAD 版本，逐字未动。
- 无 skip/xfail：`git grep -nE "skip|xfail|pytestmark"` 无匹配（exit 1）；collect-only 8 条全部被收集，命令无 `-k`/`--deselect`。
- 无 commit：HEAD=ffc9fe5、reflog 顶端=ffc9fe5。
- `--basetemp` 落在 `.gitignore:17` 的 `backend/.pytest-tmp/`，`git status` 干净，未污染工作树。

## 3. 独立复跑（条目 2）

```text
.venv/Scripts/python.exe -m pytest backend/tests/unit/test_p2_t207_fix_p.py -q -p no:cacheprovider \
  --basetemp backend/.pytest-tmp/p2-t207-fix-p-r1-verify
→ 8 passed, 1 warning in 0.02s（退出码 0；两次独立运行结果相同）
```
Warning 仅为 `StarletteDeprecationWarning`（环境性）。与开发证据 `05-p-r1-pytest.txt` 的差异只有 `--basetemp` 目录名（`...-r1` vs `...-r1-verify`），输出等价。原始输出见证据 02。

## 4. 边界用例方向独立复核（条目 3）

探针 `evidence/verify-r1/probe_r1.py`：直接用 `_validate_answer` 复算每种情形；"旧口径"用 `git show HEAD~1:.../service.py`（2398 行、sha16 `8b2dbc7539a4f62e`、无 `question` 形参）复制到**工作区外**临时目录整包加载，再用**当前测试文件原件**在旧口径下跑一遍。

| 用例（行号） | 断言方向（我复核） | 新口径 | 旧口径 |
|---|---|---|---|
| (a) `test_p2_t207_fix_p.py:110` | 带 question 接受 8000；同文本**不传** question 仍拒（:123-127 两条一起） | ACCEPT / REJECT | 带 question=`TypeError`；不带 → REJECT |
| (b) `test_p2_t207_fix_p.py:130` | 同句式 1.88 仍拒（:144） | REJECT | 带 question=`TypeError`（旧代码本就拒） |
| (c) `test_p2_t207_fix_p.py:147` | 三样本（不带 question）输出逐字不变（:156-174） | ACCEPT/ACCEPT/REJECT | **完全相同**，且旧口径下此用例**通过** |
| (d) `test_p2_t207_fix_p.py:177` | 错误前提 3000 照抄后接受（:194-195） | ACCEPT | 带 question=`TypeError`；不带 → REJECT |
| 既有 #3（:74）顺带复核 | 两行都在 allowed/evidence、只引用 A 行时用 B 行的 2.5 | REJECT | —（该调用用了 question，旧代码 TypeError） |

关键判读：

1. **(a)/(d) 确实只在新口径成立**：旧代码连签名都没有 `question`（`TypeError: unexpected keyword argument 'question'`）；把同一文本按旧口径调用则 `REJECT`。当前测试文件在旧口径下 **6 failed / 2 passed**，failed 全部是"调用旧签名时传 `question=`"导致的 `TypeError`，2 passed 恰为 (c) 与"不传问题保持旧行为"。⇒ 放行**只来自**"问题原文 token 并入白名单"，不是测试构造出来的假象。
2. **(b) 与 (a) 成对**：1.88 既不在问题也不在引用来源（POLICY 正文无 ASCII 数字），带 question 仍拒 ⇒ 放宽是"整 token 逐字相等"，不是对"值位置"整体放行。
3. **(c) 的不变性成立**：三样本旧/新输出逐字相同（旧口径 pytest 下该用例即 pass，说明它钉的是"不变"而非"新行为"）。
4. **"值位置"是叙述用语**：实现是 token 级集合包含（`service.py:837`），不区分答案里的位置；(a) 与 (d) 因此走**同一条代码路径**，(d) 的价值在"显式标注已知放宽、不得读作正确性通过"，不增加覆盖。
5. **评测侧声明可查但未被单测钉住**：`_gold_number_keys`（`backend/src/mktkb/evaluation/scorers.py:363-370`）把 `case.question` 计入白名单，`value_no_fabricated` 在 :556-557 用该集合 ⇒ 报告"错误前提值不会被 value_no_fabricated 拦住"属实；但 (d) 只调产品闸、**没有调用评测器**，这条是文档结论而非测试证据。

## 5. 报告一致性（条目 4）

| 声明 | 实测 | 判定 |
|---|---|---|
| 新单测 FIX-P 交付 89 行 / sha16 `d5ccc109e05b9e2a` | 89 行 / `d5ccc109e05b9e2a` | ✅ |
| P-R1 后 195 行（非空 161）/ sha16 `5c3e9c33d3a0a012` / 8 用例 | 195 / 161 / `5c3e9c33d3a0a012` / 8 | ✅ |
| `service.py` 2408 行 / `e9272b62492bafaf` / :837 并入问题 token / :2323 传 question / 记录型 :2310 不传 | 全部逐行核对一致 | ✅ |
| `_gold_number_keys` 位于 `scorers.py:363` 且含 `case.question` | :363-370 属实；:556-557 使用 | ✅ |
| 限制：T209 知悉、本包不动产品/评测代码 | `service.py`==HEAD；`evaluation/` 改动属并行包 | ✅ |
| report 现 116 行 vs FIX-P 包 ≤100 行 | 100 → 116（P-R1 节 15 行，行 102-116） | 见下 |

**116 行的性质与判定**：≤100 行出自 **P2-T207-FIX-P 开发任务书「交付」**（"report.md ≤100 行"），P-R1 任务书只要求"追加短节 `## P-R1`"、未再设上限；在不删既有证据的前提下追加必然越界，report 末行也已注明"≤100 是 FIX-P 包上限、本节按 P-R1 任务书追加"。⇒ **可接受，不构成返工理由**；但：①该上限的出处被写成"原 §1"（§1 是结论表，未写该上限，真实出处是 FIX-P 任务书），②建议经理记录里注明"report 现 116 行，≤100 只适用于 FIX-P 首次交付"，避免后续拿旧上限卡包。

## 6. 合规（条目 5）

- 零真实调用：测试文件只 import `mktkb.conversations.service._validate_answer` 与 `providers.types`（`test_p2_t207_fix_p.py:19-24`），不构造 Provider/网关；复跑 0.02s、无网络夹具；证据 05 与实际输出一致（非编造）。
- 未读 `.env`/H1/H2：本次复核未打开任何 `.env`/holdout 文件；P-R1 产物用到的 8000 前提句来自**公开**语料 `corpus/enterprise-20261101/questions.json`（E059）与公开控制用例 `test_p2_public_controls.py:108`，1.88/3000 为构造值（3000 未出现在语料中）⇒ 产物层面无 holdout 泄漏痕迹。**限制**：开发过程不可审计，只能做产物级判断。
- 未 commit/push：HEAD 与 reflog 均停在 ffc9fe5。

## 7. 瑕疵清单（全部非阻断，建议下一手顺手改）

1. **(c) 的样本出处措辞偏宽**：docstring 称"样本取自既有记录型用例（`test_conversations.py:127-143 / :248-257 / :272-279`）"，实际只有样本 1（`位置是B区1号货架第二层。`）与 :127-134 逐字相同；样本 2/3 用本文件 `ROW`（`PX-0001/2.99`）按同形态改写（电话号 010-99999999 沿自 :252）。建议改为"1 条逐字取自既有用例 + 2 条同形态改写"，或补一条真正逐字的门店电话正例。
2. **(a)/(d) 的"值位置"表述**易被后人当成"只放宽值位置"：实现是 token 全局集合，与位置无关。建议在 docstring/report 加一句"位置无关，只按问题原文整 token 匹配"。
3. **report 末行出处**："原 §1 的 'report ≤100 行'" → 应为 FIX-P 开发任务书「交付」节（review.md §1 条目 5 曾复述该上限）。
4. **非本包引入的既存口子（供 T209 参考，不算本包缺陷）**：`_value_tokens` 的 `_VALUE_TOKEN` 只认 ASCII，全角数字（`８０００`）在旧/新口径下都**不产生 token 因而一律放行**（我实测旧口径同样 ACCEPT）；千分位 `8,000` 则被拒。属修复前既有性质，与 FIX-P/P-R1 无关，但 T209 收口时值得一并处理。

## 8. 建议

**接收**。P-R1 完成了"把唯一放宽显式钉住 + 更正行数 + 补证据"的目标，新增用例方向经旧/新对照独立验证成立，无产品代码改动、无 skip/xfail、无 commit。§7 的第 1-3 项建议在后续文档整理（T209 文档清理项）中顺手修，不必为此开返工单。

## 9. 证据索引（`evidence/verify-r1/`）

1. `01-scope-and-baseline.txt`：提交/reflog、工作树全量清单与并行包排除、3 路径 numstat、`backend/src` 零改动与 service.py 三版 sha16、skip/xfail、行数对照、116 行性质。
2. `02-pytest-rerun.txt`：本包单测独立复跑原始输出 + collect-only 8 条清单 + 退出码。
3. `03-old-vs-new-and-boundary.txt`：修复前 service.py 的获取与加载方式、新旧探针原始 JSON、**当前测试文件在旧口径下的 6 failed / 2 passed**、逐用例判读、限制。
4. `probe_r1.py`：自建探针源码（零真实调用，可对工作树/临时旧口径各跑一次）。
