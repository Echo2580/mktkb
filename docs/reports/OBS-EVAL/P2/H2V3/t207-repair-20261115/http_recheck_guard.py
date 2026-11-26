"""Force httpx proxy independence for the isolated HTTP regression process."""
import json
import os

import httpx

_counts = {"sync": 0, "async": 0}
_sync_init = httpx.Client.__init__
_async_init = httpx.AsyncClient.__init__


def _sync(self, *args, **kwargs):
    _counts["sync"] += 1
    kwargs["trust_env"] = False
    return _sync_init(self, *args, **kwargs)


def _async(self, *args, **kwargs):
    _counts["async"] += 1
    kwargs["trust_env"] = False
    return _async_init(self, *args, **kwargs)


httpx.Client.__init__ = _sync
httpx.AsyncClient.__init__ = _async


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("HTTP_RECHECK_TRUST_RECEIPT")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"forced_trust_env_false": True, "client_counts": _counts,
                       "exitstatus": int(exitstatus)}, handle, indent=2)
