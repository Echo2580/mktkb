# SAFE-CASE-v10-PREPARE

状态：等待 B 复核；未读取真实证据或 key。

- `safe_case_v10.py` 对照 v9 仅修改目标集合比较：无法证明标注目标门店集合完整且无歧义，`saved_stores_equal_constrained_targets` 固定为 `unknown`；已验证 saved stores 的数量仍独立输出。
- 保留 v9 的其余案例诊断、v8 loader/绑定检查、网络守卫及固定异常出口；实际投影文件名调整为 `SAFE-CASE-v10.json`。
- 合成自测覆盖 B 的空实体键和重复 target 反例、目标完整性未证实以及数量保留，并复跑既有 v9 自测；正对照 3/3。回执见 `SAFE-CASE-v10-SELFTEST.json`。
- 未执行真实投影、真实请求、重打分或产品验收。
