"""Non-mutating data-fetch projections: optional UI summaries cannot drop canonical truth."""
from platform_core.runtime_catalog_service import RuntimeCatalogService
import platform_core.conversion_management_service as conversion_management_owner
import platform_core.deployment_validation_service as deployment_validation_owner

import app as api
import pytest


def test_jobs_summary_is_opt_in_and_cannot_mutate_full_report(monkeypatch):
    original = {
        "id": "job-1", "status": "done", "history": [{"epoch": 1}],
        "evaluation": {"large": "evidence"},
        "training_report": {"status": "succeeded", "epoch_history": [1, 2]},
    }
    monkeypatch.setattr(api, "get_project", lambda project_id: {"id": project_id})
    monkeypatch.setattr(api, "sync_jobs_index", lambda project_id, read_only: [original])
    monkeypatch.setattr(api, "_v53_fast_jobs_summary", lambda project_id: [api._v53_job_summary(original)])

    projected = api.list_jobs("fixture", summary_only=True)
    assert projected[0]["id"] == "job-1"
    assert projected[0]["status"] == "done"
    assert "history" not in projected[0]
    assert "evaluation" not in projected[0]
    assert "epoch_history" not in projected[0]["training_report"]

    canonical = api.list_jobs("fixture")
    assert canonical[0] == original
    assert original["evaluation"]["large"] == "evidence"


def test_fast_jobs_summary_uses_bounded_index_and_live_task_truth(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    job_root = tmp_path / "project" / "jobs"
    job_root.mkdir(parents=True)
    (job_root / "index.json").write_text(json.dumps([
        {"id": "task-1", "asset_algorithm_id": "algorithm-1", "status": "queued",
         "created_at": "2026-11-08T01:00:00Z", "evaluation": {"huge": "hidden"}},
        {"id": "task-0", "status": "done", "created_at": "2026-11-07T01:00:00Z"},
        {"id": "task-retired", "status": "done", "created_at": "2026-11-06T01:00:00Z"},
    ]), encoding="utf-8")
    monkeypatch.setattr(api, "project_dir", lambda project_id: job_root.parent)
    task = SimpleNamespace(
        task_id="task-1", project_id="fixture", kind=api.TaskKind.TRAINING,
        status=api.TaskStatus.RUNNING, updated_at="2026-11-08T02:00:00Z",
        created_at="2026-11-08T01:00:00Z", payload_ref="payload.json",
    )

    class Repository:
        def deleted_task_ids(self, identities, *, project_id):
            assert project_id == 'fixture'
            assert set(identities) == {'task-1', 'task-0', 'task-retired'}
            return {'task-retired'}

        def list(self, **kwargs):
            if kwargs.get("statuses"):
                return SimpleNamespace(items=(task,), next_cursor=None)
            assert kwargs["limit"] == 50
            return SimpleNamespace(items=(task,), next_cursor=None)

        def get(self, task_id):
            raise AssertionError("no N+1 lookup for an already loaded active task")

    monkeypatch.setattr(api, "shared_task_repository", Repository)
    monkeypatch.setattr(api, "task_to_public", lambda task, repository: {
        "status": "RUNNING", "phase": "training", "persisted_status": "RUNNING",
        "progress_percent": 37, "current_item": "epoch 2", "worker_id": "worker-1",
    })
    monkeypatch.setattr(conversion_management_owner, 'task_to_public', api.task_to_public)
    monkeypatch.setattr(deployment_validation_owner, 'task_to_public', api.task_to_public)
    monkeypatch.setattr(api, "sync_jobs_index", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("summary cannot scan all archived training jobs")
    ))
    rows = api._v53_fast_jobs_summary("fixture")
    assert len(rows) == 2
    assert rows[0]["id"] == "task-1"
    assert rows[0]["status"] == "running"
    assert rows[0]["progress_percent"] == 37
    assert rows[0]["asset_algorithm_id"] == "algorithm-1"
    assert "evaluation" not in rows[0]
    assert rows[1]["id"] == "task-0"


@pytest.mark.parametrize('projection', ['_v53_fast_jobs_summary', '_v53_live_jobs'])
@pytest.mark.parametrize('failure', ['repository', 'tombstones'])
def test_jobs_projection_fails_closed_when_deletion_identity_is_unavailable(tmp_path,monkeypatch,projection,failure):
    import json
    import sqlite3
    jobs=tmp_path/'jobs'
    jobs.mkdir()
    indexed=[{'id':'retired','status':'done'}]
    (jobs/'index.json').write_text(json.dumps(indexed),encoding='utf-8')
    monkeypatch.setattr(api,'project_dir',lambda _:tmp_path)
    # Force the old-index fallback, where unverified deletion used to resurrect.
    monkeypatch.setattr(api,'sync_jobs_index',lambda *args,**kwargs:(_ for _ in ()).throw(sqlite3.OperationalError('projection unavailable')))
    class Repository:
        def deleted_task_ids(self,*args,**kwargs):
            raise sqlite3.OperationalError('tombstones unavailable')
    def repository():
        if failure=='repository':raise sqlite3.OperationalError('database unavailable')
        return Repository()
    monkeypatch.setattr(api,'shared_task_repository',repository)
    with pytest.raises(api.HTTPException) as error:
        getattr(api,projection)('fixture')
    assert error.value.status_code==503
    assert 'TRAINING_TASK_DELETE_STATE_UNAVAILABLE' in str(error.value.detail)
    assert json.loads((jobs/'index.json').read_text())==indexed


@pytest.mark.parametrize('source',['live','fallback'])
def test_live_jobs_verifies_deletion_for_both_live_and_fallback_rows(tmp_path,monkeypatch,source):
    import json
    jobs=tmp_path/'jobs'
    jobs.mkdir()
    rows=[{'id':'retired','status':'done'},{'id':'kept','status':'running'}]
    (jobs/'index.json').write_text(json.dumps(rows),encoding='utf-8')
    monkeypatch.setattr(api,'project_dir',lambda _:tmp_path)
    def sync(*args,**kwargs):
        if source=='fallback':raise OSError('one job cannot be enriched')
        return rows
    monkeypatch.setattr(api,'sync_jobs_index',sync)
    class Repository:
        def deleted_task_ids(self,identities,*,project_id):
            assert project_id=='fixture' and set(identities)=={'retired','kept'}
            return {'retired'}
    monkeypatch.setattr(api,'shared_task_repository',Repository)
    assert [row['id'] for row in api._v53_live_jobs('fixture')]==['kept']


def test_fast_summary_enrichment_failure_keeps_only_deletion_verified_index(tmp_path,monkeypatch):
    import json
    import sqlite3
    jobs=tmp_path/'jobs'
    jobs.mkdir()
    indexed=[{'id':'retired','status':'done'},{'id':'kept','status':'done'}]
    (jobs/'index.json').write_text(json.dumps(indexed),encoding='utf-8')
    monkeypatch.setattr(api,'project_dir',lambda _:tmp_path)
    calls=[]
    class Repository:
        def deleted_task_ids(self,identities,*,project_id):
            calls.append((set(identities),project_id))
            return {'retired'}
        def list(self,**kwargs):
            raise sqlite3.OperationalError('enrichment unavailable after tombstone verification')
        def get(self,*args):
            pytest.fail('fallback must not perform N+1 lookups')
    monkeypatch.setattr(api,'shared_task_repository',Repository)
    assert [row['id'] for row in api._v53_fast_jobs_summary('fixture')]==['kept']
    assert calls==[({'retired','kept'},'fixture')]


def test_recommendation_is_neutral_and_never_probes_web_cuda_by_default(monkeypatch):
    monkeypatch.setattr(RuntimeCatalogService, "gpu_runtime_truth", staticmethod(lambda: {"workers": [], "gpus": []}))
    monkeypatch.setattr(api.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("default recommendation must not start a GPU probe")
    ))
    payload = api.system_recommendation()
    assert payload["recommendation_source"] == "unverified_fallback"
    assert payload["worker_verified"] is False
    assert payload["cuda"] is None
    assert payload["cpu_count"] is None
    assert payload["ram_gb"] is None
    assert payload["recommendation"]["device"] == "auto"


def test_recommendation_uses_only_fresh_gpu_visible_to_live_training_worker(monkeypatch):
    runtime = {
        "generated_at": "2026-11-08T04:00:00Z",
        "workers": [
            {"node_id": "train-node", "worker_id": "worker-1", "online": True,
             "task_kinds": ["TRAINING"]},
            {"node_id": "old-node", "worker_id": "worker-2", "online": False,
             "task_kinds": ["TRAINING"]},
        ],
        "worker_gpu_visibility": [
            {"node_id": "train-node", "worker_id": "worker-1", "gpu_uuid": "uuid-1"},
            {"node_id": "old-node", "worker_id": "worker-2", "gpu_uuid": "uuid-2"},
        ],
        "gpus": [
            {"node_id": "train-node", "gpu_uuid": "uuid-1", "name": "A800",
             "metrics_fresh": True, "telemetry_available": True},
            {"node_id": "old-node", "gpu_uuid": "uuid-2", "name": "4070",
             "metrics_fresh": True, "telemetry_available": True},
        ],
    }
    monkeypatch.setattr(RuntimeCatalogService, "gpu_runtime_truth", staticmethod(lambda: runtime))
    recommendation = api.system_recommendation()
    assert recommendation["recommendation_source"] == "worker_gpu_telemetry"
    assert recommendation["worker_verified"] is True
    assert recommendation["gpu"] == "A800"
    assert recommendation["worker_gpu_count"] == 1
    assert recommendation["recommendation"]["device"] == "auto"

    runtime["gpus"][0]["metrics_fresh"] = False
    fallback = api.system_recommendation()
    assert fallback["recommendation_source"] == "unverified_fallback"
    assert fallback["worker_verified"] is False


def test_algorithm_card_summary_never_claims_exact_lifetime_count_from_window(monkeypatch):
    monkeypatch.setattr(api, "list_algorithms_internal", lambda project_id, summary_only=False: [
        {"id": "algorithm-1", "name": "行人检测", "versions": [], "versions_compact": summary_only}
    ])
    monkeypatch.setattr(api, "_successful_training_counts", lambda project_id: {"algorithm-1": 151})
    compact = api.v12_list_algorithms("fixture", summary_only=True)
    assert compact["items"][0]["successful_training_count"] is None
    assert compact["items"][0]["versions_compact"] is True
    full = api.v12_list_algorithms("fixture")
    assert full["items"][0]["successful_training_count"] == 151
