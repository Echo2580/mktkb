import json,sys,pathlib
for p in sys.argv[1:]:
    path=pathlib.Path(p)
    try:
        raw=path.read_bytes()
    except OSError:
        print("unreadable", path.name); continue
    try:
        obj=json.loads(raw.decode("utf-8"))
    except Exception as e:
        print("invalid", path.name, "bytes=%d"%len(raw), type(e).__name__); continue
    print("ok", path.name, "bytes=%d"%len(raw), "type=%s"%type(obj).__name__, "keys=%d"%(len(obj) if isinstance(obj,dict) else -1))
