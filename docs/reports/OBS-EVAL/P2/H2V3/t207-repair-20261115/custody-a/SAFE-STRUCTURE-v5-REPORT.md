# SAFE-STRUCTURE-v5-REPORT

状态：等待 B 核查数据出口，未读取真实证据。

- `safe_structure_v5.py` 恢复既有 `load_v3_bundle` 与 `_validate_case_plan_document` 身份校验，使用同批次密钥初始化和 `read_encrypted_evidence`。这些只读函数可能在受控内存中加载题库和合同；包装器不对题面或回答文本作语义处理，不调用 runner 或重打分。
- 绑定检查：安全逐题工件 SHA256 固定；四个 case 分别绑定预期 run；验证后 case-plan 的 run ID、证据绑定和 turn index 均须一致，失败不输出逐题结果。
- 高优先级结构事件重复、缺字段或值不在枚举中均为 `unknown`；`final_kind` 原字段名保留。目标计数是标注 `targets` 数量，不代表运行时槽位数。其他无法直接证明的字段保持 `unknown`。
- `--self-test` 仅用合成材料，覆盖重复冲突、缺字段、错 run、错哈希、禁止字段不输出、异常固定码以及 Python 和 C 运行时 stdout/stderr 屏蔽；本机零出站正对照 3/3。
- 真实入口 `--project-after-b-review` 本次未执行。输出屏蔽已覆盖 Python 流及 C 运行时文件描述符；依赖库或操作系统其他原生输出渠道尚未实证，请 B 核查。不得将本报告视作真实数据出口已通过复核。
