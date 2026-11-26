# 保护文件和交付 SHA-256

结束字节；本次仅修改 evaluation_capture.py。

- `backend/src/mktkb/observability/evaluation_capture.py`: `24a66783fb622164cf5c22ab79cffb211f7b44f7d97e4a9c6590e1cc7bd4b675`
- `backend/src/mktkb/conversations/service.py`: `8f913cb3b7270c8e0fbf1b6720d95a3a388cf9364bd097d1b192c16f3bf0f6f5`
- `backend/src/mktkb/rag/answer.py`: `9dd83f275aad5c02526ca2669df8520710e23871930b24774ade01cbeb8d7626`
- `backend/src/mktkb/rag/retrieval.py`: `3d3c2c4cf475187afd19b3bfc4c76d4d9493c4e628dc5cf3420dd7024a001cd7`
- `backend/src/mktkb/rag/query.py`: `bedeedaba966209ea26a37fd3bee60fdb96fea21c87ac33dd7dce5ceb3db6fb0`
- `backend/src/mktkb/rag/facts.py`: `cf795cfd16fe15fdfa73f9bc12311cf9bcf55b2fafdb67a9a8f6719192dc7001`
- `backend/src/mktkb/qa/service.py`: `627c328a62a77a81edd5fbf0b7fa293a63024a1f284bfcce2aece5e2cd9906b1`

开工 `evaluation_capture.py`：`7429be11226916419d8061241b6284b6b9b2a0e8467cb8aae37646d81a1967c1`。

## 交付文件

- `patches/cumulative-rollback.json`: `4ab3397ba3fa6a672d79f91bbf244e710276e6df42920d820c3bb38ac54ad310`
- `patches/cumulative-rollback.patch`: `497029bf64b6014a0f51ff7ad97002bafda0bee8d07d3200e1023f00c6d18902`
- `patches/cumulative-source.json`: `a01d7e359b7fd43b4fc5f59328b829440a5abe9e9a6027827c0a1ea3f98cd65e`
- `patches/cumulative-source.patch`: `d5adf4441cf20b8debd94cbfecfd5820b323627075c81d37df6baeba3b4a14c8`
- `patches/increment-rollback.json`: `907e0fdac45fbfb43348b1052b7ced813f4d7c94d9017cd0751ad27b19531161`
- `patches/increment-rollback.patch`: `3a89ba8f2d15e8ba8787bb1923601f07d60401a7c194769be0848248a00689dc`
- `patches/increment-source.json`: `48998bf07e6e8f84cd850b49500c63f5bf4425a96b08f0fbdc59772370758312`
- `patches/increment-source.patch`: `891c4fd7c308e944a5d2ebb5a8d0c41f1000645fc15389ad16c1a16f53397cd9`
- `SAFE-TOOL.patch`: `e30a5498f099aae11ea69ba95deecbb31b7f8a797a294d5cd9507fc711b7de7e`
- `work/native_patch.py`: `0412731057f45a0d028b33292cfd04d54d5e8a6dac4812b7e0b9c149ecbc4959`
- `work/reproduce_after.py`: `decf4515dfcb8f22ef34029cb9ebe9e889db215f294935d208b69f27eea52d06`
- `work/reproduce_before.py`: `427db7c81fc3864c1c49bbcf9d4b3061de67809e2cb43061041eafbc51d46738`
- `work/reproduce_before_exact.py`: `3e2e926f69ae5b8c0b6f523319f7ba7b2e2969fced614c4010ec6f4baff20fea`
- `work/safe_plan_projection.py`: `486fae88978aa876ade7461948f07883632da523a49bb17fd34a2f222c1375ca`
- `work/test_native_patch.py`: `bf3c08c4af0317a1070e46923517e0437b5c583c5d0a3c147cceaa0b350260d2`
- `work/test_repair1.py`: `e13539d61e731cc6bce4b2ec9ac29720833c2eedb405d62f16c626f057ab0139`

原 SOURCE.patch `2a8e2ad71bc3afc0e7076e58857805924f594d713d016c27eabf3633262f4f4f`；ROLLBACK.patch `e0c68e59d861e116ffd210746fd9c9c1e8354102788153bf7ca1b262296cadab`，与独立验收记录一致。未取得所有旧文件的开工哈希，不能扩大保护结论。
