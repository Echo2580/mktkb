# SAFE-STRUCTURE-v3-REPORT

状态：代码待 B 数据出口核查，未读取真实证据。

- 包装器：`safe_structure_v3.py`。真实投影入口为 `--project-after-b-review`，本次未运行。
- 密钥初始化沿用 `final/work/recompute_axes_final.py` 的同一批次路径和内存初始化方式；证据使用 `read_encrypted_evidence` 及绑定检查。包装器不调用重算入口。
- 仅输出固定 case ID、run ID、结构字段、固定枚举、布尔值、计数、来源保护哈希及网络正对照结果。`final_kind` 按原字段输出；未确认的拒答、旧记录标识、多目标和实际代码路径保持 `unknown`。`target_count` 来自 cross_entity 标注中的 `targets`，不代表运行时实际槽位数量。
- 合成检查：`--self-test` 通过；覆盖白名单枚举、文本不输出、缺字段、异常固定码和目标计数。本机正对照 `socket`、`urllib ProxyHandler({})`、`httpx trust_env=False` 为 3/3。
- 本次未触及真实密钥或证据，未执行真实请求、重打分或产品验收。真实投影前请 B 核查完整数据出口、初始化一致性及字段语义。
