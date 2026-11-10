角色：开发助手。任务 T101（MKTKB 项目 P1 第 3 包：ERR-03 词表语境与法规优先）。
第一步：完整读 `.claude\handoffs\T101-vocab-context\handoff.md`，按其「输入 / 交付物 / 验收标准 / 边界」执行。
核心：修 `conversations/intent.py` 的缺失字段词表无条件劫持（「价格/销售」误伤法规题）；加语境约束 + 法规/制度优先 + 词表单一口径；E118/E120/E087/E095/E116/E122 等不再提前返回「资料中未记录：采购价格」；「宣传海报的采购价格是多少？」仍 not_found；RG001 由 RED 转 PASS；可向 regression.jsonl 追加 T101 种子。
证据 ≤4 份放 `docs\reports\OBS-EVAL\P1\evidence\T101\`；写同目录 `report.md`（五段、≤80 行、自证带命令/路径）；按 handoff §7 做 **1 个 commit**；回复末尾 ≤10 行交接摘要（含 commit sha、改动文件、三组测试结果、b0/badcase/regression 对照）。
禁止：改 service 层模板/截断分支、检索取数逻辑、b0/badcase、gate_v0_1、账本/GO、业务 API 字段结构；skip/xfail/放宽断言；真实模型调用；读 `.env`/Holdout；切分支；push；新增生产依赖。
`report.md` 首行注明：`wb / cn:deepseek-v4.1-flash / reasoning_effort=max`。
