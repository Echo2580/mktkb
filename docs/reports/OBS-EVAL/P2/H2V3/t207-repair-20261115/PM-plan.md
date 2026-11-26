# T207 零调用修复经理任务书（2026-11-15）

## 授权和停止边界

主人已授权恢复 T207 开发；开发使用新窗口 GPT-6.1 Terra / high。最新明确要求覆盖旧工作流：中途不做独立验收，全部开发及自测完成后一次提交，由主人安排其他独立 AI 验收。PM 不开发、不验收，不读取真实 H2 题面、答案、私有密文、key 或 .env。

本轮包含 T207 零调用修复：优先四硬失败 C13/C22/C26/C28，再处理 scorecard/summary binding 保留及三处已知产品缺陷（record_facts 准入、D01_ 标题前缀、双门店槽位）。只增加合成 conflict 测试，不改冻结真实题库、标签、四状态和阈值。T208/T209/T900 不启动。

真实复跑不在本次授权内；须新计划与新 GO。旧授权不继承。本轮不能宣称 T207 通过，真实结论维持 CLOSEOUT 的 20/30、硬失败 4，直至获准验证并有新证据。

## 基线及保全

- 分支 codex/p2-e2e；HEAD 97b0066726e5b8d6f94cbc0b63a890084550c106；暂存空；相对交接新增提交 0。
- tracked modified 25 条，已与 fix-2/evidence/preservation-after.json 的路径集合核对一致；每个被触及文件必须保留其现有未提交内容，另存本轮增量 diff。
- C 冻结 12 已逐件 SHA256 核对一致；scenarios、holdout_plan、excel 也吻合交接值。禁止修改冻结件及依赖保护清单。
- live-ledger.jsonl SHA256=e007fee3456e5d13f737a82ed29af45eb4707e3576c444e3520d9ca941dc2899；2547 行；reserved=result=1273，reservation_id 配对且每项一次。
- budget.json SHA256=79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e；项目 22.8965946/40 元，P2-LIVE 7.8256501/20 元；请求余227。
- 两项公开 PM 元数据与32件冻结清单的记录 SHA 不符，旧 fix-2 快照已记载：PM/manager-acceptance.json bd44601c… → 502e41e1…；PM/review-aggregate.json eeb72bc3… → d8c7abeb…。只核查公开变更依据并如实披露，不重签、不改清单、不把当前状态写成32/32。
- Git 登记两个历史 worktree（其中一个 prunable）；不清理、不新建分支/worktree。
- 禁止 reset/clean/stash/stage/commit/push，禁止改预算、账本、GO、旧证据及真实语料。

## 包划分与开发完成标准

1. DEV-A：公开材料保全差异核查、四硬失败的可公开固定码分型；若需要私有输入，停在该子项并记录保管角色所需最小请求，不自行读取；其他独立任务继续。
2. DEV-B：按缺陷类别顺序修复硬失败相关产品行为，每类立刻开发自测，不进行中间独立验收。不得用放宽 matcher、阈值或更改预先登记掩盖失败；matcher v2 与冻结 locator 的口径分开。
3. DEV-C：修复未来 scorecard/summary binding 保留，使用合成材料验证官方 composer 路径；不伪造或补写旧真实运行 binding，不改冻结 composer。
4. DEV-D：三处已知产品缺陷及合成 conflict 回归；不得擅自改变冻结真实题库的 conflict=0 事实。
5. DEV-E：本轮相关定向回归、增量 diff、基线/终态保护件 SHA、合成反例与零出站证据、交付清单及总验收说明。未解决项、未运行项必须列明。

每包只记开发进展和自测结果，不写独立验收通过、经理已验收或 T207 通过。开发可以整理材料，但不得自行组织独立验收。PM 只复核交付是否齐备，最终验收由主人另行安排。

## 出站和额度

H2 请求上限 0，本轮账本新增费用上限 0；不得启动真实入口、自动联网测试、安装依赖、下载模型或浏览器。测试必须清除代理变量、urllib ProxyHandler({})、httpx trust_env=False，并用本机拦截的正对照证明出站被阻断；保护账本和预算的 hash 前后一致。以实际执行测试为准，不编造 collect 或退出码。

派发前 get_usage_limits：Codex 300分钟窗口 usedPercent=10，剩余90%；来源为本宿主当前账户工具，非项目预算。后续派发前重新读取；低于5%停止新派发。助手成本与项目H2账本分别核算。

## 角色与状态

- PM：本聊天，只派单、协调、收口。
- 开发：新建本地聊天，gpt-6.1-terra / high，同一工作区仅一个开发写入者。
- 独立验收：未派发；由主人在全部开发完成后安排其他AI。
- 开发聊天：01a1deb8-e8b8-7cb2-b11f-2240c44f7a62（host=local），标题 T207 零调用修复开发｜Terra high；create_thread 已接受 gpt-6.1-terra / high，使用本地原 checkout，未申请 worktree。
- 当前状态：通用离线修复及开发自测材料已收齐；四个真实case仍未完成具体根因与真实闭环，尚不符合“全部搞定再验收”，未提请独立产品验收。真实诊断需要主人批准CONTROLLED-DIAG-PROPOSAL.md范围及新GO；旧成绩20/30、硬失败4不变。
