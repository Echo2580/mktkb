"""验收用突变插件：把 resolve_request_ceiling 退回「旧接线」语义（effective=计划峰值、不 fail closed）。

只用于证明本包新增回归确实能抓住 F-1；不进入任何产品路径。
"""

from __future__ import annotations

import mktkb.evaluation.p2_live as p2_live


def _legacy(config, *, plan_peak_cny: float, authorization_cny: float):
    return p2_live.RequestCeiling(
        plan_peak_cny=float(plan_peak_cny),
        provider_bounds_cny={},
        authorization_cny=float(authorization_cny),
        effective_cny=float(plan_peak_cny),
    )


def pytest_configure(config):  # noqa: D103 - pytest hook
    p2_live.resolve_request_ceiling = _legacy
