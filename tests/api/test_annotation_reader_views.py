from types import SimpleNamespace
import pytest
import app as api

def test_annotation_reader_detail_identity_and_unknown_counts(monkeypatch):
    task=SimpleNamespace(task_id='t',kind=api.TaskKind.AI_ANNOTATION,status=api.TaskStatus.QUEUED)
    monkeypatch.setattr(api,'_require_annotation_review_task',lambda p,t:task)
    monkeypatch.setattr(api,'_annotation_summary',lambda t:{})
    monkeypatch.setattr(api,'public_annotation_task',lambda t,**kw:{'id':'t','project_id':'p','summary':{},'failed_count':0,'total_count':0,'error':'password=secret /private/data'})
    result=api.get_annotation_task('p','t',reader_view=True)
    assert result['project_id']=='p' and result['task']['id']=='t'
    assert result['task']['counts']['failed'] is None
    assert '/private' not in result['task']['error']

def test_reader_candidate_endpoint_cannot_fetch_review_rows(monkeypatch):
    monkeypatch.setattr(api,'_require_annotation_review_task',lambda p,t:object())
    with pytest.raises(api.HTTPException) as error:
        api.get_annotation_candidates('p','t',reader_view=True,filter='all')
    assert error.value.status_code==422
