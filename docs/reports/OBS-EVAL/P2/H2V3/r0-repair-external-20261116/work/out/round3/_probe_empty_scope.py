import json,sys,pathlib
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text(encoding="utf-8"))
r=d["runs"][0]
print("compat_empty_scope:", json.dumps(r["compat_empty_scope"], ensure_ascii=False, sort_keys=True))
case=[c for c in r["cases"] if c["case_id"]=="H2V3-C17"][0]
print("C17 keys:", sorted(case.keys()))
print("C17 new_axes keys:", {a: sorted(case["new_axes"][a].keys()) for a in case["new_axes"]})
print("C17 audit:", json.dumps(case["new_axes"]["cross_entity"], ensure_ascii=False, sort_keys=True))
