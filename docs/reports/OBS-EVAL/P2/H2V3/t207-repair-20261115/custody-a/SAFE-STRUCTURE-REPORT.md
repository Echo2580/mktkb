# SAFE-STRUCTURE-REPORT

- 最新逐题固定码投影：`docs/reports/OBS-EVAL/P2/H2V3/final/evidence/recompute-v2.json`；SHA256：`1987dfcf5920513aa639fe2da4c459f8ac28658fe64eaea5d34487690e3a97cd`。
- `H2V3-C13` / `H2V3-C22` / `H2V3-C26` / `H2V3-C28`：`answer_state`、`refusal_detected`、`clarification`、`target_count`、`old_record_identity_inherited`、`multi_target_present`、`actual_product_call_path` 均为 `unknown`。
- 缺失层：最新公开逐题投影未输出以上字段；不能据此断定底层证据缺失。既有受控重算入口有内存证据读取能力，但未见可直接输出上述字段的受控逐题投影；本次未执行该入口。
- 代码能力：`backend/src/mktkb/evaluation/p2_evidence_rescore.py` 有 `final_kind`；`backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py` 有可空布尔字段 `empty_use_scope_input.plan.clarification`；`backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py` 有 `target_count`；`backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py` 有 `entity_inheritance` 视图。以上是代码层能力，未确认该轮四题字段存在或相关路径实际执行；`final_kind` 与 `refusal_detected` 不等同，`entity_inheritance` 不证明旧记录标识继承。
- 本次未读取私有原文、密文或凭据；本机正对照 `socket` / `urllib ProxyHandler({})` / `httpx trust_env=False` 为 3/3。
