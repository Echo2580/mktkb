"""SAFE projection of a plan event; callers must keep inputs inside custody."""
from collections.abc import Mapping

ROLES = frozenset({"location", "contact", "phone", "address", "status", "quantity", "price", "note", "date", "effective_from", "effective_to", "spec", "height", "clause"})
JOIN = frozenset({"unknown", "not_applicable", "not_record_or_enumerate", "roles_not_cross_level", "item_filter_missing", "multiple_items", "multiple_stores", "item_row_not_unique", "store_value_missing", "store_value_ambiguous", "store_row_missing", "store_row_ambiguous", "joined", "already_present"})


def project_plan(payload, *, processed=True):
    if not processed:
        return {"status": "projection_not_processed"}
    try:
        if not isinstance(payload, Mapping):
            return {"status": "projection_failed"}
        if payload.get('roles_state') == 'unknown':
            return {"status": "unknown"}
        if "field_roles" not in payload:
            if "field_role" in payload:
                role = payload['field_role']
                if role is None:
                    return {"status": "single_role_empty", "field_roles": [], "invalid_count": 0}
                if type(role) is str and role in ROLES:
                    return {"status": "single_role_observed", "field_roles": [role], "invalid_count": 0}
                return {"status": "invalid_role", "field_roles": [], "invalid_count": 1}
            return {"status": "field_missing"}
        values = payload["field_roles"]
        if not isinstance(values, (list, tuple)):
            return {"status": "invalid_type"}
        valid = sorted({v for v in values if type(v) is str and v in ROLES})
        invalid = sum(1 for v in values if type(v) is not str or v not in ROLES)
        prior_invalid = payload.get('role_unknown_count', 0)
        if type(prior_invalid) is int and prior_invalid >= 0:
            invalid += prior_invalid
        return {"status": "invalid_role" if invalid else ("observed" if values else "observed_empty"),
                "field_roles": valid, "invalid_count": invalid}
    except Exception:
        return {"status": "projection_failed"}


def project_retrieval(payload, *, processed=True):
    if not processed:
        return {"status": "projection_not_processed"}
    try:
        if not isinstance(payload, Mapping):
            return {"status": "projection_failed"}
        if "store_join_status" not in payload:
            return {"status": "field_missing"}
        join = payload['store_join_status']
        if type(join) is not str or join not in JOIN:
            return {"status": "invalid_join_status"}
        if 'roles_state' not in payload or 'effective_roles' not in payload:
            role_projection = {"status": "field_missing"}
        elif payload['roles_state'] == 'unknown':
            role_projection = {"status": "unknown"}
        elif payload['roles_state'] == 'available':
            role_projection = project_plan({"field_roles": payload['effective_roles'], "role_unknown_count": payload.get('role_unknown_count', 0)})
        else:
            role_projection = {"status": "invalid_type"}
        count = payload.get('candidate_count')
        count_status = 'observed' if type(count) is int and count >= 0 else 'unknown'
        result = {"status": "observed", "join": join, "roles": role_projection,
                  "candidate_count_status": count_status}
        mode = payload.get('effective_mode')
        result['effective_mode'] = mode if mode in ('record', 'document', 'unknown') else 'unknown'
        result['effective_enumerate'] = payload['effective_enumerate'] if type(payload.get('effective_enumerate')) is bool else None
        result['candidate_scope_limit'] = 'unknown'
        if count_status == 'observed':
            result['candidate_count'] = count
        stores_count = payload.get('stores_count')
        if payload.get('stores_state') == 'available' and type(stores_count) is int and stores_count >= 0:
            result['stores_status'] = 'observed'
            result['stores_count'] = stores_count
        else:
            result['stores_status'] = 'unknown'
        for key in ('truncated', 'page_has_more'):
            result[key] = payload[key] if type(payload.get(key)) is bool else None
        return result
    except Exception:
        return {"status": "projection_failed"}
