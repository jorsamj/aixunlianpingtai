"""History preview cache must track dependencies, not Worker telemetry."""

import sqlite3

from platform_core.material_history_index import _source_signature, query_material_history
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def test_history_signature_ignores_progress_and_log_writes_but_tracks_evidence(tmp_path):
    project = tmp_path / 'projects' / 'p'
    project.mkdir(parents=True)
    repository = TaskRepository(tmp_path / 'task_runtime' / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'task_runtime' / 'artifacts')
    task = TaskRecord.new('training-task', 'p', TaskKind.TRAINING, 'request.json', 'cpu')
    repository.create(task, artifacts=artifacts)
    artifacts.atomic_write_json(task.task_id, task.payload_ref, {'train_image_ids': ['image-a']})

    def signature():
        return _source_signature('p', project, repository, artifacts)

    initial = signature()
    calls = []

    def scanner(*_args, with_reasons=False):
        assert with_reasons
        calls.append(True)
        return {'image-a': [{'reason': 'TRAINING_HISTORY', 'protected': True}]}

    first = query_material_history('p', project, repository, artifacts, scanner,
                                   reference_image_ids=['image-a'])
    with sqlite3.connect(repository.path) as db:
        db.execute("UPDATE tasks SET progress=0.6,stage='training',updated_at='2026-11-02T12:00:00Z' "
                   "WHERE task_id='training-task'")
    with artifacts.artifact_path(task.task_id, task.log_ref).open('a', encoding='utf-8') as log:
        log.write('Worker progress updated\n')
    assert signature() == initial
    assert query_material_history('p', project, repository, artifacts, scanner,
                                  reference_image_ids=['image-a']) == first
    assert len(calls) == 1

    with sqlite3.connect(repository.path) as db:
        db.execute("UPDATE tasks SET status='RUNNING' WHERE task_id='training-task'")
    changed_status = signature()
    assert changed_status != initial
    artifacts.atomic_write_json(task.task_id, 'input-freeze.json', {'train_image_ids': ['image-b']})
    assert signature() != changed_status
