
import sys, json
sys.path.insert(0, r"backend/src")
from mktkb.evaluation import p2_runner as runner
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.product_adapter import P2RunDataset
T1 = "多轮第一问：城东店的宣传海报到底放在哪个区的货架"
T2 = "多轮第二问：那城西店的呢"
case = CaseSpec(case_id="H2V-MT", suite="p2-holdout", split="holdout", stratum="multi_turn",
    business_date="2026-10-28", question="", turns=({"question": T1}, {"question": T2}),
    expected_kind="answer", expected_values=("第二层",), reference_answer="第二层", label_version="p")
ds = P2RunDataset(visibility="holdout", cases=(case,), identity={"dataset_version":"v","label_version":"p",
    "suite":"p2-holdout","manifest_sha256":"f"*64,"case_count":1,"strata":{"multi_turn":1}})
res = {}
for name, payload in {
    "turn1_question": {"blocks":[{"code":"x","evidence":{"note": T1}}]},
    "turn2_question": {"blocks":[{"code":"x","evidence":{"note": T2}}]},
    "reference_answer": {"blocks":[{"code":"x","evidence":{"note":"第二层"}}]},
    "case_id": {"blocks":[{"code":"x","evidence":{"note":"H2V-MT"}}]},
}.items():
    try:
        runner._assert_holdout_scorecard_payload(payload, ds); res[name] = "NOT_CAUGHT"
    except Exception as exc:
        res[name] = f"caught:{getattr(exc,'code',type(exc).__name__)}"
print(json.dumps(res, ensure_ascii=False))
print("scanned_fields:", [f for f in ("question","reference_answer","turns") if hasattr(case,f)])
print("case.question repr:", repr(case.question), "turns:", len(case.turns))
