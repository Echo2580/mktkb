# SAFE-STRUCTURE-v2-REPORT

- 状态：`blocked`。四个 case 的 `final_kind`、`answer_state`、`refusal_detected`、`clarification`、`target_count`、`old_record_identity_inherited`、`multi_target_present`、`actual_product_call_path` 均为 `unknown`。
- 缺失层：`backend/src/mktkb/evaluation/p2_evidence_io.py` 的 `read_encrypted_evidence` 要求调用方提供密钥字节；已检查的受控代码没有发现只读返回证据密钥字节的 API。既有最终重算脚本直接读取密钥，并运行重打分，因此不能作为本次允许的只读投影入口调用。未对真实数据试错，也未编写读取密钥的旁路。
- 既有 `target_count` 是另一套适配器的代码能力；未确认存在满足本次约束且绑定最终四题的直接只读投影。不能把代码能力当作已取得的实际字段值。
- `socket` / `urllib ProxyHandler({})` / `httpx trust_env=False` 本机正对照 3/3；账本和预算在本次产物写入前后 SHA256 一致，具体值见 JSON。未读取私有材料、执行真实请求或重打分。
