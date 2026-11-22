import sqlite3
import sys
from pathlib import Path

for raw in sys.argv[1:]:
    p = Path(raw).resolve()
    uri = p.as_uri() + "?mode=ro"
    c = sqlite3.connect(uri, uri=True)
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
    print(p.name, "->", tables)
    for t in tables:
        n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print("   ", t, n)
    c.close()
