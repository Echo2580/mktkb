"""Synthetic direct-RAG observation with a real offline index."""
import socket
import subprocess
import importlib.util
from pathlib import Path

import httpx
import pytest

from mktkb.observability.evaluation_capture import CaptureSink, capture_scope


def test_offline_index_capture_and_guard(rag_index, add_records, monkeypatch):
    attempts = []
    def blocked(*args, **kwargs):
        attempts.append('blocked')
        raise RuntimeError('blocked')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', blocked)
    monkeypatch.setattr(subprocess, 'Popen', blocked)
    add_records([{'标识': 'T01', '门店': '虚构甲店', '物品': '虚构桌', '位置': '虚构一区'}])
    root = Path(__file__).resolve().parents[3]
    def baseline_module(name, filename):
        spec = importlib.util.spec_from_file_location(name, root / '.tmp-r2-obs-baseline' / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    before_answer = baseline_module('mktkb.rag._r2_baseline_answer', 'backend_src_mktkb_rag_answer.py')
    before_retrieval = baseline_module('mktkb.rag._r2_baseline_retrieval', 'backend_src_mktkb_rag_retrieval.py')
    original_search = rag_index.search
    monkeypatch.setattr(rag_index, 'search', lambda p, **kw: before_retrieval.search(rag_index, p, **kw))
    before = before_answer.answer_question(rag_index, '把虚构甲店的所有物品位置列出来', user_id='u', conversation_id='before')
    monkeypatch.setattr(rag_index, 'search', original_search)
    off = rag_index.ask('把虚构甲店的所有物品位置列出来', user_id='u', conversation_id='off')
    sink = CaptureSink()
    with capture_scope(sink):
        on = rag_index.ask('把虚构甲店的所有物品位置列出来', user_id='u', conversation_id='on')
    events = [e['payload'] for e in sink.events if e['kind'] == 'retrieval_observed']
    assert not sink.failed and len(events) == 1
    assert events[0]['candidate_count'] > 0
    assert (off.kind, off.text, off.citations, off.facts) == (on.kind, on.text, on.citations, on.facts)
    assert (before.kind, before.text, before.citations, before.facts) == (on.kind, on.text, on.citations, on.facts)
    for key in ('total', 'returned', 'has_more', 'next_page', 'revision'):
        assert off.diagnostics.get(key) == on.diagnostics.get(key)
        assert before.diagnostics.get(key) == on.diagnostics.get(key)
    assert attempts == []
    with pytest.raises(RuntimeError): socket.create_connection(('203.0.113.1', 9))
    with pytest.raises(RuntimeError): subprocess.Popen(['synthetic'])
    assert attempts == ['blocked', 'blocked']
