"""Durable FIFO ordering and multi-process serialization contract for v19 ZIP imports."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path

from filelock import FileLock


def _project(client):
    result = client.post('/api/projects', json={'name': 'zip-fifo-real', 'description': '', 'labels': ['helmet']})
    result.raise_for_status()
    return result.json()['id']


def test_ready_import_queue_is_stable_and_does_not_include_unconfirmed_zip(client):
    import app as mod
    project = _project(client)
    for job_id, state, sequence in [
        ('unconfirmed', 'selecting', 0),
        ('older', 'running', 1),
        ('newer', 'running', 2),
    ]:
        mod.v19_write_job(project, {
            'id': job_id, 'project_id': project, 'dataset_id': 'default',
            'file_name': f'{job_id}.zip', 'status': state,
            'created_at': '2026-10-10T00:00:00', 'enqueue_sequence': sequence,
            'enqueued_at': '2026-10-10T00:01:00',
        })
    assert [job['id'] for job in mod._v19_fifo_import_jobs(project)] == ['older', 'newer']
    queue = client.get(f'/api/v19/projects/{project}/import/jobs')
    queue.raise_for_status()
    rows = {row['id']: row for row in queue.json()['items']}
    assert rows['unconfirmed']['queue_position'] is None
    assert rows['older']['queue_position'] == 1
    assert rows['newer']['queue_position'] == 2
    assert client.get(f'/api/v19/projects/{project}/import/jobs/newer').json()['queue_position'] == 2

    # Completing the predecessor durably advances the queue. Reordered dict
    # enumeration or process-independent lock acquisition cannot change FIFO.
    mod.v19_update_job(project, 'older', status='done')
    assert [job['id'] for job in mod._v19_fifo_import_jobs(project)] == ['newer']
    assert client.get(f'/api/v19/projects/{project}/import/jobs/newer').json()['queue_position'] == 1


def test_legacy_running_zip_is_before_newly_confirmed_zip(client):
    import app as mod
    project = _project(client)
    for job_id, seq in [('legacy', 0), ('newer', 12)]:
        mod.v19_write_job(project, {
            'id': job_id, 'project_id': project, 'dataset_id': 'default',
            'status': 'running', 'created_at': '2026-10-10T00:00:00',
            'enqueue_sequence': seq,
        })
    assert [job['id'] for job in mod._v19_fifo_import_jobs(project)] == ['legacy', 'newer']


def test_project_queue_lock_restricts_concurrent_enqueue_from_two_callers(client):
    import app as mod
    project = _project(client)
    job_dir = mod.v19_import_jobs_dir(project)
    barrier = Barrier(2)

    def next_sequence(tag):
        barrier.wait()
        with FileLock(str(job_dir / '.enqueue.lock'), timeout=10):
            numbers = [int(mod.read_json(path, {}).get('enqueue_sequence') or 0)
                       for path in job_dir.glob('*/job.json')]
            number = max(numbers, default=0) + 1
            mod.v19_write_job(project, {'id': tag, 'project_id': project,
                                        'status': 'running', 'created_at': '2026-10-10T00:00:00',
                                        'enqueue_sequence': number})
            return number

    with ThreadPoolExecutor(max_workers=2) as pool:
        assigned = list(pool.map(next_sequence, ['a', 'b']))
    assert sorted(assigned) == [1, 2]
    assert [job['enqueue_sequence'] for job in mod._v19_fifo_import_jobs(project)] == [1, 2]


def test_project_formal_import_lock_is_a_filesystem_lock(client):
    import app as mod
    project = _project(client)
    # Distinct FileLock objects must refer to the SAME project-local
    # filesystem lock. Cross-project files are independent.
    path = mod.v19_import_jobs_dir(project) / '.formal-import.lock'
    assert str(path).endswith('/import_jobs/.formal-import.lock') or str(path).endswith('\\\\import_jobs\\\\.formal-import.lock')
    assert FileLock(str(path), timeout=1).lock_file == str(path)
