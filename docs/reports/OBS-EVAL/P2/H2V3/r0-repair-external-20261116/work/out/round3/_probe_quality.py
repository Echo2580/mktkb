import json,sys,pathlib
q=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print("doc_keys:", sorted(q.keys()))
print("case_fields:", sorted(q["cases"][0].keys()))
print("check_id_totals:", json.dumps(q["check_id_totals"], sort_keys=True))
for c in q["cases"]:
    print(c["case_id"], c["quality_status"], json.dumps(c["failed_check_ids"]))
