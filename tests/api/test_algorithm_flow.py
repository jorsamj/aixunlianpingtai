def test_create_algorithm_returns_persisted_asset(client, seeded_project):
    project_id, _ = seeded_project
    payload = {
        "name": "烟火判断",
        "industry": "工业安全",
        "algorithm_type": "yolo_ultralytics",
        "remark": "",
    }
    response = client.post(f"/api/v12/projects/{project_id}/algorithms", json=payload)

    assert response.status_code == 200
    algorithm = response.json()["algorithm"]
    assert algorithm["name"] == "烟火判断"
    listed = client.get(f"/api/v12/projects/{project_id}/algorithms").json()["items"]
    assert [item["id"] for item in listed].count(algorithm["id"]) == 1


def test_duplicate_algorithm_name_is_actionable(client, seeded_project):
    project_id, _ = seeded_project
    payload = {
        "name": "烟火判断",
        "industry": "工业安全",
        "algorithm_type": "yolo_ultralytics",
        "remark": "",
    }
    client.post(f"/api/v12/projects/{project_id}/algorithms", json=payload)
    response = client.post(f"/api/v12/projects/{project_id}/algorithms", json=payload)

    assert response.status_code == 409
    assert response.json()["code"] == "ALGORITHM_NAME_EXISTS"
    assert response.json()["solution"]


def test_algorithm_detail_endpoint_returns_current_asset_and_missing_is_404(client, seeded_project):
    project_id, _ = seeded_project
    created = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={
            "name": "训练前详情校验",
            "industry": "工业安全",
            "algorithm_type": "yolo_ultralytics",
            "remark": "",
        },
    ).json()["algorithm"]

    fetched = client.get(
        f"/api/v12/projects/{project_id}/algorithms/{created['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["algorithm"]["id"] == created["id"]
    assert fetched.json()["algorithm"]["name"] == "训练前详情校验"

    missing = client.get(
        f"/api/v12/projects/{project_id}/algorithms/algorithm-does-not-exist"
    )
    assert missing.status_code == 404


def test_quality_center_uses_no_data_instead_of_fake_zero_success_rate(client, seeded_project):
    project_id, _ = seeded_project
    response = client.get(f"/api/v44/projects/{project_id}/quality-center")
    assert response.status_code == 200
    algorithm = response.json()["algorithm"]
    assert algorithm["train_completed_count"] == 0
    assert algorithm["train_success_count"] == 0
    assert algorithm["train_failure_count"] == 0
    assert algorithm["train_success_rate"] is None


def test_modular_algorithm_catalog_preserves_existing_openapi_contract():
    import re
    import app as application

    expected = [('get',
      '/api/v12/projects/{project_id}/algorithms',
      'v12_list_algorithms',
      {'summary_only': False,
       'asset_view': False,
       'page': 1,
       'page_size': 20,
       'query': '',
       'algorithm_type': '',
       'industry': '',
       'source_type': '',
       'status': '',
       'sort': 'updated',
       'library_view': False,
       'training_state': '',
       'category_ids': ''},
      None),
     ('post',
      '/api/v12/projects/{project_id}/algorithms',
      'v12_create_algorithm',
      {'asset_view': False},
      'AlgorithmReq'),
     ('get',
      '/api/v12/projects/{project_id}/algorithms/{algorithm_id}',
      'v12_get_algorithm',
      {'asset_view': False,
       'version_id': '',
       'page': 1,
       'page_size': 20,
       'basic_only': False,
       'quality_view': False},
      None),
     ('put',
      '/api/v12/projects/{project_id}/algorithms/{algorithm_id}',
      'v12_update_algorithm',
      {'asset_view': False},
      'AlgorithmReq'),
     ('delete', '/api/v12/projects/{project_id}/algorithms/{algorithm_id}', 'v12_delete_algorithm', {}, None),
     ('get', '/api/v12/projects/{project_id}/publish/pending', 'v12_pending_models', {}, None),
     ('post',
      '/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions',
      'v12_assign_version',
      {},
      'AlgorithmVersionReq'),
     ('put',
      '/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}',
      'v12_update_version',
      {'asset_view': False},
      'VersionPatchReq'),
     ('delete',
      '/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}',
      'v12_delete_version',
      {},
      None),
     ('post',
      '/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/rollback',
      'v12_rollback_version',
      {},
      'AlgorithmVersionRollbackReq'),
     ('get',
      '/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/deployment-activation-dry-run',
      'v12_deployment_activation_dry_run',
      {'operation_id': '', 'expected_current_version_id': ''},
      None),
     ('get',
      '/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/rollback-dry-run',
      'v12_rollback_dry_run',
      {'operation_id': '', 'expected_current_version_id': ''},
      None),
     ('post',
      '/api/v12/projects/{project_id}/algorithms/{algorithm_id}/version-operations/{operation_id}/retry-cleanup',
      'v12_retry_version_cleanup',
      {},
      None),
     ('get',
      '/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/download',
      'v12_download_version',
      {},
      None)]
    schema = application.app.openapi()
    for method, path, name, defaults, body in expected:
        operation = schema["paths"][path][method]
        expected_id = re.sub(r"\W", "_", name + path) + "_" + method
        assert operation["operationId"] == expected_id
        queries = {item["name"]: item for item in operation.get("parameters", []) if item["in"] == "query"}
        assert set(queries) == set(defaults)
        assert {key: item["schema"]["default"] for key, item in queries.items()} == defaults
        if body:
            assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/" + body

    descriptions = {
        "v12_deployment_activation_dry_run": "Read-only deployment activation Dry-Run; reuses `_dry_run_operation_guard`.",
        "v12_rollback_dry_run": "Read-only rollback Dry-Run; reuses `_dry_run_operation_guard`.",
    }
    for method, path, name, _defaults, _body in expected:
        if name in descriptions:
            assert schema["paths"][path][method]["description"] == descriptions[name]
