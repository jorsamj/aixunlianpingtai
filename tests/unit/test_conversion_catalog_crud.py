import json
import sqlite3
import uuid
import pytest
from platform_core.model_artifacts import ModelArtifactRepository
from platform_core.errors import PlatformError


def mutate(repo,entity,action,record=None,identity="",**extra):
    return repo.mutate_conversion_catalog({"operation_id":str(uuid.uuid4()),"expected_revision":repo.conversion_catalog()["revision"],
        "entity":entity,"action":action,"id":identity,"record":record or {},**extra})


def seed(repo):
    vendor=mutate(repo,"vendors","create",{"name":"算能","template_id":"tpu-mlir"})["item"]
    chip=mutate(repo,"chips","create",{"name":"BM1684X","vendor_id":vendor["id"]})["item"]
    return vendor,chip


def test_vendor_and_chip_crud_keep_stable_identity_and_persist(tmp_path):
    repo=ModelArtifactRepository(tmp_path);vendor,chip=seed(repo)
    assert vendor["id"].startswith("vendor-") and chip["id"].startswith("chip-")
    assert chip["sdk_code"]=="bm1684x" and chip["constraint_id"]=="sophon-fp16-verified"
    changed=mutate(repo,"vendors","update",{"name":"新显示名"},vendor["id"])["item"]
    assert changed["id"]==vendor["id"] and changed["template_id"]=="tpu-mlir"
    mutate(repo,"chips","disable",identity=chip["id"])
    assert not ModelArtifactRepository(tmp_path).conversion_catalog()["chips"][0]["enabled"]
    mutate(repo,"chips","enable",identity=chip["id"])
    with pytest.raises(PlatformError) as error: mutate(repo,"chips","delete",identity=chip["id"])
    assert error.value.code=="CATALOG_DELETE_CONFIRMATION_REQUIRED"
    with pytest.raises(PlatformError) as error: mutate(repo,"vendors","delete",identity=vendor["id"],confirm_delete=True)
    assert error.value.code=="CATALOG_REFERENCED"
    mutate(repo,"chips","delete",identity=chip["id"],confirm_delete=True)
    mutate(repo,"vendors","delete",identity=vendor["id"],confirm_delete=True)
    assert repo.conversion_catalog()["vendors"]==repo.conversion_catalog()["chips"]==[]


def test_idempotency_revision_conflict_and_hidden_rows_are_atomic(tmp_path):
    repo=ModelArtifactRepository(tmp_path);vendor,chip=seed(repo)
    body={"operation_id":"retry-op","expected_revision":2,"entity":"chips","action":"update","id":chip["id"],"record":{"name":"new name"}}
    first=repo.mutate_conversion_catalog(body);second=repo.mutate_conversion_catalog(body)
    assert second["replayed"] and second["revision"]==first["revision"]==3
    assert len(repo.conversion_catalog()["vendors"])==len(repo.conversion_catalog()["chips"])==1
    with pytest.raises(PlatformError) as error: repo.mutate_conversion_catalog({**body,"record":{"name":"changed request"}})
    assert error.value.code=="CATALOG_OPERATION_CONFLICT"
    with pytest.raises(PlatformError) as error: repo.mutate_conversion_catalog({**body,"operation_id":"stale-op"})
    assert error.value.code=="CATALOG_REVISION_CONFLICT"
    audit=repo.conversion_catalog_operation("retry-op")
    assert audit["before"]["name"]=="BM1684X" and audit["after"]["name"]=="new name"
    assert repo.conversion_catalog()["revision"]==3


@pytest.mark.parametrize("record",[{"name":"算能","template_id":"rknn"},{"name":" 算能 ","template_id":"tpu-mlir"}])
def test_duplicate_vendor_name_is_rejected_without_changing_catalog(tmp_path,record):
    repo=ModelArtifactRepository(tmp_path);seed(repo);before=repo.conversion_catalog()
    with pytest.raises(PlatformError) as error: mutate(repo,"vendors","create",record)
    assert error.value.code=="CATALOG_DUPLICATE_NAME" and repo.conversion_catalog()==before


@pytest.mark.parametrize("source",["job","durable_task","artifact","mapping","publication","version"])
def test_referenced_chip_cannot_be_physically_deleted_or_rebound(tmp_path,source):
    repo=ModelArtifactRepository(tmp_path);vendor,chip=seed(repo)
    payload={"params":{"local_vendor_id":vendor["id"],"local_chip_id":chip["id"],"chip":"bm1684x"},"target":"sophon"}
    if source=="job":
        path=tmp_path/"projects"/"p"/"deployment"/"jobs"/"job-1"/"job.json";path.parent.mkdir(parents=True);path.write_text(json.dumps(payload))
    elif source=="durable_task":
        from platform_core.task_runtime.repository import TaskRepository
        from platform_core.task_runtime.models import TaskRecord,TaskKind
        from platform_core.task_runtime.artifacts import ArtifactStore
        tasks=TaskRepository(tmp_path/"task_runtime"/"tasks.sqlite3")
        store=ArtifactStore(tmp_path/"task_runtime"/"artifacts");store.atomic_write_json("t","request.json",payload)
        tasks.create(TaskRecord.new("t","p",TaskKind.MODEL_CONVERSION,"request.json","conversion"),artifacts=store)
    elif source=="artifact":
        repo.upsert({"artifact_id":"artifact-1","project_id":"p","algorithm_id":"a","version_id":"v","target":"sophon","artifact_kind":"converted",
            "file_name":"x.bmodel","source_path":"/isolated/x.bmodel","sha256":"a"*64,"size_bytes":12,"metadata":payload["params"]})
    elif source=="mapping":
        path=tmp_path/"external_algorithm_publish"/"config.json";path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"target_mappings":{"sophon":{"chip_mappings":{"BM1684X":"external-id"}}}}))
    elif source=="publication":
        from platform_core.external_algorithm_publish import ExternalPublicationRepository
        publications=ExternalPublicationRepository(tmp_path)
        with sqlite3.connect(publications.db_path) as db:
            db.execute("INSERT INTO external_model_artifacts (artifact_id,publication_key,project_id,algorithm_id,version_id,target,file_name,source_path,source_sha256,size_bytes,chip_code,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("old","pub","p","a","v","sophon","x.bmodel","/isolated/x.bmodel","a"*64,12,"BM1684X","old","old"))
    else:
        path=tmp_path/"projects"/"p"/"algorithms.json";path.parent.mkdir(parents=True);path.write_text(json.dumps([{"versions":[{"conversion_params":payload["params"]}]}]))
    before=repo.conversion_catalog();refs=repo.conversion_catalog_references("chips",chip["id"])
    assert refs["references"] and not refs["can_delete"]
    for action,record in [("delete",{}),("update",{"sdk_code":"bm1688"})]:
        with pytest.raises(PlatformError) as error: mutate(repo,"chips",action,record,chip["id"],confirm_delete=True)
        assert error.value.code=="CATALOG_REFERENCED"
    assert repo.conversion_catalog()==before
    mutate(repo,"chips","disable",identity=chip["id"])


def test_corrupt_reference_evidence_fails_closed(tmp_path):
    repo=ModelArtifactRepository(tmp_path);_,chip=seed(repo)
    path=tmp_path/"projects"/"p"/"deploy"/"jobs"/"broken"/"job.json";path.parent.mkdir(parents=True);path.write_text("{broken")
    with pytest.raises(PlatformError) as error: mutate(repo,"chips","delete",identity=chip["id"],confirm_delete=True)
    assert error.value.code=="CATALOG_REFERENCE_CHECK_FAILED"


def test_server_search_filters_pagination_and_counts_are_real(tmp_path):
    from platform_core.compute_platform_catalog import conversion_catalog_records
    repo=ModelArtifactRepository(tmp_path);vendor,chip=seed(repo)
    for i in range(12):mutate(repo,"vendors","create",{"name":f"Other {i:02}","template_id":"cambricon","enabled":i%2==0})
    page=conversion_catalog_records(repo.conversion_catalog(),entity="vendors",query="Other",page=2,page_size=5)
    assert page["total"]==12 and len(page["items"])==5 and page["page"]==2
    filtered=conversion_catalog_records(repo.conversion_catalog(),entity="vendors",template_id="cambricon",enabled="true")
    assert filtered["total"]==6
    chips=conversion_catalog_records(repo.conversion_catalog(),entity="chips",vendor_id=vendor["id"])
    assert chips["items"][0]["id"]==chip["id"]
    vendors=conversion_catalog_records(repo.conversion_catalog(),entity="vendors",query="算能")
    assert vendors["items"][0]["chip_count"]==vendors["items"][0]["enabled_chip_count"]==1


def test_external_binding_save_serializes_with_catalog_delete_without_membership_gate(tmp_path):
    from contextlib import contextmanager
    from filelock import FileLock,Timeout
    from platform_core.external_algorithm_publish import ExternalPublicationRepository,ExternalPublishConfigPayload
    repository=ExternalPublicationRepository(tmp_path)
    class CheckOriginalWriteLock:
        def __enter__(self):
            with pytest.raises(Timeout):FileLock(str(tmp_path/"model_artifacts"/".conversion-catalog.lock")).acquire(timeout=0)
        def __exit__(self,*args):return False
    repository.lock=CheckOriginalWriteLock()
    saved=repository.save_config(ExternalPublishConfigPayload(target_mappings={"sophon":{"compute_platform_id":"parent","chip_mappings":{"BM1684X":"child"}}}))
    assert saved["target_mappings"]["sophon"]["chip_mappings"]["BM1684X"]=="child"


def test_automatic_record_identities_and_trusted_aliases_belong_to_backend(tmp_path):
    repo=ModelArtifactRepository(tmp_path)
    vendor=mutate(repo,"vendors","create",{"name":"SDK vendor","template_id":"tpu-mlir"})["item"]
    ids=set()
    for name,expected in [("bm-1684x","bm1684x"),("BM1688","bm1688"),("定制BM1684X","")]:
        chip=mutate(repo,"chips","create",{"name":name,"vendor_id":vendor["id"]})["item"]
        uuid.UUID(chip["id"].removeprefix("chip-"));ids.add(chip["id"])
        assert chip["sdk_code"]==expected
    other=mutate(repo,"vendors","create",{"name":"other","template_id":"rknn"})["item"]
    unknown=mutate(repo,"chips","create",{"name":"BM1684X","vendor_id":other["id"]})["item"]
    assert unknown["sdk_code"]==unknown["constraint_id"]=="" and len(ids)==3


def test_duplicate_chip_code_name_and_invalid_association_preserve_original(tmp_path):
    repo=ModelArtifactRepository(tmp_path);vendor,chip=seed(repo);original=repo.conversion_catalog()
    for record in [{"name":"BM1684X","vendor_id":vendor["id"]},{"name":"Different","code":chip["code"],"vendor_id":vendor["id"]},
                   {"name":"Different","vendor_id":"missing"}]:
        with pytest.raises(PlatformError): mutate(repo,"chips","create",record)
        assert repo.conversion_catalog()==original
    with pytest.raises(PlatformError) as error: mutate(repo,"chips","update",{"id":"changed"},chip["id"])
    assert error.value.code=="CATALOG_ID_IMMUTABLE"
    changed=mutate(repo,"chips","update",{"sdk_code":"bm1688"},chip["id"])
    assert changed["item"]["id"]==chip["id"] and changed["item"]["sdk_code"]=="bm1688"


def test_reference_scan_includes_artifacts_beyond_default_list_limit(tmp_path):
    repo=ModelArtifactRepository(tmp_path);vendor,chip=seed(repo)
    with sqlite3.connect(repo.db_path) as db:
        for index in range(501):
            db.execute("INSERT INTO model_artifacts (artifact_id,project_id,algorithm_id,version_id,target,artifact_kind,file_name,source_path,sha256,size_bytes,metadata_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(index),"p","a",str(index),"sophon","converted","x.bmodel","/isolated/x","a"*64,12,json.dumps({"local_chip_id":chip["id"]}) if index==500 else "{}","old","old"))
    refs=repo.conversion_catalog_references("chips",chip["id"])
    assert not refs["can_delete"] and refs["references"]==[{"type":"MODEL_ARTIFACT","id":"500"}]


def test_reference_scan_includes_late_durable_job_dir_payloads(tmp_path):
    from platform_core.task_runtime.repository import TaskRepository
    from platform_core.task_runtime.models import TaskRecord,TaskKind
    from platform_core.task_runtime.artifacts import ArtifactStore
    repo=ModelArtifactRepository(tmp_path);vendor,chip=seed(repo)
    tasks=TaskRepository(tmp_path/"task_runtime"/"tasks.sqlite3");store=ArtifactStore(tmp_path/"task_runtime"/"artifacts")
    job=tmp_path/"projects"/"p"/"deployment"/"jobs"/"late";job.mkdir(parents=True)
    (job/"job.json").write_text(json.dumps({"params":{"local_chip_id":chip["id"]}}))
    for index in range(101):
        identity=f"task-{index:03}";store.atomic_write_json(identity,"request.json",{"job_dir":str(job)} if index==100 else {"target":"rockchip","params":{"chip":"rk3568"}})
        tasks.create(TaskRecord.new(identity,"p",TaskKind.MODEL_CONVERSION,"request.json","conversion"),artifacts=store)
    assert any(r["id"]=="task-100" for r in repo.conversion_catalog_references("chips",chip["id"])["references"])
    (job/"job.json").unlink()
    with pytest.raises(PlatformError) as error: repo.conversion_catalog_references("chips",chip["id"])
    assert error.value.code=="CATALOG_REFERENCE_CHECK_FAILED"

@pytest.mark.parametrize("invalid",[None,"broken",42])
def test_corrupt_algorithm_payload_never_proves_absence_of_references(tmp_path,invalid):
    repo=ModelArtifactRepository(tmp_path);_,chip=seed(repo)
    path=tmp_path/"projects"/"p"/"algorithms.json";path.parent.mkdir(parents=True);path.write_text(json.dumps(invalid))
    with pytest.raises(PlatformError) as error: repo.conversion_catalog_references("chips",chip["id"])
    assert error.value.code=="CATALOG_REFERENCE_CHECK_FAILED"


def test_explicit_local_identity_does_not_bind_another_vendor_same_sdk(tmp_path):
    repo=ModelArtifactRepository(tmp_path);vendor,chip=seed(repo)
    other=mutate(repo,"vendors","create",{"name":"Second","template_id":"tpu-mlir"})["item"]
    other_chip=mutate(repo,"chips","create",{"name":"BM1684X","vendor_id":other["id"]})["item"]
    job=tmp_path/"projects"/"p"/"deploy"/"jobs"/"explicit"/"job.json";job.parent.mkdir(parents=True)
    job.write_text(json.dumps({"target":"sophon","params":{"local_vendor_id":vendor["id"],"local_chip_id":chip["id"],"chip":"bm1684x"}}))
    assert repo.conversion_catalog_references("chips",other_chip["id"])["can_delete"]
    assert not repo.conversion_catalog_references("chips",chip["id"])["can_delete"]
    mutate(repo,"chips","delete",identity=other_chip["id"],confirm_delete=True)


def test_legacy_version_without_ids_is_not_hidden_by_a_sibling_with_local_ids(tmp_path):
    repo=ModelArtifactRepository(tmp_path);vendor,chip=seed(repo)
    old=mutate(repo,"chips","create",{"name":"BM1688","vendor_id":vendor["id"]})["item"]
    path=tmp_path/"projects"/"p"/"algorithms.json";path.parent.mkdir(parents=True)
    path.write_text(json.dumps([{"versions":[{"target":"sophon","params":{"local_chip_id":chip["id"],"chip":"bm1684x"}},{"target":"sophon","params":{"chip":"bm1688"}}]}]))
    assert not repo.conversion_catalog_references("chips",old["id"])["can_delete"]
