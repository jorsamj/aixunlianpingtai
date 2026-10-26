import json

import pytest

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.material_batches import BatchRequestError


def test_findings_pagination_review_identity_and_no_formal_writes(tmp_path):
    from platform_core.smart_material_audit.results import build_results, findings_page, review_finding
    project = tmp_path/"project"
    materials = MaterialRepository(project)
    annotations = AnnotationRepository(project)
    materials.upsert_many([dict(id=f"i-{i}", filename=f"i-{i}.png", content_sha256="a"*64) for i in range(121)])
    inputs = [dict(image_id=f"i-{i}", content_sha256="a"*64,
        annotation_digest=annotations.record_digest(annotations.get(f"i-{i}")), annotation_version=0) for i in range(121)]
    outcome = {"similar_pairs": [dict(image_ids=["i-0",f"i-{i}"],distance=.1) for i in range(1,121)], "annotation_candidates": [], "checks": {}}
    path = tmp_path/"derived/findings.sqlite3"
    build_results(path, inputs, outcome, generation=1)
    before = materials.read()
    page = findings_page(path, project, offset=0, limit=25)
    assert page["total"] == 120 and len(page["items"]) == 25
    second = findings_page(path, project, offset=25, limit=25)
    assert not set(row["issue_id"] for row in page["items"]) & set(row["issue_id"] for row in second["items"])
    item = page["items"][0]
    saved = review_finding(path, project, item["issue_id"], dict(verdict="no_issue", expected_review_token=item["review_token"], note="人工认为正常"), actor_id="signed-user")
    assert saved["review"]["verdict"] == "no_issue" and saved["review_valid"]
    assert materials.read() == before
    assert annotations.summary()["total"] == 0
    materials.patch({item["image_id"]: {"content_sha256": "b"*64}})
    stale = findings_page(path, project, offset=0, limit=25)["items"][0]
    assert stale["stale"] and not stale["review_valid"]
    with pytest.raises(BatchRequestError) as caught:
        review_finding(path, project, item["issue_id"], dict(verdict="no_issue", expected_review_token=item["review_token"]), actor_id="signed-user")
    assert caught.value.code == "SMART_AUDIT_EVIDENCE_CHANGED"


def test_corrected_verdict_requires_actual_saved_gt_change(tmp_path):
    from platform_core.smart_material_audit.results import build_results, findings_page, review_finding
    project = tmp_path/"project"
    materials = MaterialRepository(project)
    annotations = AnnotationRepository(project)
    materials.upsert(dict(id="one", filename="one.png", content_sha256="a"*64))
    inputs = [dict(image_id="one",content_sha256="a"*64,annotation_digest=annotations.record_digest(annotations.get("one")),annotation_version=0)]
    path = tmp_path/"derived/findings.sqlite3"
    build_results(path,inputs,{"annotation_candidates":[dict(image_id="one",issue_type="suspected_annotation")],"similar_pairs":[],"checks":{}},generation=1)
    row = findings_page(path,project)["items"][0]
    with pytest.raises(BatchRequestError) as caught:
        review_finding(path,project,row["issue_id"],dict(verdict="corrected",expected_review_token=row["review_token"]),actor_id="u")
    assert caught.value.code == "SMART_AUDIT_GT_SAVE_REQUIRED"
    # Only the original GT Owner can create the change that makes this verdict valid.
    (project/'project.json').write_text(json.dumps({'id':'project','labels':['fire']}))
    box=dict(label='fire',class_id=0,x1=1,y1=1,x2=10,y2=10)
    annotations.upsert('one',[box],annotation_state='annotated',annotation_scope=['fire'],project_material=False,expected_version=0)
    current=findings_page(path,project)['items'][0]
    receipt=review_finding(path,project,current['issue_id'],dict(verdict='corrected',expected_review_token=current['review_token']),actor_id='u')
    assert receipt['review_valid'] and receipt['review']['verdict']=='corrected'
    assert findings_page(path,project)['review_counts']['corrected']==1
    annotations.upsert('one',[dict(box,x2=12)],annotation_state='annotated',annotation_scope=['fire'],project_material=False,expected_version=1)
    final=findings_page(path,project)
    assert not final['items'][0]['review_valid']
    assert final['review_counts']['corrected']==0 and final['review_counts']['stale']==1
