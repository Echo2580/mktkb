# SAFE-STRUCTURE-v3-REPORT

状态：`blocked`，当前版本尚不能给出“可执行受控元数据投影”的意见。仅审查源码与纯合成数据，未读取真实材料。

必要修改：

1. `safe_structure_v3.py:project_turn` 在较高优先级事件重复时继续降级选择其他事件。合成反例中两条互相冲突的 `commit_observed` 加一条 `answer_result`，实际输出确定值；该歧义应保留 `unknown`，并补相应反例。
2. `project` 除证据只读 loader 外还调用 `load_v3_bundle`；后者会加载 holdout 数据集、合同并解密标注，且 case-plan 验证会调用 `case_questions`。这超出“只调用既有只读 loader、不读取文本语义”的本次核查边界，不能仅凭包装器表层声称只读取证据结构。需将调用范围收紧到明确获准的只读路径，并证明不处理题面语义；如果实现依赖其他现有受控 loader，应先澄清其具体必要范围。
3. run ID 仅检查集合，未固定逐 case 的预期 run，也未显式比对已校验 plan 的 run ID 与外层 run ID。应逐 case 固定 run 映射并核对绑定，避免误配仍输出确定投影。
4. 保护出口：保持原始对象、异常内容不输出，确保依赖库的输出也被可靠拦截；经合成反例检查完整写出数据只能包含允许字段、枚举、布尔和计数。当前 `redirect_stdout` / `redirect_stderr` 仅覆盖 Python 层输出，不能单凭源码证明底层或依赖没有其他输出渠道。

已核对：证据 key 的路径和 `.read_bytes().strip()` 初始化与本批既有重算脚本一致；包装器直接调用既有 `read_encrypted_evidence`。该包装器代码没有直接调用重算、runner 或真实 HTTP；未对所有依赖执行路径作运行时证明。`--self-test` 退出码 0，本机拦截正对照 3/3；另有上述独立合成反例。账本和预算哈希前后一致。

本结论仅涉及数据出口与阻塞依据，不是产品验收。
