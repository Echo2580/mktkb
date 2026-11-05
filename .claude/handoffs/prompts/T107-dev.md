角色：开发助手。任务 T107（MKTKB 项目 P1 第 2 包：regression suite 与数据集契约扩展）。
第一步：完整读 `.claude\handoffs\T107-regression-suite\handoff.md`，按其「输入 / 交付物 / 验收标准 / 边界」执行。
只改 handoff 允许的文件；证据 ≤4 份放 `docs\reports\OBS-EVAL\P1\evidence\T107\`；中间草稿放 `backend\.pytest-tmp\`。
结束时写同目录 `report.md`（五段齐全、≤80 行、自证带命令/路径），按 handoff §7 做 **1 个 commit**，回复末尾给 ≤10 行交接摘要（含 commit sha、改动文件、本包/受影响目录/全量三组结果、初始 RED 种子表摘要）。
禁止：真实模型/embedding/rerank/OCR 调用；读 `.env`；读 Holdout 目录；改 b0/badcase/gate_v0_1/账本/GO/业务代码；skip/xfail/删断言；切换分支；push；新增生产依赖。
