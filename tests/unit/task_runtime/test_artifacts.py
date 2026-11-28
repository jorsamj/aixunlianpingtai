import pytest

from platform_core.task_runtime import ArtifactStore


def test_artifacts_are_atomic_and_task_relative(tmp_path):
    store = ArtifactStore(tmp_path)
    store.atomic_write_json("task-1", "checkpoints/video.json", {"next_index": 31})
    assert store.read_json("task-1", "checkpoints/video.json") == {"next_index": 31}

    store.append_log("task-1", "logs/task.log", "frame batch committed\n")
    assert store.artifact_path("task-1", "logs/task.log").read_text(encoding="utf-8") == (
        "frame batch committed\n"
    )


@pytest.mark.parametrize(
    "value",
    [
        "../escape.json",
        "/tmp/escape.json",
        r"C:\escape.json",
        r"folder\..\escape.json",
    ],
)
def test_artifact_store_rejects_escape(tmp_path, value):
    with pytest.raises(ValueError, match="relative task artifact"):
        ArtifactStore(tmp_path).artifact_path("task-1", value)


def test_task_id_is_also_a_single_safe_path_component(tmp_path):
    store = ArtifactStore(tmp_path)
    for task_id in ("../task", "nested/task", r"nested\task", "C:"):
        with pytest.raises(ValueError, match="task id"):
            store.artifact_path(task_id, "payload.json")


def test_delete_task_never_follows_another_tasks_root_link(tmp_path):
    store=ArtifactStore(tmp_path/'artifacts')
    store.atomic_write_json('protected','payload.json',{'original':True})
    alias=store.root/'alias'
    try:
        alias.symlink_to(store.root/'protected',target_is_directory=True)
    except OSError as error:
        pytest.skip(f'symlink creation unavailable: {error}')
    with pytest.raises(ValueError,match='root link'):
        store.delete_task('alias')
    assert store.read_json('protected','payload.json')=={'original':True}


def test_large_frozen_evidence_is_independent_of_payload_size_limit(tmp_path):
    from platform_core.task_runtime.payload_publications import PayloadPublicationIdentity
    store=ArtifactStore(tmp_path,max_payload_bytes=1024)
    evidence={'rows':[{'image_id':f'image-{i:08d}','content_sha256':'a'*64,
        'annotation_hash':'b'*64,'relative_path':f'images/{i:08d}.jpg'} for i in range(20000)]}
    ref=store.write_evidence_json('large',evidence)
    assert (tmp_path/'large'/ref).stat().st_size>1024*1024
    proposal=store.prepare_payload_publication(PayloadPublicationIdentity(task_id='large',project_id='p',
        kind='TRAINING',phase='create',expected_ref='',expected_parent_attempt=0,
        intent={'request_id':'large'}),{'input_freeze_ref':ref})
    assert len(proposal.version.raw)<1024
    assert ArtifactStore(tmp_path,max_payload_bytes=1024).read_json('large',ref)==evidence
