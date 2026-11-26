from dataclasses import replace
from types import SimpleNamespace as NS
import pytest
from mktkb.observability import evaluation_capture as cap
from mktkb.rag import retrieval as r
from mktkb.rag.types import QueryPlan, QueryState
from mktkb.rag.types import RagAnswer, RetrievalResult
from mktkb.rag import answer as a
from mktkb.rag.errors import RagError


def plan(**kw):
    return replace(QueryPlan(question='x', mode='record', query_text='x', field_role=None,
        field_label=None, filters={'item': 'synthetic'}, terms=(), state=QueryState(),
        enumerate=True, field_roles=('location', 'status')), **kw)


def chunk(kind, uid, store='store'):
    return NS(entity_type=kind, record_unit_id=uid, chunk_id=uid, filters_norm={'store': store}, role_values={})


@pytest.mark.parametrize('p,expected', [
    (plan(mode='document'), 'not_record_or_enumerate'),
    (plan(enumerate=False), 'not_record_or_enumerate'),
    (plan(field_roles=('location',)), 'roles_not_cross_level'),
    (plan(filters={}), 'item_filter_missing'),
    (plan(state=QueryState(items=('a', 'b'))), 'multiple_items'),
    (plan(state=QueryState(stores=('a', 'b'))), 'multiple_stores'),
])
def test_conditions(p, expected):
    d = r._store_join_chunks(None, p)
    assert tuple(d) == ('', []) and d.observed == expected


def test_early_and_decisions(monkeypatch):
    monkeypatch.setattr(r, '_base_stmt', lambda *a, **k: None)
    rows = []
    monkeypatch.setattr(r, '_load', lambda *a: rows.pop(0))
    def run(batches):
        rows[:] = batches
        return r._store_join_chunks(None, plan())
    assert run([[]]).observed == 'item_row_not_unique'
    assert run([[chunk('item', 'i', '')]]).observed == 'store_value_missing'
    assert run([[chunk('item', 'i', 'a'), chunk('item', 'i', 'b')]]).observed == 'store_value_ambiguous'
    assert run([[chunk('item', 'i')], []]).observed == 'store_row_missing'
    assert run([[chunk('item', 'i')], [chunk('store', 's'), chunk('store', 't')]]).observed == 'store_row_ambiguous'
    assert run([[chunk('item', 'i')], [chunk('store', 's')]]).observed == 'rows_found'


def test_recall_joined_existing_and_unknown(monkeypatch):
    monkeypatch.setattr(r, '_base_stmt', lambda *a, **k: None)
    row = chunk('store', 's')
    monkeypatch.setattr(r, '_load', lambda *a: [])
    monkeypatch.setattr(r, '_store_join_chunks', lambda *a: r._StoreJoin('synthetic', [row], 'joined', 'rows_found'))
    with cap.capture_scope(cap.CaptureSink()):
        diag = {}; r._exact_recall(None, None, plan(), diag)
        assert diag['store_join_observed'] == 'joined'
        monkeypatch.setattr(r, '_load', lambda *a: [row])
        diag = {}; r._exact_recall(None, None, plan(), diag)
        assert diag['store_join_observed'] == 'already_present'
        monkeypatch.setattr(r, '_store_join_chunks', lambda *a: ('', []))
        diag = {}; r._exact_recall(None, None, plan(), diag)
        assert diag['store_join_observed'] == 'unknown'


def test_schema_legacy_and_sentinels():
    old = {'request_id': None, 'scope': 'synthetic', 'unit_ids': [], 'candidate': True, 'truncated': False, 'empty': True}
    assert cap.clean_event_payload('retrieval_observed', old) == old
    new = {**old, 'effective_roles': ['location'], 'role_unknown_count': 1, 'roles_state': 'available', 'stores_state': 'unknown', 'stores_count': None, 'store_join_status': 'unknown', 'candidate_count': 0, 'page_has_more': False}
    assert cap.clean_event_payload('retrieval_observed', new) == new
    for key, value in (('effective_roles', ['SECRET_SENTINEL']), ('store_join_status', 'SECRET_SENTINEL'), ('candidate_count', -1)):
        with pytest.raises(cap.CaptureEventError):
            cap.clean_event_payload('retrieval_observed', {**new, key: value})
    assert cap.safe_roles(['location', 'SECRET_SENTINEL', object()]) == (['location'], 2)
    assert cap.safe_stores(NS()) == ('unknown', None)
    assert cap.safe_stores(NS(stores=[])) == ('available', 0)


@pytest.mark.parametrize('size,mode', [(0, 'record'), (1, 'document'), (513, 'record')])
def test_answer_event_and_capture_parity(monkeypatch, size, mode):
    p = plan(mode=mode)
    chunks = [NS(chunk_id=str(i), kind='record', record_unit_id=str(i), unit_ids=()) for i in range(size)]
    result = RetrievalResult(plan=p, revision=1, exact=chunks, total=size, has_more=True,
                             diagnostics={'store_join_observed': 'joined'})
    calls = []
    class Index:
        config = NS(provider_mode='offline', page_size=10, record_only=False, business_date=None)
        def load_state(self, *args): return QueryState()
        def lexicon_data(self): return {}
        def search(self, *args, **kwargs): calls.append('search'); return result
        def save_state(self, state): calls.append('save')
    monkeypatch.setattr(a, 'build_lexicon', lambda *args: None)
    monkeypatch.setattr(a, 'parse_query', lambda *args, **kwargs: p)
    monkeypatch.setattr(a, 'financial_metric_question', lambda *args: None)
    monkeypatch.setattr(a, 'FactValidator', lambda *args: None)
    def render(index, plan, result, validator, diagnostics, started):
        return RagAnswer(kind='answer', question='x', text='synthetic', state=plan.state.to_dict(), diagnostics=diagnostics)
    monkeypatch.setattr(a, '_answer_record', render)
    monkeypatch.setattr(a, '_answer_document', render)
    off = a.answer_question(Index(), 'x', user_id='u', conversation_id='c')
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        on = a.answer_question(Index(), 'x', user_id='u', conversation_id='c')
    events = [event for event in sink.events if event['kind'] == 'retrieval_observed']
    assert not sink.failed and len(events) == 1
    payload = events[0]['payload']
    assert payload['candidate_count'] == size and payload['truncated'] == (size > cap.MAX_LIST_ITEMS)
    assert payload['page_has_more'] is True
    assert payload['store_join_status'] == ('not_applicable' if mode == 'document' else 'joined')
    assert (off.kind, off.text, off.citations, off.facts, off.state) == (on.kind, on.text, on.citations, on.facts, on.state)
    assert calls == ['search', 'save', 'search', 'save']


def test_retrieval_exception_emits_no_success(monkeypatch):
    p = plan()
    class Index:
        config = NS(provider_mode='offline', page_size=10, record_only=False, business_date=None)
        def load_state(self, *args): return QueryState()
        def lexicon_data(self): return {}
        def search(self, *args, **kwargs): raise RagError('synthetic')
        def save_state(self, state): pass
    monkeypatch.setattr(a, 'build_lexicon', lambda *args: None)
    monkeypatch.setattr(a, 'parse_query', lambda *args, **kwargs: p)
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        result = a.answer_question(Index(), 'x', user_id='u', conversation_id='c')
    assert result.kind == 'error'
    assert not [e for e in sink.events if e['kind'] == 'retrieval_observed']


def test_pre_retrieval_refusal_has_no_event(monkeypatch):
    p = plan(reason='DOCUMENT_NOT_FOUND')
    calls = []
    class Index:
        config = NS(provider_mode='offline', page_size=10, record_only=False, business_date=None)
        def load_state(self, *args): return QueryState()
        def lexicon_data(self): return {}
        def search(self, *args, **kwargs): calls.append('search')
        def save_state(self, state): calls.append('save')
    monkeypatch.setattr(a, 'build_lexicon', lambda *args: None)
    monkeypatch.setattr(a, 'parse_query', lambda *args, **kwargs: p)
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        result = a.answer_question(Index(), 'x', user_id='u', conversation_id='c')
    assert result.kind == 'no_answer' and calls == ['save']
    assert not [e for e in sink.events if e['kind'] == 'retrieval_observed']


def test_sink_failure_does_not_change_answer(monkeypatch):
    p = plan()
    result = RetrievalResult(plan=p, revision=1)
    calls = []
    class Index:
        config = NS(provider_mode='offline', page_size=10, record_only=False, business_date=None)
        def load_state(self, *args): return QueryState()
        def lexicon_data(self): return {}
        def search(self, *args, **kwargs): calls.append('search'); return result
        def save_state(self, state): calls.append('save')
    monkeypatch.setattr(a, 'build_lexicon', lambda *args: None)
    monkeypatch.setattr(a, 'parse_query', lambda *args, **kwargs: p)
    monkeypatch.setattr(a, 'financial_metric_question', lambda *args: None)
    monkeypatch.setattr(a, 'FactValidator', lambda *args: None)
    monkeypatch.setattr(a, '_answer_record', lambda i, p, r, v, d, t: RagAnswer(kind='answer', question='x', text='synthetic', state=p.state.to_dict(), diagnostics=d))
    off = a.answer_question(Index(), 'x', user_id='u', conversation_id='c')
    def broken(*args, **kwargs): raise RuntimeError('SECRET_SENTINEL')
    monkeypatch.setattr(a, 'emit_capture_event', broken)
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        on = a.answer_question(Index(), 'x', user_id='u', conversation_id='c')
    assert sink.failed and 'SECRET_SENTINEL' not in str(sink.errors)
    assert (off.kind, off.text, off.state, off.citations, off.facts) == (on.kind, on.text, on.state, on.citations, on.facts)
    assert calls == ['search', 'save', 'search', 'save']


def test_offline_guard_and_positive_controls(monkeypatch):
    import socket
    import subprocess
    import httpx
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
    test_answer_event_and_capture_parity(monkeypatch, 1, 'record')
    assert attempts == []
    with pytest.raises(RuntimeError): socket.create_connection(('203.0.113.1', 9))
    with pytest.raises(RuntimeError): subprocess.Popen(['synthetic'])
    assert attempts == ['blocked', 'blocked']
