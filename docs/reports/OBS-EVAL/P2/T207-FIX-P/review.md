# P2-T207-FIX-P 独立验收复核（全新上下文，证伪优先）

- 角色：独立验收助手（未经开发对话）；只读复核 + 自写探针；未改代码/测试/夹具，未 commit，未读 `.env`/H1/H2，零真实出站。
- 交付只写本目录：`review.md` + `evidence/verify/{probe_verify_p.py,01-before-after-and-rootcause.txt,02-pytest.txt,03-probe-t205-and-consistency.txt}`。
- 分支 `codex/p2-e2e`。**现场漂移（必须记录）**：到达时 HEAD=`9a740ce`，复核期间另有他人提交 `18159a1`(fix p2-t207-fix-b) 与 `96fede3`(docs p2-t207)，离开时 HEAD=`96fede3`。两提交都**没有**触碰 `conversations/service.py`（`git log -- service.py` 末次为 `f54cd77`），故"旧代码"对照取自 HEAD 与取自 9a740ce 等价（已用签名断言证明：HEAD 版无 `question` 形参）。
- 固定文件基线（到达/离开各核一次，均一致）：账本 `6b053520…`（1,050,298 B / 1095 行）、预算 `79b21700…`、GO `79a5f318…`。

## 1. 逐条判定

| # | 任务书条目 | 判定 | 独立证据 |
|---|---|---|---|
| 1 | 范围合规（只改 service.py + 新增单测；无 skip/xfail；无 commit；三份 SHA 不变） | **PASS** | `git status` 中本包仅 `M backend/src/mktkb/conversations/service.py`（+11/−1）与 `?? backend/tests/unit/test_p2_t207_fix_p.py`；`git diff -- backend/tests fixtures retrieval/... intent.py` 为空；新测试无 skip/xfail 标记；本包未产生 commit；三份 SHA 到达=离开 |
| 2 | 真实缺陷修复（正确回答复述问题前提值不再被判无效）+ 未弱化 + 记录型不变 | **PASS（含 1 处须经理知情的放宽）** | 见 §2、§3 |
| 3 | 根因重定性（4 反例非产品规则缺陷）5 条子结论 | **成立（5/5 复核为真）** | 见 §4 |
| 4 | 回归不回退（9 文件 210 / p0 7 / t09 mutation 13 / probe 出站 0 且输出一致） | **PASS** | 见 §5 |
| 5 | 报告/证据一致性（≤100 行、sha/行数/命令/结论可复现、限制如实） | **PASS（1 处行数笔误）** | report 恰 100 行；service.py sha16=`e9272b62492bafaf`/2408 行**一致**；新测试 sha16=`d5ccc109e05b9e2a` **一致**但报告写"82 行"、实测 **89 行**（71 非空行）；§4/§6 的限制（测试加固未做、F04 标签未改、E-2 未过、Mock 应答限制）逐条属实 |
| 6 | 合规（零真实出站、未读 .env/H1/H2、未 commit） | **PASS** | 探针两次跑 `outbound_network=0 / chat_calls=5 全 MockTransport / rag_provider_posts=0`；本次未打开任何 `.env`/H1/H2 文件；无 commit |

## 2. 修复前/后对照（我自己构造，未用开发脚本）

探针 `evidence/verify/probe_verify_p.py`：隔离产品应用 + Mock chat（`ChatBehavior(answer=…)`）=**只把"正确回答"喂给产品**，不依赖 Mock 的默认生成器；HEAD 版 `service.py` 用 `git show` 复制到**工作区外**临时目录加载（不改工作区）。

| 题 | 正确回答（含前提值） | 修复前（HEAD 语义） | 修复后（工作树） |
|---|---|---|---|
| F01 | 年度目标 90%；口径 ×100% | answer / pass | answer / pass（题中无 ASCII 数字 ⇒ 不受影响，与开发自述一致） |
| F02 | "单场预算 **8000** 元的活动由市场部经理审批。" | **service_error / MODEL_OUTPUT_INVALID**（sources=0） | **answer / 200 / sources=2** |
| F03 | "**2026年Q4** …档期特价为 **2.99** 元/瓶。" | **service_error / MODEL_OUTPUT_INVALID** | **answer / sources=2** |
| F04 | "资料中未记录咸味饼干 **120g** 的批发价。" | **service_error / MODEL_OUTPUT_INVALID** | **answer / sources=2** |
| F05 | 6 个自然日（无前提值，对照） | answer / pass | answer / pass |

- 单元级（用产品本轮**真实下发的 evidence** 逐题对照）：`old=REJECT("回答包含引用来源中不存在的数据值")` vs `new=ACCEPT` 出现在 F02/F03/F04；F01/F05 两边都 ACCEPT。⇒ 缺陷存在且已修，"修复前会判 MODEL_OUTPUT_INVALID"的说法**成立**。
- 记录型（不带 `question`）**逐字不变**：5 个样本（接受正例 / facts 绑定 / 未引用值 / 年份值 / facts 不符）旧新输出**完全相同**（`all_samples_identical=true`）；源码上记录分支调用点 `_validate_answer(output, allowed, facts)` 在 HEAD 与工作树中都逐字存在，只有正文分支新增 `question=question`（`service.py:2310` vs `:2315-2324`），新形参是最后一个 kw-only 参数，既有 3 位置参数的调用者不受影响。

## 3. 未弱化（逐条实测）与唯一被放宽的边界

| 反例 | 旧 | 新 |
|---|---|---|
| 编造值 1.88（既不在问题、也不在引用来源） | REJECT | **REJECT**（未弱化） |
| 引用 A 行却用未引用 B 行的值（`2.5` 只出现在未引用的 2025 行，仅引用 1 条） | REJECT | **REJECT**（未弱化） |
| **问题前提值被挪到值位置**："审批门槛为 8000 元，由市场部经理审批。" | REJECT | **ACCEPT**，且评测器同题判 **pass** |

- 第三条是这次口径**有意放宽**的边界（报告 §6.2 已定性承认）。我补的是可复现的反例：旧口径会把"把用户给的 8000 说成审批门槛"判成 MODEL_OUTPUT_INVALID（拒答），新口径下它变成一条**判 pass 的错误事实**；评测器的 `value_no_fabricated` 也拦不住（`_gold_number_keys` 把 `question` 数字计入白名单，F02 金标数字集合 = `{2026,10,28,8000}`）。
- 影响面与判读：只对**正文型**回答生效，前提值仅限"问题里逐字出现的 ASCII 数据 token"；不改变"未引用行不得背书"。它不是"放松到不校验"，但确实把"问题里的数字"升级成了可用值。**建议作为接收条件记录**（不阻断）：给该边界补一条显式单测（当前 4 条单测只钉了"问题值可复述/来源外值仍拒/未引用行仍拒/不传问题仍旧口径"，未钉"前提值可挪到别的字段位置"），并把该风险转 T209 阈值决策。

## 4. 「4 个公开反例不是产品规则缺陷」——独立复核结论：**成立**

| 子结论 | 我的复核 | 证据 |
|---|---|---|
| a) F01–F05 意图全为 `mode=document`、`requested_fields=()`、`entities={}`，记录型分支不执行 | **成立** | 用产品自己的库/索引跑 `intent.load_lexicon`+`parse_question`：词典 stores=0/items=0/identifiers=0，5 题全 `mode=document / requested_fields=[] / entities={}`；记录型代码 `_facts`/`_record_units`/`_match_record_clause`/`_record_answer_text` 均挂在 `if plan.mode == "record"`（`service.py:2274/2309/2326`）之下 |
| b) "缺 90%/2.99" 来自 Mock 只回**首条证据前 3 个字段** | **成立** | 代码 `product_adapter.py:531/545`（`list(fields.items())[:3]`；无字段回 `first["text"]`；并行包 FIX-A 改动前行号 518/530-533/535，与开发引用一致）。用**本轮真实下发的 evidence** 复算 Mock 渲染，与产品原样回答**5/5 逐字相等**；字段顺序也与开发所述一致（E10 row103 8 列、E03 NKA row7 13 列，`目标`/`价格(元)` 分别在第 4/第 7 位 ⇒ 前 3 字段天然不含它们） |
| c) E-2 分档修复仍 fail，因 5000/20000 不在 F02 金标数字集合 | **成立** | `_gold_number_keys(F02)`=`{10,2026,28,8000}`；"5000 元至 20000 元由市场部经理审批。"→ `fail(value_no_fabricated)`；"只答审批人"→ `pass`；整条第六条→ `fail(value_forbidden,value_no_fabricated)` |
| d) F04 标签自相矛盾 | **成立** | `should_refuse=False` + `expected_kind="not_found"`；`not_found` 属 `REFUSAL_KINDS` ⇒ 正确拒答 → `refusal_unexpected` fail；改成作答 → `kind_correct` fail。两种结局都跑过，均 fail |
| e) 4 诱饵仍 fail、2 正向仍 pass、`test_p2_public_controls.py` 6 passed | **成立** | 我复跑 probe_t205：F01 fail(value_hit)/F02 fail(value_forbidden,value_no_fabricated)/F03 fail(value_hit,value_no_fabricated)/F04 fail(kind_correct)/F05 pass；pytest 单文件 **6 passed** |

**限定语（经理必读）**：(c)(d) 的失败在**冻结标签/评分契约**侧，属"要不要改期望"的决策，不是"产品规则写了也过不了"；a)(b) 的失败在 **Mock 适配器**侧（`evaluation/**`，本包禁改、另有并行包在改）。因此"4 个反例都不是 fix-scope §E 所指那段产品规则的缺陷"这一重定性**成立**；但**不等于"产品侧没有缺陷"**——本包修的那条（正确回答复述前提值被判无效）就是被反例掩盖的真缺陷，且它是"真实模型在这类题上只会拿到 service_error"的直接原因。

## 5. 回归（自己复跑，非引用开发数值）

- 受影响 9 文件：**210 passed**（147.33s，`--basetemp backend/.pytest-tmp/p2-t207-fix-p-verify`），与开发基线 210 一致，无回退。
- `test_p2_public_controls.py` 单跑 **6 passed**；`test_p0_acceptance.py` **7 passed**；`test_t09_mutation.py` **13 passed**；新增 `test_p2_t207_fix_p.py` **4 passed**。
- `probe_t205.py` 复跑：JSON 主体与开发 evidence/01、/04 **逐字一致**（三方同 3258 字节），`outbound_network=0`、`rag_provider_posts=0`、chat 5 次全 MockTransport。
- 断言未删/未放宽：本包 diff 不含 `backend/tests/**` 任何改动（`test_p2_public_controls.py` 的 if/else 分支是 T205 既有形态，本包未动）；冻结夹具/期望零改动。

## 6. 限制 / NOT-RUN

1. **未跑全仓**；只跑任务书指定集合 + 本包新增单测。真实模型/OCR/embedding/rerank/gate/H2/浏览器均未跑（零真实调用是本包约束）。
2. 记录型路径**没有端到端新探针**：公开语料（E10/W03/E03）不产 store/item 实体，任何问题都进不到 `mode=record`；该路径靠"旧/新函数同输入同输出 5/5"+ "调用点逐字未变" + `test_conversations.py`/`test_t09_d6_r1_record_phrasing.py` 在 210 里通过来兜底（这是**测试级**而非我新造探针的覆盖）。
3. 复核期间工作树被并行包（FIX-B-R1/FIX-A）持续编辑（`evaluation/p2_runner.py`、`product_adapter.py` 在飞改动）；我的结论以"我只读的 `service.py`+探针时刻"为准，`evaluation/**` 一律未验证、未回退、未修改。FIX-A 的 `document_ref` 增量使 `_answer_json` 行号后移 13 行（内容未变）。
4. 反例的"产品侧是否另有缺陷"只证到"正确回答可被接受"这一层；未进一步验证真实模型是否会给出这些正确措辞（无真实调用）。

## 7. 最终建议：**接收**（无阻断项；3 条记录项）

接收理由：预置修复只动 `_validate_answer` 一处口径、+11/−1；修复前/后对照与"未弱化"两类反例都由我独立复现；记录型路径逐字不变；4 条公开反例的重定性 5/5 复核为真；210/7/13/6/4 全绿且探头零出站。

记录项（不阻断）：
1. **口径放宽需经理知会 T209**：问题前提值可被挪到值位置并同时通过产品闸与 `value_no_fabricated`（§3 反例）。建议补一条显式单测钉住该边界，避免后人误以为"不会发生"。
2. **报告行数笔误**：`test_p2_t207_fix_p.py` 实为 89 行（报告写 82），sha 与内容一致，属笔误。
3. **现场漂移**：HEAD 在复核期间由 `9a740ce` 前进到 `96fede3`（他人提交 FIX-B/PM 文档）；本包仍未 commit，经理接收时请以本 review 记录的工作树状态（`service.py` sha16 `e9272b62492bafaf`）为准。
