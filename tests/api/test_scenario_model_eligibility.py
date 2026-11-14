"""Scenario admission exercises the real finalizer and task/artifact repositories."""
import hashlib
import uuid
from pathlib import Path

import pytest

import app as api
from platform_core.algorithms import list_algorithms, save_algorithms
from platform_core.snapshots import ensure_dataset_revision, dataset_revision_document
from platform_core.task_runtime import ArtifactStore, TaskRepository, TaskKind, TaskRecord
from platform_core.task_runtime.worker import WorkerContext
from platform_core.training_tasks import TrainingHandler


@pytest.fixture
def trained(seeded_project, monkeypatch, tmp_path, request):
    project_id, _ = seeded_project
    project = api.project_dir(project_id)
    task_id = 'scenario-' + uuid.uuid4().hex[:12]
    algorithm_id = 'scenario-algorithm'
    save_algorithms(project / 'algorithms.json', [{'id': algorithm_id, 'name': '场景算法', 'versions': []}])
    repository = TaskRepository(tmp_path / 'runtime' / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'runtime' / 'artifacts')
    monkeypatch.setattr(api, 'shared_task_repository', lambda: repository)
    monkeypatch.setattr(api, 'shared_task_artifacts', lambda: artifacts)
    payload = {'framework': 'ultralytics', 'algorithm_asset_id': algorithm_id, 'epochs': 1}
    artifacts.atomic_write_json(task_id, 'payload.json', payload)
    snapshot = ensure_dataset_revision({'schema_version': 3, 'snapshot_id': task_id,
        'counts': {'train': 0, 'validation': 0, 'test': 0, 'total': 0},
        'requested': {'test_source': 'explicit'}, 'test_image_ids': [], 'label_schema': [{'class_id': 0, 'code': 'fire'}], 'images': []})
    revision = dataset_revision_document(snapshot)
    artifacts.atomic_write_json(task_id, 'snapshot.json', snapshot)
    artifacts.atomic_write_json(task_id, 'dataset-revision.json', revision)
    artifacts.atomic_write_json(task_id, 'work/bundle/snapshot.json', snapshot)
    artifacts.atomic_write_json(task_id, 'work/bundle/dataset-revision.json', revision)
    yaml = artifacts.artifact_path(task_id, 'work/bundle/dataset/data.yaml')
    yaml.parent.mkdir(parents=True)
    yaml.write_text('path: .\ntrain: images/train\nval: images/validation\nnames: {0: fire}\n')
    artifacts.atomic_write_json(task_id, 'work/bundle/manifest.json', {
        'schema_version': 3, 'snapshot_id': task_id,
        'dataset_revision_schema_version': snapshot['dataset_revision_schema_version'],
        'canonical_annotation_schema_version': snapshot['canonical_annotation_schema_version'],
        'dataset_revision_id': snapshot['dataset_revision_id'],
        'snapshot_ref': 'snapshot.json',
        'snapshot_sha256': hashlib.sha256(artifacts.artifact_path(task_id, 'work/bundle/snapshot.json').read_bytes()).hexdigest(),
        'dataset_revision_ref': 'dataset-revision.json',
        'dataset_revision_sha256': hashlib.sha256(artifacts.artifact_path(task_id, 'work/bundle/dataset-revision.json').read_bytes()).hexdigest(),
        'data_yaml_ref': 'dataset/data.yaml', 'splits': {'train': [], 'validation': [], 'test': []}})
    model = project / 'models' / (task_id + '.pt')
    model.parent.mkdir(exist_ok=True)
    model.write_bytes(b'isolated worker-verified training bytes')
    job = {'id': task_id, 'task_id': task_id, 'status': 'done', 'artifact_verified': True,
        'verified_models': [str(model)], 'best_path': str(model), 'snapshot_id': task_id,
        'dataset_revision_id': snapshot['dataset_revision_id'], 'asset_algorithm_id': algorithm_id,
        'training_outcome': 'completed', 'finished_at': '2026-10-22T00:00:00Z',
        'training_report': {'test_result': {'status': 'not_requested', 'metrics': {}}}}
    mode = getattr(request, 'param', '')
    if mode in {'partial', 'validation'}:
        job['training_report']['test_result'] = {'status': 'failed', 'metrics': {},
            'protocol': {'mode': 'blind_image_only_inference_then_hidden_ground_truth_scoring'}, 'error': 'isolated test failure'}
    if mode == 'validation':
        job['training_report']['validation_error'] = 'isolated final validation failure'
    job_path = project / 'jobs' / task_id / 'job.json'
    api.write_json(job_path, job)
    repository.create(TaskRecord.new(task_id, project_id, TaskKind.TRAINING, 'payload.json', 'scenario-fixture'))
    lease = repository.claim_next(task_id, [TaskKind.TRAINING], set())
    monkeypatch.setattr('platform_core.training_tasks._request_external_publish_after_training', lambda **_: False)
    context = WorkerContext(lease.task, lease, repository, artifacts)
    status, ref = TrainingHandler(api.DATA_DIR)._finalize_completed_job(context, payload, project, job)
    context.finish(status, ref)
    version = list_algorithms(project / 'algorithms.json')[0]['versions'][0]
    if mode == 'remote':
        # The remote Owner persists a verified manifest/commit, not a server job.json.
        from platform_core.remote_training_results import create_training_result_archive, verify_training_result_archive
        archive = create_training_result_archive(project_dir=project, job=job, task_id=task_id,
            execution_generation=2, snapshot_id=task_id, destination=tmp_path / 'remote-result.zip')
        verified = verify_training_result_archive(archive.path, tmp_path / 'verified-remote',
            expected_sha256=archive.sha256, expected_size_bytes=archive.size_bytes,
            expected_task_id=task_id, expected_execution_generation=2, expected_snapshot_id=task_id)
        primary = verified.models[0]
        storage = {'storage_source_id': 'isolated-source', 'object_key': 'models/isolated-best.pt'}
        committed = {'role': 'best', 'path': str(model), 'sha256': primary['sha256'], 'size_bytes': primary['size_bytes'],
            'artifact_id': 'isolated-artifact', **storage}
        version.update({'stored_path': str(model), 'best_path': str(model), 'execution_generation': 2,
            'result_ref': 'remote-results/2/result.json', 'verified_models': [committed],
            'model_artifact_ids': ['isolated-artifact']})
        version['training_lineage']['artifacts'][0]['role'] = 'best'
        save_algorithms(project / 'algorithms.json', [{'id': algorithm_id, 'name': '远程场景算法',
            'current_version_id': version['id'], 'versions': [version]}])
        result = {'task_id': task_id, 'project_id': project_id, 'remote_execution': True,
            'snapshot_id': task_id, 'dataset_revision_id': snapshot['dataset_revision_id'],
            'training_outcome': verified.manifest['training_outcome'], 'completion': verified.manifest['completion'],
            'training_report': verified.manifest['training_report'], 'verified_models': list(verified.models),
            'execution_generation': 2, 'algorithm_id': algorithm_id, 'version_id': version['id'],
            'model_artifacts_committed': True, 'output_sha256': archive.sha256, 'output_size_bytes': archive.size_bytes}
        artifacts.atomic_write_json(task_id, version['result_ref'], result)
        artifacts.atomic_write_json(task_id, 'remote-results/2/upload.json', {'task_id': task_id, 'project_id': project_id,
            'execution_generation': 2, 'confirmed': True, 'result_ref': version['result_ref'],
            'sha256': archive.sha256, 'size_bytes': archive.size_bytes})
        artifacts.atomic_write_json(task_id, 'remote-results/2/training-models.json', {'task_id': task_id, 'project_id': project_id,
            'execution_generation': 2, 'confirmed': True, 'version_id': version['id'],
            'models': [{'role': 'best', 'sha256': primary['sha256'], 'size_bytes': primary['size_bytes'], 'storage_ref': storage}]})
        payload['remote_execution'] = {'training': {'snapshot_id': task_id, 'dataset_revision_id': snapshot['dataset_revision_id']}}
        artifacts.atomic_write_json(task_id, 'payload.json', payload)
        with repository._connect() as db:
            db.execute('UPDATE tasks SET result_ref=? WHERE task_id=?', (version['result_ref'], task_id))
        job_path.unlink()
    return project_id, algorithm_id, version, job_path


def catalog(client, project_id):
    response = client.get(f'/api/v12/projects/{project_id}/test_models?probe_optional=false&model_scope=scenario')
    assert response.status_code == 200, response.text
    return response.json()['items']


def test_scenario_catalog_requires_formal_training_and_preserves_generic(client, trained):
    project_id, algorithm_id, version, _ = trained
    rows = catalog(client, project_id)
    assert len(rows) == 1
    assert rows[0]['scenario_eligible'] is True
    assert rows[0]['algorithm_id'] == algorithm_id
    assert rows[0]['version_id'] == version['id']
    assert rows[0]['training_task_id'] == version['task_id']
    assert rows[0]['model_sha256'] == hashlib.sha256(Path(version['stored_path']).read_bytes()).hexdigest()
    assert rows[0]['model_size'] == Path(version['stored_path']).stat().st_size
    generic = client.get(f'/api/v12/projects/{project_id}/test_models?probe_optional=false').json()['items']
    assert any(row['model_source'] == 'builtin' for row in generic)


@pytest.mark.parametrize('source', ['builtin', 'local', 'project', 'deployment_artifact'])
def test_scenario_submission_rejects_nonformal_sources(client, trained, source):
    project_id, _, version, _ = trained
    response = client.post(f'/api/v61/projects/{project_id}/deployment-tests',
        data={'model_scope': 'scenario', 'model_source': source, 'model_name': 'yolo11n.pt', 'local_path': version['stored_path']},
        files={'file': ('sample.jpg', b'isolated-image', 'image/jpeg')})
    assert response.status_code == 409, response.text


@pytest.mark.parametrize('trained', ['partial', 'validation'], indirect=True)
def test_partial_success_requires_completed_training_and_independent_test_failure(client, trained):
    project_id, _, version, _ = trained
    assert version['training_status'] == 'PARTIAL_SUCCESS'
    rows = catalog(client, project_id)
    result = api.shared_task_artifacts().read_json(version['task_id'], 'result.json')
    assert len(rows) == (0 if result['training_report'].get('validation_error') else 1)


def submit_scenario(client, trained, monkeypatch):
    from types import SimpleNamespace
    project_id, algorithm_id, version, _ = trained
    monkeypatch.setattr(api, '_remote_execution_transport_service', lambda: SimpleNamespace(stage_deployment_test=lambda **_: None))
    monkeypatch.setattr(api, 'resolve_inference_python', lambda *_: api.sys.executable)
    response = client.post(f'/api/v61/projects/{project_id}/deployment-tests',
        data={'model_scope': 'scenario', 'model_source': 'algorithm_version', 'algorithm_id': algorithm_id, 'version_id': version['id']},
        files={'file': ('sample.jpg', b'isolated-image', 'image/jpeg')})
    assert response.status_code == 202, response.text
    return api.shared_task_repository().get(response.json()['id'])


def test_scenario_submission_freezes_verified_source_identity(client, trained, monkeypatch):
    task = submit_scenario(client, trained, monkeypatch)
    assert task.payload_ref == 'scenario/request.json'
    request = api.shared_task_artifacts().read_json(task.task_id, task.payload_ref)
    assert request['model_scope'] == 'scenario'
    assert request['scenario_model']['training_task_id'] == trained[2]['task_id']
    assert request['model_identity']['model_sha256'] == request['scenario_model']['model_sha256']
    assert request['model_path'] == trained[2]['stored_path']


@pytest.mark.parametrize('damage', ['official', 'sha', 'size', 'staging_bytes'])
def test_scenario_submission_rechecks_portable_model_and_bytes_after_staging(client, trained, monkeypatch, damage):
    from types import SimpleNamespace
    project_id, algorithm_id, version, _ = trained
    digest = hashlib.sha256(Path(version['stored_path']).read_bytes()).hexdigest()
    model = {'type': 'object', 'sha256': digest, 'size_bytes': Path(version['stored_path']).stat().st_size}
    if damage == 'official': model = {'type': 'official', 'reference': 'yolo11n.pt'}
    if damage == 'sha': model['sha256'] = 'a' * 64
    if damage == 'size': model['size_bytes'] += 1
    def stage(**_):
        if damage == 'staging_bytes':
            Path(version['stored_path']).write_bytes(b'replaced-during-staging')
            return None
        return {'deployment': {'model': model}}
    monkeypatch.setattr(api, '_remote_execution_transport_service', lambda: SimpleNamespace(stage_deployment_test=stage))
    monkeypatch.setattr(api, 'resolve_inference_python', lambda *_: api.sys.executable)
    before = len(api.shared_task_repository().list(project_id=project_id, kinds=(TaskKind.DEPLOYMENT_TEST,)).items)
    response = client.post(f'/api/v61/projects/{project_id}/deployment-tests',
        data={'model_scope': 'scenario', 'model_source': 'algorithm_version', 'algorithm_id': algorithm_id, 'version_id': version['id']},
        files={'file': ('sample.jpg', b'isolated-image', 'image/jpeg')})
    assert response.status_code == 409, response.text
    assert len(api.shared_task_repository().list(project_id=project_id, kinds=(TaskKind.DEPLOYMENT_TEST,)).items) == before


@pytest.mark.parametrize('trained', ['remote'], indirect=True)
def test_remote_formal_manifest_commit_qualifies_without_server_job_copy(client, trained, monkeypatch):
    assert not trained[3].exists()
    rows = catalog(client, trained[0])
    assert len(rows) == 1
    assert rows[0]['scenario_eligible'] is True
    assert rows[0]['model_sha256'] == trained[2]['verified_models'][0]['sha256']
    submit_scenario(client, trained, monkeypatch)


@pytest.mark.parametrize('trained', ['remote'], indirect=True)
@pytest.mark.parametrize('damage', ['generation', 'unconfirmed', 'version', 'storage', 'bytes'])
def test_remote_formal_commit_rejects_generation_identity_and_byte_drift(client, trained, damage):
    project_id, _, version, _ = trained
    artifacts = api.shared_task_artifacts()
    if damage == 'bytes': Path(version['stored_path']).write_bytes(b'replaced remote model')
    elif damage == 'generation':
        result = artifacts.read_json(version['task_id'], version['result_ref'])
        result['execution_generation'] = 3
        artifacts.atomic_write_json(version['task_id'], version['result_ref'], result)
    else:
        ref = 'remote-results/2/training-models.json'
        state = artifacts.read_json(version['task_id'], ref)
        if damage == 'unconfirmed': state['confirmed'] = False
        if damage == 'version': state['version_id'] = 'unrelated-version'
        if damage == 'storage': state['models'][0]['storage_ref']['object_key'] = 'unrelated.pt'
        artifacts.atomic_write_json(version['task_id'], ref, state)
    assert catalog(client, project_id) == []


@pytest.mark.parametrize('damage', ['bytes', 'argument', 'identity', 'training_status', 'official_reference', 'framework', 'drop_scope', 'drop_both'])
def test_scenario_worker_and_recovery_reject_queued_source_drift(client, trained, monkeypatch, damage):
    from types import SimpleNamespace
    from platform_core.deployment.inference_tasks import run_deployment_test, _recover_completed_deployment_test
    from platform_core.scenario_models import ScenarioModelUnavailable
    task = submit_scenario(client, trained, monkeypatch)
    artifacts, repository = api.shared_task_artifacts(), api.shared_task_repository()
    request = artifacts.read_json(task.task_id, task.payload_ref)
    if damage == 'bytes': Path(request['model_path']).write_bytes(b'queued-model-replaced')
    if damage == 'argument': request['model_path'] = str(Path(request['model_path']).with_name('other.pt'))
    if damage == 'identity': request['model_identity']['version_id'] = 'other-version'
    if damage == 'official_reference':
        request['model_reference_type'] = 'official_downloadable'
        request['model_reference'] = 'yolo11n.pt'
    if damage == 'framework': request['framework'] = 'paddle'
    if damage in {'drop_scope', 'drop_both'}: request.pop('model_scope')
    if damage == 'drop_both': request.pop('scenario_model')
    if damage == 'training_status':
        with repository._connect() as db:
            db.execute("UPDATE tasks SET status='FAILED' WHERE task_id=?", (trained[2]['task_id'],))
    artifacts.atomic_write_json(task.task_id, task.payload_ref, request)
    artifacts.atomic_write_json(task.task_id, 'result.json', {'task_id': task.task_id})
    context = SimpleNamespace(task=task, repository=repository, artifacts=artifacts)
    def no_launch(*_, **__): raise AssertionError('invalid scenario must not launch inference')
    monkeypatch.setattr('platform_core.deployment.inference_tasks.launch_process', no_launch)
    with pytest.raises(ScenarioModelUnavailable): run_deployment_test(context)
    with pytest.raises(ScenarioModelUnavailable): _recover_completed_deployment_test(context)


@pytest.mark.parametrize('damage', ['version_flag', 'version_task', 'version_outcome', 'job_algorithm', 'job_failed', 'job_validation', 'bytes', 'result_digest', 'task_failed', 'duplicate_version', 'task_project', 'task_kind', 'result_missing', 'missing_task', 'lineage_sha', 'snapshot', 'version_path'])
def test_scenario_catalog_and_submission_reject_broken_evidence(client, trained, damage):
    project_id, algorithm_id, version, job_path = trained
    algorithms = list_algorithms(api.project_dir(project_id) / 'algorithms.json')
    row = algorithms[0]['versions'][0]
    job = api.read_json(job_path, {})
    if damage == 'version_flag': row['artifact_verified'] = False
    if damage == 'version_task': row['job_id'] = 'unrelated'
    if damage == 'version_outcome': row['training_outcome'] = 'failed'
    if damage == 'duplicate_version':
        import copy
        duplicate = copy.deepcopy(row)
        duplicate['id'] = 'duplicate-official-version'
        algorithms[0]['versions'].append(duplicate)
    if damage == 'lineage_sha': row['training_lineage']['artifacts'][0]['sha256'] = 'a' * 64
    if damage == 'snapshot': row['snapshot_id'] = 'unrelated-snapshot'
    if damage == 'version_path': row['stored_path'] = str(job_path.parent / 'best.pt')
    if damage == 'job_algorithm': job['asset_algorithm_id'] = 'unrelated'
    if damage == 'job_failed': job['status'] = 'failed'
    if damage == 'job_validation': job['training_report']['validation_error'] = 'failed final validation'
    if damage == 'bytes': Path(version['stored_path']).write_bytes(b'replaced model')
    if damage == 'result_digest':
        result = api.shared_task_artifacts().read_json(version['task_id'], 'result.json')
        result['verified_models'][0]['sha256'] = 'a' * 64
        api.shared_task_artifacts().atomic_write_json(version['task_id'], 'result.json', result)
    if damage == 'task_failed':
        with api.shared_task_repository()._connect() as db:
            db.execute("UPDATE tasks SET status='FAILED' WHERE task_id=?", (version['task_id'],))
    if damage in {'task_project', 'task_kind', 'result_missing', 'missing_task'}:
        with api.shared_task_repository()._connect() as db:
            if damage == 'task_project': db.execute("UPDATE tasks SET project_id='unrelated' WHERE task_id=?", (version['task_id'],))
            if damage == 'task_kind': db.execute("UPDATE tasks SET kind='MODEL_CONVERSION' WHERE task_id=?", (version['task_id'],))
            if damage == 'result_missing': db.execute("UPDATE tasks SET result_ref=NULL WHERE task_id=?", (version['task_id'],))
            if damage == 'missing_task': db.execute('DELETE FROM tasks WHERE task_id=?', (version['task_id'],))
    save_algorithms(api.project_dir(project_id) / 'algorithms.json', algorithms)
    api.write_json(job_path, job)
    assert catalog(client, project_id) == []
    response = client.post(f'/api/v61/projects/{project_id}/deployment-tests',
        data={'model_scope': 'scenario', 'model_source': 'algorithm_version', 'algorithm_id': algorithm_id, 'version_id': version['id']},
        files={'file': ('sample.jpg', b'isolated-image', 'image/jpeg')})
    assert response.status_code == 409, response.text


def scenario_agent(client, trained, monkeypatch):
    from types import SimpleNamespace
    from platform_core.agent_execution import AgentExecutionService
    from platform_core.remote_execution_transport import RemoteExecutionTransportService
    from platform_core.service_nodes import ServiceNodeRepository
    task = submit_scenario(client, trained, monkeypatch)
    repository, artifacts = api.shared_task_repository(), api.shared_task_artifacts()
    payload = artifacts.read_json(task.task_id, task.payload_ref)
    frozen = payload['scenario_model']
    payload['execution_mode'] = 'agent'
    payload['remote_execution'] = {'version': 1, 'task_kind': 'DEPLOYMENT_TEST', 'transport': 'object-storage-v1',
        'deployment': {'framework': 'ultralytics', 'runtime_format': 'pt', 'confidence': 0.25,
            'model': {'type': 'object', 'sha256': frozen['model_sha256'], 'size_bytes': frozen['model_size'],
                'storage_source_id': 'isolated', 'object_key': 'model.pt'},
            'input': {'storage_source_id': 'isolated', 'object_key': 'input.jpg'},
            'output': {'storage_source_id': 'isolated', 'object_key': 'result.jpg'}}}
    artifacts.atomic_write_json(task.task_id, task.payload_ref, payload)
    transport = RemoteExecutionTransportService(data_dir=api.DATA_DIR, project_dir=api.project_dir,
        algorithms_file=api.algorithms_file, storage_sources_factory=lambda: None,
        storage_credentials_factory=lambda: None, model_artifacts=SimpleNamespace(), task_artifacts=artifacts)
    transport.task_repository = repository
    signed = []
    def download(project_id, ref):
        signed.append(ref['object_key'])
        return {'method': 'GET', 'url': 'https://isolated.invalid/' + ref['object_key'],
            'size_bytes': ref.get('size_bytes', 1), 'sha256': ref.get('sha256', 'a' * 64)}
    monkeypatch.setattr(transport, '_download_contract', download)
    nodes = ServiceNodeRepository(repository)
    _, token = nodes.create({'node_id': 'scenario-agent', 'display_name': 'isolated agent',
        'connection_mode': 'agent', 'enabled': True, 'allowed_capabilities': ['deployment-test']})
    nodes.heartbeat('scenario-agent', token, {'hostname': 'isolated', 'reported_capabilities': ['deployment-test'],
        'resources': {'memory': {'available_bytes': 1024**3}}})
    service = AgentExecutionService(repository, artifacts, execution_payload_resolver=transport.resolve_execution_payload)
    assignment = service.allocator.assign_next()
    assert assignment and assignment['task_id'] == task.task_id
    claimed = service.claim_assignment('scenario-agent', token)
    assert claimed
    return task, payload, service, transport, token, claimed['assignment']['assignment_lease_token'], signed


@pytest.mark.parametrize('damage', ['none', 'training_failed', 'bytes', 'official', 'drop_scope', 'drop_both'])
def test_real_agent_start_rechecks_scenario_source_before_signing(client, trained, monkeypatch, damage):
    from platform_core.agent_execution import AgentExecutionError
    task, payload, service, _, token, lease, signed = scenario_agent(client, trained, monkeypatch)
    if damage == 'training_failed':
        with service.repository._connect() as db:
            db.execute("UPDATE tasks SET status='FAILED' WHERE task_id=?", (trained[2]['task_id'],))
    if damage == 'bytes': Path(payload['model_path']).write_bytes(b'changed-after-assignment')
    if damage == 'official': payload['remote_execution']['deployment']['model'] = {'type': 'official', 'reference': 'yolo11n.pt'}
    if damage in {'drop_scope', 'drop_both'}: payload.pop('model_scope')
    if damage == 'drop_both': payload.pop('scenario_model')
    service.artifacts.atomic_write_json(task.task_id, task.payload_ref, payload)
    if damage == 'none':
        result = service.start_execution('scenario-agent', token, task.task_id, lease)
        assert result['payload']['model']['type'] == 'object'
        assert service.repository.get(task.task_id).status.value == 'RUNNING'
        assert signed
    else:
        with pytest.raises(AgentExecutionError) as denied:
            service.start_execution('scenario-agent', token, task.task_id, lease)
        assert denied.value.code == 'SCENARIO_MODEL_INELIGIBLE'
        assert service.repository.get(task.task_id).status.value == 'QUEUED'
        assert signed == []


@pytest.mark.parametrize('damage', ['training_failed', 'official', 'drop_both'])
def test_remote_mint_refresh_and_confirm_reuse_scenario_qualification(client, trained, monkeypatch, damage):
    from platform_core.agent_execution import AgentExecutionError
    from platform_core.remote_execution_transport import RemoteExecutionTransportError
    task, payload, service, transport, token, lease, signed = scenario_agent(client, trained, monkeypatch)
    started = service.start_execution('scenario-agent', token, task.task_id, lease)
    execution = started['execution']
    signed.clear()
    if damage == 'training_failed':
        with service.repository._connect() as db:
            db.execute("UPDATE tasks SET status='FAILED' WHERE task_id=?", (trained[2]['task_id'],))
    if damage == 'official': payload['remote_execution']['deployment']['model'] = {'type': 'official', 'reference': 'yolo11n.pt'}
    if damage == 'drop_both':
        payload.pop('model_scope')
        payload.pop('scenario_model')
    service.artifacts.atomic_write_json(task.task_id, task.payload_ref, payload)
    for operation in (
        lambda: transport.resolve_execution_payload(task, payload, {}),
        lambda: transport.prepare_result_upload(task, payload, {}),
        lambda: transport.confirm_result_upload(task, payload, {}),
    ):
        with pytest.raises(RemoteExecutionTransportError) as denied: operation()
        assert denied.value.code == 'SCENARIO_MODEL_INELIGIBLE'
    for operation in (
        lambda: service.prepare_result_upload('scenario-agent', token, task.task_id,
            execution['lease_token'], execution['generation'], sha256='a'*64, size_bytes=1),
        lambda: service.confirm_result_upload('scenario-agent', token, task.task_id,
            execution['lease_token'], execution['generation']),
        lambda: service.finish_execution('scenario-agent', token, task.task_id,
            execution['lease_token'], execution['generation'], status='SUCCEEDED'),
    ):
        with pytest.raises(AgentExecutionError) as denied: operation()
        assert denied.value.code == 'SCENARIO_MODEL_INELIGIBLE'
    assert signed == []


def test_scenario_list_digest_cache_reuses_only_unchanged_bytes_and_never_training_state(client, trained, monkeypatch):
    import platform_core.scenario_models as models
    calls = []
    original = models._sha256
    def counted(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(models, '_sha256', counted)
    assert len(catalog(client, trained[0])) == 1
    assert len(catalog(client, trained[0])) == 1
    assert len(calls) == 1
    with api.shared_task_repository()._connect() as db:
        db.execute("UPDATE tasks SET status='FAILED' WHERE task_id=?", (trained[2]['task_id'],))
    assert catalog(client, trained[0]) == []
    assert len(calls) == 1


def test_scenario_submission_and_worker_always_hash_fresh_after_list_cache(client, trained, monkeypatch):
    from types import SimpleNamespace
    import platform_core.scenario_models as models
    calls = []
    original = models._sha256
    def counted(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(models, '_sha256', counted)
    assert len(catalog(client, trained[0])) == 1
    assert len(catalog(client, trained[0])) == 1
    assert len(calls) == 1
    task = submit_scenario(client, trained, monkeypatch)
    assert len(calls) == 3
    request = api.shared_task_artifacts().read_json(task.task_id, task.payload_ref)
    models.verify_scenario_request(SimpleNamespace(task=task, repository=api.shared_task_repository(),
        artifacts=api.shared_task_artifacts()), request)
    assert len(calls) == 4
    path = Path(request['model_path'])
    before = path.stat()
    path.write_bytes(b'x' * before.st_size)
    assert catalog(client, trained[0]) == []
    assert len(calls) == 5
