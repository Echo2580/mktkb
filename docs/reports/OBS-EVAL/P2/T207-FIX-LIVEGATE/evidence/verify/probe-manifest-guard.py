
import os, sys
from pathlib import Path
REPO = Path(r"D:/GPT项目/市场部AI知识库")
sys.path.insert(0, str(REPO / "backend" / "src"))
from mktkb.evaluation import p2_dataset as ds

root = Path(r"D:/mktkb-p2-holdout")
root_manifest = Path(r"D:/mktkb-p2-holdout/v2/manifest.json")
repo_manifest = REPO / "docs" / "evaluation" / "p2-holdout-v2.manifest.json"

print("HOLDOUT_ROOT_ENV =", ds.HOLDOUT_ROOT_ENV, "| HOLDOUT_KEY_FILE_ENV =", ds.HOLDOUT_KEY_FILE_ENV)
print("root_manifest inside root ? ", ds._resolve(root_manifest).is_relative_to(ds._resolve(root)))
print("repo_manifest inside root ? ", ds._resolve(repo_manifest).is_relative_to(ds._resolve(root)))

# runbook 规则验证：holdout 加载用 repo 副本必须被拒；且拒绝发生在读取 key/密文之前
os.environ[ds.HOLDOUT_ROOT_ENV] = str(root)
os.environ[ds.HOLDOUT_KEY_FILE_ENV] = str(root / "keys" / "do-not-touch.key")  # 不会被读取：校验先于读 key
try:
    ds.load_p2_dataset(repo_manifest, visibility="holdout")
    print("UNEXPECTED: repo 副本人被接受")
except ds.P2DatasetError as exc:
    print("repo copy rejected:", getattr(exc, "reason", None), "|", str(exc)[:120])
except Exception as exc:
    print("other:", type(exc).__name__, str(exc)[:200])
