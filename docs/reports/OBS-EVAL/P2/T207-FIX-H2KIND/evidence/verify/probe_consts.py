import json
from mktkb.evaluation import p2_scoring as ps
print(json.dumps({"module": ps.__file__, "TOTAL": ps.P2_HOLDOUT_TOTAL, "MIN_PASS": ps.P2_HOLDOUT_MIN_PASS, "HARD_MAX": ps.P2_HOLDOUT_MAX_HARD_FAILURES, "STRATA": dict(ps.P2_HOLDOUT_STRATA), "has_compat": hasattr(ps, "score_public_case")}, sort_keys=True))