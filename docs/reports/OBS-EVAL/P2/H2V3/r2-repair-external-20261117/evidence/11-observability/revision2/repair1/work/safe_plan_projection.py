"""SAFE projection; payload functions are low-level, not a sink-integrity gate."""
from collections.abc import Mapping

ROLES = frozenset({'location','contact','phone','address','status','quantity','price','note','date','effective_from','effective_to','spec','height','clause'})
JOIN = frozenset({'unknown','not_applicable','not_record_or_enumerate','roles_not_cross_level','item_filter_missing','multiple_items','multiple_stores','item_row_not_unique','store_value_missing','store_value_ambiguous','store_row_missing','store_row_ambiguous','joined','already_present'})


def project_plan(payload, *, processed=True):
    if not processed:
        return {'status': 'projection_not_processed'}
    try:
        if not isinstance(payload, Mapping):
            return {'status': 'projection_failed'}
        if 'role_unknown_count' in payload and (type(payload['role_unknown_count']) is not int or payload['role_unknown_count'] < 0):
            return {'status': 'malformed'}
        roles_unknown = payload.get('roles_state') == 'unknown'
        if 'roles_state' in payload and payload['roles_state'] not in ('available', 'unknown'):
            return {'status': 'malformed'}
        names = [name for name in ('field_roles', 'safe_roles') if name in payload]
        if not names and 'field_role' not in payload:
            return {'status': 'unknown' if roles_unknown else 'field_missing'}
        roles = set()
        invalid = payload.get('role_unknown_count', 0)
        for name in names:
            values = payload[name]
            if type(values) not in (list, tuple):
                return {'status': 'invalid_type'}
            for value in values:
                if type(value) is str and value in ROLES:
                    roles.add(value)
                else:
                    invalid += 1
        if 'field_role' in payload and payload['field_role'] is not None:
            value = payload['field_role']
            if type(value) is str and value in ROLES:
                roles.add(value)
            else:
                invalid += 1
        status = 'unknown' if roles_unknown else ('invalid_role' if invalid else 'observed' if roles else 'observed_empty')
        result = {'status': status, 'field_roles': sorted(roles), 'invalid_count': invalid}
        return result
    except Exception:
        return {'status': 'projection_failed'}


def project_retrieval(payload, *, processed=True):
    if not processed:
        return {'status': 'projection_not_processed'}
    try:
        if not isinstance(payload, Mapping):
            return {'status': 'projection_failed'}
        for name in ('candidate_count', 'stores_count', 'role_unknown_count'):
            if name in payload and not (name == 'stores_count' and payload[name] is None and payload.get('stores_state') == 'unknown'):
                if type(payload[name]) is not int or payload[name] < 0:
                    return {'status': 'malformed', 'invalid_field': name}
        for name in ('truncated', 'page_has_more', 'empty', 'effective_enumerate'):
            if name in payload and type(payload[name]) is not bool:
                return {'status': 'malformed', 'invalid_field': name}
        if 'store_join_status' not in payload:
            return {'status': 'field_missing'}
        join = payload['store_join_status']
        if type(join) is not str or join not in JOIN:
            return {'status': 'invalid_join_status'}
        if payload.get('roles_state') == 'unknown':
            role_projection = project_plan({'field_roles': payload.get('effective_roles', []), 'roles_state': 'unknown', 'role_unknown_count': payload.get('role_unknown_count', 0)})
        elif 'roles_state' not in payload or 'effective_roles' not in payload:
            role_projection = {'status': 'field_missing'}
        elif payload['roles_state'] == 'available':
            role_projection = project_plan({'field_roles': payload['effective_roles'], 'role_unknown_count': payload.get('role_unknown_count', 0)})
        else:
            return {'status': 'malformed', 'invalid_field': 'roles_state'}
        if role_projection['status'] in ('malformed', 'invalid_type', 'projection_failed'):
            return {'status': 'malformed', 'invalid_field': 'effective_roles'}
        state = payload.get('stores_state')
        if state not in (None, 'unknown', 'available'):
            return {'status': 'malformed', 'invalid_field': 'stores_state'}
        if state == 'unknown' and 'stores_count' in payload and payload['stores_count'] is not None:
            return {'status': 'malformed', 'invalid_field': 'stores_count'}
        if state == 'available' and 'stores_count' in payload and payload['stores_count'] is None:
            return {'status': 'malformed', 'invalid_field': 'stores_count'}
        count = payload.get('candidate_count')
        result = {'status':'observed', 'join':join, 'roles':role_projection,
                  'candidate_count_status': 'observed' if type(count) is int else 'not_captured',
                  'stores_status': ('unknown' if state == 'unknown' else 'observed' if state == 'available' and type(payload.get('stores_count')) is int else 'not_captured'),
                  'candidate_scope_limit':'unknown'}
        if type(count) is int: result['candidate_count'] = count
        if result['stores_status'] == 'observed': result['stores_count'] = payload['stores_count']
        for name in ('truncated','page_has_more'):
            result[name] = payload.get(name)
            result[name + '_status'] = 'observed' if name in payload else 'not_captured'
        mode = payload.get('effective_mode')
        result['effective_mode'] = mode if mode in ('record','document','unknown') else 'unknown'
        result['effective_enumerate'] = payload.get('effective_enumerate')
        return result
    except Exception:
        return {'status':'projection_failed'}


def project_validated_turn(envelope, *, expected_bindings):
    """Validate structure/completeness only; the caller must authenticate provenance."""
    try:
        from mktkb.evaluation.p2_evidence_capture import BINDING_KEYS
        from mktkb.evaluation.p2_evidence_io import validate_turn_evidence
        if not isinstance(expected_bindings, Mapping) or not all(k in expected_bindings for k in BINDING_KEYS):
            return {'status':'binding_unavailable'}
        data = validate_turn_evidence(envelope, expected_bindings=expected_bindings)
        capture = data['capture']
        if capture['status'] == 'failed' or capture['errors']:
            return {'status':'sink_failed'}
        if capture['status'] != 'sealed':
            return {'status':'sink_unsealed'}
        complete = data['completeness']
        if complete['status'] != 'complete' or complete['replay'] or complete['errors'] or complete['missing_event_kinds'] or data['turn']['timed_out']:
            return {'status':'incomplete'}
        events = [event['payload'] for event in capture['events'] if event['kind'] == 'retrieval_observed' and event['payload'].get('scope') == 'direct_rag_retrieval']
        plans = [project_plan(event['payload']) for event in capture['events'] if event['kind'] == 'plan_observed']
        if not events:
            direct = [event['payload'] for event in capture['events'] if event['kind'] == 'direct_rag_answer']
            pre_search = {'DOCUMENT_NOT_FOUND', 'UNKNOWN_STORE', 'RECORD_ONLY'}
            executed = 'not_executed' if len(direct) == 1 and direct[0].get('reason') in pre_search else 'unknown'
            result = {'status':'not_captured', 'execution':executed}
            if plans:
                result['prepared_plans'] = plans
            return result
        return {'status':'observed', 'prepared_plans':plans, 'events':[project_retrieval(event) for event in events]}
    except Exception:
        return {'status':'invalid_envelope'}


def project_authenticated_turn(path, key, *, expected_bindings):
    """Read/authenticate a controlled encrypted turn; outputs SAFE values only."""
    try:
        from mktkb.evaluation.p2_evidence_capture import BINDING_KEYS
        from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
        if not isinstance(expected_bindings, Mapping) or not all(k in expected_bindings for k in BINDING_KEYS):
            return {'status':'binding_unavailable'}
        envelope = read_encrypted_evidence(path, key=key, expected_bindings=expected_bindings)
        return project_validated_turn(envelope, expected_bindings=expected_bindings)
    except Exception:
        return {'status':'authentication_or_read_failed'}
