"""Independent synthetic direct-RagIndex acceptance; never reads production fixtures."""
from __future__ import annotations

import argparse
import asyncio  # Load stdlib Windows Popen subclass before wrapping launch functions.
import contextlib
import hashlib
import importlib.abc
import importlib.util
import json
import os
import platform
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, replace

BEFORE = {
    'conversations/service.py': '5281d44fb4f9b03eb3cb7d2470aba1513a277950b8650040b6e4d75a6ce9ee92',
    'observability/evaluation_capture.py': '8497fd334bba2c29c378045b047ca26c78d987a39ed43445c73486ea6a27d477',
    'rag/answer.py': 'b89622beb20f0d73849f2af9dab91a54835a24006059b3ff38a8d67b40e20288',
    'rag/retrieval.py': 'd43530922355206746e40316d6dd5a875da6a3081c68db866cffa2d61b2abdaa',
}
AFTER = {
    'conversations/service.py': '8f913cb3b7270c8e0fbf1b6720d95a3a388cf9364bd097d1b192c16f3bf0f6f5',
    'observability/evaluation_capture.py': '24a66783fb622164cf5c22ab79cffb211f7b44f7d97e4a9c6590e1cc7bd4b675',
    'rag/answer.py': '9dd83f275aad5c02526ca2669df8520710e23871930b24774ade01cbeb8d7626',
    'rag/retrieval.py': '3d3c2c4cf475187afd19b3bfc4c76d4d9493c4e628dc5cf3420dd7024a001cd7',
    'rag/query.py': 'bedeedaba966209ea26a37fd3bee60fdb96fea21c87ac33dd7dce5ceb3db6fb0',
    'rag/facts.py': 'cf795cfd16fe15fdfa73f9bc12311cf9bcf55b2fafdb67a9a8f6719192dc7001',
    'qa/service.py': '627c328a62a77a81edd5fbf0b7fa293a63024a1f284bfcce2aece5e2cd9906b1',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def require(value, code):
    if not value:
        raise AssertionError(code)


class BaselineFinder(importlib.abc.MetaPathFinder):
    def __init__(self, directory):
        self.mapping = {'mktkb.' + name[:-3].replace('/', '.'): directory / name for name in BEFORE}

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.mapping:
            return importlib.util.spec_from_file_location(fullname, self.mapping[fullname])


class OfflineGuard:
    """Block communication and process-launch channels before product import."""
    def __init__(self):
        self.phase = 'product'
        self.ledger = {'product': Counter(), 'positive': Counter()}
        self.patches = []
        self.native_connect = socket.socket.connect

    def block(self, code):
        def denied(*args, **kwargs):
            self.ledger[self.phase][code] += 1
            raise RuntimeError('GUARD_BLOCKED')
        return denied

    def patch(self, obj, name, code):
        if hasattr(obj, name):
            original = getattr(obj, name)
            setattr(obj, name, self.block(code))
            self.patches.append((obj, name, original, code))

    def install(self):
        # Audit hook is independent of monkeypatches; arguments are never logged.
        def audit(event, args):
            if event in ('socket.connect', 'socket.sendto', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn'):
                self.block('audit.' + event)()
            if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
                name = os.fsdecode(args[0]).replace('\\', '/').split('/')[-1].lower()
                if name == '.env' or name.startswith('.env.'):
                    self.block('private.env_read')()
        sys.addaudithook(audit)
        for name in ('connect', 'connect_ex', 'send', 'sendall', 'sendto', 'sendmsg'):
            self.patch(socket.socket, name, 'socket.' + name)
        for name in ('create_connection', 'getaddrinfo', 'gethostbyname', 'gethostbyname_ex', 'gethostbyaddr'):
            self.patch(socket, name, 'socket.' + name)
        for name in ('Popen', 'run', 'call', 'check_call', 'check_output', 'getoutput', 'getstatusoutput'):
            self.patch(subprocess, name, 'subprocess.' + name)
        for name in ('system', 'popen', 'startfile', 'spawnl', 'spawnle', 'spawnlp', 'spawnlpe', 'spawnv', 'spawnve', 'spawnvp', 'spawnvpe', 'execl', 'execle', 'execlp', 'execlpe', 'execv', 'execve', 'execvp', 'execvpe', 'posix_spawn', 'posix_spawnp'):
            self.patch(os, name, 'os.' + name)
        import http.client
        import urllib.request
        import httpx
        for cls in (httpx.Client, httpx.AsyncClient):
            self.patch(cls, 'send', 'httpx.' + cls.__name__ + '.send')
        self.patch(httpx.HTTPTransport, 'handle_request', 'httpx.transport')
        self.patch(httpx.AsyncHTTPTransport, 'handle_async_request', 'httpx.async_transport')
        self.patch(http.client.HTTPConnection, 'connect', 'http.connect')
        self.patch(http.client.HTTPConnection, 'request', 'http.request')
        self.patch(http.client.HTTPSConnection, 'connect', 'https.connect')
        self.patch(urllib.request, 'urlopen', 'urllib.urlopen')

    def positive(self):
        self.phase = 'positive'
        # Every installed wrapper is actually called; it cannot touch an OS channel.
        for obj, name, original, code in self.patches:
            try:
                getattr(obj, name)()
            except RuntimeError as exc:
                require(str(exc) == 'GUARD_BLOCKED', 'POSITIVE_WRAPPER_ERROR')
            else:
                raise AssertionError('POSITIVE_NOT_BLOCKED')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as endpoint:
            try:
                self.native_connect(endpoint, ('203.0.113.1', 9))
            except RuntimeError as exc:
                require(str(exc) == 'GUARD_BLOCKED', 'AUDIT_POSITIVE_ERROR')
            else:
                raise AssertionError('AUDIT_POSITIVE_NOT_BLOCKED')
        self.phase = 'product'
        return {phase: dict(sorted(counts.items())) for phase, counts in self.ledger.items()}


def config(directory):
    from mktkb.rag import RagConfig
    return RagConfig(provider_mode='offline', data_dir=directory, business_date='2026-11-17', embedding_dimensions=24, top_k=5, page_size=10, chunk_max_chars=420, chunk_max_units=3, max_retries=0)


def add(index, rows=(), *, kind='item', paragraphs=()):
    from mktkb.rag import AtomicUnit, DocumentSpec
    doc = DocumentSpec(doc_id='synthetic-' + kind, source_path='synthetic/' + kind + '.xlsx', title='虚构验收' + kind, file_kind='docx' if paragraphs else 'xlsx', version_id='synthetic-' + kind + '-v1', version_label='当前', sha256=digest(kind), business_date='2026-11-17')
    units = []
    for number, fields in enumerate(rows):
        units.append(AtomicUnit(unit_id='synthetic-' + kind + '-' + str(number), doc_id=doc.doc_id, version_id=doc.version_id, kind='table_row', ordinal=number, unit_key='row:' + str(number + 2), text='；'.join(str(k) + ':' + str(v) for k, v in fields.items()), fields=fields, sheet='虚构记录', locator={'sheet': '虚构记录', 'row': number + 2, 'header_row': 1}, header_row=1, row_number=number + 2, title=doc.title))
    for number, text in enumerate(paragraphs):
        units.append(AtomicUnit(unit_id='synthetic-' + kind + '-' + str(number), doc_id=doc.doc_id, version_id=doc.version_id, kind='paragraph', ordinal=number, unit_key='paragraph:' + str(number), text=text, fields={}, locator={'paragraph': number + 1}, title=doc.title))
    index.add_document(doc, units, embed=True)


def item(number=0, store='虚构甲店', name='虚构折叠桌'):
    return {'标识': 'SYN-I-' + str(number), '门店': store, '物品': name, '位置': '虚构架' + str(number), '数量': number + 1}


def seed(root):
    from mktkb.rag import QueryState, RagIndex
    seeds = root / 'seeds'
    seeds.mkdir()
    names = ('joined', 'missing', 'ambiguous', 'pagination', 'large', 'document', 'empty', 'multi_item', 'multi_store', 'already_present', 'store_value_missing', 'store_value_ambiguous', 'item_not_unique')
    manifest = {}
    for name in names:
        path = seeds / (name + '.sqlite3')
        index = RagIndex(path, config=config(seeds))
        try:
            if name not in ('empty', 'document'):
                if name == 'pagination':
                    rows = [item(i, name='虚构物品%03d' % i) for i in range(25)]
                elif name == 'large':
                    rows = [item(i, name='虚构物品%03d' % i) for i in range(520)]
                elif name == 'multi_item':
                    rows = [item(), item(1, name='虚构折叠椅')]
                elif name == 'multi_store':
                    rows = [item(), item(1, store='虚构乙店')]
                elif name == 'item_not_unique':
                    rows = [item(), item(1)]
                else:
                    rows = [item()]
                add(index, rows)
                if name != 'missing':
                    stores = [{'标识': 'SYN-S-0', '店家': '虚构甲店', '合作状态': '合作中', '电话': '000-00000000'}]
                    if name == 'ambiguous':
                        stores.append({'标识': 'SYN-S-1', '店家': '虚构甲店', '合作状态': '暂停合作'})
                    add(index, stores, kind='store')
            if name == 'document':
                add(index, kind='policy', paragraphs=['虚构提报制度：每月五日前须提交虚构合作汇总。', '虚构审核要求：材料由虚构部门复核。'])
            # Initial persisted user/session identity and nonzero turn are identical across modes.
            index.save_state(QueryState(user_id='synthetic-user', conversation_id='synthetic-chat', turn=4, page_size=10))
        finally:
            index.close()
        # Persisted deliberately inconsistent metadata exercises otherwise unreachable boundaries.
        if name in ('already_present', 'store_value_missing', 'store_value_ambiguous'):
            with sqlite3.connect(path) as db:
                if name == 'already_present':
                    db.execute("UPDATE rag_chunks SET filters_norm=json_set(filters_norm, '$.item', ?) WHERE entity_type='store'", ('虚构折叠桌',))
                elif name == 'store_value_missing':
                    db.execute("UPDATE rag_chunks SET filters_norm=json_remove(filters_norm, '$.store') WHERE entity_type='item'")
                else:
                    # Duplicate physical chunk, same record identity, distinct normalized store metadata.
                    columns = [row[1] for row in db.execute('PRAGMA table_info(rag_chunks)')]
                    values = list(db.execute("SELECT * FROM rag_chunks WHERE entity_type='item' LIMIT 1").fetchone())
                    values[columns.index('chunk_id')] += '-synthetic-boundary'
                    field_index = columns.index('filters_norm')
                    metadata = json.loads(values[field_index]); metadata['store'] = '虚构乙店'
                    values[field_index] = json.dumps(metadata, ensure_ascii=False)
                    db.execute('INSERT INTO rag_chunks (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', values)
        manifest[name] = {'db_sha256': sha(path)}
    return manifest


def state_hash(path):
    with sqlite3.connect(path) as db:
        rows = db.execute('SELECT * FROM rag_query_state ORDER BY user_id, conversation_id').fetchall()
    return digest(rows)


def business_wrapper(obj, name, counter):
    original = getattr(obj, name)
    def wrapped(*args, **kwargs):
        counter[name] += 1
        return original(*args, **kwargs)
    setattr(obj, name, wrapped)


def union_ids(result):
    chunks = {c.chunk_id: c for c in result.exact + result.lexical + result.vector + [c for c, _ in result.fused]}
    identities = set()
    for chunk in chunks.values():
        if chunk.kind == 'record' and chunk.record_unit_id:
            identities.add(str(chunk.record_unit_id))
        identities.update(str(x) for x in chunk.unit_ids or ())
        if chunk.kind == 'record' and chunk.record_unit_id is None:
            identities.add(str(chunk.chunk_id))
    return sorted(identities)


def answer_snapshot(answer, index, counts, path):
    pagination = {k: answer.diagnostics.get(k) for k in ('total', 'returned', 'has_more', 'next_page', 'page', 'page_size', 'revision')}
    return {'kind': answer.kind, 'reason': answer.reason, 'text_sha256': digest(answer.text), 'sources_sha256': digest([asdict(x) for x in answer.citations]), 'facts_sha256': digest([asdict(x) for x in answer.facts]), 'state_sha256': digest(answer.state), 'persisted_state_sha256': state_hash(path), 'pagination': pagination, 'revision': index.revision(), 'business_calls': dict(sorted(counts.items())), 'citation_count': len(answer.citations), 'fact_count': len(answer.facts)}


def run_matrix(root, mode):
    from mktkb.rag import QueryState, QueryPlan, RagIndex
    from mktkb.rag.models import RagChunk
    from mktkb.observability.evaluation_capture import CaptureSink, capture_scope
    from sqlalchemy import event
    class FailureSink(CaptureSink):
        def emit(self, kind, payload):
            if kind == 'retrieval_observed':
                raise RuntimeError('SYNTHETIC_SINK_FAILURE')
            return super().emit(kind, payload)
    results = {}
    directory = root / mode
    directory.mkdir()
    def open_index(seed_name, case):
        dbpath = directory / (case + '.sqlite3')
        seedpath = root / 'seeds' / (seed_name + '.sqlite3')
        shutil.copy2(seedpath, dbpath)
        initial_hash = sha(dbpath)
        require(initial_hash == sha(seedpath), 'INITIAL_DB_MISMATCH')
        index = RagIndex(dbpath, config=config(directory))
        counts = Counter()
        for method in ('load_state', 'save_state', 'lexicon_data', 'revision', 'search'):
            business_wrapper(index, method, counts)
        business_wrapper(index.embedder, 'embed', counts)
        business_wrapper(index.reranker, 'rerank', counts)
        return index, counts, dbpath, initial_hash
    def ask_case(case, seed_name, questions, *, drift=False):
        index, counts, dbpath, initial_hash = open_index(seed_name, case)
        initial_state = state_hash(dbpath)
        search_results = []
        original_search = index.search
        def recorded_search(*args, **kwargs):
            value = original_search(*args, **kwargs)
            search_results.append(value)
            return value
        index.search = recorded_search
        if drift:
            triggered = [False]
            def concurrent_revision(connection, cursor, statement, parameters, context, many):
                if not triggered[0] and counts['search'] and 'FROM rag_chunks' in statement:
                    triggered[0] = True
                    with sqlite3.connect(dbpath, timeout=2) as other:
                        other.execute("UPDATE rag_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
            event.listen(index.engine, 'before_cursor_execute', concurrent_revision)
        sink = FailureSink() if mode == 'failure' else CaptureSink()
        answers, snapshots = [], []
        try:
            scope = capture_scope(sink) if mode in ('on', 'failure') else contextlib.nullcontext()
            with scope:
                for question in questions:
                    answer = index.ask(question, user_id='synthetic-user', conversation_id='synthetic-chat')
                    answers.append(answer)
                    snapshots.append(answer_snapshot(answer, index, counts, dbpath))
            captured = [x['payload'] for x in sink.events if x['kind'] == 'retrieval_observed' and x['payload']['scope'] == 'direct_rag_retrieval']
            success = len(search_results)
            if mode == 'on':
                require(not sink.failed, case + '.SINK_FAILED')
                require(len(captured) == success, case + '.EVENT_SEARCH_MISMATCH')
                for payload, retrieval in zip(captured, search_results):
                    identities = union_ids(retrieval)
                    require(payload['candidate_count'] == len(identities), case + '.CANDIDATE_COUNT')
                    require(payload['unit_ids'] == identities[:512], case + '.CANDIDATE_IDS')
                    require(payload['truncated'] == (len(identities) > 512), case + '.TRUNCATION')
                    require(payload['empty'] == (not identities), case + '.EMPTY')
                    require(payload['page_has_more'] == retrieval.has_more, case + '.PAGE_MORE')
            if mode == 'failure' and success:
                require(sink.failed and not captured, case + '.FAULT_NOT_EXERCISED')
            results[case] = {'boundary': 'public_ask', 'core': {'initial_db_sha256': initial_hash, 'initial_state_sha256': initial_state, 'answers': snapshots}, 'observation': {'search_attempts': counts['search'], 'search_successes': success, 'events': len(captured), 'sink_failed': sink.failed, 'statuses': [x['store_join_status'] for x in captured], 'candidate_counts': [x['candidate_count'] for x in captured], 'truncated': [x['truncated'] for x in captured], 'page_has_more': [x['page_has_more'] for x in captured], 'empty': [x['empty'] for x in captured], 'effective_modes': [x['effective_mode'] for x in captured]}}
            (root / (mode + '-progress.json')).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
            if case == 'pre_refusal':
                require(counts['search'] == 0 and answers[0].reason == 'SECURITY_RESTRICTED_CONTACT', 'REFUSAL_NOT_REACHED')
            if case == 'search_exception':
                require(triggered[0] and counts['search'] == 1 and success == 0 and answers[0].reason == 'KNOWLEDGE_CHANGED', 'REAL_SEARCH_ERROR_NOT_REACHED')
        finally:
            index.close()
    cross = '虚构折叠桌的位置在哪里，合作状态分别是什么？'
    for name in ('joined', 'missing', 'ambiguous'):
        ask_case(name, name, [cross])
    ask_case('pagination', 'pagination', ['把虚构甲店的所有物品位置列出来', '下一页', '下一页'])
    ask_case('large', 'large', ['把虚构甲店的所有物品位置列出来'])
    ask_case('document', 'document', ['虚构提报要求是怎么规定的？'])
    ask_case('empty', 'empty', ['虚构提报要求是怎么规定的？'])
    ask_case('pre_refusal', 'joined', ['虚构甲店的虚构折叠桌电话是多少？'])
    ask_case('search_exception', 'joined', [cross], drift=True)
    ask_case('multi_item_ask', 'multi_item', ['虚构折叠桌和虚构折叠椅分别在哪个位置，合作状态分别是什么？'])

    def plan_case(case, seed_name='joined', *, enumerate=True, roles=('location', 'status'), filters=None, items=(), stores=(), primary=None):
        index, counts, dbpath, initial_hash = open_index(seed_name, case)
        initial_state = state_hash(dbpath)
        state = QueryState(user_id='synthetic-user', conversation_id='synthetic-chat', items=items, stores=stores, as_of='2026-11-17', enumerate=enumerate, field_roles=roles)
        plan = QueryPlan(question='虚构边界查询', mode='record', query_text='虚构边界查询', field_role=primary, field_label=None, filters={'item': '虚构折叠桌'} if filters is None else filters, terms=(), state=state, enumerate=enumerate, field_roles=roles)
        sink = CaptureSink()
        try:
            with capture_scope(sink) if mode in ('on', 'failure') else contextlib.nullcontext():
                value = index.search(plan)
            payload = value.diagnostics.get('store_join')
            core = {'initial_db_sha256': initial_hash, 'initial_state_sha256': initial_state, 'persisted_state_sha256': state_hash(dbpath), 'revision': value.revision, 'business_calls': dict(sorted(counts.items())), 'exact_sha256': digest([asdict(x) for x in value.exact]), 'lexical_sha256': digest([asdict(x) for x in value.lexical]), 'vector_sha256': digest([asdict(x) for x in value.vector]), 'fused_sha256': digest([(asdict(c), score) for c, score in value.fused]), 'evidence_sha256': digest([asdict(x) for x in value.evidence]), 'store_join_sha256': digest(payload), 'total': value.total, 'returned': value.returned, 'has_more': value.has_more, 'next_page': value.next_page}
            results[case] = {'boundary': 'real_index_search_constructed_plan', 'core': core, 'observation': {'status': value.diagnostics.get('store_join_observed'), 'search_attempts': counts['search'], 'events': len([e for e in sink.events if e['kind'] == 'retrieval_observed']), 'exact_count': len(value.exact), 'state_unchanged': state_hash(dbpath) == initial_state, 'synthetic_metadata_inconsistency': seed_name in ('already_present', 'store_value_missing', 'store_value_ambiguous')}}
            (root / (mode + '-progress.json')).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
            if mode in ('on', 'failure'):
                require(value.diagnostics.get('store_join_observed') == case.replace('plan_', ''), case + '.STATUS_NOT_REACHED')
                require(not sink.failed, case + '.SEARCH_SINK_FAILED')
        finally:
            index.close()
    plan_case('plan_not_record_or_enumerate', enumerate=False)
    plan_case('plan_roles_not_cross_level', roles=('location',))
    plan_case('plan_item_filter_missing', filters={})
    plan_case('plan_multiple_items', 'multi_item', items=('虚构折叠桌', '虚构折叠椅'))
    plan_case('plan_multiple_stores', 'multi_store', stores=('虚构甲店', '虚构乙店'))
    plan_case('plan_item_row_not_unique', 'item_not_unique')
    plan_case('plan_store_value_missing', 'store_value_missing')
    plan_case('plan_store_value_ambiguous', 'store_value_ambiguous')
    plan_case('plan_already_present', 'already_present')
    # Normal-ingestion invariant proof over every healthy persisted record chunk.
    invariant_rows = invariant_violations = 0
    for name in ('joined', 'missing', 'ambiguous', 'pagination', 'large', 'multi_item', 'multi_store', 'item_not_unique'):
        with sqlite3.connect(root / 'seeds' / (name + '.sqlite3')) as db:
            for entity, raw in db.execute('SELECT entity_type, filters_norm FROM rag_chunks'):
                metadata = json.loads(raw)
                invariant_rows += 1
                invariant_violations += int((entity == 'store' and bool(metadata.get('item'))) or (entity == 'item' and not metadata.get('store')))
    require(invariant_violations == 0, 'INGEST_INVARIANT_VIOLATED')
    return {'cases': results, 'ingest_invariant': {'rows': invariant_rows, 'violations': invariant_violations}}


def worker(args):
    root = Path(args.root)
    workspace = Path(args.workspace)
    temp = root / ('runtime-' + args.mode)
    temp.mkdir()
    tempfile.tempdir = str(temp)
    os.environ['TEMP'] = str(temp)
    os.environ['TMP'] = str(temp)
    sys.path.insert(0, str(workspace / 'backend/src'))
    # SQLAlchemy imports platform.machine(), whose Windows fallback launches cmd.
    # Explicit dependency-only fixture avoids host probing; no retrieval result is replaced.
    platform._uname_cache = platform.uname_result('Windows', 'synthetic', '10', 'synthetic', 'AMD64')
    if args.mode == 'baseline':
        finder = BaselineFinder(root / 'baseline-source')
        sys.meta_path.insert(0, finder)
    guard = OfflineGuard()
    guard.install()
    import mktkb.rag.answer as answer
    import mktkb.rag.retrieval as retrieval
    import mktkb.observability.evaluation_capture as capture
    import mktkb.conversations.service as conversations
    modules = {'rag/answer.py': answer, 'rag/retrieval.py': retrieval, 'observability/evaluation_capture.py': capture, 'conversations/service.py': conversations}
    identity = {}
    for name, module in modules.items():
        expected_path = (root / 'baseline-source' / name if args.mode == 'baseline' else workspace / 'backend/src/mktkb' / name).resolve()
        require(Path(module.__file__).resolve() == expected_path, 'SOURCE_ORIGIN_MISMATCH')
        expected_hash = BEFORE[name] if args.mode == 'baseline' else AFTER[name]
        require(sha(expected_path) == expected_hash, 'SOURCE_HASH_MISMATCH')
        identity[name] = {'sha256': expected_hash, 'origin_matches': True}
    require(hasattr(capture, 'safe_roles') == (args.mode != 'baseline'), 'SOURCE_SYMBOL_NEGATIVE_CONTROL')
    require(('store_join_observed' in Path(retrieval.__file__).read_text(encoding='utf-8')) == (args.mode != 'baseline'), 'SOURCE_TEXT_NEGATIVE_CONTROL')
    require(('MAX_LIST_ITEMS' in Path(answer.__file__).read_text(encoding='utf-8')) == (args.mode != 'baseline'), 'ANSWER_NEGATIVE_CONTROL')
    result = {'source_identity': identity, 'negative_source_control': True}
    if args.mode == 'seed':
        result['seed_manifest'] = seed(root)
    else:
        result.update(run_matrix(root, args.mode))
    result['guard'] = guard.positive()
    require(sum(result['guard']['product'].values()) == 0, 'PRODUCT_OUTBOUND_ATTEMPT')
    result['ok'] = True
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--mode', required=True)
    parser.add_argument('--output', required=True)
    options = parser.parse_args()
    try:
        worker(options)
    except BaseException as error:
        # Do not echo synthetic identities, raw payloads, environments, or secrets.
        import traceback
        frames = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name} for f in traceback.extract_tb(error.__traceback__)]
        Path(options.output).write_text(json.dumps({'ok': False, 'exception_type': type(error).__name__, 'failure_code': str(error) if isinstance(error, AssertionError) else 'WORKER_EXCEPTION', 'failure_sha256': digest(str(error)), 'stack': frames}, indent=2), encoding='utf-8')
        raise SystemExit(1)
