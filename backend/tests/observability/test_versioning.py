"""T001：版本绑定 / 配置摘要 / 问题哈希锁定测试（设计 §6.5 / §7.3）。

只依赖契约与版本模块：不建索引、不读 .env、不访问网络、不调用模型 / OCR / embedding / rerank。
"""

from __future__ import annotations

import ast
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from mktkb.observability.versioning import (
    CONFIG_HASH_FIELDS,
    config_hash,
    hash_question,
    key_fingerprint,
    pipeline_version,
)

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
OBSERVABILITY_ROOT = SRC_ROOT / "mktkb" / "observability"
HEX12 = re.compile(r"[0-9a-f]{12}")


# ---- §5.4 pipeline_version ----


def test_pipeline_version_is_deterministic_for_same_components():
    base = {
        "embedding_model": "text-embedding-v4",
        "embedding_dimensions": 1024,
        "top_k": 8,
        "prompt": "A",
    }
    assert pipeline_version(base) == pipeline_version(dict(base))
    assert HEX12.fullmatch(pipeline_version(base))


def test_pipeline_version_changes_with_prompt_or_config():
    base = {
        "embedding_model": "text-embedding-v4",
        "embedding_dimensions": 1024,
        "top_k": 8,
        "prompt": "A",
    }
    assert pipeline_version(base) != pipeline_version({**base, "prompt": "B"})
    assert pipeline_version(base) != pipeline_version({**base, "top_k": 12})


def test_pipeline_version_renders_canonical_json_independent_of_key_order():
    left = {"top_k": 8, "embedding_model": "m", "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "embedding_model": "m", "top_k": 8}
    assert pipeline_version(left) == pipeline_version(right)


VERSION_SOURCES = [
    ("mktkb.qa.service", "QA_ENGINE_VERSION"),
    ("mktkb.rag.index", "SCHEMA_VERSION"),
    ("mktkb.rag.index", "INDEX_CACHE_VERSION"),
    ("mktkb.retrieval.tokenize", "TOKENIZER_VERSION"),
]


@pytest.mark.parametrize(("module_name", "attribute"), VERSION_SOURCES)
def test_default_components_are_imported_lazily_at_call_time(monkeypatch, module_name, attribute):
    """若常量在模块顶层 import，monkeypatch 源模块不会影响已绑定值，此测试会失败。"""
    module = importlib.import_module(module_name)
    baseline = pipeline_version()
    monkeypatch.setattr(module, attribute, "t001-probe-lazy-version")
    assert pipeline_version() != baseline


def test_default_pipeline_version_is_hex12():
    assert HEX12.fullmatch(pipeline_version())


def test_module_level_imports_are_stdlib_only():
    """模块顶层 import 不引入业务包（qa/rag/conversations/main 等），避免循环导入。"""
    for filename in ("contracts.py", "versioning.py"):
        tree = ast.parse((OBSERVABILITY_ROOT / filename).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in sys.stdlib_module_names, f"{filename} 顶层 import 非 stdlib: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{filename} 顶层不允许相对 import"
                assert node.module is not None
                root = node.module.split(".")[0]
                assert root in sys.stdlib_module_names, f"{filename} 顶层 import 非 stdlib: {node.module}"


def test_package_imports_cleanly_in_fresh_process():
    code = (
        "from mktkb.observability import TRACE_SCHEMA_VERSION, pipeline_version\n"
        "print(TRACE_SCHEMA_VERSION)\n"
        "print(pipeline_version())\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.strip().splitlines()
    assert lines[-2] == "mktkb.trace.v0.1"
    assert HEX12.fullmatch(lines[-1])


# ---- §5.5 hash_question ----


def test_hmac_hash_requires_key():
    with pytest.raises(ValueError):
        hash_question("城东店", key=b"", algo="hmac-sha256")
    with pytest.raises(ValueError):
        hash_question("城东店", key=None, algo="hmac-sha256")  # type: ignore[arg-type]


def test_hash_question_does_not_return_raw_text():
    digest = hash_question("城东店", key=b"k" * 32, algo="hmac-sha256")
    assert "城东店" not in digest
    assert len(digest) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_hmac_hash_is_key_dependent_and_deterministic():
    first = hash_question("城东店海报", key=b"k" * 32, algo="hmac-sha256")
    assert first == hash_question("城东店海报", key=b"k" * 32, algo="hmac-sha256")
    assert first != hash_question("城东店海报", key=b"j" * 32, algo="hmac-sha256")
    assert first != hash_question("城东店海报", key=b"k" * 31, algo="hmac-sha256")


def test_sha256_allows_empty_key():
    digest = hash_question("合成语料问题", key=b"", algo="sha256")
    assert len(digest) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert "合成语料问题" not in digest


def test_sha256_ignores_key_material():
    assert hash_question("q", key=b"", algo="sha256") == hash_question("q", key=b"secret", algo="sha256")


def test_hash_question_rejects_unknown_algo():
    with pytest.raises(ValueError):
        hash_question("q", key=b"k", algo="md5")  # type: ignore[arg-type]


def test_hash_question_rejects_non_string_question():
    with pytest.raises(TypeError):
        hash_question(b"not-text", key=b"k", algo="hmac-sha256")  # type: ignore[arg-type]


def test_key_fingerprint_is_stable_and_does_not_reveal_key():
    key = b"real-hmac-key-material-0123456789"
    first = key_fingerprint(key)
    assert HEX12.fullmatch(first)
    assert first == key_fingerprint(bytes(key))
    assert first != key_fingerprint(b"another-hmac-key-material-98765")
    assert key.decode("ascii") not in first
    assert key.hex() not in first


def test_key_fingerprint_rejects_empty_key():
    with pytest.raises(ValueError):
        key_fingerprint(b"")


# ---- §5.6 config_hash ----


@pytest.mark.parametrize(
    "secret_name",
    ["api_key", "API_KEY", "embedding_api_key", "secret", "client_secret", "access_token", "db_password", "Password"],
)
def test_config_hash_rejects_secret_keys(secret_name):
    with pytest.raises(ValueError):
        config_hash({secret_name: "should-never-be-hashed"})
    with pytest.raises(ValueError):
        config_hash({"top_k": 8, secret_name: "should-never-be-hashed"})


def test_config_hash_whitelist_is_documented_and_content_affecting():
    assert CONFIG_HASH_FIELDS, "白名单不能为空"
    assert {"top_k", "embedding_model", "rerank_model", "chunk_max_chars"} <= set(CONFIG_HASH_FIELDS)
    for name in CONFIG_HASH_FIELDS:
        assert config_hash({name: "value-a"}) != config_hash({name: "value-b"}), name


def test_config_hash_deterministic_and_hex12():
    config = {"top_k": 8, "embedding_model": "text-embedding-v4", "hard_filters": ["store", "item"]}
    assert config_hash(config) == config_hash(dict(config))
    assert HEX12.fullmatch(config_hash(config))


def test_config_hash_ignores_fields_outside_whitelist():
    base = {"top_k": 8, "embedding_model": "text-embedding-v4"}
    assert config_hash({**base, "unrelated_metadata": "x"}) == config_hash(base)


def test_config_hash_accepts_empty_config():
    assert HEX12.fullmatch(config_hash({}))


def test_config_hash_does_not_contain_raw_values():
    digest = config_hash({"embedding_model": "text-embedding-v4"})
    assert "text-embedding-v4" not in digest
