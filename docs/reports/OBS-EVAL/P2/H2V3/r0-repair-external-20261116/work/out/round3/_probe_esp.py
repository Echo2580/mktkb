import json,sys,pathlib
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text(encoding="utf-8"))
r=d["runs"][0]
for c in r["cases"]:
    if c["case_id"] in ("H2V3-C16","H2V3-C17","H2V3-C26","H2V3-C02","H2V3-C21","H2V3-C27"):
        print(c["case_id"], "esp=", json.dumps(c.get("empty_scope_proof"), ensure_ascii=False, sort_keys=True))
        print("   audit=", json.dumps(c.get("axes_audit_codes"), ensure_ascii=False, sort_keys=True))
        print("   changed=", c.get("changed_axes"))
