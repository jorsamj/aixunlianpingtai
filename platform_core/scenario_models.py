"""Strict scenario-only projection over existing training/version truth."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from pathlib import Path
from collections.abc import Mapping

from .algorithms import is_trainable_version, list_algorithms
from .task_runtime import TaskKind, TaskStatus


_LIST_DIGEST_CACHE = OrderedDict()
_LIST_DIGEST_LOCK = threading.Lock()
_LIST_DIGEST_LIMIT = 256
_LIST_DIGEST_TTL_SECONDS = 5


class ScenarioModelUnavailable(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise ScenarioModelUnavailable(reason)


def _same(values, expected, reason):
    _require(all(str(value) == str(expected) for value in values if value not in (None, '')), reason)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _file_fingerprint(path):
    stat = path.stat()
    return (str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_ctime_ns, stat.st_mtime_ns, stat.st_size)


def _model_digest(path, *, use_list_cache):
    if not use_list_cache:
        return _sha256(path)
    key = _file_fingerprint(path)
    now = time.monotonic()
    with _LIST_DIGEST_LOCK:
        cached = _LIST_DIGEST_CACHE.get(key)
        if cached and now - cached[0] <= _LIST_DIGEST_TTL_SECONDS:
            _LIST_DIGEST_CACHE.move_to_end(key)
            return cached[1]
    digest = _sha256(path)
    _require(_file_fingerprint(path) == key, 'model bytes changed during list verification')
    with _LIST_DIGEST_LOCK:
        _LIST_DIGEST_CACHE[key] = (now, digest)
        _LIST_DIGEST_CACHE.move_to_end(key)
        while len(_LIST_DIGEST_CACHE) > _LIST_DIGEST_LIMIT:
            _LIST_DIGEST_CACHE.popitem(last=False)
    return digest


def _remote_primary(project_id, project, algorithm_id, version, task, payload, result, artifacts):
    from .training_tasks import _SUCCESSFUL_TRAINING_OUTCOMES
    generation = int(result.get('execution_generation') or 0)
    _require(generation > 0 and generation == int(version.get('execution_generation') or 0), 'remote generation mismatch')
    _require(task.result_ref == f'remote-results/{generation}/result.json', 'remote committed result reference mismatch')
    _require(result.get('task_id') == task.task_id and result.get('project_id') == project_id
        and result.get('algorithm_id') == algorithm_id and result.get('version_id') == version['id']
        and result.get('model_artifacts_committed') is True, 'remote training commit identity incomplete')
    training = payload['remote_execution']['training']
    _require(training.get('snapshot_id') == result.get('snapshot_id')
        and training.get('dataset_revision_id') == result.get('dataset_revision_id'), 'remote frozen dataset mismatch')
    completion = result.get('completion') or {}
    _require(result.get('training_outcome') in _SUCCESSFUL_TRAINING_OUTCOMES
        and completion.get('training_outcome') == result.get('training_outcome') and completion.get('finished_at'),
        'remote job completion is not trustworthy')
    upload = artifacts.read_json(task.task_id, f'remote-results/{generation}/upload.json', default={})
    models = artifacts.read_json(task.task_id, f'remote-results/{generation}/training-models.json', default={})
    for state in (upload, models):
        _require(state.get('confirmed') is True and state.get('task_id') == task.task_id
            and state.get('project_id') == project_id and state.get('execution_generation') == generation,
            'remote generation upload is unconfirmed')
    _require(upload.get('result_ref') == task.result_ref and models.get('version_id') == version['id'],
             'remote confirmed version/result mismatch')
    _require(upload.get('sha256') == result.get('output_sha256') and len(str(upload.get('sha256') or '')) == 64
        and int(upload.get('size_bytes') or 0) == int(result.get('output_size_bytes') or 0)
        and int(upload.get('size_bytes') or 0) > 0, 'remote verified result archive identity mismatch')
    roles = {row['role']: row for row in result.get('verified_models') or []}
    role = 'best' if 'best' in roles else 'last'
    evidence = roles[role]
    committed = next(row for row in version.get('verified_models') or [] if row.get('role') == role)
    confirmed = next(row for row in models.get('models') or [] if row.get('role') == role)
    for row in (committed, confirmed):
        _require(row.get('sha256') == evidence.get('sha256') and row.get('size_bytes') == evidence.get('size_bytes'),
                 'remote model upload/commit identity mismatch')
    storage = confirmed.get('storage_ref') or {}
    _require(committed.get('artifact_id') in (version.get('model_artifact_ids') or [])
        and committed.get('storage_source_id') and committed.get('object_key')
        and committed.get('storage_source_id') == storage.get('storage_source_id')
        and committed.get('object_key') == storage.get('object_key'), 'remote artifact storage identity mismatch')
    path = Path(str(committed.get('path') or '')).resolve()
    _require((project / 'models').resolve() in path.parents, 'remote primary is outside project models')
    return path, evidence, role


def resolve_scenario_model(project_id, project, algorithm, version, repository, artifacts, *, use_list_cache=False):
    """Require a committed training lifecycle and the exact verified primary bytes.

    Missing historical evidence stays unavailable; filenames and compatibility
    success labels alone never qualify a model for this scoped use.
    """
    try:
        return _resolve(project_id, Path(project), algorithm, version, repository, artifacts, use_list_cache=use_list_cache)
    except (OSError, ValueError, TypeError, KeyError, StopIteration, AttributeError, OverflowError) as error:
        raise ScenarioModelUnavailable(str(error)) from error


def _resolve(project_id, project, algorithm, version, repository, artifacts, *, use_list_cache):
    from .training_tasks import _training_completion_error, _SUCCESSFUL_TRAINING_OUTCOMES
    algorithm_id, version_id = str(algorithm.get('id') or ''), str(version.get('id') or '')
    _require(algorithm_id and version_id, 'missing algorithm/version identity')
    _require(is_trainable_version(version, 'ultralytics'), 'unverified or unsuccessful version')
    _require(version.get('framework') == 'ultralytics' and version.get('trainable') is True,
             'formal training framework or trainable evidence missing')
    task_id = str(version.get('task_id') or version.get('job_id') or version.get('training_job_id') or '')
    _require(task_id, 'missing formal training task')
    _same([version.get(key) for key in ('task_id', 'job_id', 'training_job_id')], task_id, 'version task identity conflict')
    linked = [row for row in algorithm.get('versions') or [] if task_id in {
        str(row.get('task_id') or ''), str(row.get('job_id') or ''),
        str(row.get('training_job_id') or ''), str((row.get('training_lineage') or {}).get('task_id') or ''),
    }]
    _require(len(linked) == 1 and linked[0].get('id') == version_id, 'training task/version association is ambiguous')
    task = repository.get(task_id)
    _require(task and task.project_id == project_id and task.kind == TaskKind.TRAINING,
             'training task project or kind mismatch')
    _require(task.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS} and task.result_ref and task.finished_at,
             'training task has not completed successfully')
    _require(version.get('training_status') == task.status.value, 'version/task status mismatch')
    _same([version.get('result_ref')], task.result_ref, 'version result reference conflict')
    result = artifacts.read_json(task_id, task.result_ref, default={})
    payload = artifacts.read_json(task_id, task.payload_ref, default={})
    _require(isinstance(result, dict) and isinstance(payload, dict), 'missing training result/payload')
    _require(str(payload.get('algorithm_asset_id') or '') == algorithm_id, 'training payload algorithm mismatch')
    _require(payload.get('framework') == 'ultralytics', 'training payload framework mismatch')
    _require(result.get('training_outcome') in _SUCCESSFUL_TRAINING_OUTCOMES
        and version.get('training_outcome') == result.get('training_outcome'), 'version training outcome conflict')
    remote = result.get('remote_execution') is True
    job = {}
    if remote:
        path, evidence, primary_role = _remote_primary(project_id, project, algorithm_id, version, task, payload, result, artifacts)
        ref = str(evidence.get('ref') or '')
        _require(ref.startswith('models/'), 'remote model manifest reference invalid')
        reports = [result.get('training_report') or {}]
    else:
        job_path = project / 'jobs' / task_id / 'job.json'
        job = json.loads(job_path.read_text(encoding='utf-8'))
        _require(isinstance(job, dict), 'missing training job')
        _require(_training_completion_error(job, expected_task_id=task_id,
            expected_snapshot_id=str(result.get('snapshot_id') or ''), expected_models_root=project / 'models') is None,
            'training completion handshake is not trustworthy')
        _require(str(job.get('asset_algorithm_id') or job.get('algorithm_asset_id') or '') == algorithm_id,
                 'training job algorithm mismatch')
        _same([job.get('asset_algorithm_id'), job.get('algorithm_asset_id')], algorithm_id, 'job algorithm identity conflict')
        _same([job.get('auto_version_id'), job.get('version_id')], version_id, 'job version identity conflict')
        _same([job.get('id'), job.get('task_id')], task_id, 'job task identity conflict')
        _require(result.get('training_outcome') == job.get('training_outcome'), 'training completion outcome conflict')
        ref = result.get('best_model_ref') or result.get('last_model_ref')
        _require(ref, 'missing primary model reference')
        evidence = next(row for row in result.get('verified_models') or [] if row.get('ref') == ref)
        path = artifacts.artifact_path(task_id, ref).resolve()
        primary_role = 'primary'
        reports = [job.get('training_report') or {}, result.get('training_report') or {}]
    _require(all(not report.get('validation_error') for report in reports), 'final validation failed')
    if task.status == TaskStatus.PARTIAL_SUCCESS:
        _require(all((report.get('test_result') or {}).get('status') == 'failed'
            and (report.get('test_result') or {}).get('protocol', {}).get('mode') ==
                'blind_image_only_inference_then_hidden_ground_truth_scoring' for report in reports),
            'partial success lacks independent blind-test failure evidence')
    else:
        _require(all((report.get('test_result') or {}).get('status') in {'not_requested', 'passed', 'succeeded'}
                     for report in reports), 'successful training has inconsistent test result')
    snapshot_id, revision_id = str(result.get('snapshot_id') or ''), str(result.get('dataset_revision_id') or '')
    _require(snapshot_id and revision_id, 'missing frozen training identity')
    _require(version.get('snapshot_id') == snapshot_id and version.get('dataset_revision_id') == revision_id,
             'version frozen identity missing or changed')
    _same([version.get('snapshot_id'), job.get('snapshot_id')], snapshot_id, 'snapshot identity conflict')
    _same([version.get('dataset_revision_id'), job.get('dataset_revision_id')], revision_id, 'dataset revision conflict')
    digest, size = str(evidence.get('sha256') or '').lower(), int(evidence.get('size_bytes') or 0)
    _require(len(digest) == 64 and size > 0, 'invalid verified model identity')
    _require(path.suffix.lower() == '.pt' and path.is_file() and path.stat().st_size == size,
             'formal model file unavailable or changed')
    _require(Path(str(version.get('stored_path') or '')).resolve() == path, 'version primary model path mismatch')
    _require(_model_digest(path, use_list_cache=use_list_cache) == digest, 'formal model bytes changed')
    for owner in ((version,) if remote else (version, result)):
        lineage = owner.get('training_lineage') or {}
        _require(str(lineage.get('task_id') or '') == task_id, 'training lineage task mismatch')
        outcome = lineage.get('outcome') or {}
        _require(outcome.get('status') == task.status.value
            and outcome.get('training_outcome') == result.get('training_outcome') and outcome.get('finished_at'),
            'training lineage completion conflict')
        _require(lineage.get('snapshot_id') == snapshot_id and lineage.get('dataset_revision_id') == revision_id,
                 'lineage frozen identity missing or changed')
        primary = next(row for row in lineage.get('artifacts') or [] if row.get('role') == primary_role)
        _require(primary.get('verified') is True and primary.get('sha256') == digest
                 and int(primary.get('size_bytes') or 0) == size, 'lineage primary identity mismatch')
    return {'model_source': 'algorithm_version', 'framework': 'ultralytics',
        'algorithm_id': algorithm_id, 'version_id': version_id,
        'version_name': version.get('version_name') or version_id,
        'created_at': version.get('created_at') or '', 'finished_at': version.get('finished_at') or '',
        'label': f"算法版本：{algorithm.get('name')} / {version.get('version_name') or version_id}",
        'scenario_eligible': True, 'training_task_id': task_id, 'model_sha256': digest,
        'model_size': size, 'path': str(path), 'artifact_name': path.name,
        'training_result_ref': task.result_ref, 'training_model_ref': ref}


def verify_scenario_request(context, request):
    """Recheck queued/recovered scenario work before any inference process runs."""
    protected_ref = str(getattr(context.task, 'payload_ref', '') or '').startswith('scenario/')
    if not isinstance(request, Mapping):
        _require(not protected_ref, 'persisted scenario payload is invalid')
        return
    if not protected_ref and request.get('model_scope') != 'scenario' and 'scenario_model' not in request:
        return
    _require(request.get('model_scope') == 'scenario' and isinstance(request.get('scenario_model'), dict),
             'persisted scenario task classification or evidence was removed')
    frozen = request.get('scenario_model') or {}
    project = Path(str(frozen.get('project_path') or ''))
    _require(project.name == context.task.project_id, 'scenario project identity changed')
    algorithm = next((row for row in list_algorithms(project / 'algorithms.json')
                      if row.get('id') == frozen.get('algorithm_id')), {})
    version = next((row for row in algorithm.get('versions') or []
                    if row.get('id') == frozen.get('version_id')), {})
    current = resolve_scenario_model(context.task.project_id, project, algorithm, version,
                                     context.repository, context.artifacts)
    for key in ('algorithm_id', 'version_id', 'training_task_id', 'model_sha256', 'model_size',
                'path', 'training_result_ref', 'training_model_ref'):
        _require(current.get(key) == frozen.get(key), 'scenario model identity changed: ' + key)
    _require(request.get('model_path') == current['path'], 'scenario model argument changed')
    _require(not request.get('model_reference') and not request.get('model_reference_type')
        and request.get('framework') == current['framework'] and request.get('runtime_format') == 'pt',
        'scenario model runtime source changed')
    identity = request.get('model_identity') or {}
    _require(identity.get('model_source') == 'algorithm_version', 'scenario model source changed')
    for key in ('algorithm_id', 'version_id', 'model_sha256'):
        _require(identity.get(key) == current[key], 'scenario model request identity changed')
    remote = request.get('remote_execution')
    if remote is not None:
        model = (remote.get('deployment') or {}).get('model') or {}
        _require(model.get('type') == 'object' and model.get('sha256') == current['model_sha256']
            and model.get('size_bytes') == current['model_size'], 'scenario portable model identity changed')
