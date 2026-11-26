import json,sys,pathlib
q=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
for c in q["cases"]:
    if c["case_id"] in ("H2V3-C12","H2V3-C21","H2V3-C27"):
        print(c["case_id"], json.dumps(c["check_statuses"], ensure_ascii=False, sort_keys=True)[:1200])
