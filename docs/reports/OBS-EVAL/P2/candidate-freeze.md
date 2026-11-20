# P2 送审候选冻结清单

2026-11-21T01:16:20+08:00 · 经理核收冻结（schema v0.2）。本清单锁定送审候选，T900 独立总验收以此为准。

## 身份

- 分支：`codex/p2-e2e`
- HEAD：`97b0066726e5b8d6f94cbc0b63a890084550c106`
- 接手锚点：`97b0066726e5b8d6f94cbc0b63a890084550c106`
- 工作树：47 tracked 修改 / 5257 未跟踪 / 共 5304 行

## 关键身份

| 项 | 值 |
| --- | --- |
| 批准配置 | `b1094cc726230be2ec22ec811d34a948ea4a2fe03aab2c0fcc4f20c99764d961` / canonical `7fa6f47a445f9643…`（**未跟踪，须显式取件**） |
| 正式 B0 基线 | `7981d4afc2d1` / run `p2-t209-b0-20261120-02` |
| B0 准入证据 | `2226fa208aec7db84ab69e5f7a068e94322414d38b90c14399979b96fcea8b5d` |
| 跨场景门禁 JSON | `d4c98f92c0873addbda01b28394b292b3fcd4bdec2aa39a25af6b8384ba66461`（53053 B） |
| 门禁判定 | decision=`pass` / technical_gate=`pass` / release_allowed=`False` / owner=`not_decided` |
| 行数 | 47；行 id 摘要 `985d055638477e5f44b5b696…` |
| `gate.py` 当前 | `e04990db52d72c06dcd4e87fea8f80644171fd5b686810bc0fa6aa3fa8c831b7` |

**`gate.py` 三值身份链**：HEAD `97b00667` `7e54fbf672cbc1c02bbe746c164038613d5861070796794f6a41aae1595b7fe7`︱D-004 前工作树（**git 不可重建**） `102350994939fcd47b9c268cf732743a322b1b05bd282d563de06a354b1fec1b`︱当前 `e04990db52d72c06dcd4e87fea8f80644171fd5b686810bc0fa6aa3fa8c831b7`

## 一、`frozen_artifacts`（必须逐字节不变）

| # | 路径 | SHA-256 | 字节 | 跟踪 |
| --- | --- | --- | --- | --- |
| 1 | `backend/src/mktkb/evaluation/gate.py` | `e04990db52d72c06dcd4e87fea8f80644171fd5b686810bc0fa6aa3fa8c831b7` | 148546 | 是 |
| 2 | `backend/src/mktkb/evaluation/p2_scoring.py` | `6e197bc3b0b3bd275bacb2af5f7f2a24acffe8927061ffa1e1d3bb9078234344` | 100309 | 是 |
| 3 | `backend/src/mktkb/evaluation/p2_score_run.py` | `6a5edd87b8f73fb999a816096a25a005fcada63fc2e32c09147928182b45cb47` | 43024 | 是 |
| 4 | `backend/src/mktkb/evaluation/p2_b0.py` | `1f00d882d1e1de97a7977b3444fa7e32d0a10b5cf2ca764574694d9305c9f34e` | 35898 | **否（未跟踪，冻结须显式纳入）** |
| 5 | `backend/src/mktkb/evaluation/cli.py` | `f2ca03ab8e84b1454d3f3173eb137aa5afae6e9952fed125415725ec956f82dc` | 74595 | 是 |
| 6 | `backend/src/mktkb/evaluation/p2_contracts.py` | `be873d7b38aa87e44189fedba135e415452d90f510f230d24e11102b824a7b73` | 69780 | 是 |
| 7 | `backend/src/mktkb/evaluation/p2_hard_evidence.py` | `3f1c88baa56838a3fbe02c462b74646bb224dd57f60b115442b58dc30be91ffd` | 193686 | **否（未跟踪，冻结须显式纳入）** |
| 8 | `backend/src/mktkb/evaluation/p2_evidence_rescore.py` | `a0061289d13921d212ba83e81d36fd46ce07c0f7636128701501f4323714ca1b` | 63542 | **否（未跟踪，冻结须显式纳入）** |
| 9 | `backend/src/mktkb/evaluation/p2_release_model.py` | `3aab5f06148cd58759b6675c62f8597eecf7953e8725b21040e86cb2502e3fdc` | 14173 | **否（未跟踪，冻结须显式纳入）** |
| 10 | `backend/src/mktkb/evaluation/p2_release_inputs.py` | `4ec060a7adab179bc18686ab4fc3e3d46600e28000e390b73bdbd44023530743` | 38318 | **否（未跟踪，冻结须显式纳入）** |
| 11 | `backend/src/mktkb/evaluation/p2_release_public.py` | `706dc3ad690f566acbcaec6f34033b420db4cb2a4ab4d9f56e94238d6cc44840` | 64664 | **否（未跟踪，冻结须显式纳入）** |
| 12 | `backend/src/mktkb/evaluation/p2_release_h2.py` | `4a00a31366e8b2f95a4fe9358963478499b306561c030971c14c03bf53bb0474` | 22358 | **否（未跟踪，冻结须显式纳入）** |
| 13 | `backend/src/mktkb/evaluation/p2_release_h2_aggregate.py` | `92a5e41a64bbb096b9190b9e5124eccc108e9b461bb1dd7b3cf6bc15ec46f4b0` | 30825 | **否（未跟踪，冻结须显式纳入）** |
| 14 | `backend/src/mktkb/evaluation/p2_release_binding.py` | `a2481fffd2297aaa6b321c16d9c1b4c8f9f751d4e3a303567e4976019b3a819f` | 27008 | **否（未跟踪，冻结须显式纳入）** |
| 15 | `backend/src/mktkb/evaluation/p2_release_gate.py` | `552d6ff7cfe467bafeaea4b564d55c29a0a7d7dba44c727109154d5f3ee2e330` | 26904 | **否（未跟踪，冻结须显式纳入）** |
| 16 | `tools/p2_h2_controlled_execute.py` | `2e442c6992eeae2383331fb41f76172e0edf66e102700292dcc5ca60da689f0a` | 150917 | **否（未跟踪，冻结须显式纳入）** |
| 17 | `tools/p2_h2_v3_controlled_execute.py` | `953fda08df6f0ce1121ded011aed4fd7724f5867bd9d61abc9f4402be1cc63f5` | 108460 | **否（未跟踪，冻结须显式纳入）** |
| 18 | `docs/evaluation/gate_v0_3_approved.json` | `b1094cc726230be2ec22ec811d34a948ea4a2fe03aab2c0fcc4f20c99764d961` | 5785 | **否（未跟踪，冻结须显式纳入）** |
| 19 | `docs/evaluation/p2-holdout-v3.source-map.json` | `03665c48c0716e45e0a6313c6f1823e6714c996d85254f01283fc0ef5ed2e8b8` | 2648 | **否（未跟踪，冻结须显式纳入）** |
| 20 | `docs/evaluation/p2-h2-scenarios-H2v3.json` | `9dfefc3966a437684cfa67cd7c1113b55665956ff3869242887e14506b7c8af8` | 1140 | **否（未跟踪，冻结须显式纳入）** |
| 21 | `backend/tests/evaluation/test_p2_gate.py` | `712fb0c3ca213c7057b6519f15d7a4095ac35d0add89f2dd3409b37481965d03` | 39691 | 是 |
| 22 | `backend/tests/evaluation/test_p2_release_gate_fixtures.py` | `1d47f467e4f8ac6c160fab866e8460f200593b33a4233c7718d125eaeb1d7ce5` | 37520 | **否（未跟踪，冻结须显式纳入）** |
| 23 | `backend/tests/evaluation/test_p2_release_gate_positive.py` | `3bbad536e63586f6b05ed2ecd404a188901713df98b73355853e7087c45c9ceb` | 8064 | **否（未跟踪，冻结须显式纳入）** |
| 24 | `backend/tests/evaluation/test_p2_release_gate_negative.py` | `14ab76d9f52e8c972ad326b476b00e4d1ecf2420e6c7d16814987a8ec976d99c` | 21997 | **否（未跟踪，冻结须显式纳入）** |
| 25 | `backend/tests/evaluation/test_p2_release_gate_real_ncu.py` | `8901b9aedf5fcf9987ec1f2d43044a103370b8aceb87d6ea1136dc09988c54d7` | 11510 | **否（未跟踪，冻结须显式纳入）** |
| 26 | `backend/tests/evaluation/test_p2_hard_evidence.py` | `f82046612427cbbee1d1694e7a843b238f2756875b45bb253cb5d96f305d48de` | 183239 | **否（未跟踪，冻结须显式纳入）** |
| 27 | `backend/tests/evaluation/test_p2_holdout_scenarios.py` | `ea1a63dc8d5d6e67258160aeb1b3c4c2721a4033955a413a73d8ebc680d00199` | 37029 | 是 |
| 28 | `backend/tests/evaluation/test_p2_h2_docforbidden_identity.py` | `22004b466bca7b0154f527bc8ebe68caabc4d4e1419cc553ba2b4d665b086b8f` | 32592 | **否（未跟踪，冻结须显式纳入）** |
| 29 | `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/report.md` | `adc8cb0cc73902a7cb443d26b5ed81ef39433cad7623232fa0aa211c1b329499` | 57118 | **否（未跟踪，冻结须显式纳入）** |
| 30 | `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/review.md` | `0e074bcbf44dc1dbbf43b5dc2a4e95f218510fee46c4567abfb49bb9b6e9f48c` | 63050 | **否（未跟踪，冻结须显式纳入）** |
| 31 | `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/gate-result.real-ncu.json` | `d4c98f92c0873addbda01b28394b292b3fcd4bdec2aa39a25af6b8384ba66461` | 53053 | **否（未跟踪，冻结须显式纳入）** |
| 32 | `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/inputs.template.json` | `a29b6426a1215daea909939277c884c43b84e7bd1546c8d4819f2c684c6d90ab` | 928 | **否（未跟踪，冻结须显式纳入）** |
| 33 | `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py` | `3d7ca62bf1ca217c02aa50ed70425015ffc08d1c34808ab54ebcfc539528f923` | 12674 | **否（未跟踪，冻结须显式纳入）** |
| 34 | `docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/build_template_inputs.py` | `314d8fb9146ab0067ce1c65d71473ef5bf3ef0ad073ba5021c6582bbbc433d32` | 2481 | **否（未跟踪，冻结须显式纳入）** |
| 35 | `docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/report.md` | `bf448b0ebc4e2bf54207c0a442d0277256c2fd3f3dc3ae4155696c9c4b8a4127` | 36046 | **否（未跟踪，冻结须显式纳入）** |
| 36 | `docs/reports/OBS-EVAL/P2/H2-DOC-REBUILD/review.md` | `9c0c641260c0c89fcd3e1af1f1d7253705e13373d8fc9e89a99fe8778079b0ac` | 35878 | **否（未跟踪，冻结须显式纳入）** |
| 37 | `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/report.md` | `1314683fac1cb31a7cc1206413d9fa1123e2107b25a3204a92547301de14a1d9` | 46561 | **否（未跟踪，冻结须显式纳入）** |
| 38 | `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/review.md` | `8deb31b48933278ac88f3ec4e6c069776b99a7c23f69491acebed811c7c55a11` | 36330 | **否（未跟踪，冻结须显式纳入）** |
| 39 | `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/cards-index.json` | `f20661d23822b6ad2f11d70feb21b818dc8f08843da80c2ccd0e3e5a57e1e487` | 1301 | **否（未跟踪，冻结须显式纳入）** |
| 40 | `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/h2-composition-aggregate.json` | `096de42fd573c107f97fa247cc8157ed191bdce2b32a2e26eb6d3b9c680e1c94` | 4102 | **否（未跟踪，冻结须显式纳入）** |
| 41 | `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/h2-source-proof.json` | `359c9554ab78176abd0588c8d129a47f598c183d3e7eae1a93a3b28730461a90` | 6530 | **否（未跟踪，冻结须显式纳入）** |
| 42 | `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/h2-source-proof.full.json` | `f6465fcb206821f26d51c5f93918aefe229908120cd4708917424e9ebb61d555` | 5167 | **否（未跟踪，冻结须显式纳入）** |
| 43 | `docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS/scripts/derive_v3_cards.py` | `315a389cc174766340d03f006b308266a36cce6e4c56529afaf5ca0c98476861` | 24149 | **否（未跟踪，冻结须显式纳入）** |
| 44 | `docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/report.md` | `52c33b1475eec177c017f5855afb6529be4afc89137ae492330ea91f05ca5cd3` | 58861 | **否（未跟踪，冻结须显式纳入）** |
| 45 | `docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/manifest.json` | `0129cd2ba6abf625c61afaaf958ae2e30e675977ad3045eb381d568ab4ab3fab` | 141097 | **否（未跟踪，冻结须显式纳入）** |
| 46 | `docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/review.md` | `d59499741bfaab13b90ff6415234d0d0ca78af2c11818284dae54f6bb2005370` | 34045 | **否（未跟踪，冻结须显式纳入）** |
| 47 | `docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/SHA256SUMS` | `746fa6633186356c0795583d8dccb84bb0414c94d39d7a5cb4a65f8dbac55b01` | 1598 | **否（未跟踪，冻结须显式纳入）** |

## 二、`records_append_only`（允许仅追加，旧内容不得改写）

校验规则：`sha256(current[0:bytes_at_freeze]) == sha256_at_freeze`。

| # | 路径 | 冻结时字节 | 冻结时 SHA-256 |
| --- | --- | --- | --- |
| 1 | `docs/reports/OBS-EVAL/P2/manager-decisions.md` | 16145 | `fee1f5ec4718aca2e40c4ca58ff6c703b515d33b549dd70d6123e9f24240dfbf` |
| 2 | `docs/reports/OBS-EVAL/P2/manager-acceptance.md` | 21633 | `13339d09559f7ba48f5b78453d09a08b5c3561ece58b16cc99c0291b6248f14d` |

## 冻结声明

1. `frozen_artifacts` 以字节为准；任何变动即候选漂移，须重新冻结并定向复验。
2. `records_append_only` 是经理记录类文档，允许追加（核收、决定、复验结果）；判据是**前缀不变**，不是字节不变。旧内容被改写即视为篡改。
3. `docs/evaluation/gate_v0_3_approved.json` 未跟踪，冻结/归档必须显式取件。
4. 门禁 JSON 的 47 行行 id 集合已入册；`hard_gate_min_sample.run_level_subset` 是**要求的披露行**，消费方不得删除。单读 `technical_gate=pass` 而不读该行，会误读为「10 条 run 级证据都过了门」。
5. 技术门通过只作 T900 独立验收输入；发布由主人决定（`release_allowed=false`、`owner_release_decision=not_decided`）。
6. 本清单取代 v0.1；v0.1 的 `candidate_drift` 事故见 `manager-acceptance.md` D-012。
