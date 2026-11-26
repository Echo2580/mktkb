import json,sys,pathlib
d=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print("keys:", sorted(d.keys()))
def walk(name, node, depth=0):
    if depth>2: return
    if isinstance(node, dict):
        for k,v in node.items():
            if isinstance(v,(dict,list)):
                print("  "*depth, name+"."+k, type(v).__name__, len(v))
                walk(k, v, depth+1)
            else:
                print("  "*depth, name+"."+k, "=", (v if isinstance(v,(int,bool)) or (isinstance(v,str) and len(v)<=40 and (v.replace("_","").replace("-","").isalnum())) else type(v).__name__))
    elif isinstance(node, list):
        print("  "*depth, name, "list len", len(node))
walk("receipt", d)
