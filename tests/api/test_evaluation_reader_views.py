import json
from types import SimpleNamespace
import pytest
import app as api

def test_original_evaluation_endpoints_offer_opt_in_safe_pages(monkeypatch):
    evidence={'evaluation_id':'e','status':'succeeded','metrics':{'map50':0},'sample_outcomes':[{'image_id':'i','image':'photo.jpg','image_content_sha256':'a'*64,'fp_count':1}], 'per_class':[{'class_id':0,'label':'person','map50':0,'secret':'PRIVATE'}]}
    calls=[]
    def owner(p,a,v):
        calls.append((p,a,v));return {'id':v,'evaluation':evidence},{'current_version_id':v}
    monkeypatch.setattr(api,'_advanced_evaluation_context',owner)
    safe=api.advanced_evaluation_report('p','a','v',reader_view=True,section='classes',limit=1)
    assert safe['project_id']=='p' and safe['version_id']=='v' and safe['total']==1
    assert safe['evaluation']['per_class'][0]['map50']==0 and 'PRIVATE' not in json.dumps(safe)
    old=api.advanced_evaluation_report('p','a','v')
    assert 'algorithm' in old and old['algorithm']['versions'][0]['evaluation']['per_class'][0]['secret']=='PRIVATE'
    samples=api.evaluation_sample_page('p','a','v',issue='fp',reader_view=True)
    assert samples['total']==1 and 'expected_evaluation_id=e' in samples['items'][0]['preview_url']
    assert '/private' not in json.dumps(samples) and calls==[('p','a','v')]*3
    with pytest.raises(api.HTTPException) as error:api.advanced_evaluation_report('p','a','v',reader_view=True,limit=101)
    assert error.value.status_code==422

def test_comparison_keeps_original_uncomparable_verdict_and_safe_parameters(monkeypatch):
    monkeypatch.setattr(api,'_algorithm_version_for_action',lambda p,a,v:({}, {'evaluation':{},'training_lineage':{'parameters':{'actual':{'precision':'fp32','weights':'/private/model.pt'}}}}))
    result=api.compare_version_evaluation('p','a','new','old',reader_view=True)
    assert result['comparison']['comparable'] is False
    assert result['comparison']['current_version_id']=='new' and result['comparison']['source_version_id']=='old'
    assert 'evaluation_missing' in result['comparison']['reason_codes']
    assert '/private' not in json.dumps(result)
