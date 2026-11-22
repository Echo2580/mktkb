"""T302：只读运营查询包。

6 个 GET 端点（overview / requests / requests/{id} / documents / documents/{id} /
evaluation-runs），全部仅管理员可读。本包只做查询聚合，不写业务库、不写 Trace 库、
不发起评测、不调用外部服务；时间统一按 ``Asia/Shanghai`` 聚合为左闭右开 UTC 窗口。
"""

from .routes import router

__all__ = ["router"]
