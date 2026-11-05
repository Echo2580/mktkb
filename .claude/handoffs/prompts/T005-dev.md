角色：开发助手。任务 T005「Replay / Local Runner + 运行清单」（P0 第 9 包）。全新上下文。
第一步：完整读 `.claude\handoffs\T005-runner\handoff.md`，按其「输入 / 交付物 / §5 验收标准 / 边界」执行；基线 `p0/obs-eval` @ `f126598`（HEAD 可能是 PM 簿记 commit `9d52b7c`，代码相同，先 `git log --oneline -3` 与 `git status --short` 确认）。
交付物只写到 handoff §2 指定路径；中间草稿放 `.claude\handoffs\_scratch\T005\`，产物放 `var/eval/runs/`（gitignore）或 `%TEMP%`，不要落项目根、不要 commit 产物。
提速策略 A/C：本包 1 次 + `backend/tests/evaluation` 1 次 + 全量仅提交前 1 次；证据 ≤4 份、报告 ≤80 行。
结束时写同目录 `report.md`（五段齐全，自证带命令或 `文件:行`），并给 ≤10 行交接摘要（commit sha、证据路径、未提交改动范围）。
