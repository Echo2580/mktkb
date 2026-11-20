"""Closed-vocabulary H2 diagnostics. No input text is ever an output key/value."""
from __future__ import annotations

import copy
import re
from collections.abc import Mapping

from ..providers.types import MODEL_FAILURE_REASONS, safe_model_failure_reason

STRATA = ('paraphrase', 'multi_turn', 'negative', 'stale_conflict', 'cross_doc_security')
KINDS = tuple('kind_' + x for x in (
    'answer', 'clarification', 'not_found', 'no_answer', 'refusal', 'conflict',
    'knowledge_changed', 'unknown'))
CHECKS = ('value_hit', 'value_forbidden', 'value_no_fabricated', 'source_hit',
          'source_forbidden', 'kind_correct', 'refusal_expected', 'refusal_unexpected',
          'pagination_total', 'pagination_returned', 'pagination_has_more',
          'pagination_next_page', 'unknown')
ERRORS = ('not_executed', 'unknown', 'mapping_blocked', 'MODEL_OUTPUT_INVALID',
          'MODEL_TIMEOUT', 'MODEL_UNAVAILABLE', 'MODEL_CALL_FAILED', 'MODEL_NOT_CONFIGURED',
          'MODEL_BUDGET_REFUSED', 'QA_INTERNAL_ERROR', 'RETRIEVAL_ERROR', 'REQUEST_CANCELLED',
          'TURN_TIMEOUT', 'source_version_conflict', 'product_kind_missing',
          'case_row_invalid', 'turns_invalid')
STRUCTURAL = ('source_forbidden_document', 'source_outside_run',
              'citation_not_unit_level', 'source_not_active')
HARD_KINDS = ('safety', 'cross_user', 'cross_entity', 'stale_source')
COUNTS = ('planned', 'scored', 'errors', 'not_executed', 'observed', 'unknown_kind')
BLOCKED_DETAIL = 'H2 聚合在受限进程内算不出来/审计失败：按 error 记，不猜通过'


def validate_scorecard(payload, *, total, run_id=None, config_hash=None):
    """Closed full-card boundary; only runner-bound correlation metadata is free text."""
    if isinstance(payload, dict) and payload.get("schema_version") == "mktkb.p2.scoring.v0.2":
        # T207 B 包：显式 versioned 分派到新版四轴硬证据全卡 validator；旧 v0.1 语义不变。
        from .p2_hard_evidence import validate_hard_evidence_scorecard

        return validate_hard_evidence_scorecard(
            payload, total=total, run_id=run_id, config_hash=config_hash
        )
    def require(condition):
        if not condition:
            raise ValueError('holdout_scorecard_invalid')
    def exact(value, keys):
        require(type(value) is dict and set(value) == set(keys))
    def integer(value, maximum=30):
        require(type(value) is int and 0 <= value <= maximum)
    def strata(value, *, buckets=False):
        require(type(value) is dict and set(value) <= set(STRATA))
        for bucket in value.values():
            if buckets:
                exact(bucket, ('total', 'passed', 'failed', 'errors'))
                for count in bucket.values():
                    integer(count)
                require(bucket['total'] == bucket['passed'] + bucket['failed'] + bucket['errors'])
            else:
                integer(bucket)
    exact(payload, ('schema_version', 'total', 'executed', 'errors', 'passed', 'failed',
        'min_pass', 'threshold_met', 'hard_failures', 'hard_failures_max', 'hard_failures_by_kind',
        'by_stratum', 'thresholds_approved', 'detail_export', 'blocks', 'release_ready',
        'execution_mode', 'real_calls', 'run_id', 'config_hash', 'diagnostics'))
    require(payload['schema_version'] == 'mktkb.p2.scoring.v0.1')
    for key in ('total', 'executed', 'errors', 'passed', 'failed', 'min_pass', 'hard_failures', 'hard_failures_max'):
        integer(payload[key])
    require(payload['total'] == total and payload['min_pass'] == 24 and payload['hard_failures_max'] == 0)
    require(payload['executed'] == payload['passed'] + payload['failed'])
    require(total == payload['executed'] + payload['errors'])
    require(payload['hard_failures'] == 0)
    exact(payload['hard_failures_by_kind'], HARD_KINDS)
    require(all(type(x) is int and x == 0 for x in payload['hard_failures_by_kind'].values()))
    strata(payload['by_stratum'], buckets=True)
    for key in ('total', 'passed', 'failed', 'errors'):
        require(payload[key] == sum(b[key] for b in payload['by_stratum'].values()))
    for key in ('threshold_met', 'thresholds_approved', 'detail_export', 'release_ready'):
        require(type(payload[key]) is bool)
    require(payload['threshold_met'] == (total == 30 and payload['passed'] >= 24))
    require(payload['detail_export'] is False and payload['release_ready'] is False)
    require(payload['execution_mode'] in ('live', 'local_mock'))
    integer(payload['real_calls'], 1600)
    require(payload['run_id'] == run_id and (run_id is None or
        (type(run_id) is str and 0 < len(run_id) <= 120 and '\n' not in run_id and '\r' not in run_id)))
    require(payload['config_hash'] == config_hash and (config_hash is None or
        (type(config_hash) is str and re.fullmatch('[0-9a-f]{64}', config_hash) is not None)))
    validate_diagnostics(payload['diagnostics'], total=total)
    d = payload['diagnostics']['counts']
    require(d['scored'] == payload['executed'] and d['errors'] + d['not_executed'] == payload['errors'])
    require(payload['passed'] <= d['observed'])
    for name, counts in payload['diagnostics']['by_stratum'].items():
        bucket = payload['by_stratum'].get(name, dict(total=0, passed=0, failed=0, errors=0))
        require(counts['planned'] == bucket['total']
                and counts['scored'] == bucket['passed'] + bucket['failed']
                and counts['errors'] + counts['not_executed'] == bucket['errors']
                and bucket['passed'] <= counts['observed'])
    require(type(payload['blocks']) is list and len(payload['blocks']) <= 20)
    def evidence_types(value):
        if type(value) is dict:
            for item in value.values():
                evidence_types(item)
        elif type(value) is list:
            require(len(value) <= 30)
            for item in value:
                evidence_types(item)
        elif type(value) is int:
            integer(value, 1600)
        else:
            require(type(value) is str)
    for block in payload['blocks']:
        exact(block, ('code', 'severity', 'detail', 'evidence'))
        code, detail, e = block['code'], block['detail'], block['evidence']
        require(type(code) is str and type(detail) is str and type(e) is dict)
        evidence_types(e)
        require(block['severity'] == ('quality' if code == 'holdout_below_threshold' else 'unknown'))
        if code == 'holdout_sample_missing':
            require(detail == f'H2 样本数 {total} != 冻结题数 30' and e == {'total': total, 'expected': 30})
        elif code == 'holdout_strata_mismatch':
            require(detail == 'H2 分层计数与冻结分层不一致')
            exact(e, ('actual', 'expected'))
            strata(e['actual']); strata(e['expected'])
        elif code == 'holdout_case_error':
            require(detail == 'H2 存在未执行/error 题，不得并入正确数' and e == {'errors': payload['errors']})
        elif code == 'holdout_below_threshold':
            require(detail == f"H2 通过 {payload['passed']} < 门槛 24/30" and
                    e == {'passed': payload['passed'], 'min_pass': 24})
        elif code == 'holdout_threshold_unapproved':
            require(detail == 'H2 阈值/门禁版本未审批（gate_v0_3 初始 unapproved），不得按通过处理'
                    and e == {'gate_status': 'unapproved'})
        elif code in ('holdout_document_code_unmapped', 'holdout_document_code_ambiguous'):
            if e == {'stage': 'document_codes'}:
                require(detail == 'H2 语料文件名无法建出文档代号映射，来源比对不可信')
            elif set(e) == {'missing_count', 'mapped'}:
                require(detail == '数据集期望来源的 doc_code 无法由 H2 语料文件名映射（不猜、不放行）')
                integer(e['missing_count'], 120); integer(e['mapped'], 120)
            else:
                require(detail in (BLOCKED_DETAIL, '') and e in ({'stage': 'holdout_scorecard'}, {}))
        elif code == 'holdout_hard_failure_unclassified':
            require(detail == '逐题行里出现来源/安全类结构问题：本卡不计 pass，硬失败类别由封存标注方判定')
            exact(e, ('codes', 'counted_as', 'hard_failures_owner'))
            require(type(e['codes']) is list and len(e['codes']) <= len(STRUCTURAL)
                    and all(type(x) is str and x in STRUCTURAL for x in e['codes'])
                    and e['counted_as'] == 'error' and e['hard_failures_owner'] == 'sealed-labels')
        elif code == 'holdout_hard_failure_unverified':
            require(detail == '四类硬失败缺少受控分类证据，零计数不证明安全' and e == {'owner': 'sealed_reviewer'})
        elif code in ('holdout_case_unscorable', 'holdout_scorecard_leak'):
            if code == 'holdout_case_unscorable' and set(e) == {'cases', 'codes'}:
                require(detail == '有题在受限进程内无法评分（数据/证据缺失）：按 error 记，不计入 pass')
                integer(e['cases'])
                require(type(e['codes']) is list and len(e['codes']) <= len(ERRORS)
                        and all(type(x) is str and x in ERRORS for x in e['codes']))
            else:
                require(detail in (BLOCKED_DETAIL, '') and e in ({'stage': 'holdout_scorecard'}, {}))
        else:
            require(False)
    codes = {block['code'] for block in payload['blocks']}
    require('holdout_hard_failure_unverified' in codes)
    # Only the registered all-error fallback may express failure with its stable block.
    fallback = (payload['errors'] == total and payload['executed'] == 0
                and d['errors'] == total and any(
                    block['code'] in ('holdout_case_unscorable', 'holdout_scorecard_leak',
                        'holdout_document_code_unmapped', 'holdout_document_code_ambiguous')
                    and block['detail'] in (BLOCKED_DETAIL, '')
                    and block['evidence'] in ({'stage': 'holdout_scorecard'}, {})
                    for block in payload['blocks']))
    if not fallback:
        for needed, code in (
            (total != 30, 'holdout_sample_missing'),
            (payload['errors'] > 0, 'holdout_case_error'),
            (payload['passed'] < 24, 'holdout_below_threshold'),
            (not payload['thresholds_approved'], 'holdout_threshold_unapproved'),
        ):
            require(not needed or code in codes)


def fixed(value, choices, fallback='unknown'):
    return value if type(value) is str and value in choices else fallback


def _kind(value):
    return fixed('kind_' + value, KINDS, 'kind_unknown') if type(value) is str else 'kind_unknown'


def _empty():
    return {
        'schema_version': 'p2-safe-diagnostics/v1',
        'counts': dict.fromkeys(COUNTS, 0),
        'kind_matrix': {x: dict.fromkeys(KINDS, 0) for x in KINDS},
        'failed_checks': dict.fromkeys(CHECKS, 0),
        'refusal_confusion': dict.fromkeys(('tp', 'fp', 'tn', 'fn', 'errors', 'not_executed', 'unknown'), 0),
        'errors': dict.fromkeys(ERRORS, 0),
        'model_failure_reasons': dict.fromkeys(MODEL_FAILURE_REASONS, 0),
        'source': dict.fromkeys(('matched', 'unmatched', 'mapping_blocked'), 0),
        'by_stratum': {x: dict.fromkeys(COUNTS, 0) for x in STRATA},
        'classification_status': 'unverified',
        'classification_owner': 'sealed_reviewer',
        'hard_failure_evidence': {x: {'checked': 0, 'unknown': 0, 'violations': 0}
                                  for x in HARD_KINDS},
        'structural_evidence': dict.fromkeys(STRUCTURAL, 0),
    }


def validate_diagnostics(payload, *, total=None):
    """Validate ORIGINAL full tree, exact keys/types, fixed strings and equations."""
    if isinstance(payload, dict) and payload.get("schema_version") == "p2-safe-diagnostics/v2":
        # T207 B 包：新版诊断（四轴硬证据计数口径），旧 v1 模板/等式保持原样。
        from .p2_hard_evidence import validate_hard_evidence_diagnostics

        resolved = total
        if resolved is None:
            counts = payload.get("counts")
            resolved = int(counts.get("planned") or 0) if isinstance(counts, dict) else 0
        validate_hard_evidence_diagnostics(payload, total=int(resolved))
        return
    def walk(value, template):
        if type(template) is dict:
            if type(value) is not dict or value.keys() != template.keys():
                raise ValueError('diagnostics_invalid')
            for key in template:
                walk(value[key], template[key])
        elif type(template) is int:
            if type(value) is not int or not 0 <= value <= 360:
                raise ValueError('diagnostics_invalid')
        elif type(value) is not str or value != template:
            raise ValueError('diagnostics_invalid')
    walk(payload, _empty())
    c = payload['counts']
    n = c['planned']
    def require(condition):
        if not condition:
            raise ValueError('diagnostics_invalid')
    require(n <= 30 and (total is None or n == total))
    for bucket in (c, *payload['by_stratum'].values()):
        require(bucket['planned'] == bucket['scored'] + bucket['errors'] + bucket['not_executed'])
        require(bucket['observed'] + bucket['unknown_kind'] == bucket['scored'])
    for key in COUNTS:
        require(c[key] == sum(x[key] for x in payload['by_stratum'].values()))
    require(sum(sum(x.values()) for x in payload['kind_matrix'].values()) == c['observed'] + c['unknown_kind'])
    require(sum(x['kind_unknown'] for x in payload['kind_matrix'].values()) == c['unknown_kind'])
    require(sum(payload['errors'].values()) == c['errors'] + c['not_executed'])
    require(payload['errors']['not_executed'] == c['not_executed'])
    require(sum(payload['model_failure_reasons'].values()) == c['errors'])
    refusal = payload['refusal_confusion']
    require(sum(refusal.values()) == n and refusal['errors'] == c['errors']
            and refusal['not_executed'] == c['not_executed'])
    require(sum(refusal[key] for key in ('tp', 'fp', 'tn', 'fn')) == c['observed']
            and refusal['unknown'] == c['unknown_kind'])
    require(sum(payload['source'].values()) <= n)
    require(payload['source']['mapping_blocked'] == payload['errors']['mapping_blocked'])
    for section in ('failed_checks', 'structural_evidence'):
        require(all(x <= n for x in payload[section].values()))
    for evidence in payload['hard_failure_evidence'].values():
        # This package has no trusted classifier. A zero is never a verified result.
        require(evidence == {'checked': 0, 'unknown': n, 'violations': 0})


class HoldoutDiagnostics:
    def __init__(self):
        self.payload = _empty()

    def record(self, case, row, scored=None, *, error=None, mapping_blocked=False, status=None):
        p = self.payload
        stratum = fixed(case.stratum, STRATA, None)
        if stratum is None:
            raise ValueError('diagnostics_invalid')
        status = status or getattr(getattr(scored, 'score', None), 'status', None)
        state = ('errors' if error is not None or mapping_blocked else
                 'not_executed' if status == 'not_executed' or row is None else
                 'scored' if status in ('pass', 'fail') else 'errors')
        outcome = getattr(scored, 'outcome', None)
        if state == 'scored' and (outcome is None or type(case.should_refuse) is not bool):
            raise ValueError('diagnostics_invalid')
        for bucket in (p['counts'], p['by_stratum'][stratum]):
            bucket['planned'] += 1
            bucket[state] += 1
        for evidence in p['hard_failure_evidence'].values():
            evidence['unknown'] += 1
        if state == 'not_executed':
            p['errors']['not_executed'] += 1
        elif state == 'errors':
            code, reason = error, 'unknown'
            if isinstance(row, Mapping):
                code = code or row.get('error_code')
                for turn in row.get('turns') or ():
                    if isinstance(turn, Mapping):
                        product = turn.get('product') or {}
                        if isinstance(product, Mapping):
                            reason = safe_model_failure_reason(product.get('model_failure_reason'))
                            code = code or turn.get('error_code') or product.get('error_code')
                        if turn.get('status') != 'ok' or turn.get('error_code'):
                            break
            code = 'mapping_blocked' if mapping_blocked else fixed(code, ERRORS)
            # not_executed is reserved for missing executions, never arbitrary external codes.
            if code == 'not_executed':
                code = 'unknown'
            if code != 'MODEL_OUTPUT_INVALID':
                reason = 'unknown'
            p['errors'][code] += 1
            p['model_failure_reasons'][reason] += 1
        if mapping_blocked:
            p['source']['mapping_blocked'] += 1
        actual = _kind(outcome.kind) if outcome is not None else 'kind_unknown'
        refusal_state = ('errors' if state == 'errors' else 'not_executed' if state == 'not_executed'
                         else 'unknown' if actual == 'kind_unknown' or type(case.should_refuse) is not bool
                         else ('tp' if case.should_refuse else 'fp') if actual in
                         ('kind_no_answer', 'kind_not_found', 'kind_refusal')
                         else ('fn' if case.should_refuse else 'tn'))
        p['refusal_confusion'][refusal_state] += 1
        if outcome is not None:
            expected, actual = _kind(case.expected_kind), _kind(outcome.kind)
            if state == 'scored':
                p['kind_matrix'][expected][actual] += 1
                observation = 'unknown_kind' if actual == 'kind_unknown' else 'observed'
                p['counts'][observation] += 1
                p['by_stratum'][stratum][observation] += 1
            checks = getattr(scored.score, 'checks', ())
            failed = {fixed(x.get('check_id'), CHECKS) for x in checks if x.get('status') == 'fail'}
            for key in failed:
                p['failed_checks'][key] += 1
            source = next((x for x in checks if x.get('check_id') == 'source_hit'), None)
            if source is not None and source.get('status') in ('pass', 'fail'):
                p['source']['matched' if source['status'] == 'pass' else 'unmatched'] += 1
            issues = {x.code for x in scored.score.issues}
            for key in STRUCTURAL:
                p['structural_evidence'][key] += int(key in issues)

    def to_dict(self):
        validate_diagnostics(self.payload)
        return copy.deepcopy(self.payload)
