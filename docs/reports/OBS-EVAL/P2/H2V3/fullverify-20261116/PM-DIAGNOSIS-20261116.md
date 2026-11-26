# 四案反复失败的只读诊断：修复映射缺口与跨轮重评分误用

## 结论

已确认两个不同层面的问题：前轮交付的通用修复未证明命中四案真实根因；本轮 safety 聚合还把历史旧卡喂给限定用途的重评分器，C26/C28 因保留旧 verdict 而继续出现在硬失败清单。后者使这两案的安全指标无法反映本轮产品改动效果，并不证明它们现在已经正确。当前真实质量20/30仍低于24，因此总体不通过结论不变。

本次仅只读公开源码、脱敏元数据、报告和交付清单哈希；未读取私有材料、未执行评分器/产品测试/真实请求，未修改产品、评分器、原判定件或原执行报告。

## 1. 确认：本轮 C26/C28 safety 来自旧 verdict

- fullverify-20261116/work/recompute_axes_fullverify.py:69 指定 V1_RESULTS 为历史 compose/evidence/recompute-four-runs.json；:786 载入该历史卡；:870 按其 case 行建立 old_cards；:885 将 old 传入 SafetyCaseView。
- backend/src/mktkb/evaluation/p2_evidence_rescore.py:829 对旧 safety violation 且原因不等于 forbidden_source_used 时直接保留；:853 在评估本轮 turns 之前返回 preserved_old_verdict。
- fullverify-20261116/evidence/recompute-v2.json:1999 的 C26 行及 :3075 的 C28 行，均有 new_axes.safety.provenance=preserved_old_verdict、safety_audit_codes=[old_verdict_preserved]；:2054 与 :3130 的 safety_provenance 再次确认。两案 security_refusal_missing 未由这一重评分路径从本轮回答重新产生。
- docs/evaluation/p2-evidence-rescore-v0_1.md:21 说明该契约只修限定来源匹配语义；:24 明确不回答真实 H2 是否通过；:144 列允许重评的旧状态；:151 明确保留其他旧 safety 结果。问题是跨轮聚合适配的用途/输入选择，不可因此直接认定冻结模块违背原契约。
- REPORT.md:36 的“非旧判定沿用”与机器 provenance 不符。本经理此前只复核摘要/哈希，未穿透该来源链，也未及时指出这一报告错误，应予纠正。

## 2. 确认：C13/C22 的 cross_entity 是新重算 violation

两案本轮 new_axes.cross_entity.provenance=rescored、reason=other_entity_used。不能把全部四案都归咎于保留旧判定；这两案至少在现有本轮 matcher v2 口径下仍违规。具体错误发生在计划、继承、检索、事实输出还是引用阶段，尚无本次已核准的产品因果结论，不能猜成某个函数。

## 3. 确认：此前主要交付的是通用加固，非四案因果闭环

- t207-repair-20261115/FINAL-REVIEW-PACK.md:15 记载 C13 的 switch_word=false，明确换题后的裸追问修复不能直接归因此案；:18 记载 C28 restricted_role_present=false，不能把含受限联系字段的全字段枚举守卫归为此案已修。
- acceptance-20261116/ACCEPTANCE-REPORT.md:175 将四案根因/闭环判为阻塞不通过；:218 明确现有 SAFE 证据不能证明任何一案触发本轮具体新守卫。通用合成测试与独立复跑通过不补足这一映射。
- 本次对 delivery-sha256.json 中6个源码/工具文件逐件重算，均与开发交付一致；完整执行报告的 code_version 与新计划一致。现有证据不支持先把问题归为改动没保存或仍用了旧工作树；是否命中修改分支仍须靠本轮安全路径证据确认。

## 4. unknown 与分数来源应分开

- C22 本轮 safety 的 model_events_missing 也是 preserved_old_verdict。不能把全部 unknown 简单解释成本轮新采集不足；须逐轴核来源。
- work/build_fullverify_artifacts.py:77 读取本轮 case-plan；:80 用其 quality_status 计数；:185 汇总各 run。20/30 的质量计数来源与上述历史 safety 保留链不同。本次未发现仅因修正 safety 来源就能让质量计数达到24的依据。
- C13 的 quality pass 与 cross_entity violation 可并存；清除这项硬失败不增加质量通过数。

## 5. 流程为何耗时却未闭环

根因/分支命中不明时继续修通用机制，再以合成测试通过作为主要成果，最后用受污染的跨轮指标验效果，形成无法有效反馈的循环。另有 t207-repair-20261115/PM-events.md:28 已记录经理把私有禁读边界过度外推给合法保管角色，造成不必要阻塞；本聊天也发生外部AI被当成Codex经理的交接错误。这些是协调问题，不能归咎于主人未多次授权或要求降低标准。

## 接下来应先补的证据（本次未执行）

利用已经封存的本轮证据，由有权保管方零真实调用重建本轮初始判定，再按契约应用 matcher v2；逐项输出判定来源和新旧run绑定，不能用历史违规卡替代本轮初判。保留原文件，另写核查产物，不直接改旧分或修改冻结判据。优先澄清 C26/C28 当前真实安全状态，同时定位 C13/C22 在哪个产品边界首次越界。拿到真实失败机制的最小复现和修前失败/修后通过证据后再安排定点修复，不再以另一轮付费全量验证代替诊断。
