"""Read-only preparation; the single plan-private call requires a separate instruction."""
import os
import socket
for name in list(os.environ):
    if name.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy", "node_use_env_proxy"}:
        os.environ.pop(name, None)
def blocked(*_args, **_kwargs):
    raise OSError("network_blocked")
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.create_connection = blocked
socket.getaddrinfo = blocked

import contextlib
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import urllib.request
sys.dont_write_bytecode = True

REPO = pathlib.Path(__file__).resolve().parents[8]
PRIOR = REPO / "docs/reports/OBS-EVAL/P2/H2V3/final/work/recompute_axes_final.py"
LEDGER = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
BUDGET = REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
PREFIX_SHA = "f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014"
LEDGER_SHA = "e007fee3456e5d13f737a82ed29af45eb4707e3576c444e3520d9ca941dc2899"
BUDGET_SHA = "79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e"
HEAD = "97b0066726e5b8d6f94cbc0b63a890084550c106"

@contextlib.contextmanager
def quiet():
    with open(os.devnull, "w", encoding="utf-8") as sink:
        old_out, old_err = os.dup(1), os.dup(2)
        try:
            sys.stdout.flush(); sys.stderr.flush()
            os.dup2(sink.fileno(), 1); os.dup2(sink.fileno(), 2)
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                yield
        finally:
            os.dup2(old_out, 1); os.dup2(old_err, 2)
            os.close(old_out); os.close(old_err)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def controls():
    import httpx
    hits = []
    def deny(*_a, **_k):
        hits.append(True)
        raise OSError("network_blocked")
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.create_connection = deny
    socket.getaddrinfo = deny
    tests = (lambda: socket.socket().connect(("127.0.0.1", 9)),
             lambda: urllib.request.build_opener(urllib.request.ProxyHandler({})).open("http://127.0.0.1:9/", timeout=1),
             lambda: httpx.get("http://127.0.0.1:9/", trust_env=False, timeout=1))
    for test in tests:
        n = len(hits)
        try:
            test()
        except Exception:
            pass
        if len(hits) == n:
            raise ValueError("network_control_failed")

def git(*args):
    r = subprocess.run(["git", "--no-optional-locks", *args], cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if r.returncode:
        raise ValueError("git_state_unavailable")
    return r.stdout.decode("utf-8").strip()

def load_prior():
    sys.path.insert(0, str(REPO / "backend/src"))
    spec = importlib.util.spec_from_file_location("custody_plan_prior", PRIOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def prepare():
    controls()
    if pathlib.Path.cwd().resolve() != REPO.resolve():
        raise ValueError("cwd_mismatch")
    if git("rev-parse", "--abbrev-ref", "HEAD") != "codex/p2-e2e" or git("rev-parse", "HEAD") != HEAD:
        raise ValueError("git_identity_mismatch")
    if len(git("status", "--porcelain", "--untracked-files=no").splitlines()) != 25 or git("diff", "--cached", "--name-only"):
        raise ValueError("git_worktree_mismatch")
    if sha(LEDGER) != LEDGER_SHA or sha(BUDGET) != BUDGET_SHA:
        raise ValueError("protection_hash_mismatch")
    prior = load_prior()
    entry = prior.ENTRY
    if entry._ENV_CONFLICT is not None:
        raise ValueError("environment_conflict")
    from mktkb.live_authorization import historical_prefix_sha256
    if historical_prefix_sha256(LEDGER) != PREFIX_SHA:
        raise ValueError("ledger_prefix_mismatch")
    batches = entry._v3_ingest_batch_plan()
    if [batches[s] for s in entry.v2.SCENARIO_ORDER] != [9, 10, 13, 15]:
        raise ValueError("ingest_batches_mismatch")
    dates = entry.run_date.verified_run_dates()
    if [dates[i].business_date for i in (0, 1)] != ["2026-10-15", "2026-07-15"]:
        raise ValueError("business_date_mismatch")
    old_binding = entry.v2._read_json_mapping(prior.WORK / "regen-1500" / "bindings" / "run0-base_b0.binding.json", "old_binding_invalid")
    entry._validate_binding_document(old_binding)
    root = pathlib.Path(old_binding["inputs"]["holdout_manifest"]["path"]).parent.resolve()
    key = pathlib.Path(old_binding["inputs"]["scenario_key_file"]["path"]).resolve()
    output = (prior.WORK / "custody-plan-20261116-single-01").resolve()
    if not root.is_dir() or not key.is_file() or not output.parent.is_dir() or output.exists():
        raise ValueError("private_path_precondition_failed")
    if output == REPO or REPO in output.parents or root == REPO or REPO in root.parents or key == REPO or REPO in key.parents:
        raise ValueError("private_path_boundary_failed")
    records = entry._records_from_paths(root, key)
    if records["ingest_plan"]["sha256"] != old_binding["inputs"]["ingest_plan"]["sha256"]:
        raise ValueError("ingest_binding_mismatch")
    digest = entry.v2.code_digest()
    if digest != entry.v2.code_digest() or sha(LEDGER) != LEDGER_SHA or sha(BUDGET) != BUDGET_SHA:
        raise ValueError("preparation_changed")
    return {"status": "prepared", "code_version": digest, "historical_prefix_sha256": PREFIX_SHA,
            "index_batches": [9, 10, 13, 15], "network_controls": {"socket": True, "urllib": True, "httpx": True},
            "private_output_absent": True, "private_inputs_present": True, "protection_unchanged": True}

def main():
    if sys.argv[1:] != ["--prepare"]:
        print('{"status":"blocked","code":"mode_not_authorized"}')
        return 2
    try:
        with quiet():
            result = prepare()
        print(json.dumps(result, sort_keys=True))
        return 0
    except BaseException:
        print('{"status":"blocked","code":"preparation_failed"}')
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
