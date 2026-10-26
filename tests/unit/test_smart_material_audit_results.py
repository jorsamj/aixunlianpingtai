import json
import pytest

import pytest

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository

@pytest.mark.parametrize('checked',[True,False])
def test_native_annotation_summary_distinguishes_box_image_and_unknown_counts(tmp_path,checked):
    from platform_core.smart_material_audit.results import build_results,findings_page
    project=tmp_path/'p';materials=MaterialRepository(project);AnnotationRepository(project)
    inputs=[]
    for name in ['a','b']:
        materials.upsert(dict(id=name,filename=name+'.png',content_sha256='a'*64))
        inputs.append(dict(image_id=name,content_sha256='a'*64))
    path=tmp_path/'derived.sqlite3'
    check={'status':'completed','checked':2,'location_evidence':True} if checked else {'status':'not_checked','checked':0}
    build_results(path,inputs,{'annotation_candidates':[{'image_id':'a','possible_missing':2,'possible_spurious':0,'mistakenness':.1,'mistakenness_loc':.8},
        {'image_id':'b','possible_missing':1,'possible_spurious':1,'mistakenness':.9,'mistakenness_loc':.1}],'checks':{'mistakenness':check}},generation=1)
    summary=findings_page(path,project)['annotation_summary']
    assert summary['suspected_images']==(2 if checked else None)
    assert summary['possible_missing_boxes']==(3 if checked else None)
    assert summary['location_difference_images']==(1 if checked else None)
    assert summary['class_difference_images']==(1 if checked else None)
    assert summary['label_conflicts'] is None
    assert summary['pending_candidates']==2 and summary['confirmed_candidates']==0
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
