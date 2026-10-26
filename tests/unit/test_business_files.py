import hashlib
import json

import pytest

from platform_core.business_files import BusinessFileNotFound, BusinessFileService


def put(root, relative, value=b'image'):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value)
    return target


def save(root, relative, value):
    return put(root, relative, json.dumps(value).encode())


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'projects' / 'p1'
    root.mkdir(parents=True)
    return tmp_path, root


def test_job_authorizes_exact_model_not_same_basename(project):
    data, root = project
    model = put(root, 'models/best.pt')
    other = put(root, 'models/other.pt')
    save(root, 'jobs/j1/job.json', {'id': 'j1', 'project_id': 'p1', 'models': [str(model)]})
    service = BusinessFileService(data)
    assert service.resolve('p1', 'models', 'best.pt').path == model
    with pytest.raises(BusinessFileNotFound):
        service.resolve('p1', 'models', other.name)


@pytest.mark.parametrize('relative', ['../auth/session.json', 'models/../models/a.pt', 'models\\a.pt',
    'models/a.pt:stream', '/models/a.pt', 'models/%2e%2e/a.pt', 'jobs/j1/job.json', 'predictions/a.evidence.json'])
def test_denies_unsafe_or_sensitive_paths(project, relative):
    data, _ = project
    with pytest.raises(BusinessFileNotFound, match='File not found'):
        BusinessFileService(data).resolve_legacy('p1', relative)


def test_algorithm_and_conversion_records(project):
    data, root = project
    model = put(root, 'models/version.pt')
    save(root, 'algorithms.json', [{'id': 'a', 'versions': [{'id': 'v', 'stored_path': str(model)}]}])
    converted = put(root, 'jobs/c1/artifacts/model.rknn')
    save(root, 'jobs/c1/job.json', {'id': 'c1', 'outputs': [{'path': str(converted), 'rel': 'artifacts/model.rknn'}]})
    service = BusinessFileService(data)
    assert service.resolve('p1', 'models', model.name).path == model
    assert service.resolve_legacy('p1', 'jobs/c1/artifacts/model.rknn').path == converted


def test_explicit_manifest_digest_is_enforced(project):
    data, root = project
    target = put(root, 'predictions/t1/result.jpg')
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    records = lambda pid, kind: [{'project_id': pid, 'path': str(target), 'sha256': digest}]
    service = BusinessFileService(data, records=records)
    assert service.resolve('p1', 'predictions', 't1/result.jpg').path == target
    target.write_bytes(b'changed')
    with pytest.raises(BusinessFileNotFound):
        service.resolve('p1', 'predictions', 't1/result.jpg')


def test_wrong_project_record_and_symlink_are_denied(project):
    data, root = project
    model = put(root, 'models/a.pt')
    records = lambda pid, kind: [{'project_id': 'p2', 'path': str(model)}]
    with pytest.raises(BusinessFileNotFound):
        BusinessFileService(data, records=records).resolve('p1', 'models', 'a.pt')
    link = root / 'models' / 'link.pt'
    try:
        link.symlink_to(model)
    except OSError:
        pytest.skip('symlink unavailable')
    save(root, 'jobs/j/job.json', {'models': [str(link)]})
    with pytest.raises(BusinessFileNotFound):
        BusinessFileService(data).resolve('p1', 'models', 'link.pt')


def test_unregistered_prediction_and_export_are_denied(project):
    data, root = project
    put(root, 'predictions/random_result.jpg')
    put(root, 'exports/random.zip')
    for relative in ['predictions/random_result.jpg', 'exports/random.zip']:
        with pytest.raises(BusinessFileNotFound):
            BusinessFileService(data).resolve_legacy('p1', relative)


def test_url_encodes_and_validates_components():
    assert BusinessFileService.url('p1', 'models', '模型.pt') == '/api/projects/p1/files/models/%E6%A8%A1%E5%9E%8B.pt'
    with pytest.raises(BusinessFileNotFound):
        BusinessFileService.url('../p1', 'models', 'a.pt')


def test_registered_task_artifact_requires_exact_alias_and_sha(project):
    data, root = project
    model = put(data, 'task_runtime/artifacts/t1/model.pt')
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    record = {'project_id': 'p1', 'path': str(model), 'identifier': 't1/model.pt', 'sha256': digest}
    service = BusinessFileService(data, records=lambda pid, kind: [record])
    assert service.resolve('p1', 'models', 't1/model.pt').path == model
    record.pop('sha256')
    with pytest.raises(BusinessFileNotFound):
        service.resolve('p1', 'models', 't1/model.pt')


def test_record_cannot_alias_another_project_or_private_data(project):
    data, root = project
    for relative in ['projects/p2/models/a.pt', 'auth/private.pt']:
        model = put(data, relative)
        row = {'project_id': 'p1', 'path': str(model), 'identifier': 'a.pt',
               'sha256': hashlib.sha256(model.read_bytes()).hexdigest()}
        with pytest.raises(BusinessFileNotFound):
            BusinessFileService(data, records=lambda pid, kind: [row]).resolve('p1', 'models', 'a.pt')


def test_prediction_input_and_export_use_existing_metadata(project):
    data, root = project
    image = put(root, 'predictions/t1_input.png')
    save(root, 'predictions/t1.evidence.json', {'prediction_id': 't1', 'input_file': image.name,
        'input_sha256': hashlib.sha256(image.read_bytes()).hexdigest()})
    archive = put(root, 'exports/export_model_e1.zip')
    save(root, 'exports/export_model_e1/model_meta.json', {'project_id': 'p1', 'export_id': 'e1',
        'model_path_source': str(root / 'models/a.pt'), 'model_file': 'model/a.pt'})
    service = BusinessFileService(data)
    assert service.resolve('p1', 'predictions', image.name).path == image
    assert service.resolve('p1', 'exports', archive.name).path == archive
    image.write_bytes(b'modified')
    with pytest.raises(BusinessFileNotFound):
        service.resolve('p1', 'predictions', image.name)


def test_cross_project_alias_with_dot_segments_is_denied(project):
    data, root = project
    target = put(data, 'projects/p2/models/a.pt')
    row = {'project_id': 'p1', 'identifier': 'a.pt', 'path': str(root / '..' / 'p2/models/a.pt'),
           'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    with pytest.raises(BusinessFileNotFound):
        BusinessFileService(data, records=lambda pid, kind: [row]).resolve('p1', 'models', 'a.pt')
