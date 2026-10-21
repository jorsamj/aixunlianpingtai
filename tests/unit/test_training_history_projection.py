import json
import pytest

from platform_core.training_history_projection import TrainingHistoryProjection, successful_training_counts


def test_incremental_history_reads_only_changed_files_and_returns_copies(tmp_path):
    job = tmp_path / 'one' / 'job.json'
    job.parent.mkdir()
    job.write_text(json.dumps({'id': 'one', 'status': 'failed'}))
    reads = []
    def read(path):
        reads.append(path)
        return json.loads(path.read_text())
    projection = TrainingHistoryProjection()
    rows = projection.read(tmp_path, read)
    rows[0]['status'] = 'corrupted'
    assert projection.read(tmp_path, read)[0]['status'] == 'failed'
    assert len(reads) == 1
    job.write_text(json.dumps({'id': 'one', 'status': 'done', 'artifact_verified': True}))
    assert projection.read(tmp_path, read)[0]['status'] == 'done'
    assert len(reads) == 2
    job.unlink()
    assert projection.read(tmp_path, read) == []


def test_counts_require_success_evidence_and_canonical_identity():
    rows = [
        {'id': 'ok', 'asset_algorithm_id': 'a', 'status': 'done', 'artifact_verified': True},
        {'id': 'shadow', 'task_id': 'ok', 'asset_algorithm_id': 'a', 'status': 'done', 'artifact_verified': True},
        {'id': 'failed', 'asset_algorithm_id': 'a', 'status': 'failed', 'artifact_verified': True},
        {'id': 'no-evidence', 'asset_algorithm_id': 'a', 'status': 'done'},
        {'id': 'running', 'asset_algorithm_id': 'a', 'status': 'running', 'artifact_verified': True},
        {'id': 'convert', 'asset_algorithm_id': 'a', 'status': 'done', 'kind': 'MODEL_CONVERSION', 'artifact_verified': True},
        {'id': 'other', 'asset_algorithm_id': 'b', 'status': 'finished', 'artifact_verified': True},
    ]
    assert successful_training_counts(rows) == {'a': 1, 'b': 1}


def test_durable_truth_overrides_legacy_and_retry_is_one_identity():
    rows = [{'id': 'one', 'asset_algorithm_id': 'a', 'status': 'done', 'artifact_verified': True}]
    assert successful_training_counts(rows, {'one': {'status': 'FAILED', 'kind': 'TRAINING'}}) == {}
    assert successful_training_counts(rows, {'one': {'status': 'SUCCEEDED', 'kind': 'TRAINING', 'result_ref': 'result.json'}}) == {'a': 1}
    assert successful_training_counts(rows, {'one': {'status': 'RUNNING', 'kind': 'TRAINING'}}) == {}


def test_count_has_no_history_page_limit():
    rows = [{'id': f'job-{i}', 'asset_algorithm_id': 'a', 'status': 'done', 'artifact_verified': True} for i in range(151)]
    assert successful_training_counts(rows) == {'a': 151}


@pytest.mark.parametrize('status', ['QUEUED', 'PENDING', 'WAITING_RESOURCE', 'PREPARING', 'STARTING', 'RUNNING', 'PAUSED', 'RESUMING', 'FAILED', 'CANCELLED', 'STOPPED', 'BLOCKED', ''])
def test_non_success_states_never_count_even_with_model_evidence(status):
    assert successful_training_counts([{'id': 'one', 'asset_algorithm_id': 'a', 'status': status, 'artifact_verified': True}]) == {}
