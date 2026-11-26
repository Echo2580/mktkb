from safe_plan_projection import project_plan, project_retrieval


def test_field_states():
    assert project_plan({}) == {"status": "field_missing"}
    assert project_plan({'field_role': 'location'})['status'] == 'single_role_observed'
    assert project_plan({'field_role': None})['status'] == 'single_role_empty'
    assert project_plan({"field_roles": []}) == {"status": "observed_empty", "field_roles": [], "invalid_count": 0}
    assert project_plan({"field_roles": ["location", "status"]}) == {"status": "observed", "field_roles": ["location", "status"], "invalid_count": 0}
    result = project_plan({"field_roles": ["location", "PRIVATE_SENTINEL", object()]})
    assert result == {"status": "invalid_role", "field_roles": ["location"], "invalid_count": 2}
    assert "PRIVATE_SENTINEL" not in str(result)
    assert project_plan({"field_roles": None}) == {"status": "invalid_type"}
    assert project_plan({}, processed=False) == {"status": "projection_not_processed"}
    assert project_plan(None) == {"status": "projection_failed"}


def test_retrieval_never_exports_identity_or_invalid_codes():
    assert project_retrieval({}) == {"status": "field_missing"}
    assert project_retrieval({"store_join_status": "SECRET_SENTINEL"}) == {"status": "invalid_join_status"}
    result = project_retrieval({"store_join_status": "joined", "roles_state": "available", "effective_roles": ["location", "SECRET_SENTINEL"],
        "unit_ids": ["PRIVATE_ID"], "candidate_count": 1, "stores_state": "available", "stores_count": 0,
        "truncated": False, "page_has_more": True})
    assert result['join'] == 'joined' and result['roles']['status'] == 'invalid_role'
    assert result['stores_count'] == 0 and result['candidate_count'] == 1
    assert 'PRIVATE_ID' not in str(result) and 'SECRET_SENTINEL' not in str(result)
    assert project_retrieval({'store_join_status': 'unknown', 'roles_state': 'unknown', 'effective_roles': []})['roles']['status'] == 'unknown'
