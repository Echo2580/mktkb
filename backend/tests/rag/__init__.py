"""LOCAL-R1 隔离 RAG 测试包标记。

存在该文件时 pytest（prepend 导入模式）把本目录的 conftest 以 ``rag.conftest``
导入，而不会与 ``tests/conftest.py`` 的顶层模块名 ``conftest`` 冲突。
本文件仅为测试收集/导入消歧，不改变产品行为，也不改变任何安全断言。
"""
