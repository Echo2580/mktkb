# SAFE-C26-REVIEW

结论：`blocked_dependency_snapshot_drift`，当前不应执行真实证据投影。脚本 SHA256 `3ef02c224aefeccf08f5d97396e93267b2d88feb08a24b606f9c4410027737f6` 与 A 准备回执及本次指定值一致，但当前公共依赖快照 `3c5d297686aa1324b8713671c6e524af03371b54066274530635bdfa2b30164a` 与准备快照 `2e406884796a28054eee31bcc1e9ee8bc0fe5e930d1ef3e0ba7eb8e09590d049` 不一致。脚本只比较自身执行前后的快照，没有将其与准备回执中的快照比较。

`backend/src/mktkb/evaluation/p2_authorization.py` 和 `backend/src/mktkb/rag/budget.py` 的修改时间晚于准备回执，是需核查的公开依赖候选；由于回执没有逐文件基线，不能据此断定它们就是摘要差异的全部来源。请在 CAP 停写后由 A 更新准备快照，再对照最终依赖复核。

已核对：调用冻结 `classify_case_evidence`，未见使用历史 oldcard 或伪造 passed 卡；公开重算脚本和安全来源固定哈希一致，冻结分类器及证据 loader 哈希与既有保护基线一致。代码检查 run、计划、日期、turn 和封存树哈希，并使用既有 loader；私有处理在输出屏蔽区，异常输出固定码。安全出口限定状态、原因、固定枚举、布尔、计数与哈希。

安全初判中的禁源采用冻结 locator 口径，不能解释为 matcher v2 结果或产品验收。本机 socket / urllib / httpx 拦截正对照 3/3；账本和预算符合脚本固定哈希。B 未读取私有输入、未运行本脚本的真实入口、未调用产品或评分。
