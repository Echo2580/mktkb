"""pytest 插件：把“被请求字段集合”的两个常量还原成修复前的取值（只在内存里）。

用法：``PYTHONPATH=<本目录> pytest <测试> -p oldmode``。用于证明第三轮新增的形状断言
在修复前是红的，且工作树不被改动。
"""

from __future__ import annotations

from mktkb.rag import query as _query

_query._FIELD_LIST_JOINERS = ("和", "及", "以及", "、", "与")
_query._EXTRA_FIELD_ROLE_WORDS.clear()
